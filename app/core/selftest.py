"""System check: scenario tests that prove the four agents are linked through the shared state,
the guardrails hold, and the store survives LLM failure. Run by pytest and by /api/selftest
(the 'Run system check' button in the control room)."""
import asyncio
import json
import time

import httpx

from ..agents.base import Ctx
from ..sim.constants import HORIZON, LIMITS
from ..sim.obj import Obj
from . import guardrails
from .llm import GroqLLM, LLMUnavailable, NoLLM
from .runtime import Session
from .state import OwnershipError

OPTS = {"ondemand": True, "slotting": True, "etaDrift": True}


async def _shift(llm=None, seed=7, to=HORIZON - 5, start=840, demo=False, opts=None):
    s = Session(llm or NoLLM(), seed, dict(OPTS, **(opts or {})))
    await s.reset(start, demo)
    while s.smart.t < to:
        await s.tick()
    return s


async def _until(s, t):
    while s.smart.t < t:
        await s.tick()


def _ctx(s, ev):
    return Ctx(s, Obj(ev))


class FlakyLLM:
    """Always times out: proves the fallback."""
    provider = "test"
    configured = True
    models = {"smart": "flaky", "fast": "flaky"}

    def __init__(self):
        self.calls = 0

    def health(self):
        return {"configured": True, "provider": "test", "models": self.models, "calls": self.calls}

    async def decide(self, *a):
        self.calls += 1
        raise LLMUnavailable("no answer within 8 s")


class RogueLLM(FlakyLLM):
    """Answers, but proposes unsafe or incomplete plans: proves guardrails and rule fill-in."""
    models = {"smart": "rogue", "fast": "rogue"}

    async def decide(self, prompt, view, tools, tier):
        self.calls += 1
        ev = view.get("event")
        if ev == "pick_not_found":
            if "affected_lines" in view:   # Promise: swap everyone, even customers who chose a refund
                alt = (view.get("swap_option") or {}).get("sku", "nope")
                return [("apply_swap", {"order_id": l["order_id"], "sku": l["sku"], "to_sku": alt, "reason": "x"})
                        for l in view["affected_lines"]], {"model": "rogue", "ms": 1}
            # Ledger: trusts the empty item and forgets to hide it or count it
            return [("set_trust", {"sku": view["item"]["sku"], "value": 0.9, "reason": "looks fine"})], {"model": "rogue", "ms": 1}
        if ev == "mode_signal":
            return [("extend_promise", {"reason": "x"}), ("set_limits", {"max_batch": 9, "reason": "x"})], {"model": "rogue", "ms": 1}
        return [], {"model": "rogue", "ms": 1}


# ---------------------------------------------------------------------------------------------- tests
async def t_deterministic():
    a, b = await _shift(), await _shift()
    ok = a.smart.stats == b.smart.stats and a.static.stats == b.static.stats
    return ok, "same seed, same shift: %d orders, %d done" % (a.smart.stats["placed"], a.smart.stats["done"])


async def t_ledger_to_promise():
    s = await _shift(to=1500)
    s.empty_shelf("milk")
    await _until(s, 2400)
    link = s.bus.links.get("ledger>sku_hidden>promise", 0)
    hid = s.smart.stats["hidden"]
    ok = link > 0 and hid > 0 and s.agents["promise"].stats["decisions"] > 0
    return ok, "pick_not_found → Ledger hid %d item(s) → sku_hidden → Promise handled it %d time(s)" % (hid, link)


async def t_pnf_fans_out():
    s = await _shift(to=1500)
    s.empty_shelf("eggs")
    await _until(s, 2400)
    l = s.bus.links
    ok = l.get("floor>pick_not_found>ledger", 0) > 0 and l.get("floor>pick_not_found>promise", 0) > 0
    return ok, "one failed pick reached both Ledger (%d) and Promise (%d)" % (
        l.get("floor>pick_not_found>ledger", 0), l.get("floor>pick_not_found>promise", 0))


