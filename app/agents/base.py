"""Agent base: the six-step decision loop shared by Ledger, Captain, Relay and Promise.

1 Sense   plain code raises events (simulator, or an agent's own sense() on 'minute')
2 View    a compact JSON of only what this decision needs
3 Decide  the LLM replies with tool calls only (or rules, when the LLM is off or slow)
4 Check   guardrails block any call that breaks a hard limit
5 Act     approved calls write the shared state, with the reason
6 Fill    if the LLM skipped a required action, the rules add it"""
import time

from ..core import guardrails
from ..core.llm import LLMUnavailable
from ..core.state import OwnershipError
from ..sim.constants import pystr


class Ctx:
    def __init__(self, rt, event):
        self.rt = rt
        self.state = rt.state
        self.event = event
        self.llm = rt.llm
        self.llm_on = rt.llm_on
        self.dry_run = rt.layer == "shadow"


def req(a, k):
    if k not in a:
        raise KeyError(k)
    return a[k]


class Agent:
    name = title = tier = ""
    prompt = ""
    triggers = frozenset()
    senses = frozenset()

    def __init__(self):
        self.stats = {"decisions": 0, "llm": 0, "rules": 0, "fallbacks": 0, "blocked": 0, "actions": 0,
                      "ms_total": 0, "last_fallback": None}
        self.tools = []
        self._via = "rules"

    # overridable hooks
    def sense(self, ev, ctx):
        pass

    def wants_llm(self, ev, ctx):
        return True

    def view(self, ev, ctx):
        return {}

    def rules(self, ev, ctx):
        return []

    def required(self, ev, ctx):
        return set()

    def execute(self, name, args, ctx):
        raise NotImplementedError

    def post(self, ev, ctx):
        pass

    @property
    def tool_names(self):
        return {t["function"]["name"] for t in self.tools}

    async def handle(self, ev, ctx):
        if ev.type in self.senses:
            self.sense(ev, ctx)
            return None
        if ev.type not in self.triggers:
            return None
        self.stats["decisions"] += 1
        plan, via, meta = None, "rules", {}
        if ctx.llm_on and self.wants_llm(ev, ctx):
            try:
                ctx.rt.thinking = {"agent": self.name, "event": ev.type, "tier": self.tier}
                calls, meta = await ctx.llm.decide(self.prompt, self.view(ev, ctx), self.tools, self.tier)
                names = self.tool_names
                plan = [c for c in calls if c[0] in names and isinstance(c[1], dict)]
                via = "llm"
            except LLMUnavailable as e:
                self.stats["fallbacks"] += 1
                self.stats["last_fallback"] = str(e)
                meta = {"fallback": str(e)}
            finally:
                ctx.rt.thinking = None
        need = self.required(ev, ctx) if via == "llm" else set()
        if plan is None:
            plan = self.rules(ev, ctx)
        if via == "llm":
            self.stats["llm"] += 1
            self.stats["ms_total"] += meta.get("ms", 0) or 0
        else:
            self.stats["rules"] += 1
        t0 = time.perf_counter()
        done, blocked = self._run(plan, via, meta, via == "llm", ctx)
        missing = [x for x in need if x not in set(done)]
        if missing:
            fill = [c for c in self.rules(ev, ctx) if c[0] in missing]
            meta["filled"] = sorted(missing)
            d2, b2 = self._run(fill, "rules", meta, False, ctx)
            done += d2
            blocked += b2
        self._via = via
        if not ctx.dry_run:
            self.post(ev, ctx)
        return {"agent": self.name, "via": via, "actions": done, "blocked": blocked, "ms": meta.get("ms"),
                "model": meta.get("model"), "fallback": meta.get("fallback"), "filled": meta.get("filled"),
                "code_ms": round((time.perf_counter() - t0) * 1000, 2)}

    def _run(self, plan, via, meta, reason_on, ctx):
        done, blocked = [], []
        for name, args in plan:
            ok, why = guardrails.check(self.name, name, args, ctx)
            reason = pystr(args["reason"]).strip() if "reason" in args else ""
            if not ok:
                self.stats["blocked"] += 1
                blocked.append(name)
                ctx.state.log(self.name, "Blocked %s: %s." % (name, why), via="guardrail", meta={"proposed_by": via})
                continue
            if ctx.dry_run:
                ctx.state.log(self.name, self.describe(name, args, ctx), via=via, shadow=True,
                              why=reason if reason_on and reason else None)
                done.append(name)
                continue
            try:
                out = self.execute(name, args, ctx)
            except OwnershipError:
                raise
            except Exception as e:  # a bad argument from the model: block this call, keep the store running
                blocked.append(name)
                ctx.state.log(self.name, "Could not run %s: %s." % (name, type(e).__name__), via="guardrail")
                continue
            self.stats["actions"] += 1
            done.append(name)
            if out:
                hi = story = None
                if isinstance(out, tuple):
                    text = out[0]
                    hi = out[1] if len(out) > 1 else None
                    story = out[2] if len(out) > 2 else None
                else:
                    text = out
                m = {k: meta[k] for k in ("model", "ms") if k in meta}
                ctx.state.log(self.name, text, hi=hi, via=via, story=story,
                              why=reason if reason_on and reason else None, meta=m)
        return done, blocked

    def describe(self, name, args, ctx):
        return "%s(%s)" % (name, ", ".join("%s=%s" % (k, pystr(v)) for k, v in args.items() if k != "reason"))

    def public_stats(self):
        s = dict(self.stats)
        s["avg_ms"] = round(s["ms_total"] / s["llm"]) if s["llm"] else None
        s["name"], s["title"], s["tier"] = self.name, self.title, self.tier
        s["triggers"] = sorted(self.triggers)
        s["tools"] = sorted(self.tool_names)
        return s
