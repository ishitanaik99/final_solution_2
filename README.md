---
title: SyncStore
emoji: 🛒
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 7860
pinned: false
short_description: Four AI agents run a dark store at peak
---

# SyncStore: four AI agents that keep a dark store's plan live

Team Problem Breakers · Abhikalp 2026 · Round 2 · Case 4 (Quick Commerce & Dark Store Logistics)

At the 8 PM rush a fixed pick plan sends pickers to empty shelves and gets paid orders cancelled.
SyncStore runs four agents (**Ledger, Captain, Relay, Promise**) and a fast optimiser on top of the store,
so every failed pick becomes a fix before it costs an order.

**Sign in** with a demo account shown on the sign-in page (password `SyncStore@2026`), then press
**Controls → Replay peak hour**.

## Architecture

```
Browser (control room)  ── commands ──▶  FastAPI  /ws  (one store session per tab)
                        ◀─ snapshots 4/s ─┘
Store session
  Simulator ─ events ─▶ Event bus ─▶ Ledger · Captain · Relay · Promise ─▶ Groq LLM (proposes tool calls only)
                           ▲                      │
                           │               Guardrails (hard limits, checked in code)
                           │                      ▼
                           └──── events ◀── Shared store state (one writer per field) ──▶ Fast optimiser (every 5 s)
```

**How the agents stay in sync.** Agents never call each other. They meet in one shared store state where
each field has exactly one writer (any other writer raises `OwnershipError`). A write can raise the next event,
and the bus routes it to the next agent. Example chain, live in the *How agents sync* view:

`pick_not_found` → **Ledger** sets trust 0.10, hides milk, sends a count → its write emits `sku_hidden`
→ **Promise** swaps the lines whose customers chose a swap and refunds the rest → the optimiser re-routes →
the count comes back → **Ledger** corrects the record and refills.

| Agent | Owns (writes) | Wakes on | Tools | Model tier |
|---|---|---|---|---|
| Ledger | trust, visibility, record, counts and refills | pick_not_found, trust_drift, count_result, refill_done | set_trust, hide_item, lower_aisle_trust, create_count_task, correct_record, trigger_refill, restore_item, raise_reorder | fast |
| Captain | mode and limits, front racks, approvals and briefing | mode_signal, demand_forecast, shift_summary | set_mode, set_limits, move_fast_movers, request_staff, book_ondemand, brief_shift_lead | smart |
| Relay | release policy, priority | rider_late, eta_change, bench_congested, bench_cleared | prioritise, set_pacing, announce | fast |
| Promise | order items, customer messages | pick_not_found, sku_hidden | apply_swap, refund_item, notify_customer | smart |

**Every decision in six steps:** sense → compact JSON view → Groq replies with tool calls only →
guardrails check each call → approved calls write the shared state, with a reason → if Groq is slow (over 8 s),
rate-limited or down, the rules decide and the store keeps running. If the model skips a required step
(for example, it forgets to hide an empty item), the rules fill it in.

**Conflict rules:** 1 safety, 2 customer promise (the 10-minute promise is never extended), 3 complete basket,
4 efficiency.

## Run locally

```bash
pip install -r requirements.txt
export GROQ_API_KEY=gsk_...          # optional: without it the agents use their rules
uvicorn app.server.app:app --port 8000
# open http://localhost:8000
```

Opening `static/index.html` directly as a file also works: the same engine then runs in the browser.

## Deploy (hosted link for judges)

**Hugging Face Spaces (recommended: free, no Git, stays awake for 48 h after the last visit)**
1. huggingface.co → **New Space** → name `syncstore`, SDK **Docker** → *Blank*, hardware **CPU basic (free)**, Public.
2. **Files → Add file → Upload files**: drag in everything in this folder (`app/`, `static/`, `Dockerfile`,
   `requirements.txt`, `README.md`, …) → **Commit**.
3. **Settings → Variables and secrets → New secret**: `GROQ_API_KEY` = your key. The Space restarts.
4. Share `https://<your-username>-syncstore.hf.space` (the direct link, full screen).

**Render (alternative; the free plan sleeps after 15 minutes, so open the link a minute before judging)**
Push this folder to a GitHub repo → render.com → **New → Blueprint** → pick the repo → paste `GROQ_API_KEY`.
`render.yaml` sets everything else.

| Variable | Default | Meaning |
|---|---|---|
| `GROQ_API_KEY` | – | Groq key. Never commit it; set it as a secret. |
| `GROQ_MODEL_SMART` | `llama-3.3-70b-versatile` | Captain and Promise. Falls back along a chain if retired or rate-limited. |
| `GROQ_MODEL_FAST` | `llama-3.1-8b-instant` | Ledger and Relay. |
| `GROQ_RPM` / `GROQ_RPD` | 25 / 900 | Budgets shared by every viewer, so one key survives a room of judges. |
| `LLM_TIMEOUT_S` | 8 | Slower than this → rules decide. |
| `MAX_SESSIONS` | 30 | Beyond this, extra tabs run the engine in their browser. |

## Tests

`pytest -q` runs 23 tests: the 21 scenario tests, a WebSocket server test, and a parity test that runs the
original in-browser engine (`tools/engine.js`, needs Node) and this Python engine on five seeds and checks every
counter and every log line match. The same 21 scenarios run from **How agents sync → Run system check**.

## API

| Endpoint | |
|---|---|
| `GET /` | Control room |
| `WS /ws` | Live store session |
| `GET /api/agents` | The four agents: prompts, tools, triggers, owned fields, routes |
| `GET /api/health` | Status, sessions, Groq usage |
| `POST /api/selftest` | Run the system check |
| `POST /api/brief` | CEO view's written brief |

The store, orders and demand are simulated (MUM-114, Andheri East, evening peak). Lever sizes are team
estimates that the pilot would test.

## Live demo on GitHub Pages

This repo is set up for GitHub Pages: **Settings → Pages → Deploy from a branch → `main` / `(root)`**.
The root `index.html` opens `static/index.html`, where the store, the agents' rules and the optimiser run in the browser.
To use the LLM on GitHub Pages: sign in, open **Controls**, click **Connect to LLM** and paste a Groq API key
(free at console.groq.com). The key is saved only in that browser and sent only to api.groq.com; it is never
stored in this repository. The agents then decide with Groq (rules stay as the backup) and the CEO brief is
written by Groq. The system check still needs the Python server (see `render.yaml`).
