"""Snapshots sent to the control room ~4 times a second, plus the CEO-view counters."""
import math

from ..agents.captain import gig_suggest
from ..core.state import OWNERSHIP
from ..sim.constants import BUFFER, GIG, HORIZON, LIMITS, MODE_LABEL, MODE_METHOD, PX_M, SKU_DEFS, f2, fmt

CHECKOUT_ITEMS = ["milk", "bread", "breadb", "eggs", "curd", "paneer", "chips", "popcorn", "cola", "biscuit", "coffee", "icv"]
PRICE = {d[0]: d[5] for d in SKU_DEFS}


def js_round(x):
    return math.floor(x + 0.5)


def s_stats(w):
    s = dict(w.stats)
    s["avgPick"] = round(w.avg_pick(), 1)
    s["walkPerOrder"] = round(w.stats["walk"] * PX_M / max(1, w.stats["pickN"]), 1)
    s["riderWaitAvg"] = round(w.stats["riderWait"] / w.stats["riderWaitN"], 1) if w.stats["riderWaitN"] else 0
    return s


def s_trip(tr):
    return {"id": tr.id, "picker": tr.p.name, "zone": tr.zone, "n": len(tr.orders), "ids": [o.id for o in tr.orders],
            "start": tr.start, "end": round(tr.end, 1), "stops": len(tr.stops), "len": round(tr.len),
            "pts": [[round(p["x"], 1), round(p["y"], 1), round(p["t"], 2)] for p in tr.pts]}


def state_rows(sess):
    w = sess.smart
    t, skus = w.t, list(w.skus.values())
    low = min(skus, key=lambda s: s.trust)
    pool = [o for o in w.pool if o.status == "pool"]
    tight = min(pool, key=lambda o: w.slack_of(o)) if pool else None
    aisles = [0] * 9
    for tr in w.trips:
        if not tr.done and tr.end > t:
            for a in tr.aisles:
                aisles[a] += 1
    busy = 1
    for a in range(2, 9):
        if aisles[a] > aisles[busy]:
            busy = a
    saved = sum(1 for o in w.active_orders() if o.saved or o.chose)
    rp = w.release_policy
    live = {
        "sku.trust": "%s at %s (lowest)" % (low.name, f2(low.trust)),
        "sku.visibility": "%d hidden in the app" % sum(1 for s in skus if s.hidden),
        "sku.record": "%d records above the real shelf" % sum(1 for s in skus if s.record > s.shelf),
        "count_and_refill": "%d tasks open" % sum(1 for s in skus if s.counting),
        "mode_and_limits": ("%s · ≤%d per trolley · hold ≤%d s" % (MODE_LABEL[w.mode], w.lim["max"], w.lim["hold"]))
        if sess.layer == "live" else "Agents not driving the floor",
        "front_racks": "Fast movers in front" if any(s.fwd for s in skus) else "Home slots",
        "approvals_and_brief": "%d awaiting the shift lead" % sum(1 for a in w.approvals if a["status"] == "pending"),
        "release_policy": "bench cap %d · pace slack %d s" % (rp["bench_cap"], rp["pace_slack"]),
        "priority": ("#%d tightest at %d s" % (tight.id, round(w.slack_of(tight))) if tight else "No orders waiting")
        + (" · %d boosted" % len(w.priority) if w.priority else ""),
        "order_items": "%d live orders have a saved or chosen swap" % saved,
        "customer_messages": "%d sent this shift" % w.stats["notified"],
    }
    rows = [{"field": f, "owner": o, "readers": r, "live": live[f], "writes": sess.state.writes.get(f, 0)} for f, o, r in OWNERSHIP]
    rows.append({"field": "trolleys_and_routes", "owner": "opt", "readers": "Captain, pickers",
                 "live": ("Aisle A%d busiest (%d trolleys)" % (busy, aisles[busy])) if aisles[busy] else "All aisles clear",
                 "writes": len(sess.opt_times)})
    return rows


