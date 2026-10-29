"""CAPTAIN: the shift lead's copilot. Warns of surges 15 minutes ahead and briefs in Hindi.

Owns: mode_and_limits, front_racks, approvals_and_brief.
Wakes on: mode_signal, demand_forecast, shift_summary. Senses: minute (utilisation now and in 15 min)."""
import math

from ..core.llm import tool
from ..sim.constants import GIG, LIMITS, MODE_LABEL, MODE_UP, MODES, OPS_BOUNDS, f2, pystr
from .base import Agent, req

MODE_HI = {"trough": "शांत", "normal": "सामान्य", "peak": "पीक", "surge": "सर्ज"}
CAPTAIN_PROMPT = """You are CAPTAIN, the shift-lead copilot. You own the store's operating mode and its limits,
the fast-mover front racks, staffing requests to the shift lead, and the Hindi voice briefing.

Modes: trough (discrete picking, 1 order per trolley, no hold), normal (cluster, up to 3, hold 30 s),
peak (cluster, up to 4, hold 75 s), surge (zone pick-and-merge, up to 4, hold 90 s).
Ops bounds you can never exceed: at most 4 orders per trolley, hold cap at most 90 s.
Thresholds on utilisation: below 0.50 trough, below 0.80 normal, else peak; 0.92 now or a backlog growing
3 minutes in a row means surge. Step down only one mode at a time and only after 3 calm minutes (the
input tells you when that is satisfied).

On mode_signal: decide with set_mode (and set_limits only if you want tighter limits than the mode
default). Going into peak or surge: move_fast_movers to the front, request_staff floater_in_store (and
floater_borrow for surge). Going down to normal or trough: move_fast_movers back. Always end with
brief_shift_lead: a short spoken briefing in Hindi (Devanagari script) plus its English meaning.
If the 15-minute forecast is high (0.85 or more) and on-demand pickers are available, book_ondemand hourly pickers
for the peak (count 1-4, hours 1-3); the shift lead approves the spend. On shift_summary: call brief_shift_lead once with a 2-sentence summary using the numbers given.
Never extend the 10-minute promise."""
STAFF = {"floater_in_store": "Call the in-store floater picker (Kiran) for the peak",
         "floater_borrow": "Borrow a floater picker from the nearby store (Neel, about 4 minutes away)"}


def gig_suggest(w):
    """How many hourly pickers would bring the 15-minute forecast back to about 0.80 utilisation."""
    n = max(1, len(w.active_pickers()))
    room = max(0, GIG["maxOnFloor"] - w.gig_on_floor())
    need = math.ceil(w.u_fc * n / 0.8 - n)
    return {"count": max(0, min(room, need)), "hours": 2 if w.u_fc >= 0.95 else 1, "uFc": w.u_fc, "pickers": n}


