"""Build static/index.html from the original control room.

Every change is an exact, counted replacement (the build fails if one does not apply), so the UI the
judges saw is kept and only the transport and the coordination view change:
  * SyncBridge: WebSocket to the Python server when served by it; the in-browser engine otherwise
  * Coordination: live agent-link graph, recent chains, and a 'Run system check' button
  * LLM labels follow the server's provider (Groq) instead of saying Claude"""
import sys
from pathlib import Path

src = Path(sys.argv[1]).read_text(encoding="utf-8")
out_path = Path(sys.argv[2])
html = src


def rep(old, new, count=1):
    global html
    n = html.count(old)
    if n != count:
        raise SystemExit("expected %d x %r, found %d" % (count, old[:90], n))
    html = html.replace(old, new)


# ---------------------------------------------------------------- 1. bridge: keep the local runtime, add the server one
rep("  window.SyncBridge = {\n    start: function (cb) {\n      onMsg = cb;",
    "  window.SyncLocalBridge = {\n    start: function (cb) {\n      onMsg = cb;")
SERVER_BRIDGE = r"""
<script>
/* Transport chooser. Served by the SyncStore Python server (window.SYNC_SERVER is set): the store, the four
   agents, the bus and Groq run on the server, and this page only renders snapshots from /ws. Opened as a
   plain file (or if the server can't be reached): the same engine runs in the browser. */
(function () {
  'use strict';
  var Local = window.SyncLocalBridge;
  if (!window.SYNC_SERVER) { window.SyncBridge = Local; return; }
  var ws = null, cb = null, fails = 0, local = false, opened = false, queue = [];
  function url() { return (location.protocol === 'https:' ? 'wss://' : 'ws://') + location.host + '/ws'; }
  function goLocal(why) {
    if (local) return; local = true;
    try { if (ws) ws.close(); } catch (e) {}
    if (cb) cb({ type: 'toast', text: why });
    Local.start(cb);
  }
  function open() {
    try { ws = new WebSocket(url()); } catch (e) { goLocal('WebSockets are blocked here, so the store runs in your browser.'); return; }
    ws.onopen = function () { opened = true; fails = 0; while (queue.length) ws.send(queue.shift()); };
    ws.onmessage = function (e) {
      var m; try { m = JSON.parse(e.data); } catch (x) { return; }
      if (m.type === 'busy') { goLocal(m.text); return; }
      if (cb) cb(m);
    };
    ws.onclose = function () {
      if (local) return;
      fails += 1;
      if (fails >= 5) { goLocal('Lost the SyncStore server, so the store now runs in your browser.'); return; }
      if (cb) cb({ type: 'conn', text: opened ? 'Reconnecting' : 'Waking the server' });
      setTimeout(open, Math.min(6000, 600 * fails));
    };
  }
  window.SyncServerSample = {
    json: function (prompt, opts) {
      return fetch('/api/brief', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ prompt: prompt }), signal: opts && opts.signal })
        .then(function (r) { return r.json().then(function (j) { if (!r.ok) { var c = /rate/.test(j.error || '') ? 'rate_limited' : /JSON/.test(j.error || '') ? 'invalid_json' : (j.error || 'error'); throw { code: c }; } return j; }); },
          function (e) { throw { code: e && e.name === 'AbortError' ? 'cancelled' : 'network' }; });
    }
  };
  window.SyncBridge = {
    start: function (c) { cb = c; open(); },
    send: function (o) {
      if (local) return Local.send(o);
      var s = JSON.stringify(o);
      if (ws && ws.readyState === 1) ws.send(s); else queue.push(s);
    }
  };
})();
</script>
"""
rep("    send: function (o) { try { handle(o); } catch (e) { console.error(e); } }\n  };\n})();\n\n</script>",
    "    send: function (o) { try { handle(o); } catch (e) { console.error(e); } }\n  };\n})();\n\n</script>" + SERVER_BRIDGE)

