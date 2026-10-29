"""One store session: the smart world (agents on), the static world (today's plan), the four agents,
the shared state, the event bus and the optimiser. One session per browser tab."""
import math
import random
import time

from ..agents.captain import Captain
from ..agents.ledger import Ledger
from ..agents.promise import Promise
from ..agents.relay import Relay
from ..engine.optimiser import optimiser_run
from ..sim.constants import GIG, HORIZON, PX_M, fmt, inr, mmss
from ..sim.world import World, gen_orders, make_order
from .bus import EventBus
from .state import StoreState

M32 = 0xFFFFFFFF


def js_round(x):
    return math.floor(x + 0.5)


class Session:
    def __init__(self, llm, seed=7, opts=None):
        self.llm = llm
        self.seed = seed
        self.opts = opts or {}
        self.ondemand = bool(self.opts.get("ondemand"))
        self.eta_drift = bool(self.opts.get("etaDrift"))
        self.llm_on = llm.configured
        self.layer = "live"
        self.speed = 10
        self.playing = True
        self.auto_approve = True
        self.demo = False
        self.spike_rng = random.Random(1234)
        self.user_seq = 9001
        self.thinking = None
        self._build()

    def _build(self):
        orders = gen_orders(self.seed, self.opts.get("demand"))
        self.smart = World(orders, "smart")
        self.static = World(orders, "static")
        for w in (self.smart, self.static):
            if self.opts.get("demand"):
                w.demand = self.opts["demand"]
            if self.opts.get("shrink"):
                w.shrink_plan = self.opts["shrink"]
        if self.opts.get("slotting"):
            self.smart.dyn_slot = True
            if self.smart.levers["slotting"]:
                self.smart.front_on = True
                self.smart.apply_front()
        if self.opts.get("levers"):
            self.smart.levers.update(self.opts["levers"])
        self.opt_times = []

        def run_opt(w):
            t0 = time.perf_counter()
            optimiser_run(w)
            self.opt_times.append((time.perf_counter() - t0) * 1000)
            if len(self.opt_times) > 600:
                self.opt_times.pop(0)
        self.smart.optimiser = run_opt
        self.logs, self.story = [], {}
        self.state = StoreState(self.smart, lambda a, t, o: self.log(a, t, **o))
        self.agents = {a.name: a for a in (Ledger(), Captain(), Relay(), Promise())}
        self.bus = EventBus(self)
        self.summary_done = False
        self.apply_layer(self.layer, quiet=True)

    async def reset(self, start_at=840, demo=False):
        self.demo = bool(demo)
        self._build()
        await self.fast_forward(start_at)

    async def fast_forward(self, to):
        keep = self.llm_on
        self.llm_on = False
        while self.smart.t < to:
            await self.tick()
        self.llm_on = keep

    def clock(self):
        return fmt(self.smart.t)

    def log(self, agent, text, hi=None, via="rules", story=None, shadow=False, why=None, meta=None):
        self.logs.insert(0, {"t": self.smart.t, "agent": agent, "text": text, "hi": hi, "via": via, "why": why,
                             "meta": meta or {}, "shadow": bool(shadow) or self.layer == "shadow"})
        del self.logs[400:]
        if hi and not shadow and self.layer != "shadow":
            self.smart.brief = {"t": self.smart.t, "hi": hi, "en": text, "agent": agent}
        if story and story not in self.story and not shadow:
            self.story[story] = self.smart.t

    async def tick(self):
        s = self.smart
        s.step()
        self.static.step()
        self.static.drain()
        if self.demo and s.t == 2520:
            self.rider_late(None, True)
        if self.eta_drift and s.t % 60 == 0:
            self.drift_etas()
        if s.t == 4500 and not self.summary_done:
            self.summary_done = True
            s.emit("shift_summary", {"numbers": self.summary_numbers()})
        if s.t % 60 == 0 and self.auto_approve:
            for a in list(s.approvals):
                if a["status"] == "pending" and s.t - a["t"] >= 20:
                    self.approve(a["id"], "by voice")
        await self.bus.dispatch(s.drain())
        if s.t >= HORIZON - 5:
            self.playing = False

    def drift_etas(self):
        """Live rider ETAs: a deterministic hash moves some riders earlier or later each minute."""
        m = self.smart.t // 60
        for w in (self.smart, self.static):
            for o in w.active_orders():
                if o.rider_arrive <= w.t + 40:
                    continue
                h = (((o.id * 2654435761) & M32) ^ (((m + 1) * 40503) & M32)) & M32
                r = (h % 10007) / 10007
                if r < 0.55:
                    o.eta_delta = 0
                    continue
                d = js_round((r - 0.775) / 0.225 * 50)
                o.rider_arrive += d
                o.eta_delta = d
                if w is self.smart:
                    w.kpi["etaMoves"] += 1
                    if d <= -35 and o.status == "pool":
                        w.emit("eta_change", {"order_id": o.id, "delta": d, "eta": o.rider_arrive - w.t})

    def summary_numbers(self):
        S, X = self.smart.stats, self.static.stats
        walk_s = S["walk"] * PX_M / max(1, S["pickN"])
        walk_x = X["walk"] * PX_M / max(1, X["pickN"])
        return {"wrong_records_caught": S["hidden"] + S["fixed"], "customer_chosen_swaps": S["swaps"],
                "shared_trolley_trips": S["batchedOrders"] - S["batches"],
                "walking_saved_m": max(0, round((walk_x - walk_s) * S["pickN"] / 10) * 10),
                "cancellations": S["cancels"], "cancellations_static_plan": X["cancels"]}

    def apply_layer(self, layer, quiet=False):
        prev = self.layer
        self.layer = layer
        self.smart.policy = "smart" if layer == "live" else "static"
        self.smart.agents_on = layer != "off"
        if quiet:
            return
        if layer == "off":
            self.log("system", "Agent layer offline. Fail-safe: the store fell back to today’s static picking, and orders keep flowing.")
        elif layer == "shadow":
            self.log("system", "Shadow mode: the floor runs today’s static plan; the agents only log what they would have done.")
        else:
            self.log("system", "Agent layer back online. Agents resume from the current store state." if prev == "off"
                     else "Live mode: agents act on the floor.")

    def approve(self, kind, how="from the dashboard"):
        a = next((x for x in self.smart.approvals if x["id"] == kind), None)
        if not a or a["status"] != "pending":
            return
        a["status"] = "approved"
        a["at"] = self.smart.t
        if a.get("ondemand"):
            self.book_on_demand(a["count"], a["hours"], how, True)
            return
        name, delay = ("Kiran", 60) if kind == "floater_in_store" else ("Neel", 240)
        self.smart.add_picker(name, delay)
        self.log("captain", "Shift lead approved %s: %s joins the floor in %s." % (how, name, mmss(delay)), via="shift lead")

    def gig_spend(self):
        return self.smart.kpi["gigCost"]

    def book_on_demand(self, count, hours, how=None, approved=False):
        w = self.smart
        count = max(1, min(GIG["maxOnFloor"] - w.gig_on_floor(), int(count)))
        hours = max(1, min(3, int(hours)))
        if count < 1:
            return None
        if self.gig_spend() + count * hours * GIG["rate"] > GIG["maxSpend"]:
            return None
        ps = w.add_gig(count, hours)
        how = how or "from the dashboard"
        self.log("captain", "%s%s (on-demand, %d h, ₹%s) %s the floor in 10:00." % (
            ("Shift lead approved %s: " if approved else "Shift lead booked %s: ") % how,
            ", ".join(p.name for p in ps), hours, inr(count * hours * GIG["rate"]), "join" if len(ps) > 1 else "joins"),
            via="shift lead")
        return ps

    def decline(self, kind):
        a = next((x for x in self.smart.approvals if x["id"] == kind), None)
        if not a or a["status"] != "pending":
            return
        a["status"] = "declined"
        a["at"] = self.smart.t
        self.log("captain", "Shift lead declined: %s. Captain keeps the current staffing." % a["text"], via="shift lead")

    def empty_shelf(self, sid):
        for w in (self.smart, self.static):
            w.shrink(sid, 0)
        return self.smart.skus[sid].name

    def rider_late(self, order_id=None, auto=False):
        s, t = self.smart, self.smart.t
        if order_id is None:
            best = None
            for o in s.active_orders():
                if o.status in ("pool", "picking") and o.rider_arrive > t + 20:
                    if best is None or o.rider_arrive < best.rider_arrive:
                        best = o
            if best is None:
                return None
            order_id = best.id
        for w in (self.smart, self.static):
            o = w.by_id.get(order_id)
            if o:
                o.rider_arrive += 120
        s.emit("rider_late", {"order_id": order_id})
        return order_id

    def spike(self):
        t, extra = self.smart.t, []
        for i in range(14):
            at = t + 5 + int(self.spike_rng.random() * 360)
            oid = 8001 + int(self.spike_rng.random() * 900) + i * 1000
            extra.append(make_order(self.spike_rng, at, oid))
        for w in (self.smart, self.static):
            w.insert_orders(extra)
        self.log("system", "Demand spike: 14 extra orders over the next 6 minutes (for example, a cricket match ending). "
                           "The forecast did not expect it, so Captain reacts to live load.")

    def place_order(self, cart, choices):
        from ..sim.obj import Obj
        s = self.smart
        cart = [c for c in cart if isinstance(c, str) and c in s.skus][:4]
        if not cart:
            return None

        def wants_swap(sid):
            sk, pick = s.skus[sid], (choices or {}).get(sid)
            return (pick != "refund" if sk.hidden else pick == "swap") and s.swap_candidate(sk) is not None
        any_swap = any(wants_swap(c) for c in cart)
        o = Obj(id=self.user_seq, placed=s.t + 1, items=list(cart), ride=200, riderIn=200, saved=False, chose=any_swap,
                forceChoice=any_swap, cancelIfMissing=False, user=True)
        self.user_seq += 1
        for w in (self.smart, self.static):
            w.insert_orders([o])
        self.log("promise", "Order #%d placed from the checkout with %d item%s%s" % (
            o.id, len(cart), "s" if len(cart) > 1 else "",
            "; the customer chose a swap for a low-stock item." if any_swap else "; no swap chosen, so a missing item would be refunded."))
        return o.id
