/* CEO metrics: the deck's success metrics (Appendix B) computed from the simulator.
   Counts are additive so days roll up into weeks, months and years; rates are derived after summing. */
(function (root) {
  'use strict';
  var AOV = 330, ORDERS_PER_DAY = 2140, RUN_COST = 600, RIDER_MIN = 2;   // deck A6, run cost, ₹ per idle rider-minute (assumed)   // deck A6 and run-cost upper bound
  var PRICE = {};
  function prices(E) { if (!PRICE.milk) E.SKU_DEFS.forEach(function (d) { PRICE[d[0]] = d[5]; }); }
  var KEYS = ['placed', 'done', 'onTime', 'cancels', 'closed', 'linesOrdered', 'linesFulfilled', 'perfect', 'pna', 'linesAttempted',
    'pickSum', 'pickN', 'pickLines', 'riderWait', 'riderWaitN', 'walk', 'hides', 'falseFlags', 'swaps', 'refunds', 'refundValue', 'prevented', 'gigHours', 'gigCost', 'tWalk', 'tCong', 'tSearch', 'tPick', 'tBench', 'nBench', 'rerouteSaved', 'slotSaved', 'etaMoves'];

  function worldCounts(w) {
    var st = w.stats, c = { placed: st.placed, done: st.done, onTime: st.onTime, cancels: st.cancels, pna: st.missingHits,
      linesAttempted: w.kpi.linesAttempted, pickSum: st.pickSum, pickN: st.pickN, pickLines: w.kpi.pickLines, riderWait: st.riderWait,
      riderWaitN: st.riderWaitN, walk: st.walk, hides: w.kpi.hides, falseFlags: w.kpi.falseFlags, swaps: st.swaps, refunds: st.refunds,
      prevented: st.prevented, gigHours: w.kpi.gigHours || 0, gigCost: w.kpi.gigCost || 0,
      tWalk: w.kpi.tWalk || 0, tCong: w.kpi.tCong || 0, tSearch: w.kpi.tSearch || 0, tPick: w.kpi.tPick || 0, tBench: w.kpi.tBench || 0, nBench: w.kpi.nBench || 0,
      rerouteSaved: w.kpi.rerouteSaved || 0, slotSaved: w.kpi.slotSaved || 0, etaMoves: w.kpi.etaMoves || 0, sku: Object.assign({}, w.kpi.pnaBySku), closed: 0, linesOrdered: 0, linesFulfilled: 0, perfect: 0, refundValue: 0 };
    w.by_id.forEach(function (o) {
      o.items.forEach(function (it) { if (it.st === 'dropped') c.refundValue += PRICE[it.sku] || 0; });
      if (o.status !== 'done' && o.status !== 'cancelled') return;
      c.closed += 1; c.linesOrdered += o.items.length;
      if (o.status !== 'done') return;
      var picked = 0, pna = false;
      o.items.forEach(function (it) { if (it.st === 'picked') picked++; if (it.pna) pna = true; });
      c.linesFulfilled += picked;
      if (picked === o.items.length && !pna && o.handed_at <= Math.max(o.D, o.rider_arrive)) c.perfect += 1;
    });
    return c;
  }
  function p95(a) { if (!a.length) return 0; var s = a.slice().sort(function (x, y) { return x - y; }); return s[Math.min(s.length - 1, Math.floor(0.95 * s.length))]; }
  // One shift (one evening peak) as additive counts for both worlds.
  function shiftCounts(E, sess) {
    prices(E);
    var dec = 0, blocked = 0, llm = 0;
    for (var k in sess.agents) { var a = sess.agents[k].stats; dec += a.decisions; blocked += a.blocked; llm += a.llm; }
    return { S: worldCounts(sess.smart), X: worldCounts(sess.static), decisions: dec, blocked: blocked, llm: llm,
      optP95: Math.round(p95(sess.optTimes) * 100) / 100, modeMin: Object.assign({}, sess.smart.kpi.modeMin), briefs: sess.logs.filter(function (l) { return l.hi; }).length };
  }
  function add(into, c) {
    ['S', 'X'].forEach(function (w) {
      into[w] = into[w] || { sku: {} }; KEYS.forEach(function (k) { into[w][k] = (into[w][k] || 0) + (c[w][k] || 0); });
      var sk = c[w].sku || {}; for (var id in sk) into[w].sku[id] = (into[w].sku[id] || 0) + sk[id];
    });
    ['decisions', 'blocked', 'llm', 'briefs'].forEach(function (k) { into[k] = (into[k] || 0) + (c[k] || 0); });
    into.modeMin = into.modeMin || { trough: 0, normal: 0, peak: 0, surge: 0 };
    for (var m in c.modeMin) into.modeMin[m] += c.modeMin[m];
    into.optP95 = Math.max(into.optP95 || 0, c.optP95 || 0);
    into.shifts = (into.shifts || 0) + 1;
    return into;
  }
  function sum(list) { return list.reduce(function (acc, c) { return add(acc, c); }, {}); }
  function div(a, b) { return b ? a / b : null; }
  function rates(c) {
    return { ppi: div(c.pickSum, c.pickLines), pnaRate: div(c.pna, c.linesAttempted), tfr: div(c.linesFulfilled, c.linesOrdered),
      cancelsPer1000: div(c.cancels * 1000, c.placed), perfect: div(c.perfect, c.closed), sla: div(c.onTime, c.done),
      falseFlags: div(c.falseFlags, c.hides), avgPick: div(c.pickSum, c.pickN), riderWait: div(c.riderWait, c.riderWaitN),
      walkPerOrder: div(c.walk * 0.05, c.pickN), orders: c.placed,
      bWalk: div(c.tWalk, c.pickN), bCong: div(c.tCong, c.pickN), bSearch: div(c.tSearch, c.pickN), bPick: div(c.tPick, c.pickN), bBench: div(c.tBench, c.nBench), bPack: 18,
      riderIdleMin: (c.riderWait || 0) / 60, riderCost: (c.riderWait || 0) / 60 * RIDER_MIN };
  }
  // Money: cancels avoided at the deck's average order value, plus refunds avoided at catalogue prices.
  function value(t) {
    var cancelsAvoided = t.X.cancels - t.S.cancels, refundsAvoided = t.X.refundValue - t.S.refundValue;
    var gmv = cancelsAvoided * AOV + refundsAvoided;
    var pickerHours = (t.X.pickSum - t.S.pickSum) / 3600;
    var scale = t.S.placed ? ORDERS_PER_DAY * (t.shifts || 1) / t.S.placed : 0;   // peak sample → full trading days
    return { cancelsAvoided: cancelsAvoided, gmvPeak: gmv, pickerHoursPeak: pickerHours, gmvDay: gmv * scale, pickerHoursDay: pickerHours * scale,
      gigCost: t.S.gigCost || 0, gigHours: t.S.gigHours || 0,
      runCost: RUN_COST * (t.shifts || 1) + (t.S.gigCost || 0), roi: div(gmv * scale, RUN_COST * (t.shifts || 1) + (t.S.gigCost || 0)) };
  }
  // Intraday curve for the live shift: 10-minute buckets by order time.
  function intraday(E, sess) {
    prices(E);
    var N = 12, out = [];
    for (var i = 0; i < N; i++) out.push({ S: { placed: 0, onTime: 0, done: 0, cancels: 0, pna: 0 }, X: { placed: 0, onTime: 0, done: 0, cancels: 0, pna: 0 } });
    [['S', sess.smart], ['X', sess.static]].forEach(function (p) {
      p[1].by_id.forEach(function (o) {
        var b = out[Math.min(N - 1, Math.floor(o.placed / 600))][p[0]];
        b.placed++;
        if (o.status === 'done') { b.done++; if (o.handed_at <= Math.max(o.D, o.rider_arrive)) b.onTime++; }
        if (o.status === 'cancelled') b.cancels++;
        o.items.forEach(function (it) { if (it.pna) b.pna++; });
      });
    });
    return out;
  }
  var API = { RIDER_MIN: RIDER_MIN, shiftCounts: shiftCounts, add: add, sum: sum, rates: rates, value: value, intraday: intraday, AOV: AOV, ORDERS_PER_DAY: ORDERS_PER_DAY, RUN_COST: RUN_COST };
  if (typeof module !== 'undefined' && module.exports) module.exports = API; else root.SyncKPI = API;
})(typeof window !== 'undefined' ? window : globalThis);

