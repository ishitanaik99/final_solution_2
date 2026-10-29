"""SyncStore server: FastAPI + one store session per browser tab over a WebSocket.

GET  /                 the control room (static/index.html), told to use this server
WS   /ws               snapshots ~4/s out, user commands in
GET  /api/health       liveness + LLM status (Render health check)
GET  /api/agents       the four agents: tools, triggers, owned fields, prompts, routes
POST /api/selftest     run the system check (21 scenario tests) and return the results
POST /api/brief        CEO view: a written brief from the LLM (JSON)"""
import asyncio
import json
import os
import time
from pathlib import Path

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import HTMLResponse, JSONResponse

from ..core import selftest
from ..core.bus import ROUTES
from ..core.llm import CHARTER, LLMUnavailable, make_llm
from ..core.runtime import Session
from ..core.state import OWNERSHIP
from ..sim.constants import GIG, HORIZON, inr
from .snapshot import build_snapshot

ROOT = Path(__file__).resolve().parents[2]
INDEX = ROOT / "static" / "index.html"
MAX_SESSIONS = int(os.environ.get("MAX_SESSIONS", "30"))
OPTS = {"ondemand": True, "slotting": True, "etaDrift": True}

app = FastAPI(title="SyncStore", version="2.0")
app.add_middleware(GZipMiddleware, minimum_size=2000)
LLM = make_llm()
SESSIONS = {}
STARTED = time.time()
_selftest_lock = asyncio.Lock()
_selftest_cache = {"at": 0, "results": None}


def _index_html():
    html = INDEX.read_text(encoding="utf-8")
    cfg = {"server": True, "llm": LLM.provider, "models": LLM.models, "configured": LLM.configured}
    tag = "<script>window.SYNC_SERVER=%s;</script>" % json.dumps(cfg)
    return html.replace("<head>", "<head>" + tag, 1)


@app.get("/", response_class=HTMLResponse)
async def index():
    return HTMLResponse(_index_html(), headers={"Cache-Control": "no-store"})


@app.get("/api/health")
async def health():
    return {"ok": True, "engine": "python", "uptime_s": round(time.time() - STARTED), "sessions": len(SESSIONS),
            "max_sessions": MAX_SESSIONS, "llm": LLM.health()}


@app.get("/api/agents")
async def agents():
    s = Session(LLM, 7, OPTS)
    out = {}
    for name, a in s.agents.items():
        out[name] = {"title": a.title, "tier": a.tier, "model": LLM.models.get(a.tier), "triggers": sorted(a.triggers),
                     "senses": sorted(a.senses), "owns": [f for f, o, _ in OWNERSHIP if o == name],
                     "tools": [t["function"] for t in a.tools], "prompt": a.prompt}
    return {"charter": CHARTER, "agents": out, "routes": ROUTES,
            "ownership": [{"field": f, "owner": o, "readers": r} for f, o, r in OWNERSHIP],
            "conflict_rules": ["1 Safety and compliance", "2 Customer promise (10 minutes, never extended)",
                               "3 Complete basket (or the swap the customer chose)", "4 Efficiency"]}


@app.post("/api/selftest")
async def run_selftest():
    async with _selftest_lock:
        if _selftest_cache["results"] is None or time.time() - _selftest_cache["at"] > 20:
            t0 = time.perf_counter()
            res = await selftest.run_all()
            _selftest_cache.update(at=time.time(), results={"results": res, "passed": sum(r["ok"] for r in res),
                                                            "total": len(res), "ms": round((time.perf_counter() - t0) * 1000)})
    return _selftest_cache["results"]


@app.post("/api/brief")
async def brief(req: Request):
    try:
        body = await req.json()
        prompt = str(body.get("prompt", ""))[:12000]
    except ValueError:
        return JSONResponse({"error": "bad request"}, status_code=400)
    if not prompt:
        return JSONResponse({"error": "empty prompt"}, status_code=400)
    try:
        return await LLM.complete_json(prompt, "smart")
    except LLMUnavailable as e:
        return JSONResponse({"error": str(e)}, status_code=503)


