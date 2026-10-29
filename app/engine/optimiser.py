"""Fast optimiser: plain code, not an agent. Runs every 5 sim-seconds.

Rider-first release order, savings-based batching (save(i, j) = route i + route j - combined),
hard time-buffer limit, release pacing set by Relay, limits set by Captain, zone pick-and-merge in surge."""
from ..sim.constants import BUFFER, PACK, mmss
from ..sim.world import open_skus


def optimiser_run(w):
    t = w.t
    idle = [p for p in w.active_pickers() if not p.trip]
    if not idle or not w.pool:
        return
    w.pool = [o for o in w.pool if o.status == "pool"]
    info = {}
    for o in w.pool:
        ids = open_skus(o)
        d = w.est_dur(ids)
        info[o.id] = {"ids": ids, "d": d, "slack": min(o.D, o.rider_arrive) - t - d - PACK}

    def boost(o):
        return 0 if o.id in w.priority else 1

    has_ids = [o for o in w.pool if info[o.id]["ids"]]
    if w.levers["riderFirst"]:
        cand = sorted(has_ids, key=lambda o: info[o.id]["slack"] - (60 if boost(o) == 0 else 0))
    else:
        cand = sorted(has_ids, key=lambda o: o.placed)
    rp = w.release_policy
    if len(w.bench.q) >= rp["bench_cap"]:
        before = len(cand)
        cand = [o for o in cand if info[o.id]["slack"] <= rp["pace_slack"]]
        if len(cand) < before and t - w._last_pace > 120:
            w._last_pace = t
            w.emit("log", {"agent": "relay", "via": "policy",
                           "text": "Packing bench has %d bags waiting. Holding %d orders that still have more than %d s"
                                   " of buffer, so bags don’t pile up." % (len(w.bench.q), before - len(cand), rp["pace_slack"])})
    zone_mode = w.mode == "surge"
    while idle and cand:
        seed = cand[0]
        batch = [seed]
        ids = set(info[seed.id]["ids"])
        max_b = w.lim["max"] if w.levers["batching"] else 1
        while len(batch) < max_b:
            best, best_save, best_ids = None, 0, None
            cur_len = w.route_length(ids)
            for c in cand:
                if c in batch:
                    continue
                ci = info[c.id]
                u = ids | set(ci["ids"])
                if len(u) > 9:
                    continue
                u_len = w.route_length(u)
                save = cur_len + w.route_length(ci["ids"]) - u_len
                if save <= 20:
                    continue
                u_dur = u_len / 28 + 10 * len(u)
                ok = all(info[m.id]["slack"] - (u_dur - info[m.id]["d"]) >= BUFFER for m in batch + [c])
                if ok and save > best_save:
                    best, best_save, best_ids = c, save, u
            if not best:
                break
            batch.append(best)
            ids = best_ids
        min_slack = min(info[m.id]["slack"] for m in batch)
        waited = t - seed.placed
        full = len(batch) >= max_b
        urgent = min_slack <= BUFFER + 45
        time_up = waited >= w.lim["hold"]
        if not (full or urgent or time_up):
            break
        if urgent and not full and not time_up and w.lim["hold"] > 30:
            w.stats["bufferHolds"] += 1
            if t - w._last_conflict > 300 and min_slack > 0:
                w._last_conflict = t
                w.stats["conflicts"] += 1
                w.emit("log", {"agent": "captain", "via": "rule",
                               "text": "Conflict settled: the optimiser wanted to hold #%d for a better batch, but Relay"
                                       " reports its time buffer is down to %d s. Rule 2 (customer promise) beats rule 4"
                                       " (efficiency), so #%d was released." % (seed.id, max(0, round(min_slack)), seed.id)})
        oldest = min(w.pool, key=lambda o: o.placed)
        if seed is not oldest and t - w._last_relay > 240 and seed.rider_arrive < oldest.rider_arrive - 30:
            w._last_relay = t
            w.emit("log", {"agent": "relay", "via": "policy", "story": "riderfirst",
                           "text": "Released #%d ahead of older #%d: its rider arrives in %s, while #%d’s rider is %s away."
                                   % (seed.id, oldest.id, mmss(seed.rider_arrive - t), oldest.id, mmss(oldest.rider_arrive - t))})
        for b in batch:
            w.pool.remove(b)
            cand.remove(b)
        solo = sum(w.route_length(info[b.id]["ids"]) for b in batch)
        union_len = w.route_length(ids)
        save_pct = round((1 - union_len / solo) * 100) if len(batch) > 1 and solo else 0
        if full:
            reason = "Trolley full (%d totes)" % len(batch)
        elif urgent:
            reason = "Time buffer of #%d down to %d s" % (seed.id, max(0, round(min_slack)))
        elif w.lim["hold"] == 0:
            reason = "Quiet hours: pick at once"
        else:
            reason = "Held %d s; no better partner arrived" % waited
        used = []
        if zone_mode and len(idle) >= 2:
            has_a = any(w.skus[i].aisle <= 4 for i in ids)
            has_b = any(w.skus[i].aisle > 4 for i in ids)
            if has_a:
                pa = idle.pop(0)
                used.append(pa)
                w.plan_trip(pa, batch, {1, 2, 3, 4}, "A")
            if has_b:
                pb = idle.pop(0)
                used.append(pb)
                w.plan_trip(pb, batch, {5, 6, 7, 8}, "B")
            method = "Zone pick-and-merge"
        else:
            p = idle.pop(0)
            used.append(p)
            w.plan_trip(p, batch, None)
            method = "Discrete" if len(batch) == 1 else "Cluster"
        w.decisions.insert(0, {"t": t, "ids": [o.id for o in batch], "method": method, "reason": reason,
                               "save": save_pct, "pickers": [p.name for p in used]})
        del w.decisions[30:]
        w.stats["batches"] += 1
        w.stats["batchedOrders"] += len(batch)