# ---------------------------------------------------------------- 2. connection pill + provider name helper
rep("  function send(o) { window.SyncBridge.send(o); }",
    "  function send(o) { window.SyncBridge.send(o); }\n"
    "  function LLMN() { var p = (D && D.llm && D.llm.provider) || (window.SYNC_SERVER && window.SYNC_SERVER.llm); return p === 'groq' || window.SYNC_SERVER ? 'Groq' : 'Claude'; }")
rep("      if (m.type === 'snap') { D = m; snapAt = performance.now(); if (!buildMap.done) buildMap(); setConn('Running in your browser', 'm-normal'); }\n      else if (m.type === 'toast') toast(m.text);",
    "      if (m.type === 'snap') { D = m; snapAt = performance.now(); if (!buildMap.done) buildMap(); setConn(m.server ? 'Python server · ' + (m.llmOn ? LLMN() + ' on' : 'rules') : 'Running in your browser', 'm-normal'); var lb = document.querySelector('[data-llm=\"1\"]'); if (lb && lb.textContent !== LLMN()) lb.textContent = LLMN(); }\n"
    "      else if (m.type === 'toast') toast(m.text);\n      else if (m.type === 'conn') setConn(m.text, 'm-off');")

# ---------------------------------------------------------------- 3. LLM labels
rep("var src = D.llmOn ? 'Claude · ' + model : 'Rules (Claude off)';",
    "var src = D.llmOn ? LLMN() + ' · ' + model : 'Rules (' + LLMN() + ' off)';")
rep("[[L.configured ? (D.llmOn ? 'On' : 'Off') : 'Not available', 'Claude']",
    "[[L.configured ? (D.llmOn ? 'On' : 'Off') : 'Not available', LLMN()]")
rep("The optimiser never calls the LLM. Turn Claude on under Demo controls → Decisions.</p>';",
    "The optimiser never calls the LLM. Turn ' + LLMN() + ' on under Demo controls → Decisions.' + (L.tokens ? ' ' + L.tokens.toLocaleString('en-IN') + ' tokens used.' : '') + '</p>'; var ls = document.getElementById('llmSub'); if (ls) ls.textContent = D.server ? LLMN() + ' on the SyncStore server; one key, shared budgets' : 'Claude, on your own account';\n    renderLinks();")
rep('<h3>LLM runtime</h3><span class="sub">Claude, on your own account</span>',
    '<h3>LLM runtime</h3><span class="sub" id="llmSub">Claude, on your own account</span>')
rep("Agents decide with ' + (D.llmOn ? 'Claude' : 'their rules')", "Agents decide with ' + (D.llmOn ? LLMN() : 'their rules')")
rep("c === 'rate_limited' ? 'Claude is busy. Try again in a minute.' : c === 'invalid_json' ? 'Claude’s answer couldn’t be read. Try again.' : 'Claude didn’t answer (' + (c || 'error') + '). Try again.';",
    "c === 'rate_limited' ? LLMN() + ' is busy. Try again in a minute.' : c === 'invalid_json' ? LLMN() + '’s answer couldn’t be read. Try again.' : LLMN() + ' didn’t answer (' + (c || 'error') + '). Try again.';")
rep("ai = '<p class=\"note\">Claude isn’t available in this view. Open the page on claude.ai to ask for a written brief.</p>';",
    "ai = '<p class=\"note\">' + (window.SYNC_SERVER ? 'No LLM key is set on the server, so written briefs are off. The computed insights still work.' : 'Claude isn’t available in this view. Open the page on claude.ai to ask for a written brief.') + '</p>';")
rep("<span>Claude is reading ", "<span>' + LLMN() + ' is reading ")
rep("Written by Claude from this page", "Written by ' + LLMN() + ' from this page")
rep("<p>Claude reads the selected period", "<p>' + LLMN() + ' reads the selected period")
rep("xcard('Claude brief',", "xcard(LLMN() + ' brief',")
rep("  try { if (window.claude && window.claude.use) window.claude.use('sample').then(function (s) { ceo.sample = s || null; }, function () { ceo.sample = null; }); else ceo.sample = null; } catch (e) { ceo.sample = null; }",
    "  if (window.SYNC_SERVER) ceo.sample = window.SYNC_SERVER.configured ? window.SyncServerSample : null;\n"
    "  else try { if (window.claude && window.claude.use) window.claude.use('sample').then(function (s) { ceo.sample = s || null; }, function () { ceo.sample = null; }); else ceo.sample = null; } catch (e) { ceo.sample = null; }")