# ---------------------------------------------------------------------------------------------- live sessions
class Live:
    def __init__(self, ws):
        self.ws = ws
        self.sess = Session(LLM, 7, OPTS)
        self.lock = asyncio.Lock()
        self.alive = True
        self.out = asyncio.Queue(maxsize=8)

    async def send(self, msg):
        try:
            self.out.put_nowait(msg)
        except asyncio.QueueFull:
            pass

    def toast(self, text):
        if text:
            try:
                self.out.put_nowait({"type": "toast", "text": text})
            except asyncio.QueueFull:
                pass

    async def writer(self):
        while self.alive:
            msg = await self.out.get()
            await self.ws.send_text(json.dumps(msg, ensure_ascii=False, separators=(",", ":"), default=str))

    async def snapper(self):
        while self.alive:
            await asyncio.sleep(0.25)
            if self.out.qsize() < 3:
                await self.send(build_snapshot(self.sess))

    async def sim(self):
        last, acc = time.perf_counter(), 0.0
        while self.alive:
            await asyncio.sleep(0.05)
            now = time.perf_counter()
            dt = min(0.25, now - last)
            last = now
            s = self.sess
            if not s.playing:
                acc = 0
                continue
            acc += dt * s.speed
            n = int(acc)
            acc -= n
            for _ in range(n):
                async with self.lock:
                    await s.tick()
                if not s.playing:
                    break

    async def handle(self, msg):
        s, c, t = self.sess, msg.get("cmd"), None
        if c == "play":
            if not s.playing and s.smart.t >= HORIZON - 5:
                async with self.lock:
                    await s.reset(840)
                s.playing = True
            else:
                s.playing = not s.playing
        elif c == "speed":
            try:
                s.speed = max(1, min(60, int(msg.get("value") or 10)))
            except (TypeError, ValueError):
                pass
        elif c == "reset":
            async with self.lock:
                await s.reset(840)
            s.playing = True
            t = "Reset to 18:44."
        elif c == "demo":
            async with self.lock:
                await s.reset(480, True)
            s.speed, s.playing = 20, True
            t = "Peak hour replay started at 18:38. The steps light up at the top of the Overview."
        elif c == "layer" and msg.get("value") in ("live", "shadow", "off"):
            s.apply_layer(msg["value"])
        elif c == "llm":
            if not msg.get("value"):
                s.llm_on = False
                t = "Agents now decide with their rules only."
            elif not LLM.configured:
                t = "No LLM key is set on the server, so the agents use their rules."
            else:
                s.llm_on = True
                t = "Agents now decide with Groq (%s / %s). Guardrails check every call; rules take over if Groq is slow." % (
                    LLM.models["smart"], LLM.models["fast"])
        elif c == "empty" and msg.get("sku") in s.smart.skus:
            t = "%s: shelf emptied. The record still shows stock, so watch Ledger." % s.empty_shelf(msg["sku"])
        elif c == "late":
            try:
                oid = int(msg["order_id"]) if msg.get("order_id") else None
            except (TypeError, ValueError):
                oid = None
            oid = s.rider_late(oid)
            t = ("Rider for #%d is now 2 minutes late." % oid) if oid else "No order is waiting for a rider right now."
        elif c == "spike":
            s.spike()
            t = "14 extra orders are coming in over 6 minutes."
        elif c == "approve":
            s.approve(msg.get("id"), "from the dashboard")
        elif c == "decline":
            s.decline(msg.get("id"))
        elif c == "auto_approve":
            s.auto_approve = bool(msg.get("value"))
        elif c == "ondemand_auto":
            s.ondemand = bool(msg.get("value"))
            t = ("Captain will ask for on-demand pickers when the forecast is high." if s.ondemand
                 else "Captain will no longer ask for on-demand pickers.")
        elif c == "ondemand":
            w = s.smart
            try:
                n, h = int(msg.get("count") or 1), int(msg.get("hours") or 1)
            except (TypeError, ValueError):
                n, h = 1, 1
            if w.gig_on_floor() + n > GIG["maxOnFloor"]:
                t = "At most %d on-demand pickers can be on the floor at once." % GIG["maxOnFloor"]
            elif s.gig_spend() + n * h * GIG["rate"] > GIG["maxSpend"]:
                t = "That would go over the ₹%s on-demand budget for this shift." % inr(GIG["maxSpend"])
            else:
                ps = s.book_on_demand(n, h, "from the dashboard", False)
                t = ("Booked %s for %d h. They arrive in 10 minutes." % (", ".join(p.name for p in ps), h)) if ps \
                    else "Could not book on-demand pickers right now."
        elif c == "place":
            cart = msg.get("cart") or []
            oid = s.place_order(list(cart) if isinstance(cart, list) else [], dict(msg.get("choices") or {}))
            t = ("Order #%d placed. Follow it in Relay." % oid) if oid else None
        self.toast(t)
        await self.send(build_snapshot(self.sess))


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    if len(SESSIONS) >= MAX_SESSIONS:
        await ws.send_text(json.dumps({"type": "busy", "text": "The server is at its session limit; running in your browser instead."}))
        await ws.close()
        return
    live = Live(ws)
    SESSIONS[id(live)] = live
    tasks = []
    try:
        await live.sess.reset(840)
        await live.send(build_snapshot(live.sess))
        tasks = [asyncio.create_task(f()) for f in (live.writer, live.snapper, live.sim)]
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except ValueError:
                continue
            if isinstance(msg, dict):
                await live.handle(msg)
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        live.alive = False
        for tk in tasks:
            tk.cancel()
        SESSIONS.pop(id(live), None)