# ---------------------------------------------------------------- CEO counters (mirror of the page's SyncKPI)
def world_counts(w):
    st, k = w.stats, w.kpi
    c = {"placed": st["placed"], "done": st["done"], "onTime": st["onTime"], "cancels": st["cancels"], "pna": st["missingHits"],
         "linesAttempted": k["linesAttempted"], "pickSum": st["pickSum"], "pickN": st["pickN"], "pickLines": k["pickLines"],
         "riderWait": st["riderWait"], "riderWaitN": st["riderWaitN"], "walk": st["walk"], "hides": k["hides"],
         "falseFlags": k["falseFlags"], "swaps": st["swaps"], "refunds": st["refunds"], "prevented": st["prevented"],
         "gigHours": k["gigHours"], "gigCost": k["gigCost"], "tWalk": k["tWalk"], "tCong": k["tCong"], "tSearch": k["tSearch"],
         "tPick": k["tPick"], "tBench": k["tBench"], "nBench": k["nBench"], "rerouteSaved": k["rerouteSaved"],
         "slotSaved": k["slotSaved"], "etaMoves": k["etaMoves"], "sku": dict(k["pnaBySku"]), "closed": 0, "linesOrdered": 0,
         "linesFulfilled": 0, "perfect": 0, "refundValue": 0}
    for o in w.by_id.values():
        for it in o["items"]:
            if it.st == "dropped":
                c["refundValue"] += PRICE.get(it.sku, 0)
        if o.status not in ("done", "cancelled"):
            continue
        c["closed"] += 1
        c["linesOrdered"] += len(o["items"])
        if o.status != "done":
            continue
        picked = sum(1 for it in o["items"] if it.st == "picked")
        pna = any(it.get("pna") for it in o["items"])
        c["linesFulfilled"] += picked
        if picked == len(o["items"]) and not pna and o.handed_at <= max(o.D, o.rider_arrive):
            c["perfect"] += 1
    return c


def p95(a):
    if not a:
        return 0
    s = sorted(a)
    return s[min(len(s) - 1, int(0.95 * len(s)))]


def shift_counts(sess):
    dec = blocked = llm = 0
    for a in sess.agents.values():
        dec += a.stats["decisions"]
        blocked += a.stats["blocked"]
        llm += a.stats["llm"]
    return {"S": world_counts(sess.smart), "X": world_counts(sess.static), "decisions": dec, "blocked": blocked, "llm": llm,
            "optP95": round(p95(sess.opt_times), 2), "modeMin": dict(sess.smart.kpi["modeMin"]),
            "briefs": sum(1 for l in sess.logs if l["hi"])}