# ---------------------------------------------------------------- 4. coordination: live links, chains, system check
rep('      <div class="card"><div class="card-h"><h3>Event bus</h3><span class="sub">Live: which agent handled which event, and how it decided</span></div><div class="card-b" id="trace"></div></div>',
    '      <div class="cols links-cols">\n'
    '        <div class="card"><div class="card-h"><h3>Agent links</h3><span class="sub">Live: who raised each event and which agent picked it up</span></div><div class="card-b" id="links"></div></div>\n'
    '        <div class="card"><div class="card-h"><h3>System check</h3><span class="sub">Automated tests of the agents working together</span></div><div class="card-b" id="selftest"></div></div>\n'
    '      </div>\n'
    '      <div class="card"><div class="card-h"><h3>Event bus</h3><span class="sub">Live: which agent handled which event, and how it decided</span></div><div class="card-b" id="trace"></div></div>')

LINKS_JS = r"""
  // ---------------------------------------------------------------- agent links (server build)
  var ST = { state: 'idle', res: null, err: '' };
  function renderLinks() {
    var box = document.getElementById('links'); if (!box) return;
    var L = D.links || null;
    if (!L) { box.innerHTML = '<p class="note">The live link graph needs the SyncStore server. In this view the same agents run in your browser; open the hosted link to see it.</p>'; renderSelftest(); return; }
    var P = { ledger: [170, 84], promise: [470, 84], captain: [170, 280], relay: [470, 280], hub: [320, 180] };
    var W = function (k) { return L[k] || 0; };
    var sumTo = function (agent) { var n = 0; for (var k in L) if (k.split('>')[2] === agent) n += L[k]; return n; };
    var s = '<svg class="lk" viewBox="0 0 640 372" role="img" aria-label="Agents linked through the shared store state">';
    s += '<defs><marker id="lkA" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="context-stroke"/></marker></defs>';
    ['ledger', 'promise', 'captain', 'relay'].forEach(function (a) {
      var p = P[a], h = P.hub, wr = 0, left = p[0] < h[0]; (D.stateRows || []).forEach(function (r) { if (r.owner === a) wr += r.writes || 0; });
      s += '<line class="lk-spoke" x1="' + p[0] + '" y1="' + p[1] + '" x2="' + h[0] + '" y2="' + h[1] + '"/>';
      var mx = (p[0] + h[0]) / 2, my = (p[1] + h[1]) / 2;
      s += '<text class="lk-w" x="' + (mx + (left ? -8 : 8)) + '" y="' + (my + 4) + '" text-anchor="' + (left ? 'end' : 'start') + '">' + wr + ' writes</text>';
    });
    var hn = W('ledger>sku_hidden>promise'), pfp = W('floor>pick_not_found>promise');
    s += '<path class="lk-ev' + (hn ? ' on' : '') + '" d="M212 84 L426 84" marker-end="url(#lkA)"/>';
    s += '<text class="lk-l" x="320" y="76" text-anchor="middle">sku_hidden ×' + hn + '</text>';
    s += '<path class="lk-ev' + (pfp ? ' on' : '') + '" d="M58 70 Q300 -6 440 52" marker-end="url(#lkA)"/>';
    s += '<text class="lk-l" x="250" y="22" text-anchor="middle">pick_not_found also reaches Promise ×' + pfp + '</text>';
    var pf = W('floor>pick_not_found>ledger');
    s += '<path class="lk-ev' + (pf ? ' on' : '') + '" d="M58 84 L126 84" marker-end="url(#lkA)"/>';
    s += '<text class="lk-l" x="20" y="142">pick_not_found ×' + pf + '</text>';
    s += '<text class="lk-l" x="20" y="158">count / refill ×' + (W('floor>count_result>ledger') + W('floor>refill_done>ledger')) + '</text>';
    s += '<path class="lk-ev' + (W('captain>mode_signal>captain') ? ' on' : '') + '" d="M58 280 L128 280" marker-end="url(#lkA)"/>';
    s += '<text class="lk-l" x="20" y="340">mode_signal ×' + W('captain>mode_signal>captain') + '</text>';
    s += '<text class="lk-l" x="20" y="356">forecast ×' + W('captain>demand_forecast>captain') + ' · summary ×' + W('clock>shift_summary>captain') + '</text>';
    var rl = W('rider app>rider_late>relay') + W('rider app>eta_change>relay'), bc = W('bench>bench_congested>relay') + W('bench>bench_cleared>relay');
    s += '<path class="lk-ev' + (rl || bc ? ' on' : '') + '" d="M582 280 L512 280" marker-end="url(#lkA)"/>';
    s += '<text class="lk-l" x="620" y="340" text-anchor="end">rider late / ETA ×' + rl + '</text>';
    s += '<text class="lk-l" x="620" y="356" text-anchor="end">packing bench ×' + bc + '</text>';
    s += '<g class="lk-hub"><rect x="246" y="156" width="148" height="48" rx="8"/><text x="320" y="177" text-anchor="middle">Shared store state</text><text class="lk-sub" x="320" y="193" text-anchor="middle">one writer per field</text></g>';
    s += '<line class="lk-spoke" x1="320" y1="204" x2="320" y2="300"/><g class="lk-opt"><rect x="262" y="300" width="116" height="30" rx="6"/><text x="320" y="319" text-anchor="middle">Optimiser · every 5 s</text></g>';
    var th = D.thinking && D.thinking.agent;
    ['ledger', 'promise', 'captain', 'relay'].forEach(function (a) {
      var p = P[a];
      s += '<g class="lk-node n-' + a + (th === a ? ' think' : '') + '"><circle cx="' + p[0] + '" cy="' + p[1] + '" r="40"/><text x="' + p[0] + '" y="' + (p[1] - 2) + '" text-anchor="middle">' + NAMES[a] + '</text><text class="lk-sub" x="' + p[0] + '" y="' + (p[1] + 14) + '" text-anchor="middle">' + sumTo(a) + ' events</text></g>';
    });
    s += '</svg>';
    var ch = (D.chains || []).slice(0, 5).map(function (c) { return '<li><span class="tm">' + fmtHM(c.t) + '</span><span>' + c.hops.map(esc).join(' · ') + '</span></li>'; }).join('');
    box.innerHTML = s + '<p class="note">Agents never call each other. A write to the shared state can raise the next event, and the bus routes it. ' +
      'Highlighted arrows have fired this shift.</p>' + (ch ? '<h4 class="lk-h">Recent multi-agent chains</h4><ul class="feed">' + ch + '</ul>' : '<p class="note">No multi-agent chain yet. Empty a shelf under Demo controls to start one.</p>');
    renderSelftest();
  }
  function renderSelftest() {
    var box = document.getElementById('selftest'); if (!box) return;
    if (!window.SYNC_SERVER) { box.innerHTML = '<p class="note">The system check runs the Python test suite on the SyncStore server. Open the hosted link to run it.</p>'; return; }
    var head = '<button class="btn primary small" type="button" id="stRun"' + (ST.state === 'run' ? ' disabled' : '') + '>' + (ST.state === 'run' ? 'Running…' : ST.res ? 'Run again' : 'Run system check') + '</button>';
    if (ST.err) head += ' <span class="bad-t">' + esc(ST.err) + '</span>';
    if (!ST.res) { box.innerHTML = head + '<p class="note">Runs ' + 21 + ' scenario tests on the server: agents linked through the shared state, guardrails, ownership, LLM failure and fallback, and SyncStore against today’s plan. Takes about 3 seconds.</p>'; return; }
    var r = ST.res;
    box.innerHTML = head + ' <b class="' + (r.passed === r.total ? 'good-t' : 'bad-t') + '">' + r.passed + '/' + r.total + ' passed</b> <span class="note">in ' + (r.ms / 1000).toFixed(1) + ' s</span>' +
      '<ul class="guard st-list">' + r.results.map(function (x) { return '<li><span class="ok' + (x.ok ? '' : ' alert') + '" aria-hidden="true">' + (x.ok ? '✓' : '!') + '</span><span><b>' + esc(x.name) + '</b><small>' + esc(x.detail) + '</small></span></li>'; }).join('') + '</ul>';
  }
  document.addEventListener('click', function (e) {
    if (!e.target.closest('#stRun') || ST.state === 'run') return;
    ST.state = 'run'; ST.err = ''; renderSelftest();
    fetch('/api/selftest', { method: 'POST' }).then(function (r) { return r.json(); }).then(function (j) { ST.res = j; ST.state = 'done'; renderSelftest(); },
      function () { ST.state = 'idle'; ST.err = 'Could not reach the server.'; renderSelftest(); });
  });
"""
rep("  // ---------------------------------------------------------------- log\n  function renderLog() {",
    LINKS_JS + "\n  // ---------------------------------------------------------------- log\n  function renderLog() {")