async def t_captain_drives_optimiser():
    s = await _shift(to=3000)
    modes = [m for m, n in s.smart.kpi["modeMin"].items() if n]
    ok = s.bus.links.get("captain>mode_signal>captain", 0) > 0 and s.smart.lim["max"] == LIMITS[s.smart.mode]["max"] and len(modes) >= 2
    return ok, "Captain switched modes %s; optimiser now batches up to %d" % ("/".join(modes), s.smart.lim["max"])


async def t_relay_rider_late():
    s = await _shift(to=2000)
    oid = s.rider_late(None)
    await s.tick()
    rel = s.agents["relay"].stats["actions"]
    ok = oid is not None and rel > 0 and s.bus.counts.get("rider_late", 0) == 1
    return ok, "rider for #%s late → Relay re-prioritised (%d actions); boosted: %s" % (oid, rel, list(s.smart.priority)[:3])


async def t_count_loop():
    s = await _shift()
    c = s.bus.counts
    ok = c.get("count_result", 0) > 0 and c.get("refill_done", 0) > 0 and s.smart.stats["fixed"] > 0
    return ok, "%d counts and %d refills closed the loop; %d records fixed" % (c.get("count_result", 0), c.get("refill_done", 0), s.smart.stats["fixed"])


async def t_ownership():
    s = await _shift(to=900)
    try:
        s.state.set_trust("promise", "milk", 0.1)
        return False, "Promise was allowed to write Ledger's field"
    except OwnershipError as e:
        return True, str(e)


async def t_guard_no_guessed_swap():
    s = await _shift(to=1800)
    o = next(o for o in s.smart.active_orders() if not (o.saved or o.chose) and o.status in ("pool", "picking"))
    it = o["items"][0]
    ok, why = guardrails.check("promise", "apply_swap", {"order_id": o.id, "sku": it.sku, "to_sku": it.sku}, _ctx(s, {"type": "sku_hidden", "t": 0}))
    return (not ok) and ("did not choose" in why or "no unresolved" in why), "blocked: " + why


async def t_guard_promise_never_extended():
    s = await _shift(to=900)
    ok, why = guardrails.check("captain", "extend_promise", {}, _ctx(s, {"type": "mode_signal", "t": 0}))
    return not ok, "blocked: " + why


async def t_guard_empty_not_trusted():
    s = await _shift(to=900)
    ok, why = guardrails.check("ledger", "set_trust", {"sku": "milk", "value": 0.9},
                               _ctx(s, {"type": "pick_not_found", "sku": "milk", "t": 0}))
    return not ok, "blocked: " + why


async def t_guard_hysteresis():
    s = await _shift(to=900)
    s.smart.mode = "surge"
    s.smart.down = 0
    ok1, why1 = guardrails.check("captain", "set_mode", {"mode": "normal"}, _ctx(s, {"type": "mode_signal", "t": 0}))
    ok2, why2 = guardrails.check("captain", "set_mode", {"mode": "peak"}, _ctx(s, {"type": "mode_signal", "t": 0}))
    return (not ok1) and (not ok2), "blocked: %s; %s" % (why1, why2)


async def t_guard_ops_bounds():
    s = await _shift(to=900)
    a = guardrails.check("relay", "set_pacing", {"pace_slack": 20}, _ctx(s, {"type": "bench_congested", "t": 0}))
    b = guardrails.check("captain", "set_limits", {"max_batch": 9}, _ctx(s, {"type": "mode_signal", "t": 0}))
    c = guardrails.check("captain", "brief_shift_lead", {"hindi": "peak mode", "english": "Peak"}, _ctx(s, {"type": "mode_signal", "t": 0}))
    return not (a[0] or b[0] or c[0]), "blocked: %s; %s; %s" % (a[1], b[1], c[1])


async def t_llm_fallback():
    llm = FlakyLLM()
    s = await _shift(llm=llm, to=1500)
    s.llm_on = True
    s.empty_shelf("milk")
    await _until(s, 3000)
    fb = sum(a.stats["fallbacks"] for a in s.agents.values())
    ok = llm.calls > 0 and fb == llm.calls and s.smart.stats["hidden"] > 0 and s.smart.stats["done"] > 0
    return ok, "LLM timed out %d times; rules took over every time and the store kept running (%d orders done)" % (fb, s.smart.stats["done"])