def intraday(sess):
    n = 12
    out = [{"S": dict(placed=0, onTime=0, done=0, cancels=0, pna=0), "X": dict(placed=0, onTime=0, done=0, cancels=0, pna=0)} for _ in range(n)]
    for key, w in (("S", sess.smart), ("X", sess.static)):
        for o in w.by_id.values():
            b = out[min(n - 1, o.placed // 600)][key]
            b["placed"] += 1
            if o.status == "done":
                b["done"] += 1
                if o.handed_at <= max(o.D, o.rider_arrive):
                    b["onTime"] += 1
            if o.status == "cancelled":
                b["cancels"] += 1
            for it in o["items"]:
                if it.get("pna"):
                    b["pna"] += 1
    return out


def rider_bay(w):
    """Riders at the store: waiting for a bag, leaving with one (last 40 s), or arriving in the next 2 minutes."""
    t, wait, leave, come = w.t, [], [], []
    for o in w.orders:
        if o.status == "done":
            if t - o.handed_at < 40:
                leave.append({"id": o.id, "ago": t - o.handed_at})
            continue
        if o.status == "cancelled":
            continue
        if o.rider_arrive <= t:
            wait.append({"id": o.id, "wait": t - o.rider_arrive, "ready": o.status == "ready"})
        elif o.rider_arrive - t <= 120:
            come.append({"id": o.id, "eta": o.rider_arrive - t})
    wait.sort(key=lambda r: -r["wait"])
    come.sort(key=lambda r: r["eta"])
    leave.sort(key=lambda r: r["ago"])
    return {"waiting": wait, "leaving": leave, "arriving": come}


def build_snapshot(sess, with_ceo=True):
    w, X, t = sess.smart, sess.static, sess.smart.t
    pickers = []
    for p in w.pickers:
        if p.leave_at and t >= p.leave_at and not (p.trip and not p.trip.done):
            continue
        o = {"name": p.name, "floater": p.floater, "joining": p.join_at > t,
             "trip": s_trip(p.trip) if p.trip and not p.trip.done else None}
        if p.gig:
            o.update(gig=True, join_at=p.join_at, leave_at=p.leave_at)
        pickers.append(o)
    orders = []
    for o in w.active_orders():
        row = {"id": o.id, "user": o.user, "status": o.status, "riderIn": o.rider_arrive - t,
               "items": sum(1 for i in o["items"] if i.st != "dropped"), "swapped": sum(1 for i in o["items"] if i.get("from")),
               "boost": o.id in w.priority}
        if o.status in ("pool", "picking"):
            row["slack"] = round(w.slack_of(o))
        orders.append(row)
    orders.sort(key=lambda r: (r.get("slack", 1e6), r["riderIn"]))
    keys = ["id", "name", "aisle", "slot", "temp", "price", "cat", "shelf", "record", "backroom", "trust", "hidden", "status", "fwd", "counting"]
    skus = [{k: s[k] for k in keys} for s in w.skus.values()]
    swaps = {}
    for sid in CHECKOUT_ITEMS:
        alt = w.swap_candidate(w.skus[sid])
        swaps[sid] = {"id": alt.id, "name": alt.name, "price": alt.price} if alt else None
    cong = [0] * 9
    for tr in w.trips:
        if not tr.done and tr.end > t:
            for x in tr.aisles:
                cong[x] += 1
    snap = {
        "type": "snap", "t": t, "clock": fmt(t), "horizon": HORIZON, "speed": sess.speed, "playing": sess.playing,
        "layer": sess.layer, "llmOn": sess.llm_on, "autoApprove": sess.auto_approve, "demo": sess.demo,
        "thinking": sess.thinking, "llm": sess.llm.health(), "mode": w.mode, "lim": w.lim, "limits": LIMITS,
        "methods": MODE_METHOD, "uNow": round(w.u_now, 3), "uFc": round(w.u_fc, 3), "N": len(w.active_pickers()),
        "down": w.down, "buffer": BUFFER, "arrMin": w.arr_min[:t // 60 + 1], "skus": skus, "pickers": pickers,
        "bench": {"q": len(w.bench.q), "ready": len(w.bench.ready)},
        "riders": sum(1 for o in w.active_orders() if o.rider_arrive <= t),
        "orders": orders[:40], "activeCount": len(orders), "pool": len(w.pool), "stats": s_stats(w), "staticStats": s_stats(X),
        "log": sess.logs[:150], "decisions": w.decisions[:10], "approvals": w.approvals, "brief": w.brief,
        "story": sess.story, "trace": sess.bus.trace[:40],
        "agents": {n: a.public_stats() for n, a in sess.agents.items()}, "busCounts": dict(sess.bus.counts),
        "links": dict(sess.bus.links), "chains": sess.bus.chains[:12],
        "stateRows": state_rows(sess), "releasePolicy": w.release_policy, "swaps": swaps, "checkout": CHECKOUT_ITEMS,
        "riderBay": rider_bay(w),
        "riderFeed": sorted([{"id": o.id, "eta": o.rider_arrive - t, "delta": o.get("eta_delta") or 0, "status": o.status}
                             for o in w.active_orders() if o.rider_arrive > t - 600], key=lambda r: r["eta"])[:24],
        "etaLive": sess.eta_drift, "levers": w.levers,
        "slotting": {"on": w.dyn_slot and w.levers["slotting"], "front": w.front_on,
                     "list": [{"id": i, "name": w.skus[i].name, "aisle": w.skus[i].aisle} for i in w.front_list],
                     "savedM": js_round(w.kpi["slotSaved"] * PX_M),
                     "savedPerOrder": round(w.kpi["slotSaved"] * PX_M / w.stats["pickN"], 1) if w.stats["pickN"] else 0},
        "congestion": {"aisles": cong[1:], "reroutes": w.stats["reroutes"], "savedS": js_round(w.kpi["rerouteSaved"])},
        "gig": {"auto": sess.ondemand, "rate": GIG["rate"], "leadS": GIG["leadS"], "maxOnFloor": GIG["maxOnFloor"],
                "maxSpend": GIG["maxSpend"], "spent": w.kpi["gigCost"], "hours": w.kpi["gigHours"], "onFloor": w.gig_on_floor(),
                "suggest": gig_suggest(w), "crew": [{"name": p.name, "join_at": p.join_at, "leave_at": p.leave_at} for p in w.pickers if p.gig]},
        "server": {"engine": "python", "llm": sess.llm.provider},
    }
    if with_ceo:
        snap["ceo"] = {"today": shift_counts(sess), "intraday": intraday(sess)}
    return snap
