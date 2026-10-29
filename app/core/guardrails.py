"""Hard limits, checked in code on every tool call an agent proposes (from the LLM or from rules).

A blocked call never touches the store; it is logged with its reason. The LLM can propose anything;
only calls that pass here are executed."""
import re

from ..sim.constants import GIG, MODES, OPS_BOUNDS, inr, pystr

_DEVA = re.compile("[ऀ-ॿ]")


def is_num(v):
    return isinstance(v, (int, float))


def find_item(o, sid):
    """The first unresolved line in order o for item sid (missing mid-pick, or still open)."""
    for it in o["items"]:
        if it.sku == sid and it.st in ("missing", "open"):
            return it
    return None


def g_ledger(tool, a, ctx):
    s = ctx.state.sku(a.get("sku", ""))
    if s is None:
        return False, "unknown item '%s'" % pystr(a.get("sku"))
    ev = ctx.event
    if tool == "set_trust":
        v = a.get("value")
        if not is_num(v) or not (0.0 <= v <= 0.99):
            return False, "trust must be a number between 0 and 0.99"
        if ev.type == "pick_not_found" and a.get("sku") == ev.get("sku") and v > 0.3:
            return False, "an item a picker just found empty cannot be trusted above 0.30"
    if tool == "correct_record":
        if ev.type != "count_result" or a.get("sku") != ev.get("sku"):
            return False, "a record can only be corrected from a count result"
        if int(a.get("value", -1)) != ev.counted:
            return False, "record must match the count (%d)" % ev.counted
    if tool == "restore_item":
        if s.status == "out" or ev.type not in ("refill_done", "count_result"):
            return False, "an item comes back only after a refill or a count shows stock"
        if ev.type == "count_result" and ev.counted <= 0:
            return False, "the count found none on the shelf"
    if tool == "trigger_refill":
        q = a.get("qty", 0)
        if not is_num(q) or q <= 0 or q > 24:
            return False, "refill quantity must be 1–24"
        if s.backroom <= 0:
            return False, "nothing in the backroom to refill from"
    if tool == "raise_reorder" and s.backroom > 0:
        return False, "backroom still has stock; refill instead"
    return True, ""


def g_captain(tool, a, ctx):
    w = ctx.state.w
    if tool == "set_mode":
        m = a.get("mode")
        if m not in MODES:
            return False, "unknown mode '%s'" % pystr(m)
        cur, nxt = MODES.index(w.mode), MODES.index(m)
        if nxt < cur:
            if nxt != cur - 1:
                return False, "step down one mode at a time"
            if w.down < 3:
                return False, "hysteresis: load must stay low for 3 minutes before stepping down (now %d)" % w.down
    if tool == "set_limits":
        mb, hs = a.get("max_batch"), a.get("hold_s")
        if mb is not None and not (1 <= int(mb) <= OPS_BOUNDS["max_batch"]):
            return False, "orders per trolley must be 1–%d (ops bound)" % OPS_BOUNDS["max_batch"]
        if hs is not None and not (0 <= int(hs) <= OPS_BOUNDS["hold_s"]):
            return False, "hold cap must be 0–%d s (ops bound)" % OPS_BOUNDS["hold_s"]
    if tool == "request_staff" and a.get("kind") not in ("floater_in_store", "floater_borrow"):
        return False, "kind must be floater_in_store or floater_borrow"
    if tool == "brief_shift_lead":
        hi = pystr(a["hindi"]) if "hindi" in a else ""
        en = pystr(a["english"]) if "english" in a else ""
        if not hi or not en or len(hi) > 280 or len(en) > 320:
            return False, "briefing needs short Hindi and English text"
        if not _DEVA.search(hi):
            return False, "the Hindi briefing must be in Devanagari"
    if tool == "book_ondemand":
        n, h = int(a.get("count", 0)), int(a.get("hours", 0))
        if not ctx.rt.ondemand:
            return False, "on-demand pickers are switched off for this store"
        if not (1 <= n <= GIG["maxOnFloor"]):
            return False, "book 1–%d on-demand pickers" % GIG["maxOnFloor"]
        if not (1 <= h <= 3):
            return False, "book on-demand pickers for 1–3 hours"
        if w.gig_on_floor() + n > GIG["maxOnFloor"]:
            return False, "at most %d on-demand pickers on the floor at once" % GIG["maxOnFloor"]
        if ctx.rt.gig_spend() + n * h * GIG["rate"] > GIG["maxSpend"]:
            return False, "over the ₹%s on-demand budget for this shift" % inr(GIG["maxSpend"])
    if tool == "extend_promise":
        return False, "the 10-minute promise is a hard limit and is never extended"
    return True, ""


def g_relay(tool, a, ctx):
    if tool == "set_pacing":
        bc, ps = a.get("bench_cap"), a.get("pace_slack")
        if bc is not None and not (3 <= int(bc) <= 10):
            return False, "bench cap must be 3–10 bags"
        if ps is not None and not (45 <= int(ps) <= 180):
            return False, "pace slack must be 45–180 s (never below the 45 s buffer)"
    if tool == "prioritise":
        o = ctx.state.order(a.get("order_id"))
        if o is None or o.status not in ("pool", "picking"):
            return False, "order #%s is not waiting to be picked" % pystr(a.get("order_id"))
    return True, ""


def g_promise(tool, a, ctx):
    oid = a.get("order_id")
    o = ctx.state.order(oid)
    if o is None:
        return False, "unknown order #%s" % pystr(oid)
    if tool in ("apply_swap", "refund_item"):
        if find_item(o, a.get("sku")) is None:
            return False, "#%s has no unresolved %s" % (pystr(oid), pystr(a.get("sku")))
    if tool == "apply_swap":
        if not (o.saved or o.chose):
            return False, "this customer did not choose a swap; refund instead (no guessed swaps)"
        bad, alt = ctx.state.sku(a.get("sku")), ctx.state.sku(a.get("to_sku"))
        if alt is None or bad is None:
            return False, "unknown swap item"
        if alt.cat != bad.cat or alt.price < bad.price:
            return False, "swaps must be same category and same-or-higher value"
        if alt.hidden or alt.trust < 0.7 or alt.record <= 0:
            return False, "%s is not trusted to be on the shelf" % alt.name
    if tool == "notify_customer" and len(pystr(a.get("message", ""))) > 220:
        return False, "customer message must be under 220 characters"
    return True, ""


CHECKS = {"ledger": g_ledger, "captain": g_captain, "relay": g_relay, "promise": g_promise}


def check(agent, tool, args, ctx):
    try:
        return CHECKS[agent](tool, args, ctx)
    except (TypeError, ValueError) as e:
        return False, "bad arguments (%s)" % type(e).__name__
