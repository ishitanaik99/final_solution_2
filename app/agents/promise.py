"""PROMISE: the customer's choice, kept. Swap only what the customer chose; otherwise refund instantly.

Owns: order_items, customer_messages.
Wakes on: pick_not_found (mid-pick lines) and sku_hidden (lines still waiting in the pool).
sku_hidden is raised by Ledger's hide_item write: that is the Ledger -> Promise link."""
from ..core.guardrails import find_item
from ..core.llm import tool
from ..sim.constants import pystr
from .base import Agent, req

PROMISE_PROMPT = """You are PROMISE, the customer-promise agent. You own the items in live orders and messages to
customers. An item just became unavailable. For EACH affected order line in the input:
- if customer_choice is "swap" and a swap_option exists: apply_swap to that option;
- otherwise refund_item (the customer gets an instant refund for that item).
Never swap when the customer did not choose a swap. Never pick a swap other than swap_option.
Then notify_customer once per affected order with one friendly sentence (under 25 words, no emojis),
e.g. what was swapped or refunded. Resolve every line; do not skip any."""


class Promise(Agent):
    name, title, tier = "promise", "Customer swap choices", "smart"
    triggers = frozenset({"pick_not_found", "sku_hidden"})
    prompt = PROMISE_PROMPT

    def __init__(self):
        super().__init__()
        self._tally = {"swap": 0, "drop": 0, "cancel": 0, "filled": 0}
        self.tools = [
            tool("apply_swap", "Replace the missing item with the swap the customer chose.",
                 {"order_id": {"type": "integer"}, "sku": {"type": "string"}, "to_sku": {"type": "string"}}, ["order_id", "sku", "to_sku"]),
            tool("refund_item", "Drop the missing item and refund it instantly.",
                 {"order_id": {"type": "integer"}, "sku": {"type": "string"}}, ["order_id", "sku"]),
            tool("notify_customer", "Send the customer a short update.",
                 {"order_id": {"type": "integer"}, "message": {"type": "string"}}, ["order_id", "message"]),
        ]

    def _affected(self, ev, ctx):
        w, sid, rows = ctx.state.w, ev.sku, []
        if ev.type == "pick_not_found":
            for oid, it in ev.misses:
                o = w.by_id.get(oid)
                if o and o.status != "cancelled" and it.st == "missing":
                    rows.append((o, it, ev.get("trip")))
        else:
            for o in w.pool:
                if o.status == "cancelled":
                    continue
                for it in o["items"]:
                    if it.sku == sid and it.st == "open":
                        rows.append((o, it, None))
        return rows

    def wants_llm(self, ev, ctx):
        return len(self._affected(ev, ctx)) > 0

    def view(self, ev, ctx):
        w = ctx.state.w
        s = w.skus[ev.sku]
        alt = w.swap_candidate(s)
        return {"event": ev.type, "time": ctx.rt.clock(), "unavailable_item": {"sku": s.id, "name": s.name, "price": s.price},
                "swap_option": {"sku": alt.id, "name": alt.name, "price": alt.price} if alt else None,
                "affected_lines": [{"order_id": o.id, "sku": it.sku, "where": "mid_pick" if it.st == "missing" else "not_yet_picked",
                                    "customer_choice": "swap" if (o.saved or o.chose) else "refund"}
                                   for o, it, _ in self._affected(ev, ctx)]}

    def rules(self, ev, ctx):
        w = ctx.state.w
        alt = w.swap_candidate(w.skus[ev.sku])
        plan, seen = [], set()
        for o, it, _ in self._affected(ev, ctx):
            if alt and (o.saved or o.chose):
                plan.append(("apply_swap", {"order_id": o.id, "sku": it.sku, "to_sku": alt.id}))
                msg = "%s ran out, so we packed %s as you chose. No extra charge." % (w.skus[it.sku].name, alt.name)
            else:
                plan.append(("refund_item", {"order_id": o.id, "sku": it.sku}))
                msg = "%s ran out. We refunded it instantly; the rest of your order is on its way." % w.skus[it.sku].name
            if o.id not in seen:
                seen.add(o.id)
                plan.append(("notify_customer", {"order_id": o.id, "message": msg}))
        return plan

    async def handle(self, ev, ctx):
        self._tally = {"swap": 0, "drop": 0, "cancel": 0, "filled": 0}
        return await super().handle(ev, ctx)

    def execute(self, name, a, ctx):
        st, ev = ctx.state, ctx.event
        oid = int(req(a, "order_id"))
        if name == "notify_customer":
            st.notify(self.name, oid, pystr(req(a, "message"))[:220])
            return None
        o = st.order(oid)
        if o is None:
            raise TypeError("order")
        it = find_item(o, req(a, "sku"))
        trip = None
        for _, ii, tr in self._affected(ev, ctx):
            if ii is it:
                trip = tr
                break
        if name == "apply_swap":
            st.apply_swap(self.name, oid, it, req(a, "to_sku"), trip)
            self._tally["swap"] += 1
            return None
        if name == "refund_item":
            r = st.refund(self.name, oid, it)
            self._tally["drop"] += 1
            if r == "cancel":
                self._tally["cancel"] += 1
            return None
        raise ValueError(name)

    def post(self, ev, ctx):
        left = self._affected(ev, ctx)
        tl = self._tally
        if left:
            alt = ctx.state.w.swap_candidate(ctx.state.w.skus[ev.sku])
            for o, it, trip in left:
                if alt and (o.saved or o.chose):
                    ctx.state.apply_swap(self.name, o.id, it, alt.id, trip)
                    tl["swap"] += 1
                else:
                    if ctx.state.refund(self.name, o.id, it) == "cancel":
                        tl["cancel"] += 1
                    tl["drop"] += 1
                tl["filled"] += 1
        total = tl["swap"] + tl["drop"]
        if not total:
            return
        name = ctx.state.w.skus[ev.sku].name
        where = "mid-pick" if ev.type == "pick_not_found" else "waiting in the pool"
        text = "%d live order line%s with %s (%s): %d customer-chosen swap%s applied, %d item%s refunded instantly%s. No swap was guessed." % (
            total, "s" if total > 1 else "", name, where, tl["swap"], "" if tl["swap"] == 1 else "s", tl["drop"],
            "" if tl["drop"] == 1 else "s",
            (" (%d customer%s then cancelled)" % (tl["cancel"], "s" if tl["cancel"] > 1 else "")) if tl["cancel"] else "")
        if tl["filled"]:
            text += " Rules resolved %d line%s the model skipped." % (tl["filled"], "s" if tl["filled"] > 1 else "")
        ctx.state.log(self.name, text, via=self._via, story="liveorders")

    def describe(self, name, a, ctx):
        m = {"apply_swap": "Swap %s → %s in #%s." % (pystr(a.get("sku")), pystr(a.get("to_sku")), pystr(a.get("order_id"))),
             "refund_item": "Refund %s in #%s." % (pystr(a.get("sku")), pystr(a.get("order_id"))),
             "notify_customer": "Tell #%s: %s" % (pystr(a.get("order_id")), pystr(a.get("message")))}
        return m.get(name, name)