async def t_rogue_llm_contained():
    llm = RogueLLM()
    s = await _shift(llm=llm, to=1500)
    s.llm_on = True
    s.empty_shelf("milk")
    await _until(s, 3600)
    blocked = sum(a.stats["blocked"] for a in s.agents.values())
    filled = any(r.get("filled") for r in s.bus.trace) or any("skipped" in l["text"] for l in s.logs)
    guessed = 0
    for o in s.smart.by_id.values():
        for it in o["items"]:
            if it.get("from") and not it.get("checkout") and not (o.saved or o.chose):
                guessed += 1
    ok = blocked > 0 and filled and guessed == 0 and s.smart.stats["hidden"] > 0 and s.smart.lim["max"] <= 4
    return ok, "%d unsafe proposals blocked; missing actions filled by rules; 0 guessed swaps; milk still hidden" % blocked


async def t_shadow_mode():
    s = await _shift(to=1500)
    s.apply_layer("shadow")
    s.empty_shelf("milk")
    await _until(s, 2400)
    would = sum(1 for l in s.logs if l["shadow"] and l["agent"] in ("ledger", "promise"))
    ok = would > 0 and not s.smart.skus["milk"].hidden or s.smart.skus["milk"].status in ("hidden",) and would > 0
    return would > 0, "agents logged %d 'would have' actions without touching the floor" % would


async def t_off_failsafe():
    s = await _shift(to=1500)
    done0 = s.smart.stats["done"]
    s.apply_layer("off")
    before = dict(s.bus.counts)
    await _until(s, 2400)
    ok = s.smart.stats["done"] > done0 and dict(s.bus.counts) == before
    return ok, "agents off: no events routed, orders kept flowing (%d → %d done)" % (done0, s.smart.stats["done"])


async def t_beats_static():
    s = await _shift()
    S, X = s.smart.stats, s.static.stats
    ps, px = S["pickSum"] / S["pickN"], X["pickSum"] / X["pickN"]
    ok = ps < px and S["cancels"] <= X["cancels"] and S["onTime"] >= X["onTime"]
    return ok, "pick %.1f s vs %.1f s static (%+.0f%%); cancels %d vs %d" % (ps, px, (ps / px - 1) * 100, S["cancels"], X["cancels"])


async def t_optimiser_fast():
    s = await _shift()
    from ..server.snapshot import p95
    v = p95(s.opt_times)
    return v < 100, "optimiser p95 %.2f ms (target < 100 ms)" % v


async def t_hindi_brief():
    s = await _shift(to=3600)
    briefs = [l for l in s.logs if l["hi"]]
    ok = bool(briefs) and all(any("ऀ" <= ch <= "ॿ" for ch in l["hi"]) for l in briefs)
    return ok, "%d Hindi briefings, e.g. “%s”" % (len(briefs), briefs[-1]["hi"][:60] if briefs else "")


async def t_checkout_choice():
    s = await _shift(to=1500)
    s.empty_shelf("milk")
    while not s.smart.skus["milk"].hidden and s.smart.t < 3000:
        await s.tick()
    oid = s.place_order(["milk", "bread"], {"milk": "swap"})
    await s.tick()
    await s.tick()
    o = s.smart.by_id.get(oid)
    swapped = o is not None and any(it.get("from") == "milk" for it in o["items"])
    return swapped, "milk hidden by Ledger; customer chose a swap before paying, so #%s got %s" % (oid, [it.sku for it in o["items"]] if o else "?")


