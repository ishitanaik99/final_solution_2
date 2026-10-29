"""Event bus: routes events in order to the agents that own the decision.

Agents never call each other. An agent's write to the shared state can raise the next event; the
bus routes it to the next agent and records the hop (who caused it, which event, who handled it).
That chain is how 'pick_not_found -> Ledger hides milk -> sku_hidden -> Promise swaps live orders'
happens without Ledger knowing Promise exists."""
from ..agents.base import Ctx
from ..sim.constants import f2

ROUTES = {
    "minute": ["ledger", "captain"],
    "pick_not_found": ["ledger", "promise"],
    "trust_drift": ["ledger"],
    "count_result": ["ledger"],
    "refill_done": ["ledger"],
    "sku_hidden": ["promise"],
    "mode_signal": ["captain"],
    "demand_forecast": ["captain"],
    "shift_summary": ["captain"],
    "rider_late": ["relay"],
    "eta_change": ["relay"],
    "bench_congested": ["relay"],
    "bench_cleared": ["relay"],
}
# Where events come from when no agent raised them.
SOURCES = {"pick_not_found": "floor", "count_result": "floor", "refill_done": "floor", "minute": "clock",
           "shift_summary": "clock", "rider_late": "rider app", "eta_change": "rider app",
           "bench_congested": "bench", "bench_cleared": "bench"}


def summarise(ev, w):
    t = ev.type
    if "sku" in ev:
        nm = w.skus[ev.sku].name
        if t == "pick_not_found":
            return "%s: slot empty, %d short" % (nm, len(ev.misses))
        if t == "count_result":
            return "%s: counted %d (%s)" % (nm, ev.counted, ev.mode)
        if t == "trust_drift":
            return "%s: trust %s" % (nm, f2(ev.trust))
        return nm
    if t == "mode_signal":
        return "suggest %s (%s)" % (ev.target, ev.why)
    if t == "demand_forecast":
        return "forecast %s, suggest %d on-demand pickers" % (f2(ev.u_fc), ev.count)
    if t == "rider_late":
        return "#%d rider +2 min" % ev.order_id
    if t == "eta_change":
        return "#%d rider %d s" % (ev.order_id, ev.delta)
    if t == "bench_congested":
        return "%d bags queued" % ev.queue
    if t == "minute":
        return "u=%s, fc=%s" % (f2(ev.u_now), f2(ev.u_fc))
    return ""


class EventBus:
    def __init__(self, rt):
        self.rt = rt
        self.trace = []
        self.counts = {}
        self.links = {}      # "source>event>agent" -> count: the live coordination graph
        self.chains = []     # recent multi-agent chains, newest first

    async def dispatch(self, events):
        rt = self.rt
        q = list(events)
        while q:
            ev = q.pop(0)
            if ev.type == "log":
                rt.log(ev.agent, ev.text, via=ev.get("via", "rules"), story=ev.get("story"))
                continue
            if rt.layer == "off":
                continue
            self.counts[ev.type] = self.counts.get(ev.type, 0) + 1
            cause = ev.get("cause")
            src = cause["agent"] if cause else SOURCES.get(ev.type, "store")
            for name in ROUTES.get(ev.type, []):
                res = await rt.agents[name].handle(ev, Ctx(rt, ev))
                if res is not None:
                    key = "%s>%s>%s" % (src, ev.type, name)
                    self.links[key] = self.links.get(key, 0) + 1
                    row = {"t": rt.smart.t, "event": ev.type, "detail": summarise(ev, rt.smart), "from": src}
                    row.update(res)
                    row["shadow"] = rt.layer == "shadow"
                    if cause:
                        row["cause"] = cause["event"]
                        if cause["agent"] != name:   # a hop from one agent to another
                            self._chain(cause, ev, name, rt.smart.t)
                    self.trace.insert(0, row)
                    del self.trace[80:]
                new = rt.smart.drain()
                for e in new:
                    if e.type != "log" and "cause" not in e:
                        e["cause"] = {"agent": name, "event": ev.type, "root": (cause or {}).get("root") or ev.type,
                                      "t": rt.smart.t}
                q.extend(new)

    def _chain(self, cause, ev, handler, t):
        hop = "%s → %s → %s" % (cause["agent"], ev.type, handler)
        root = cause.get("root") or cause["event"]
        if self.chains and self.chains[0]["t"] == t and self.chains[0]["root"] == root:
            if hop not in self.chains[0]["hops"]:
                self.chains[0]["hops"].append(hop)
            return
        self.chains.insert(0, {"t": t, "root": root, "hops": ["%s → %s" % (root, cause["agent"]), hop]})
        del self.chains[30:]
