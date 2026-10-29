"""pytest -q   (21 scenario tests + server + parity with the original in-browser engine)"""
import asyncio
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core import selftest
from app.server.app import app

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("name,fn", selftest.TESTS, ids=[n for n, _ in selftest.TESTS])
def test_scenario(name, fn):
    ok, detail = asyncio.run(fn())
    assert ok, detail


def test_server_websocket_session():
    c = TestClient(app)
    assert c.get("/api/health").json()["ok"]
    agents = c.get("/api/agents").json()["agents"]
    assert set(agents) == {"ledger", "captain", "relay", "promise"}
    assert "window.SYNC_SERVER" in c.get("/").text
    with c.websocket_connect("/ws") as ws:
        snap = json.loads(ws.receive_text())
        assert snap["type"] == "snap" and snap["server"]["engine"] == "python" and snap["t"] >= 840
        ws.send_text(json.dumps({"cmd": "empty", "sku": "milk"}))
        seen_toast = False
        for _ in range(10):
            m = json.loads(ws.receive_text())
            seen_toast |= m["type"] == "toast" and "milk" in m["text"].lower()
            if seen_toast:
                break
        assert seen_toast


@pytest.mark.skipif(not shutil.which("node") or not (ROOT / "tools" / "engine.js").exists(), reason="node or engine.js missing")
def test_parity_with_browser_engine():
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "compare.py")], cwd=ROOT, capture_output=True, text=True, timeout=600)
    assert r.returncode == 0, r.stdout + r.stderr