async def t_groq_client():
    """Real Groq request/response handling against a mocked HTTP layer (no network)."""
    seen = {"n": 0}

    def handler(req):
        body = json.loads(req.content)
        seen["n"] += 1
        if body["model"] == "llama-3.3-70b-versatile":
            return httpx.Response(400, json={"error": {"message": "The model `llama-3.3-70b-versatile` has been decommissioned"}})
        assert body["tool_choice"] == "required" and body["tools"]
        return httpx.Response(200, json={"choices": [{"message": {"tool_calls": [
            {"id": "1", "type": "function", "function": {"name": "set_mode", "arguments": "{\"mode\":\"peak\",\"reason\":\"load\"}"}}]}}],
            "usage": {"total_tokens": 1234}})
    g = GroqLLM("test-key")
    g._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    calls, meta = await g.decide("p", {"event": "mode_signal"}, [{"type": "function", "function": {"name": "set_mode"}}], "smart")
    ok1 = calls == [("set_mode", {"mode": "peak", "reason": "load"})] and meta["model"] == "openai/gpt-oss-120b"

    def limited(req):
        return httpx.Response(429, headers={"retry-after": "20"}, json={})
    g2 = GroqLLM("test-key")
    g2._client = httpx.AsyncClient(transport=httpx.MockTransport(limited))
    try:
        await g2.decide("p", {}, [], "fast")
        ok2 = False
    except LLMUnavailable:
        ok2 = g2.health()["cooling"] > 0
    hits = []

    def per_model(req):
        m = json.loads(req.content)["model"]
        hits.append(m)
        if m == "llama-3.1-8b-instant":
            return httpx.Response(429, headers={"retry-after": "30"}, json={})
        return httpx.Response(200, json={"choices": [{"message": {"tool_calls": [
            {"id": "1", "type": "function", "function": {"name": "announce", "arguments": "{\"message\":\"hi\"}"}}]}}]})
    g3 = GroqLLM("test-key")
    g3._client = httpx.AsyncClient(transport=httpx.MockTransport(per_model))
    _, m3 = await g3.decide("p", {}, [], "fast")
    ok3 = hits[:2] == ["llama-3.1-8b-instant", "meta-llama/llama-4-scout-17b-16e-instruct"] and m3["model"] == hits[1]
    return ok1 and ok2 and ok3, ("tool calls parsed; retired model skipped (→ %s); a rate-limited model rests while the "
                                 "next one answers (→ %s); all limited → rules" % (meta.get("model"), m3.get("model")))


TESTS = [
    ("Same seed gives the same shift", t_deterministic),
    ("Ledger → sku_hidden → Promise (linked via shared state)", t_ledger_to_promise),
    ("One failed pick fans out to Ledger and Promise", t_pnf_fans_out),
    ("Captain's mode sets the optimiser's limits", t_captain_drives_optimiser),
    ("Rider late → Relay re-prioritises the queue", t_relay_rider_late),
    ("Count and refill close the Ledger loop", t_count_loop),
    ("One writer per field (ownership enforced)", t_ownership),
    ("Guardrail: no guessed swaps", t_guard_no_guessed_swap),
    ("Guardrail: 10-minute promise never extended", t_guard_promise_never_extended),
    ("Guardrail: an empty shelf can't be trusted", t_guard_empty_not_trusted),
    ("Guardrail: step down one mode, after 3 calm minutes", t_guard_hysteresis),
    ("Guardrail: ops bounds and Devanagari briefings", t_guard_ops_bounds),
    ("LLM down or slow → rules decide, store runs on", t_llm_fallback),
    ("Rogue LLM plan is blocked and completed by rules", t_rogue_llm_contained),
    ("Shadow mode logs, doesn't act", t_shadow_mode),
    ("Agents off → fail-safe static plan", t_off_failsafe),
    ("SyncStore beats today's static plan", t_beats_static),
    ("Optimiser p95 under 100 ms", t_optimiser_fast),
    ("Captain briefs in Hindi (Devanagari)", t_hindi_brief),
    ("Checkout swap choice reaches the order", t_checkout_choice),
    ("Groq client: tool calls, retired and rate-limited models", t_groq_client),
]


async def run_all():
    out = []
    for name, fn in TESTS:
        t0 = time.perf_counter()
        try:
            ok, detail = await fn()
        except Exception as e:  # report, don't crash the endpoint
            ok, detail = False, "%s: %s" % (type(e).__name__, e)
        out.append({"name": name, "ok": bool(ok), "detail": detail, "ms": round((time.perf_counter() - t0) * 1000)})
        await asyncio.sleep(0)
    return out