CSS = """
<style>
.links-cols { align-items: stretch; }
.lk { width: 100%; height: auto; display: block; }
.lk-spoke { stroke: var(--line); stroke-width: 2; stroke-dasharray: 4 4; }
.lk-ev { fill: none; stroke: var(--muted); stroke-width: 1.5; opacity: .35; }
.lk-ev.on { stroke: var(--promise); stroke-width: 2.5; opacity: 1; }
.lk-l, .lk-w { font-size: 11.5px; fill: var(--muted); font-family: var(--mono, ui-monospace, monospace); }
.lk-hub rect { fill: var(--panel-2, #f4f4f4); stroke: var(--line); }
.lk-hub text, .lk-opt text { font-size: 12.5px; font-weight: 600; fill: var(--ink, #222); }
.lk-opt rect { fill: var(--opt-bg); stroke: var(--opt); }
.lk-sub { font-size: 10.5px !important; font-weight: 400 !important; fill: var(--muted) !important; }
.lk-node circle { stroke-width: 2.5; }
.lk-node text { font-size: 13.5px; font-weight: 700; }
.n-ledger circle { fill: var(--ledger-bg); stroke: var(--ledger); } .n-ledger text { fill: var(--ledger); }
.n-promise circle { fill: var(--promise-bg); stroke: var(--promise); } .n-promise text { fill: var(--promise); }
.n-captain circle { fill: var(--captain-bg); stroke: var(--captain); } .n-captain text { fill: var(--captain); }
.n-relay circle { fill: var(--relay-bg); stroke: var(--relay); } .n-relay text { fill: var(--relay); }
.lk-node.think circle { stroke-dasharray: 6 4; animation: lkspin 1.2s linear infinite; }
@keyframes lkspin { to { stroke-dashoffset: -20; } }
.lk-h { margin: 12px 0 4px; font-size: 13px; }
.st-list { max-height: 520px; overflow: auto; margin-top: 10px; }
@media (prefers-reduced-motion: reduce) { .lk-node.think circle { animation: none; } }
</style>
"""
rep("</head><body>", CSS + "</head><body>")
rep("<title>SyncStore Control Room</title>", "<title>SyncStore Control Room</title>\n<meta name=\"description\" content=\"SyncStore: four AI agents (Ledger, Captain, Relay, Promise) running a quick-commerce dark store at peak.\">")

