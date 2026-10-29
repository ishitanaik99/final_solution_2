"""A stand-in for Groq's chat API (tests only): answers like a sensible model would, with tool calls."""
import asyncio, json, random
from fastapi import FastAPI, Request
app = FastAPI()
N = {"n": 0}

def call(name, **a):
    a.setdefault("reason", "Model decision for the shift lead.")
    return {"id": "c%d" % random.randint(1, 10**9), "type": "function", "function": {"name": name, "arguments": json.dumps(a, ensure_ascii=False)}}

@app.post("/openai/v1/chat/completions")
async def chat(req: Request):
    body = await req.json(); N["n"] += 1
    await asyncio.sleep(0.25)
    if "tools" not in body:
        return {"choices": [{"message": {"content": json.dumps({"headline": "Fake brief: SyncStore cut cancellations.", "insights": [{"title": "Fewer cancels", "detail": "Cancels fell by half."}], "risks": [], "actions": []})}}], "usage": {"total_tokens": 300}}
    v = json.loads(body["messages"][1]["content"].split("\n", 1)[1]); ev = v.get("event"); names = {t["function"]["name"] for t in body["tools"]}
    calls = []
    if ev == "pick_not_found" and "hide_item" in names:
        sku = v["item"]["sku"]; calls = [call("set_trust", sku=sku, value=0.05), call("hide_item", sku=sku)]
        if not v["item"]["count_task_open"]: calls.append(call("create_count_task", sku=sku, mode="empty"))
    elif ev in ("pick_not_found", "sku_hidden") and "apply_swap" in names:
        alt = v.get("swap_option"); seen = set()
        for l in v["affected_lines"]:
            if l["customer_choice"] == "swap" and alt: calls.append(call("apply_swap", order_id=l["order_id"], sku=l["sku"], to_sku=alt["sku"]))
            else: calls.append(call("refund_item", order_id=l["order_id"], sku=l["sku"]))
            if l["order_id"] not in seen: seen.add(l["order_id"]); calls.append(call("notify_customer", order_id=l["order_id"], message="Sorry, an item ran out; we sorted it as you chose."))
    elif ev == "trust_drift": calls = [call("create_count_task", sku=v["item"]["sku"], mode="check")]
    elif ev == "count_result":
        c = v["count"]; sku = v["item"]["sku"]
        if c["counted_on_shelf"] != c["record_at_count"]: calls.append(call("correct_record", sku=sku, value=c["counted_on_shelf"]))
        if c["mode"] == "check": calls.append(call("set_trust", sku=sku, value=0.95))
        elif c["counted_on_shelf"] > 0: calls += [call("restore_item", sku=sku), call("set_trust", sku=sku, value=0.9)]
        elif c["backroom"] > 0: calls.append(call("trigger_refill", sku=sku, qty=min(16, c["backroom"])))
        else: calls.append(call("raise_reorder", sku=sku))
    elif ev == "mode_signal":
        calls = [call("set_mode", mode=v["suggested_mode"]), call("brief_shift_lead", hindi="मोड बदल रहा है, टीम तैयार रहे।", english="Mode change to %s; team, get ready." % v["suggested_mode"])]
    elif ev == "shift_summary":
        calls = [call("brief_shift_lead", hindi="शिफ्ट अच्छी रही।", english="Good shift: %s records caught." % v["numbers"]["wrong_records_caught"])]
    elif ev == "demand_forecast":
        s = v["ondemand"]["suggested"]; calls = [call("book_ondemand", count=s["count"], hours=s["hours"])]
    elif ev in ("rider_late", "eta_change", "bench_congested"):
        w = v.get("waiting_orders") or []
        if ev == "bench_congested": calls = [call("set_pacing", bench_cap=5, pace_slack=75), call("announce", message="Bench busy; holding orders with spare buffer.")]
        elif w: calls = [call("prioritise", order_id=w[0]["order_id"]), call("announce", message="#%d goes first." % w[0]["order_id"])]
        else: calls = [call("announce", message="Rider timing changed.")]
    if N["n"] % 9 == 0:   # now and then propose something unsafe, like a real model might
        calls.append(call("set_pacing", bench_cap=50) if "set_pacing" in names else call(next(iter(names)), sku="nope"))
    return {"choices": [{"message": {"role": "assistant", "tool_calls": calls or [call(next(iter(names)))]}}], "usage": {"total_tokens": 1800}}
