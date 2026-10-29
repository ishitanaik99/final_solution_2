"""RELAY: rider-first release. Packs first for the rider arriving soonest; paces the packing bench.

Owns: release_policy, priority.
Wakes on: rider_late, eta_change, bench_congested, bench_cleared."""
from ..core.llm import tool
from ..sim.constants import mmss, pystr
from .base import Agent, req

RELAY_PROMPT = """You are RELAY, the rider-first release agent. You own the release policy (bench_cap: how many
bags may wait at the packing bench before you hold back releases; pace_slack: orders with more buffer
than this are held while the bench is congested) and short priority boosts for specific orders.
Bounds: bench_cap 3-10, pace_slack 45-180 s. An order whose buffer is under 45 s is always released at once.

Events:
- rider_late: a rider is now 2 minutes late. Usually prioritise the waiting order whose rider arrives
  soonest (it should go first), and announce the change to the floor in one sentence.
- bench_congested: bags are piling up at the bench. Use set_pacing (typically bench_cap 4-5, pace_slack
  60-120: hold more when riders are not yet at the store, less when riders are already waiting) and announce.
Keep announcements under 30 words and mention order numbers with #."""


class Relay(Agent):
    name, title, tier = "relay", "Rider-first release", "fast"
    triggers = frozenset({"rider_late", "bench_congested", "bench_cleared", "eta_change"})
    prompt = RELAY_PROMPT

    def __init__(self):
        super().__init__()
        self.tools = [
            tool("prioritise", "Boost one waiting order so the optimiser releases it first (3 minutes).",
                 {"order_id": {"type": "integer"}}, ["order_id"]),
            tool("set_pacing", "Set how releases are paced while the packing bench is congested.",
                 {"bench_cap": {"type": "integer"}, "pace_slack": {"type": "integer"}}, []),
            tool("announce", "Tell the floor what changed and why.", {"message": {"type": "string"}}, ["message"]),
        ]

    def wants_llm(self, ev, ctx):
        return ev.type != "bench_cleared"

    def _waiting(self, ctx, exclude):
        w = ctx.state.w
        return sorted([o for o in w.active_orders() if o.status == "pool" and o.id != exclude], key=lambda o: o.rider_arrive)

    def view(self, ev, ctx):
        w = ctx.state.w
        v = {"event": ev.type, "time": ctx.rt.clock(), "release_policy": dict(w.release_policy),
             "bench_queue": len(w.bench.q), "bags_ready": len(w.bench.ready),
             "riders_at_store": sum(1 for o in w.active_orders() if o.rider_arrive <= w.t)}
        v["waiting_orders"] = [{"order_id": o.id, "rider_arrives_in_s": o.rider_arrive - w.t, "buffer_s": round(w.slack_of(o))}
                               for o in self._waiting(ctx, ev.get("order_id"))[:6]]
        if ev.type == "eta_change":
            o = w.by_id[ev.order_id]
            v["eta_change"] = {"order_id": o.id, "rider_now_arrives_in_s": o.rider_arrive - w.t, "moved_by_s": ev.delta, "status": o.status}
        if ev.type == "rider_late":
            o = w.by_id[ev.order_id]
            v["late_order"] = {"order_id": o.id, "rider_now_arrives_in_s": o.rider_arrive - w.t, "buffer_s": round(w.slack_of(o)), "status": o.status}
        return v

    def rules(self, ev, ctx):
        w = ctx.state.w
        if ev.type == "rider_late":
            lst = self._waiting(ctx, ev.order_id)
            nxt = lst[0] if lst else None
            msg = ("Rider for #%d is running 2 min late. Its time buffer grew by 120 s, so %s#%d can now share a trolley."
                   % (ev.order_id, ("#%d (rider %s away) goes first and " % (nxt.id, mmss(nxt.rider_arrive - w.t))) if nxt else "", ev.order_id))
            plan = [("prioritise", {"order_id": nxt.id})] if nxt else []
            return plan + [("announce", {"message": msg})]
        if ev.type == "bench_congested":
            waiting = sum(1 for o in w.active_orders() if o.rider_arrive <= w.t)
            slack = 60 if waiting >= 3 else 90
            return [("set_pacing", {"bench_cap": 5, "pace_slack": slack}),
                    ("announce", {"message": "Packing bench has %d bags waiting. Holding orders with more than %d s of buffer until it clears." % (ev.queue, slack)})]
        if ev.type == "bench_cleared":
            return [("set_pacing", {"bench_cap": 5, "pace_slack": 90})]
        if ev.type == "eta_change":
            return [("prioritise", {"order_id": ev.order_id}),
                    ("announce", {"message": "Rider for #%d is now %s away (%d s sooner), so #%d moves up the pick queue."
                                             % (ev.order_id, mmss(ev.eta), abs(ev.delta), ev.order_id)})]
        return []

    def execute(self, name, a, ctx):
        st, ev = ctx.state, ctx.event
        if name == "prioritise":
            st.boost(self.name, int(req(a, "order_id")))
            return None
        if name == "set_pacing":
            before = dict(st.w.release_policy)
            st.set_release_policy(self.name, a.get("bench_cap"), a.get("pace_slack"))
            after = st.w.release_policy
            if before == after or ev.type == "bench_cleared":
                return None
            return "Release pacing set: hold releases when %d+ bags wait, unless an order has under %d s of buffer." % (after["bench_cap"], after["pace_slack"])
        if name == "announce":
            return (pystr(req(a, "message"))[:300], None, "riderlate" if ev.type == "rider_late" else None)
        raise ValueError(name)

    def describe(self, name, a, ctx):
        m = {"prioritise": "Release #%s first." % pystr(a.get("order_id")),
             "set_pacing": "Pace releases (bench cap %s, slack %s s)." % (pystr(a.get("bench_cap")), pystr(a.get("pace_slack"))),
             "announce": pystr(a.get("message", ""))}
        return m.get(name, name)