# ---------------------------------------------------------------- 5. rider bay: arriving, waiting and leaving riders
rep("      riderFeed: w.activeOrders().filter(o => o.rider_arrive > t - 600)",
    "      riderBay: (function () { const wait = [], leave = [], come = [];\n"
    "        for (const o of w.orders) {\n"
    "          if (o.status === 'done') { if (t - o.handed_at < 40) leave.push({ id: o.id, ago: t - o.handed_at }); continue; }\n"
    "          if (o.status === 'cancelled') continue;\n"
    "          if (o.rider_arrive <= t) wait.push({ id: o.id, wait: t - o.rider_arrive, ready: o.status === 'ready' });\n"
    "          else if (o.rider_arrive - t <= 120) come.push({ id: o.id, eta: o.rider_arrive - t });\n"
    "        }\n"
    "        wait.sort((a, b) => b.wait - a.wait); come.sort((a, b) => a.eta - b.eta); leave.sort((a, b) => a.ago - b.ago);\n"
    "        return { waiting: wait, leaving: leave, arriving: come }; })(),\n"
    "      riderFeed: w.activeOrders().filter(o => o.rider_arrive > t - 600)")
rep("    riderG.innerHTML = '';\n    for (var i = 0; i < Math.min(18, D.riders); i++) el('circle', { cx: 930 + (i % 2) * 36, cy: 125 + Math.floor(i / 2) * 42, r: 12, class: 'rider' }, riderG);\n    $('#riderCount').textContent = D.riders + (D.riders === 1 ? ' RIDER' : ' RIDERS');",
    "    riderG.innerHTML = '';\n"
    "    var RB = D.riderBay || { waiting: [], leaving: [], arriving: [] }, slots = [], i;\n"
    "    RB.waiting.forEach(function (r) { slots.push(['w', r]); }); RB.leaving.forEach(function (r) { slots.push(['l', r]); }); RB.arriving.forEach(function (r) { slots.push(['a', r]); });\n"
    "    for (i = 0; i < Math.min(18, slots.length); i++) {\n"
    "      var k = slots[i][0], r = slots[i][1], x = 930 + (i % 2) * 36, y = 146 + Math.floor(i / 2) * 40;\n"
    "      var g = el('g', { class: 'rb rb-' + k + (k === 'w' && r.wait > 30 ? ' rb-long' : '') }, riderG);\n"
    "      el('circle', { cx: x, cy: y, r: 12, class: 'rider' }, g);\n"
    "      if (k === 'l') el('rect', { x: x + 6, y: y - 2, width: 9, height: 11, rx: 2, class: 'bag' }, g);\n"
    "      var tt = el('title', {}, g); tt.textContent = '#' + r.id + (k === 'w' ? ': rider waiting ' + r.wait + ' s' + (r.ready ? ', bag ready' : ', bag not ready yet') : k === 'l' ? ': collected the bag, leaving' : ': rider arrives in ' + r.eta + ' s');\n"
    "      var lb = el('text', { x: x, y: y + 4, class: 'rb-t', 'text-anchor': 'middle' }, g); lb.textContent = k === 'a' ? r.eta + 's' : k === 'w' ? (r.wait > 0 ? r.wait + 's' : '') : '';\n"
    "    }\n"
    "    $('#riderCount').textContent = RB.waiting.length + ' WAITING';\n"
    "    var rcs = document.getElementById('riderSub'); if (rcs) rcs.textContent = RB.arriving.length + ' ARRIVING'; var rcl = document.getElementById('riderOut'); if (rcl) rcl.textContent = RB.leaving.length + ' LEAVING';")
rep("    txt(svg, 948, 94, '', 'mlabel', 'middle').setAttribute('id', 'riderCount');",
    "    txt(svg, 948, 94, '', 'mlabel', 'middle').setAttribute('id', 'riderCount');\n    txt(svg, 948, 108, '', 'mlabel rb-sub', 'middle').setAttribute('id', 'riderSub');\n    txt(svg, 948, 121, '', 'mlabel rb-sub', 'middle').setAttribute('id', 'riderOut');")
rep(".lk { width: 100%; height: auto; display: block; }",
    ".lk { width: 100%; height: auto; display: block; }\n"
    ".rb-a .rider { fill: var(--panel, #fff); stroke: var(--relay); stroke-width: 2; stroke-dasharray: 3 3; }\n"
    ".rb-l { opacity: .55; }\n"
    ".rb-long .rider { fill: var(--warn, #B7791F); }\n"
    ".rb-t { font-size: 9.5px; font-weight: 700; fill: #fff; pointer-events: none; }\n"
    ".rb-a .rb-t { fill: var(--relay); }\n"
    ".rb-sub { font-size: 10px; }")

out_path.write_text(html, encoding="utf-8")
print("built", out_path, len(html), "bytes")