class Captain(Agent):
    name, title, tier = "captain", "Shift-lead copilot", "smart"
    triggers = frozenset({"mode_signal", "shift_summary", "demand_forecast"})
    senses = frozenset({"minute"})
    prompt = CAPTAIN_PROMPT

    def __init__(self):
        super().__init__()
        self._last_sig, self._last_target, self._last_gig = -999, None, -99999
        self.tools = [
            tool("set_mode", "Switch the store's operating mode (also resets limits to that mode's defaults).",
                 {"mode": {"type": "string", "enum": MODES}}, ["mode"]),
            tool("set_limits", "Tighten orders-per-trolley or the hold cap within ops bounds.",
                 {"max_batch": {"type": "integer"}, "hold_s": {"type": "integer"}}, []),
            tool("move_fast_movers", "Move chips, cola and popcorn to the front racks (true) or back (false).",
                 {"to_front": {"type": "boolean"}}, ["to_front"]),
            tool("request_staff", "Ask the shift lead to approve extra pickers.",
                 {"kind": {"type": "string", "enum": ["floater_in_store", "floater_borrow"]}}, ["kind"]),
            tool("book_ondemand", "Ask the shift lead to book on-demand pickers by the hour for the coming peak (they arrive in about 10 minutes).",
                 {"count": {"type": "integer"}, "hours": {"type": "integer"}}, ["count", "hours"]),
            tool("brief_shift_lead", "Speak a short briefing to the shift lead.",
                 {"hindi": {"type": "string", "description": "Devanagari, under 160 characters"}, "english": {"type": "string"}},
                 ["hindi", "english"]),
        ]

    def sense(self, ev, ctx):
        w, b = ctx.state.w, ev.backlog
        grow = len(b) == 4 and b[3] > b[2] > b[1] > b[0] and b[3] >= 6
        v = max(ev.u_now, ev.u_fc)
        target = "trough" if v < 0.5 else "normal" if v < 0.8 else "peak"
        if ev.u_now >= 0.92 or grow:
            target = "surge"
        ri, ti = MODES.index(w.mode), MODES.index(target)
        why = None
        if ti > ri:
            w.down = 0
            why = "backlog grew 3 minutes in a row" if (target == "surge" and grow) else "load is above the threshold"
        elif ti < ri:
            thr = MODE_UP[w.mode]
            w.down = w.down + 1 if v <= thr - 0.05 else 0
            if w.down >= 3:
                target = MODES[ri - 1]
                why = "load stayed 5 points below the threshold for 3 minutes"
        else:
            w.down = 0
        if why and (w.t - self._last_sig > 170 or self._last_target != target):
            self._last_sig, self._last_target = w.t, target
            w.emit("mode_signal", {"target": target, "direction": "up" if MODES.index(target) > ri else "down", "why": why,
                                   "u_now": ev.u_now, "u_fc": ev.u_fc, "backlog": b, "grow": grow})
        # High predicted demand: offer on-demand hourly pickers before the rush lands.
        if (ctx.rt.ondemand and ev.u_fc >= 0.85 and w.t - self._last_gig > 1200
                and not any(a.get("ondemand") and a["status"] == "pending" for a in w.approvals)):
            g = gig_suggest(w)
            if g["count"] > 0 and ctx.rt.gig_spend() + g["count"] * g["hours"] * GIG["rate"] <= GIG["maxSpend"]:
                self._last_gig = w.t
                w.emit("demand_forecast", {"u_fc": ev.u_fc, "u_now": ev.u_now, "count": g["count"], "hours": g["hours"],
                                           "pickers": g["pickers"]})

    def view(self, ev, ctx):
        w = ctx.state.w
        if ev.type == "shift_summary":
            return {"event": "shift_summary", "time": ctx.rt.clock(), "numbers": ev.numbers}
        if ev.type == "demand_forecast":
            return {"event": "demand_forecast", "time": ctx.rt.clock(), "forecast_15min": round(ev.u_fc, 2),
                    "utilisation_now": round(ev.u_now, 2), "pickers_on_floor": len(w.active_pickers()), "current_mode": w.mode,
                    "ondemand": {"rate_per_hour": GIG["rate"], "arrive_in_min": GIG["leadS"] / 60, "on_floor": w.gig_on_floor(),
                                 "max_on_floor": GIG["maxOnFloor"], "spent": ctx.rt.gig_spend(), "budget": GIG["maxSpend"],
                                 "suggested": {"count": ev.count, "hours": ev.hours}}}
        return {"event": "mode_signal", "time": ctx.rt.clock(), "current_mode": w.mode, "current_limits": w.lim,
                "suggested_mode": ev.target, "direction": ev.direction, "why": ev.why,
                "utilisation_now": round(ev.u_now, 2), "forecast_15min": round(ev.u_fc, 2), "backlog_last_4_min": ev.backlog,
                "pickers_on_floor": len(w.active_pickers()), "calm_minutes_for_step_down": w.down, "ops_bounds": OPS_BOUNDS,
                "ondemand": {"rate_per_hour": GIG["rate"], "on_floor": w.gig_on_floor(), "max_on_floor": GIG["maxOnFloor"],
                             "spent": ctx.rt.gig_spend(), "budget": GIG["maxSpend"], "suggested": gig_suggest(w)} if ctx.rt.ondemand else None,
                "fast_movers_in_front": any(s.fwd for s in w.skus.values()),
                "staff_already_requested": [a["id"] for a in w.approvals]}

    def required(self, ev, ctx):
        if ev.type == "shift_summary":
            return {"brief_shift_lead"}
        if ev.type == "demand_forecast":
            return set()
        return {"set_mode", "brief_shift_lead"} if ev.direction == "up" else set()

    def rules(self, ev, ctx):
        w = ctx.state.w
        if ev.type == "shift_summary":
            n = ev.numbers
            return [("brief_shift_lead", {
                "english": "Shift summary: %s wrong stock records caught, %s customer-chosen swaps applied, orders shared a trolley %s times, and about %s m of walking saved against the static plan."
                           % (n["wrong_records_caught"], n["customer_chosen_swaps"], n["shared_trolley_trips"], n["walking_saved_m"]),
                "hindi": "शिफ्ट सारांश: %s गलत स्टॉक रिकॉर्ड पकड़े गए, %s ग्राहकों की चुनी हुई अदला-बदली हुई, और लगभग %s मीटर पैदल चलना बचा।"
                         % (n["wrong_records_caught"], n["customer_chosen_swaps"], n["walking_saved_m"])})]
        if ev.type == "demand_forecast":
            n, h = ev.count, ev.hours
            return [("book_ondemand", {"count": n, "hours": h}), ("brief_shift_lead", {
                "english": "Demand forecast %s in 15 minutes with %s pickers. I asked to book %s on-demand picker%s for %s h; they arrive in 10 minutes."
                           % (f2(ev.u_fc), ev.pickers, n, "s" if n > 1 else "", h),
                "hindi": "अगले 15 मिनट में ऑर्डर बढ़ेंगे। %s घंटे वाले पिकर %s घंटे के लिए बुलाने की मंज़ूरी माँगी है।" % (n, h)})]
        m = ev.target
        fc = "utilisation %s now, %s forecast in 15 min" % (f2(ev.u_now), f2(ev.u_fc))
        plan = [("set_mode", {"mode": m})]
        if ev.direction == "up":
            if m in ("peak", "surge"):
                plan.append(("move_fast_movers", {"to_front": True}))
                plan.append(("request_staff", {"kind": "floater_in_store"}))
            if m == "surge":
                plan.append(("request_staff", {"kind": "floater_borrow"}))
            if ctx.rt.ondemand and ev.u_fc >= 0.85 and m in ("peak", "surge"):
                g = gig_suggest(w)
                if g["count"]:
                    plan.append(("book_ondemand", {"count": g["count"], "hours": g["hours"]}))
            if m == "peak":
                plan.append(("brief_shift_lead", {"english": "Peak mode: %s. Batches up to 4, hold cap 75 s. Chips, cola and popcorn to the front racks." % fc,
                                                  "hindi": "पीक मोड शुरू हो रहा है। फ्लोटर को तैयार रखिए, और चिप्स, कोला, पॉपकॉर्न आगे वाले रैक पर रखिए।"}))
            elif m == "surge":
                plan.append(("brief_shift_lead", {"english": "Surge mode: %s. Zone pick-and-merge is on. The 10-minute promise is not extended." % ev.why,
                                                  "hindi": "सर्ज मोड चालू है। ज़ोन पिकिंग शुरू। दस मिनट का वादा नहीं बदलेगा।"}))
            else:
                plan.append(("brief_shift_lead", {"english": "%s mode: %s." % (MODE_LABEL[m], fc), "hindi": MODE_HI[m] + " मोड।"}))
        else:
            if m in ("normal", "trough"):
                plan.append(("move_fast_movers", {"to_front": False}))
            plan.append(("brief_shift_lead", {"english": "%s mode: %s, so the store steps down one mode (hysteresis)." % (MODE_LABEL[m], ev.why),
                                              "hindi": "लोड कम हो रहा है। अब %s मोड।" % MODE_HI[m]}))
        return plan

    def execute(self, name, a, ctx):
        st, w, ev = ctx.state, ctx.state.w, ctx.event
        if name == "set_mode":
            prev, mode = w.mode, req(a, "mode")
            if mode == prev:
                return None
            st.set_mode(self.name, mode)
            up = MODES.index(mode) > MODES.index(prev)
            story = ("surge" if mode == "surge" else "peak" if mode == "peak" else None) if up else "winddown"
            lim = LIMITS[mode]
            return ("%s → %s mode (%s). Up to %d orders per trolley, hold cap %d s."
                    % (MODE_LABEL[prev], MODE_LABEL[mode], ev.get("why"), lim["max"], lim["hold"]), None, story)
        if name == "set_limits":
            st.set_limits(self.name, a.get("max_batch"), a.get("hold_s"))
            return "Limits tightened: up to %d per trolley, hold cap %d s." % (w.lim["max"], w.lim["hold"])
        if name == "move_fast_movers":
            on = bool(req(a, "to_front"))
            if any(s.fwd for s in w.skus.values()) == on:
                return None
            st.set_front_racks(self.name, on)
            return "Asked for chips, cola and popcorn to move to the front racks." if on else "Fast movers go back to their home slots."
        if name == "request_staff":
            kind = req(a, "kind")
            if st.request_approval(self.name, kind, STAFF[kind]):
                return "Above my limits, so I asked the shift lead: %s." % STAFF[kind]
            return None
        if name == "book_ondemand":
            n, h = int(req(a, "count")), int(req(a, "hours"))
            u = ev.get("u_fc") or 0
            if st.request_on_demand(self.name, n, h, "forecast %s in 15 min" % f2(u)):
                return ("Forecast is high (%s in 15 min), so I asked the shift lead to book %d on-demand picker%s for %d h at ₹%d an hour."
                        % (f2(u), n, "s" if n > 1 else "", h, GIG["rate"]))
            return None
        if name == "brief_shift_lead":
            st.set_brief(self.name, req(a, "hindi"), req(a, "english"))
            return (a["english"], a["hindi"], "summary" if ev.type == "shift_summary" else None)
        raise ValueError(name)

    def describe(self, name, a, ctx):
        m = {"set_mode": "Switch to %s mode." % pystr(a.get("mode")),
             "set_limits": "Set limits %s per trolley, hold %s s." % (pystr(a.get("max_batch")), pystr(a.get("hold_s"))),
             "move_fast_movers": "Move fast movers to the front." if a.get("to_front") else "Move fast movers back.",
             "book_ondemand": "Book %s on-demand pickers for %s h." % (pystr(a.get("count")), pystr(a.get("hours"))),
             "request_staff": "Ask the shift lead: %s." % STAFF.get(a.get("kind"), pystr(a.get("kind"))),
             "brief_shift_lead": "Brief: %s" % pystr(a.get("english"))}
        return m.get(name, name)
