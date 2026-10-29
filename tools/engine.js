/* SyncStore engine: a line-by-line JavaScript port of the Python platform
   (sim/, engine/, core/, agents/, server/snapshot.py). Same seed, same orders, same decisions.
   Python behaviours that matter for identical results are reproduced exactly:
   random.Random (MT19937), round() half-to-even, f"{x:.2f}" formatting, stable sorts. */
(function (root) {
  'use strict';

  // ================================================================ Python compatibility
  class PyError extends Error { constructor(kind, msg) { super(msg || kind); this.pyName = kind; } }
  const KeyErr = (k) => new PyError('KeyError', String(k));
  const ValErr = (m) => new PyError('ValueError', m);
  const TypeErr = (m) => new PyError('TypeError', m);

  class PyRandom {
    constructor(seed) {
      this.mt = new Uint32Array(624); this.mti = 625;
      let a = Math.abs(seed), key = [];
      if (a === 0) key = [0];
      while (a > 0) { key.push(a % 4294967296 >>> 0); a = Math.floor(a / 4294967296); }
      this._initByArray(key);
    }
    _initGenrand(s) {
      const mt = this.mt; mt[0] = s >>> 0;
      for (let i = 1; i < 624; i++) {
        const p = mt[i - 1] ^ (mt[i - 1] >>> 30);
        mt[i] = (Math.imul(1812433253, p) + i) >>> 0;
      }
      this.mti = 624;
    }
    _initByArray(key) {
      this._initGenrand(19650218);
      const mt = this.mt, N = 624; let i = 1, j = 0;
      for (let k = Math.max(N, key.length); k; k--) {
        const p = mt[i - 1] ^ (mt[i - 1] >>> 30);
        mt[i] = ((mt[i] ^ Math.imul(p, 1664525)) + key[j] + j) >>> 0;
        i++; j++;
        if (i >= N) { mt[0] = mt[N - 1]; i = 1; }
        if (j >= key.length) j = 0;
      }
      for (let k = N - 1; k; k--) {
        const p = mt[i - 1] ^ (mt[i - 1] >>> 30);
        mt[i] = ((mt[i] ^ Math.imul(p, 1566083941)) - i) >>> 0;
        i++;
        if (i >= N) { mt[0] = mt[N - 1]; i = 1; }
      }
      mt[0] = 0x80000000;
    }
    _int32() {
      const mt = this.mt;
      if (this.mti >= 624) {
        let kk = 0, y;
        for (; kk < 624 - 397; kk++) { y = (mt[kk] & 0x80000000) | (mt[kk + 1] & 0x7fffffff); mt[kk] = mt[kk + 397] ^ (y >>> 1) ^ (y & 1 ? 0x9908b0df : 0); }
        for (; kk < 623; kk++) { y = (mt[kk] & 0x80000000) | (mt[kk + 1] & 0x7fffffff); mt[kk] = mt[kk + (397 - 624)] ^ (y >>> 1) ^ (y & 1 ? 0x9908b0df : 0); }
        y = (mt[623] & 0x80000000) | (mt[0] & 0x7fffffff); mt[623] = mt[396] ^ (y >>> 1) ^ (y & 1 ? 0x9908b0df : 0);
        this.mti = 0;
      }
      let y = mt[this.mti++];
      y ^= y >>> 11; y ^= (y << 7) & 0x9d2c5680; y ^= (y << 15) & 0xefc60000; y ^= y >>> 18;
      return y >>> 0;
    }
    random() { const a = this._int32() >>> 5, b = this._int32() >>> 6; return (a * 67108864 + b) * (1.0 / 9007199254740992); }
  }

  // round(x): half to even
  function pyRound(x) {
    const f = Math.floor(x), d = x - f;
    if (d > 0.5) return f + 1;
    if (d < 0.5) return f;
    return f % 2 === 0 ? f : f + 1;
  }
  // exact decimal digits of |x| with n places, rounded half-even on the exact binary value
  function decRound(x, n) {
    const neg = x < 0 || Object.is(x, -0), ax = Math.abs(x);
    const s = ax.toFixed(Math.min(100, n + 30));
    const dot = s.indexOf('.');
    let intPart = s.slice(0, dot), frac = s.slice(dot + 1);
    let keep = intPart + frac.slice(0, n), rest = frac.slice(n);
    let up;
    if (rest[0] > '5') up = true;
    else if (rest[0] < '5') up = false;
    else if (/[1-9]/.test(rest.slice(1))) up = true;
    else up = (+keep[keep.length - 1]) % 2 === 1;
    if (up) {   // add one to the last digit of keep
      const arr = keep.split(''); let i = arr.length - 1;
      while (i >= 0) { if (arr[i] === '9') { arr[i] = '0'; i--; } else { arr[i] = String(+arr[i] + 1); break; } }
      if (i < 0) arr.unshift('1');
      keep = arr.join('');
    }
    const ip = keep.slice(0, keep.length - n) || '0', fp = keep.slice(keep.length - n);
    return { neg, str: n ? ip.replace(/^0+(?=\d)/, '') + '.' + fp : ip.replace(/^0+(?=\d)/, '') };
  }
  function pyRoundN(x, n) { const r = decRound(x, n); const v = Number(r.str); return r.neg ? -v : v; }
  function f2(x, n) { const r = decRound(x, n === undefined ? 2 : n); return (r.neg ? '-' : '') + r.str; }   // f"{x:.nf}"
  function pyInt(v) {
    if (typeof v === 'boolean') return v ? 1 : 0;
    if (typeof v === 'number') { if (!isFinite(v)) throw ValErr('int'); return Math.trunc(v); }
    if (typeof v === 'string') { if (/^\s*[+-]?\d+\s*$/.test(v)) return parseInt(v, 10); throw ValErr('int'); }
    throw TypeErr('int');
  }
  function pyFloat(v) {
    if (typeof v === 'boolean') return v ? 1 : 0;
    if (typeof v === 'number') return v;
    if (typeof v === 'string') { const n = Number(v.trim()); if (v.trim() === '' || isNaN(n)) throw ValErr('float'); return n; }
    throw TypeErr('float');
  }
  function pyStr(v) {
    if (v === null || v === undefined) return 'None';
    if (v === true) return 'True'; if (v === false) return 'False';
    if (typeof v === 'number') return Number.isInteger(v) && !String(v).includes('e') ? String(v) : String(v);
    if (typeof v === 'object') return JSON.stringify(v);
    return String(v);
  }
  const isNum = (v) => typeof v === 'number' || typeof v === 'boolean';
  function cmpTuple(a, b) { for (let i = 0; i < a.length; i++) { if (a[i] < b[i]) return -1; if (a[i] > b[i]) return 1; } return 0; }
  function sortBy(arr, key) { return arr.map((v, i) => [key(v), i, v]).sort((x, y) => { const k = Array.isArray(x[0]) ? cmpTuple(x[0], y[0]) : (x[0] < y[0] ? -1 : x[0] > y[0] ? 1 : 0); return k || x[1] - y[1]; }).map(x => x[2]); }
  function minBy(arr, key) { let best, bk; for (const v of arr) { const k = key(v); if (best === undefined || k < bk) { best = v; bk = k; } } return best; }
  function removeFirst(arr, v) { const i = arr.indexOf(v); if (i < 0) throw ValErr('list.remove'); arr.splice(i, 1); }
  function get(o, k, d) { return o && Object.prototype.hasOwnProperty.call(o, k) && o[k] !== undefined ? o[k] : d; }

  // ================================================================ sim/constants.py
  const START = 18 * 3600 + 30 * 60, HORIZON = 7200, SPEED_PX = 28, DWELL = 10, PACK = 18, BUFFER = 45, PX_M = 0.05;
  const CROSS_Y = 400, HOME = { x: 500, y: 445 }, SLOT_Y = [120, 210, 300], FWD_Y = 350;
  const rackX = (i) => 70 + (i - 1) * 104, cx = (i) => rackX(i) + 66;
  const MODES = ['trough', 'normal', 'peak', 'surge'];
  const MODE_LABEL = { trough: 'Trough', normal: 'Normal', peak: 'Peak', surge: 'Surge' };
  const MODE_METHOD = { trough: 'Discrete', normal: 'Cluster', peak: 'Cluster', surge: 'Zone pick-and-merge' };
  const LIMITS = { trough: { max: 1, hold: 0 }, normal: { max: 3, hold: 30 }, peak: { max: 4, hold: 75 }, surge: { max: 4, hold: 90 } };
  const MODE_UP = { normal: 0.5, peak: 0.8, surge: 0.92 };
  const OPS_BOUNDS = { max_batch: 4, hold_s: 90 };
  const PICKERS = ['Ravi', 'Sunita', 'Imran', 'Asha', 'Deepak', 'Manoj'];
  const FAST_MOVERS = ['chips', 'cola', 'popcorn'];
  // On-demand hourly pickers (gig pool). Assumed rate and limits for the prototype.
  const GIG = { rate: 180, leadS: 600, maxOnFloor: 4, maxSpend: 2000, names: ['Arjun', 'Pooja', 'Salim', 'Rekha', 'Vikram', 'Farah', 'Kunal', 'Meena'] };
  const SKU_DEFS = [
    ['bread', 'White bread 400 g', 1, 0, 'amb', 45, 'bread', 0.4, 6, 14, 40, 0.9],
    ['breadb', 'Brown bread 400 g', 1, 1, 'amb', 50, 'bread', 0.4, 4, 10, 30, 0.66],
    ['breadm', 'Multigrain bread 400 g', 1, 2, 'amb', 55, 'bread', 0.4, 2, 8, 20, 0.9],
    ['atta', 'Atta 5 kg', 2, 0, 'amb', 265, 'atta', 5, 3, 12, 30, 0.94],
    ['dal', 'Toor dal 1 kg', 2, 1, 'amb', 160, 'dal', 1, 3, 14, 30, 0.93],
    ['oil', 'Sunflower oil 1 L', 2, 2, 'amb', 150, 'oil', 0.9, 3, 12, 30, 0.95],
    ['tea', 'Tea 250 g', 3, 0, 'amb', 140, 'tea', 0.25, 3, 12, 30, 0.9],
    ['biscuit', 'Biscuits, family pack', 3, 1, 'amb', 40, 'biscuit', 0.3, 6, 24, 60, 0.9],
    ['coffee', 'Instant coffee 50 g', 3, 2, 'amb', 160, 'coffee', 0.05, 2, 10, 20, 0.62],
    ['chips', 'Salted chips 90 g', 4, 0, 'amb', 40, 'chips', 0.09, 7, 20, 60, 0.9],
    ['chipsm', 'Masala chips 90 g', 4, 1, 'amb', 40, 'chips', 0.09, 5, 18, 50, 0.88],
    ['popcorn', 'Popcorn 60 g', 4, 2, 'amb', 50, 'popcorn', 0.06, 3, 12, 30, 0.68],
    ['cola', 'Cola 750 ml', 5, 0, 'amb', 45, 'cola', 0.8, 7, 24, 60, 0.9],
    ['colaz', 'Cola zero 750 ml', 5, 1, 'amb', 45, 'cola', 0.8, 3, 12, 30, 0.9],
    ['water', 'Water 1 L', 5, 2, 'amb', 20, 'water', 1, 5, 30, 60, 0.95],
    ['milk', 'Toned milk 500 ml', 6, 0, 'chill', 29, 'milk', 0.5, 10, 24, 40, 0.92],
    ['milkfc', 'Full-cream milk 500 ml', 6, 1, 'chill', 35, 'milk', 0.5, 4, 18, 30, 0.9],
    ['curd', 'Curd 400 g', 6, 2, 'chill', 45, 'curd', 0.4, 5, 14, 30, 0.88],
    ['paneer', 'Paneer 200 g', 7, 0, 'chill', 90, 'paneer', 0.2, 4, 10, 0, 0.8],
    ['eggs', 'Eggs, 6 pack', 7, 1, 'chill', 48, 'eggs', 0.4, 6, 20, 40, 0.9],
    ['butter', 'Butter 100 g', 7, 2, 'chill', 58, 'butter', 0.1, 4, 16, 30, 0.86],
    ['icv', 'Vanilla ice cream 700 ml', 8, 0, 'frozen', 180, 'ice', 0.6, 3, 10, 20, 0.85],
    ['icc', 'Chocolate ice cream 700 ml', 8, 1, 'frozen', 200, 'ice', 0.6, 2, 8, 20, 0.9],
    ['peas', 'Frozen peas 500 g', 8, 2, 'frozen', 95, 'peas', 0.5, 2, 10, 20, 0.92],
  ];
  const SHRINK = [[1560, 'milk', 0], [2640, 'chips', 0], [3240, 'paneer', 0], [3960, 'cola', 1]];
  const lambdaAt = (t) => { const m = t / 60; return 1.6 + 2.8 * Math.exp(-(((m - 45) / 17) ** 2)); };
  const pad2 = (n) => String(n).padStart(2, '0');
  function fmt(t) { const s = START + Math.trunc(t); return pad2(Math.floor(s / 3600) % 24) + ':' + pad2(Math.floor(s / 60) % 60) + ':' + pad2(s % 60); }
  function mmss(s) { s = Math.max(0, pyRound(s)); return Math.floor(s / 60) + ':' + pad2(s % 60); }

  // ================================================================ sim/world.py
  function makeOrder(r, t, oid) {
    let x = r.random();
    const n = x < 0.3 ? 1 : x < 0.65 ? 2 : x < 0.9 ? 3 : 4;
    let total = 0; for (const d of SKU_DEFS) total += d[8];
    const items = [];
    while (items.length < n) {
      x = r.random() * total; let acc = 0;
      for (const d of SKU_DEFS) { acc += d[8]; if (x <= acc) { if (!items.includes(d[0])) items.push(d[0]); break; } }
    }
    const o = { id: oid, placed: pyRound(t), items: items };
    o.ride = 170 + Math.trunc(r.random() * 100);
    o.riderIn = 150 + Math.trunc(r.random() * 210);
    o.saved = r.random() < 0.35;
    o.chose = r.random() < 0.6;
    o.cancelIfMissing = r.random() < 0.5;
    return o;
  }
  function genOrders(seed, scale) {
    const r = new PyRandom(seed === undefined ? 7 : seed), out = []; let t = 0.0, oid = 4101;
    scale = scale || 1;
    while (true) {
      t += -Math.log(1 - r.random()) / (lambdaAt(t) * scale / 60);
      if (t >= HORIZON) break;
      out.push(makeOrder(r, t, oid)); oid++;
    }
    let k = 0;
    for (const o of out) if (o.placed >= 1575 && o.placed <= 1720 && k < 4 && !o.items.includes('milk')) { o.items.push('milk'); k++; }
    return out;
  }
  const copyOrder = (o) => Object.assign({}, o, { items: o.items.slice() });

  class World {
    constructor(orders, policy) {
      policy = policy || 'smart';
      this.policy = policy; this.agents_on = policy === 'smart'; this.t = 0;
      this.arr = orders.map(copyOrder); this.ai = 0; this.skus = {};
      for (const d of SKU_DEFS) this.skus[d[0]] = {
        id: d[0], name: d[1], aisle: d[2], slot: d[3], temp: d[4], price: d[5], cat: d[6], kg: d[7], pop: d[8],
        shelf: d[9], record: d[9], backroom: d[10], trust: policy === 'smart' ? d[11] : 1.0, hidden: false, status: 'live',
        fwd: false, reports: [], counting: false, restock_at: 0, true_out: false, last_check: 0 };
      this.orders = []; this.by_id = new Map(); this.pool = []; this.trips = []; this.ev = []; this.outbox = [];
      this.pickers = PICKERS.map((n, i) => ({ id: i, name: n, trip: null, join_at: 0, floater: false, leave_at: 0, gig: false }));
      this.bench = { q: [], busy: [0, 0], ready: [] };
      this.mode = 'normal'; this.lim = Object.assign({}, LIMITS.normal);
      this.release_policy = { bench_cap: 5, pace_slack: 90, bench_order: 'rider_first' };
      this.priority = new Map(); this.approvals = []; this.brief = null;
      this.stats = {};
      for (const k of ['placed', 'done', 'onTime', 'cancels', 'swaps', 'refunds', 'notFound', 'hidden', 'walk', 'pickSum', 'pickN', 'riderWait', 'riderWaitN', 'batches', 'batchedOrders', 'lost', 'asked', 'prevented', 'conflicts', 'reroutes', 'missingHits', 'fixed', 'autoSwaps', 'bufferHolds', 'notified']) this.stats[k] = 0;
      this.arr_min = new Array(240).fill(0); this.backlog = []; this.u_now = 0.0; this.u_fc = 0.0; this.down = 0; this.trip_seq = 0;
      this.optimiser = null; this.log = []; this.decisions = []; this.last_bench_alert = -999; this.bench_alerted = false;
      // CEO-dashboard instrumentation (read-only counters; they never feed back into decisions)
      this.demand = 1; this.shrinkPlan = SHRINK;
      this.levers = { batching: true, reroute: true, slotting: true, riderFirst: true };
      this.dynSlot = false; this.frontOn = false; this.frontList = FAST_MOVERS.slice(); this.skuMin = {};
      this.kpi = { tWalk: 0, tCong: 0, tSearch: 0, tPick: 0, tBench: 0, nBench: 0, rerouteSaved: 0, slotSaved: 0, etaMoves: 0, linesAttempted: 0, pickLines: 0, hides: 0, falseFlags: 0, modeMin: { trough: 0, normal: 0, peak: 0, surge: 0 }, pnaBySku: {}, gigHours: 0, gigCost: 0 };
    }
    get smart() { return this.policy === 'smart'; }
    emit(kind, data) { this.outbox.push(Object.assign({ type: kind, t: this.t }, data || {})); }
    drain() { const out = this.outbox; this.outbox = []; return out; }
    schedule(t, fn) { this.ev.push([t, fn]); }
    activePickers() { return this.pickers.filter(p => p.join_at <= this.t && !(p.leave_at && this.t >= p.leave_at)); }
    activeOrders() { return this.orders.filter(o => o.status !== 'done' && o.status !== 'cancelled'); }
    recentLambda() { const m = Math.floor(this.t / 60); let n = 0, k = 0; for (let i = m - 1; i > Math.max(0, m - 10) - 1; i--) { n += this.arr_min[i]; k++; } return k ? n / k : 0; }
    avgPick() { return this.stats.pickN ? this.stats.pickSum / this.stats.pickN : 0; }
    posOf(s) { return { x: cx(s.aisle), y: s.fwd ? FWD_Y : SLOT_Y[s.slot] }; }
    static pathPts(a, b) { if (a.x === b.x) return [{ x: b.x, y: b.y }]; return [{ x: a.x, y: CROSS_Y }, { x: b.x, y: CROSS_Y }, { x: b.x, y: b.y }]; }
    static dist(a, b) { if (a.x === b.x) return Math.abs(a.y - b.y); return Math.abs(a.y - CROSS_Y) + Math.abs(a.x - b.x) + Math.abs(CROSS_Y - b.y); }
    orderStops(ids) {
      const arr = ids.map(i => this.skus[i]);
      if (!this.smart) return sortBy(arr, s => [s.aisle, s.slot]);
      return sortBy(arr, s => [(s.temp === 'amb' && s.trust < 0.5) ? 0 : 1, s.aisle, s.slot]);
    }
    routeLength(ids) { let pos = HOME, len = 0; for (const s of this.orderStops(Array.from(ids))) { const p = this.posOf(s); len += World.dist(pos, p); pos = p; } return len + World.dist(pos, HOME); }
    estDur(ids) { const a = Array.from(ids); return this.routeLength(a) / SPEED_PX + DWELL * a.length; }
    static openSkus(o) { return o.items.filter(i => i.st === 'open').map(i => i.sku); }
    slackOf(o) { const ids = World.openSkus(o); const d = ids.length ? this.estDur(ids) : 0; return Math.min(o.D, o.rider_arrive) - this.t - d - PACK; }
    swapCandidate(s) {
      let best = null;
      for (const x of Object.values(this.skus)) {
        if (x === s || x.cat !== s.cat || x.price < s.price || x.hidden || x.record <= 0) continue;
        if (this.smart && x.trust < 0.7) continue;
        if (best === null || x.price < best.price) best = x;
      }
      return best;
    }
    step() {
      this.t += 1; const t = this.t;
      while (this.ai < this.arr.length && this.arr[this.ai].placed <= t) { this.place(this.arr[this.ai]); this.ai++; }
      if (this.ev.length) {
        const due = sortBy(this.ev.filter(e => e[0] <= t), e => e[0]);
        if (due.length) { this.ev = this.ev.filter(e => e[0] > t); for (const e of due) e[1](); }
      }
      for (const [st, sku, val] of this.shrinkPlan) if (st === t) this.shrink(sku, val);
      for (const p of this.pickers) if (p.trip && p.trip.end <= t) this.finishTrip(p.trip);
      if (t % 10 === 0) this.restock();
      if (t % 5 === 0) { if (this.smart && this.optimiser) this.optimiser(this); else this.optimiseStatic(); }
      this.packBench(); this.handover();
      if (t % 60 === 0) this.minute();
    }
    shrink(sid, val) { const s = this.skus[sid]; s.shelf = Math.min(s.shelf, val); }
    insertOrders(lst) { const rest = sortBy(this.arr.slice(this.ai).concat(lst.map(copyOrder)), o => o.placed); this.arr = this.arr.slice(0, this.ai).concat(rest); }
    place(src) {
      const t = this.t;
      const o = { id: src.id, placed: t, ride: src.ride, rider_arrive: t + src.riderIn, D: t + 600 - src.ride, items: [], saved: src.saved, chose: false,
        cancel_if_missing: src.cancelIfMissing, status: 'pool', pick_time: 0, legs: 0, key: src.items[0], user: !!src.user, asked: [] };
      for (const sid of src.items) {
        const s = this.skus[sid];
        if (s.hidden) {
          const alt = this.swapCandidate(s);
          if (alt && src.chose) o.items.push({ sku: alt.id, orig: sid, st: 'open', from: sid });
          this.stats.prevented += 1; continue;
        }
        o.items.push({ sku: sid, orig: sid, st: 'open' });
        if (this.smart && s.trust < 0.7) { this.stats.asked += 1; o.asked.push(sid); if (src.chose) o.chose = true; }
      }
      if ('forceChoice' in src) o.chose = src.forceChoice;
      if (!o.items.length) { this.stats.lost += 1; return; }
      if (!o.items.some(i => i.orig === o.key)) o.key = o.items[0].orig;
      this.arr_min[Math.min(this.arr_min.length - 1, Math.floor(t / 60))] += 1;
      if (this.dynSlot) { const mi = Math.floor(t / 60); for (const it of o.items) { const a = this.skuMin[it.sku] || (this.skuMin[it.sku] = []); a[mi] = (a[mi] || 0) + 1; } }
      this.pool.push(o); this.orders.push(o); this.by_id.set(o.id, o); this.stats.placed += 1;
      if (this.orders.length > 600) this.orders = this.orders.filter(x => (x.status !== 'done' && x.status !== 'cancelled') || t - (x.handed_at || x.cancelled_at || t) < 600);
    }
    optimiseStatic() {
      const idle = this.activePickers().filter(p => !p.trip);
      if (!idle.length || !this.pool.length) return;
      this.pool = sortBy(this.pool.filter(o => o.status === 'pool'), o => o.placed);
      while (idle.length && this.pool.length) { const o = this.pool.shift(); if (!World.openSkus(o).length) continue; this.planTrip(idle.shift(), [o], null); }
    }
    planTrip(p, orders, zone, zoneName) {
      const t0 = this.t, groups = new Map();
      for (const o of orders) for (const it of o.items) {
        if (it.st !== 'open') continue;
        const s = this.skus[it.sku];
        if (zone && !zone.has(s.aisle)) continue;
        if (!groups.has(s.id)) groups.set(s.id, []);
        groups.get(s.id).push([o, it]); it.st = 'queued';
      }
      const stops = this.orderStops(Array.from(groups.keys()));
      const trip = { id: this.trip_seq + 1, p: p, orders: orders, zone: zoneName === undefined ? null : zoneName, pts: [{ x: HOME.x, y: HOME.y, t: t0 }], start: t0, end: t0, len: 0,
        aisles: new Set(stops.map(s => s.aisle)), stops: stops.map(s => s.id), extended: false, rr: 0, done: false };
      this.trip_seq += 1;
      let pos = Object.assign({}, HOME), T = t0;
      const others = this.trips.filter(x => x.end > t0);
      for (const s of stops) {
        let k = 0; for (const x of others) if (x.aisles.has(s.aisle)) k++;
        const rr = this.smart && this.levers.reroute, f = 1 + (rr ? 0.05 : 0.15) * k;
        if (rr && k > 0 && trip.rr < 2) { trip.rr += 1; this.stats.reroutes += 1; }
        const share = 1 / orders.length;
        if (this.smart && s.fwd) this.kpi.slotSaved += 2 * Math.abs(SLOT_Y[s.slot] - FWD_Y) * share;
        for (const q of World.pathPts(pos, this.posOf(s))) {
          const d = Math.abs(q.x - pos.x) + Math.abs(q.y - pos.y);
          T += d / SPEED_PX * f; trip.len += d; trip.pts.push({ x: q.x, y: q.y, t: T }); pos = q;
          this.kpi.tWalk += d / SPEED_PX * share; this.kpi.tCong += d / SPEED_PX * (f - 1) * share;
          if (rr) this.kpi.rerouteSaved += d / SPEED_PX * 0.1 * k * share;
        }
        const lst = groups.get(s.id), need = lst.length, got = Math.min(need, Math.max(0, s.shelf));
        this.kpi.linesAttempted += need;
        s.shelf -= got; s.record = Math.max(0, s.record - got);
        for (const [, it] of lst.slice(0, got)) it.st = 'picked';
        let dwell = got > 0 ? DWELL + 3 * (got - 1) : 0;
        if (got < need) {
          const miss = lst.slice(got);
          for (const [, it] of miss) { it.st = 'missing'; it.pna = true; }
          dwell += this.smart ? 8 : 40;
          this.stats.missingHits += miss.length;
          this.kpi.pnaBySku[s.id] = (this.kpi.pnaBySku[s.id] || 0) + miss.length;
          const at = Math.ceil(T + dwell);
          this.schedule(at, () => this.onNotFound(s, miss, trip));
        } else if (this.smart) s.trust = Math.min(0.98, s.trust + 0.01);
        this.kpi.tPick += (got > 0 ? DWELL + 3 * (got - 1) : 0) * share; this.kpi.tSearch += (got < need ? (this.smart ? 8 : 40) : 0) * share;
        T += dwell; trip.pts.push({ x: pos.x, y: pos.y, t: T });
      }
      for (const q of World.pathPts(pos, HOME)) { const d = Math.abs(q.x - pos.x) + Math.abs(q.y - pos.y); T += d / SPEED_PX; trip.len += d; trip.pts.push({ x: q.x, y: q.y, t: T }); pos = q; this.kpi.tWalk += d / SPEED_PX / orders.length; }
      trip.end = T; this.trips.push(trip); p.trip = trip; this.stats.walk += trip.len;
      for (const o of orders) if (o.status === 'pool' || o.status === 'picking') { o.status = 'picking'; o.legs += 1; if (!('pick_start' in o)) o.pick_start = t0; }
      if (this.trips.length > 80) this.trips = this.trips.filter(x => x.end > this.t - 2);
      return trip;
    }
    posAt(tr, t) {
      const pts = tr.pts;
      if (t <= pts[0].t) return pts[0];
      if (t >= pts[pts.length - 1].t) return pts[pts.length - 1];
      for (let i = 1; i < pts.length; i++) if (t <= pts[i].t) { const a = pts[i - 1], b = pts[i]; const f = b.t === a.t ? 1 : (t - a.t) / (b.t - a.t); return { x: a.x + (b.x - a.x) * f, y: a.y + (b.y - a.y) * f }; }
      return pts[pts.length - 1];
    }
    extendTrip(tr, sec) {
      const at = this.t, pos = this.posAt(tr, at);
      let out = tr.pts.filter(q => q.t <= at);
      out = out.concat([{ x: pos.x, y: pos.y, t: at }, { x: pos.x, y: pos.y, t: at + sec }]);
      out = out.concat(tr.pts.filter(q => q.t > at).map(q => ({ x: q.x, y: q.y, t: q.t + sec })));
      tr.pts = out; tr.end += sec;
    }
    finishTrip(tr) {
      tr.p.trip = null; tr.done = true;
      const share = (tr.end - tr.start) / tr.orders.length;
      for (const o of tr.orders) {
        o.pick_time += share; o.legs -= 1;
        if (o.legs <= 0 && o.status === 'picking') {
          this.stats.pickSum += o.pick_time; this.stats.pickN += 1; this.kpi.pickLines += o.items.length;
          if (o.items.some(i => i.st === 'picked')) { o.status = 'bench'; o.bench_at = this.t; this.bench.q.push(o); }
          else this.cancel(o);
        }
      }
    }
    cancel(o) {
      if (o.status === 'done' || o.status === 'cancelled') return;
      o.status = 'cancelled'; o.cancelled_at = this.t; this.stats.cancels += 1;
      let i = this.pool.indexOf(o); if (i >= 0) this.pool.splice(i, 1);
      i = this.bench.q.indexOf(o); if (i >= 0) this.bench.q.splice(i, 1);
    }
    onNotFound(s, miss, trip) {
      this.stats.notFound += 1;
      if (this.smart || this.agents_on) this.emit('pick_not_found', { sku: s.id, record: s.record + miss.length, misses: miss.map(([o, it]) => [o.id, it]), trip: trip });
      if (!this.smart) this._staticNotFound(s, miss);
    }
    _staticNotFound(s, miss) {
      const t = this.t;
      s.reports = s.reports.filter(x => t - x < 900).concat([t]);
      if (!s.hidden && s.reports.length >= 2) {
        s.hidden = true; s.status = 'hidden'; this.kpi.hides += 1;
        const nxt = Math.ceil((t + 1) / 1800) * 1800;
        this.schedule(nxt, () => this._staticCount(s));
      }
      for (const [o, it] of miss) { if (o.status === 'cancelled') continue; this.dropItem(o, it); }
    }
    _staticCount(s) {
      if (s.shelf > 0) this.kpi.falseFlags += 1;
      s.record = s.shelf;
      if (s.backroom > 0) {
        s.status = 'refilling';
        this.schedule(this.t + 180, () => { const q = Math.min(16, s.backroom); s.shelf += q; s.record = s.shelf; s.backroom -= q; s.hidden = false; s.status = 'live'; });
      } else { s.status = 'out'; s.true_out = true; }
    }
    isKey(o, it) { return it.orig === o.key; }
    swapItem(o, it, alt, trip) {
      it.from = it.sku; it.sku = alt.id; this.stats.swaps += 1;
      if (trip && !trip.done && it.st === 'missing') {
        it.st = 'picked'; alt.shelf = Math.max(0, alt.shelf - 1); alt.record = Math.max(0, alt.record - 1);
        if (!trip.extended) { trip.extended = true; this.extendTrip(trip, 15); this.kpi.tSearch += 15 / trip.orders.length; }
      } else it.st = 'open';
    }
    dropItem(o, it) {
      it.st = 'dropped'; this.stats.refunds += 1;
      if ((this.isKey(o, it) && o.cancel_if_missing) || o.items.every(i => i.st === 'dropped')) { this.cancel(o); return 'cancel'; }
      return 'drop';
    }
    scheduleCount(sid, mode) {
      const s = this.skus[sid]; s.counting = true;
      this.schedule(this.t + 240, () => this.emit('count_result', { sku: sid, counted: s.shelf, backroom: s.backroom, mode: mode, record: s.record }));
    }
    scheduleRefill(sid, qty) {
      const s = this.skus[sid]; s.status = 'refilling';
      this.schedule(this.t + 180, () => { const q = Math.min(qty, s.backroom); s.shelf += q; s.record = s.shelf; s.backroom -= q; this.emit('refill_done', { sku: sid, qty: q, shelf: s.shelf }); });
    }
    restock() {
      for (const s of Object.values(this.skus)) {
        if (s.restock_at && this.t >= s.restock_at) { const q = Math.min(12, s.backroom); s.shelf += q; s.record += q; s.backroom -= q; s.restock_at = 0; }
        else if (!s.restock_at && !s.hidden && s.record <= 4 && s.backroom > 0) s.restock_at = this.t + 120;
      }
    }
    packBench() {
      const t = this.t, b = this.bench;
      if (this.smart && this.levers.riderFirst && this.release_policy.bench_order === 'rider_first' && b.q.length > 1) b.q = sortBy(b.q, o => o.rider_arrive);
      let i = 0;
      while (i < 2) {
        if (b.busy[i] <= t && b.q.length) {
          const o = b.q.shift();
          if (o.status !== 'bench') continue;
          o.status = 'packing'; b.busy[i] = t + PACK; this.kpi.tBench += t - (o.bench_at || t); this.kpi.nBench += 1;
          this.schedule(t + PACK, () => { if (o.status !== 'packing') return; o.status = 'ready'; o.ready_at = this.t; b.ready.push(o); });
        }
        i++;
      }
      if (this.smart) {
        const n = b.q.length;
        if (n >= this.release_policy.bench_cap && !this.bench_alerted) { this.bench_alerted = true; this.emit('bench_congested', { queue: n, ready: b.ready.length }); }
        else if (n <= 2 && this.bench_alerted) { this.bench_alerted = false; this.emit('bench_cleared', { queue: n }); }
      }
    }
    handover() {
      const t = this.t, keep = [];
      for (const o of this.bench.ready) {
        if (t >= o.rider_arrive) {
          o.status = 'done'; o.handed_at = t; this.stats.done += 1;
          if (t <= Math.max(o.D, o.rider_arrive)) this.stats.onTime += 1;
          this.stats.riderWait += t - o.rider_arrive; this.stats.riderWaitN += 1;
        } else keep.push(o);
      }
      this.bench.ready = keep;
    }
    minute() {
      const t = this.t, n = Math.max(1, this.activePickers().length);
      this.u_now = this.recentLambda() * 1.5 / n;
      this.u_fc = lambdaAt(t + 900) * this.demand * (1 + 0.05 * Math.sin(t / 700)) * 1.5 / n;
      this.kpi.modeMin[this.mode] += 1;
      if (this.smart && this.dynSlot && this.levers.slotting && t % 900 === 0) this.reslot();
      this.backlog = this.backlog.concat([this.pool.length]).slice(-4);
      const pr = new Map(); for (const [k, v] of this.priority) if (v > t) pr.set(k, v); this.priority = pr;
      this.emit('minute', { u_now: this.u_now, u_fc: this.u_fc, backlog: this.backlog.slice(), pickers: n, pool: this.pool.length });
    }
    // Dynamic slotting: the three items ordered most in the last 15 minutes take the front racks.
    reslot() {
      const mi = Math.floor(this.t / 60), score = [];
      for (const sid in this.skus) { const a = this.skuMin[sid] || []; let n = 0; for (let i = Math.max(0, mi - 15); i < mi; i++) n += a[i] || 0; score.push([sid, n, this.skus[sid].pop]); }
      score.sort((x, y) => y[1] - x[1] || y[2] - x[2]);
      const top = score.slice(0, 3).filter(x => x[1] > 0).map(x => x[0]);
      if (!top.length || top.join() === this.frontList.join()) return;
      this.frontList = top;
      if (this.frontOn) this.applyFront();
      this.emit('log', { agent: 'captain', via: 'policy', text: 'Dynamic slotting: the fastest sellers of the last 15 minutes are ' + top.map(id => this.skus[id].name).join(', ') + '.' + ' They move to the front racks, next to the cross aisle.' });
    }
    applyFront() { for (const sid in this.skus) this.skus[sid].fwd = this.frontOn && this.frontList.includes(sid); }
    addPicker(name, delay) { this.pickers.push({ id: this.pickers.length, name: name, trip: null, join_at: this.t + delay, floater: true, leave_at: 0, gig: false }); }
    gigOnFloor() { return this.pickers.filter(p => p.gig && !(p.leave_at && this.t >= p.leave_at)).length; }
    addGig(count, hours) {
      const out = [];
      for (let i = 0; i < count; i++) {
        const n = this.pickers.filter(p => p.gig).length;
        const p = { id: this.pickers.length, name: GIG.names[n % GIG.names.length], trip: null, join_at: this.t + GIG.leadS, floater: true, leave_at: this.t + GIG.leadS + hours * 3600, gig: true };
        this.pickers.push(p); out.push(p);
      }
      this.kpi.gigHours += count * hours; this.kpi.gigCost += count * hours * GIG.rate;
      return out;
    }
  }

  // ================================================================ engine/optimiser.py
  function optimiserRun(w) {
    const t = w.t;
    const idle = w.activePickers().filter(p => !p.trip);
    if (!idle.length || !w.pool.length) return;
    w.pool = w.pool.filter(o => o.status === 'pool');
    const info = new Map();
    for (const o of w.pool) { const ids = World.openSkus(o), d = w.estDur(ids); info.set(o.id, { ids: ids, d: d, slack: Math.min(o.D, o.rider_arrive) - t - d - PACK }); }
    const boost = (o) => w.priority.has(o.id) ? 0 : 1;
    let cand = w.levers.riderFirst ? sortBy(w.pool.filter(o => info.get(o.id).ids.length), o => info.get(o.id).slack - (boost(o) === 0 ? 60 : 0)) : sortBy(w.pool.filter(o => info.get(o.id).ids.length), o => o.placed);
    const rp = w.release_policy;
    if (w.bench.q.length >= rp.bench_cap) {
      const before = cand.length;
      cand = cand.filter(o => info.get(o.id).slack <= rp.pace_slack);
      if (cand.length < before && t - (w._last_pace === undefined ? -999 : w._last_pace) > 120) {
        w._last_pace = t;
        w.emit('log', { agent: 'relay', via: 'policy', text: 'Packing bench has ' + w.bench.q.length + ' bags waiting. Holding ' + (before - cand.length) + ' orders that still have more than ' + rp.pace_slack + ' s of buffer, so bags don’t pile up.' });
      }
    }
    const zoneMode = w.mode === 'surge';
    while (idle.length && cand.length) {
      const seed = cand[0];
      const batch = [seed]; let ids = new Set(info.get(seed.id).ids); const maxB = w.levers.batching ? w.lim.max : 1;
      while (batch.length < maxB) {
        let best = null, bestSave = 0, bestIds = null;
        const curLen = w.routeLength(ids);
        for (const c of cand) {
          if (batch.includes(c)) continue;
          const ci = info.get(c.id);
          const u = new Set(ids); for (const x of ci.ids) u.add(x);
          if (u.size > 9) continue;
          const uLen = w.routeLength(u);
          const save = curLen + w.routeLength(ci.ids) - uLen;
          if (save <= 20) continue;
          const uDur = uLen / 28 + 10 * u.size;
          const ok = batch.concat([c]).every(m => info.get(m.id).slack - (uDur - info.get(m.id).d) >= BUFFER);
          if (ok && save > bestSave) { best = c; bestSave = save; bestIds = u; }
        }
        if (!best) break;
        batch.push(best); ids = bestIds;
      }
      let minSlack = Infinity; for (const m of batch) minSlack = Math.min(minSlack, info.get(m.id).slack);
      const waited = t - seed.placed, full = batch.length >= maxB, urgent = minSlack <= BUFFER + 45, timeUp = waited >= w.lim.hold;
      if (!(full || urgent || timeUp)) break;
      if (urgent && !full && !timeUp && w.lim.hold > 30) {
        w.stats.bufferHolds += 1;
        if (t - (w._last_conflict === undefined ? -999 : w._last_conflict) > 300 && minSlack > 0) {
          w._last_conflict = t; w.stats.conflicts += 1;
          w.emit('log', { agent: 'captain', via: 'rule', text: 'Conflict settled: the optimiser wanted to hold #' + seed.id + ' for a better batch, but Relay reports its time buffer is down to ' + Math.max(0, pyRound(minSlack)) + ' s. Rule 2 (customer promise) beats rule 4 (efficiency), so #' + seed.id + ' was released.' });
        }
      }
      const oldest = minBy(w.pool, o => o.placed);
      if (seed !== oldest && t - (w._last_relay === undefined ? -999 : w._last_relay) > 240 && seed.rider_arrive < oldest.rider_arrive - 30) {
        w._last_relay = t;
        w.emit('log', { agent: 'relay', via: 'policy', story: 'riderfirst', text: 'Released #' + seed.id + ' ahead of older #' + oldest.id + ': its rider arrives in ' + mmss(seed.rider_arrive - t) + ', while #' + oldest.id + '’s rider is ' + mmss(oldest.rider_arrive - t) + ' away.' });
      }
      for (const b of batch) { removeFirst(w.pool, b); removeFirst(cand, b); }
      let solo = 0; for (const b of batch) solo += w.routeLength(info.get(b.id).ids);
      const unionLen = w.routeLength(ids);
      const savePct = batch.length > 1 && solo ? pyRound((1 - unionLen / solo) * 100) : 0;
      let reason;
      if (full) reason = 'Trolley full (' + batch.length + ' totes)';
      else if (urgent) reason = 'Time buffer of #' + seed.id + ' down to ' + Math.max(0, pyRound(minSlack)) + ' s';
      else if (w.lim.hold === 0) reason = 'Quiet hours: pick at once';
      else reason = 'Held ' + waited + ' s; no better partner arrived';
      const used = []; let method;
      if (zoneMode && idle.length >= 2) {
        const idArr = Array.from(ids);
        const hasA = idArr.some(i => w.skus[i].aisle <= 4), hasB = idArr.some(i => w.skus[i].aisle > 4);
        if (hasA) { const pa = idle.shift(); used.push(pa); w.planTrip(pa, batch, new Set([1, 2, 3, 4]), 'A'); }
        if (hasB) { const pb = idle.shift(); used.push(pb); w.planTrip(pb, batch, new Set([5, 6, 7, 8]), 'B'); }
        method = 'Zone pick-and-merge';
      } else {
        const p = idle.shift(); used.push(p); w.planTrip(p, batch, null);
        method = batch.length === 1 ? 'Discrete' : 'Cluster';
      }
      w.decisions.unshift({ t: t, ids: batch.map(o => o.id), method: method, reason: reason, save: savePct, pickers: used.map(p => p.name) });
      w.decisions.length = Math.min(w.decisions.length, 30);
      w.stats.batches += 1; w.stats.batchedOrders += batch.length;
    }
  }

  // ================================================================ core/state.py
  const OWNERSHIP = [
    ['sku.trust', 'ledger', 'Optimiser, Promise, Captain, customer app'],
    ['sku.visibility', 'ledger', 'Customer app, Promise'],
    ['sku.record', 'ledger', 'Reorder system, Captain'],
    ['count_and_refill', 'ledger', 'Store associates (handheld)'],
    ['mode_and_limits', 'captain', 'Optimiser'],
    ['front_racks', 'captain', 'Optimiser (routing), store associates'],
    ['approvals_and_brief', 'captain', 'Shift lead'],
    ['release_policy', 'relay', 'Optimiser, packing bench'],
    ['priority', 'relay', 'Optimiser'],
    ['order_items', 'promise', 'Picker handheld, packing bench'],
    ['customer_messages', 'promise', 'Customer app'],
  ];
  const OWNER = {}; OWNERSHIP.forEach(r => { OWNER[r[0]] = r[1]; });
  class OwnershipError extends Error {}
  class StoreState {
    constructor(world, logger) { this.w = world; this._log = logger; }
    require(agent, field) { const owner = OWNER[field]; if (agent !== owner) throw new OwnershipError(agent + " tried to write '" + field + "', which " + owner + ' owns'); }
    get t() { return this.w.t; }
    log(agent, text, o) { this._log(agent, text, o || {}); }
    sku(sid) { return typeof sid === 'string' && Object.prototype.hasOwnProperty.call(this.w.skus, sid) ? this.w.skus[sid] : null; }
    order(oid) { return this.w.by_id.has(oid) ? this.w.by_id.get(oid) : null; }
    setTrust(agent, sid, value) { this.require(agent, 'sku.trust'); this.w.skus[sid].trust = pyRoundN(Math.max(0.0, Math.min(0.99, pyFloat(value))), 2); }
    lowerAisleTrust(agent, sid, delta) {
      this.require(agent, 'sku.trust'); delta = delta === undefined ? 0.08 : delta;
      const s = this.w.skus[sid];
      for (const x of Object.values(this.w.skus)) if (x !== s && x.aisle === s.aisle && !x.hidden) x.trust = pyRoundN(Math.max(0.3, x.trust - delta), 2);
    }
    hide(agent, sid) { this.require(agent, 'sku.visibility'); const s = this.w.skus[sid]; if (s.hidden) return false; s.hidden = true; s.status = 'hidden'; this.w.stats.hidden += 1; this.w.kpi.hides += 1; this.w.emit('sku_hidden', { sku: sid }); return true; }
    restore(agent, sid) { this.require(agent, 'sku.visibility'); const s = this.w.skus[sid]; s.hidden = false; s.counting = false; s.status = 'live'; this.w.stats.fixed += 1; }
    correctRecord(agent, sid, value) { this.require(agent, 'sku.record'); this.w.skus[sid].record = pyInt(value); }
    requestCount(agent, sid, mode) {
      this.require(agent, 'count_and_refill'); const s = this.w.skus[sid];
      if (s.counting) return false;
      if (mode === 'check') s.status = 'checking'; else if (s.status !== 'hidden') s.status = 'counting';
      this.w.scheduleCount(sid, mode); return true;
    }
    requestRefill(agent, sid, qty) { this.require(agent, 'count_and_refill'); this.w.scheduleRefill(sid, pyInt(qty)); }
    markOut(agent, sid) { this.require(agent, 'count_and_refill'); const s = this.w.skus[sid]; s.status = 'out'; s.true_out = true; s.counting = false; }
    finishCheck(agent, sid) { this.require(agent, 'count_and_refill'); const s = this.w.skus[sid]; s.counting = false; s.last_check = this.w.t; if (!s.hidden) s.status = 'live'; }
    setMode(agent, mode) { this.require(agent, 'mode_and_limits'); const prev = this.w.mode; this.w.mode = mode; this.w.lim = Object.assign({}, LIMITS[mode]); this.w.down = 0; return prev; }
    setLimits(agent, maxBatch, holdS) { this.require(agent, 'mode_and_limits'); if (maxBatch !== null && maxBatch !== undefined) this.w.lim.max = pyInt(maxBatch); if (holdS !== null && holdS !== undefined) this.w.lim.hold = pyInt(holdS); }
    setFrontRacks(agent, on) { this.require(agent, 'front_racks'); if (this.w.dynSlot && this.w.levers.slotting) return; for (const sid of FAST_MOVERS) this.w.skus[sid].fwd = !!on; }
    requestApproval(agent, kind, text) { this.require(agent, 'approvals_and_brief'); if (this.w.approvals.some(a => a.id === kind)) return false; this.w.approvals.unshift({ id: kind, text: text, t: this.w.t, status: 'pending' }); return true; }
    requestOnDemand(agent, count, hours, why) {
      this.require(agent, 'approvals_and_brief');
      if (this.w.approvals.some(a => a.ondemand && a.status === 'pending')) return false;
      const cost = count * hours * GIG.rate, id = 'ondemand-' + (this.w.approvals.filter(a => a.ondemand).length + 1);
      this.w.approvals.unshift({ id: id, ondemand: true, count: count, hours: hours, cost: cost, why: why || '', t: this.w.t, status: 'pending',
        text: 'Book ' + count + ' on-demand picker' + (count > 1 ? 's' : '') + ' for ' + hours + ' hour' + (hours > 1 ? 's' : '') + ' (₹' + cost.toLocaleString('en-IN') + ', on the floor in 10 min)' });
      return true;
    }
    setBrief(agent, hi, en) { this.require(agent, 'approvals_and_brief'); this.w.brief = { t: this.w.t, hi: hi, en: en, agent: agent }; }
    setReleasePolicy(agent, benchCap, paceSlack) { this.require(agent, 'release_policy'); if (benchCap !== null && benchCap !== undefined) this.w.release_policy.bench_cap = pyInt(benchCap); if (paceSlack !== null && paceSlack !== undefined) this.w.release_policy.pace_slack = pyInt(paceSlack); }
    boost(agent, oid, secs) { this.require(agent, 'priority'); this.w.priority.set(oid, this.w.t + (secs === undefined ? 180 : secs)); }
    applySwap(agent, oid, it, altSid, trip) { this.require(agent, 'order_items'); const o = this.w.by_id.get(oid); if (!o) throw KeyErr(oid); this.w.swapItem(o, it, this.w.skus[altSid], trip); }
    refund(agent, oid, it) { this.require(agent, 'order_items'); const o = this.w.by_id.get(oid); if (!o) throw KeyErr(oid); return this.w.dropItem(o, it); }
    notify(agent, oid, msg) { this.require(agent, 'customer_messages'); const o = this.w.by_id.get(oid); if (o) { if (!o.messages) o.messages = []; o.messages.push({ t: this.w.t, text: msg }); } this.w.stats.notified += 1; }
  }

  // ================================================================ core/guardrails.py
  const isDeva = (s) => /[ऀ-ॿ]/.test(s);
  function gLedger(tool, a, ctx) {
    const s = ctx.state.sku(get(a, 'sku', ''));
    if (s === null) return [false, "unknown item '" + pyStr(get(a, 'sku', null)) + "'"];
    const ev = ctx.event;
    if (tool === 'set_trust') {
      const v = get(a, 'value', null);
      if (!isNum(v) || !(0.0 <= v && v <= 0.99)) return [false, 'trust must be a number between 0 and 0.99'];
      if (ev.type === 'pick_not_found' && a.sku === ev.sku && v > 0.3) return [false, 'an item a picker just found empty cannot be trusted above 0.30'];
    }
    if (tool === 'correct_record') {
      if (ev.type !== 'count_result' || a.sku !== ev.sku) return [false, 'a record can only be corrected from a count result'];
      if (pyInt(get(a, 'value', -1)) !== ev.counted) return [false, 'record must match the count (' + ev.counted + ')'];
    }
    if (tool === 'restore_item') {
      if (s.status === 'out' || (ev.type !== 'refill_done' && ev.type !== 'count_result')) return [false, 'an item comes back only after a refill or a count shows stock'];
      if (ev.type === 'count_result' && ev.counted <= 0) return [false, 'the count found none on the shelf'];
    }
    if (tool === 'trigger_refill') {
      const q = get(a, 'qty', 0);
      if (!isNum(q) || q <= 0 || q > 24) return [false, 'refill quantity must be 1–24'];
      if (s.backroom <= 0) return [false, 'nothing in the backroom to refill from'];
    }
    if (tool === 'raise_reorder' && s.backroom > 0) return [false, 'backroom still has stock; refill instead'];
    return [true, ''];
  }
  function gCaptain(tool, a, ctx) {
    const w = ctx.state.w;
    if (tool === 'set_mode') {
      const m = get(a, 'mode', null);
      if (!MODES.includes(m)) return [false, "unknown mode '" + pyStr(m) + "'"];
      const cur = MODES.indexOf(w.mode), nxt = MODES.indexOf(m);
      if (nxt < cur) {
        if (nxt !== cur - 1) return [false, 'step down one mode at a time'];
        if (w.down < 3) return [false, 'hysteresis: load must stay low for 3 minutes before stepping down (now ' + w.down + ')'];
      }
    }
    if (tool === 'set_limits') {
      const mb = get(a, 'max_batch', null), hs = get(a, 'hold_s', null);
      if (mb !== null && !(1 <= pyInt(mb) && pyInt(mb) <= OPS_BOUNDS.max_batch)) return [false, 'orders per trolley must be 1–' + OPS_BOUNDS.max_batch + ' (ops bound)'];
      if (hs !== null && !(0 <= pyInt(hs) && pyInt(hs) <= OPS_BOUNDS.hold_s)) return [false, 'hold cap must be 0–' + OPS_BOUNDS.hold_s + ' s (ops bound)'];
    }
    if (tool === 'request_staff' && !['floater_in_store', 'floater_borrow'].includes(get(a, 'kind', null))) return [false, 'kind must be floater_in_store or floater_borrow'];
    if (tool === 'brief_shift_lead') {
      const hi = a.hindi === undefined ? '' : pyStr(a.hindi), en = a.english === undefined ? '' : pyStr(a.english);
      if (!hi || !en || [...hi].length > 280 || [...en].length > 320) return [false, 'briefing needs short Hindi and English text'];
      if (!isDeva(hi)) return [false, 'the Hindi briefing must be in Devanagari'];
    }
    if (tool === 'book_ondemand') {
      const n = pyInt(get(a, 'count', 0)), h = pyInt(get(a, 'hours', 0));
      if (!ctx.rt.ondemand) return [false, 'on-demand pickers are switched off for this store'];
      if (!(1 <= n && n <= GIG.maxOnFloor)) return [false, 'book 1–' + GIG.maxOnFloor + ' on-demand pickers'];
      if (!(1 <= h && h <= 3)) return [false, 'book on-demand pickers for 1–3 hours'];
      if (w.gigOnFloor() + n > GIG.maxOnFloor) return [false, 'at most ' + GIG.maxOnFloor + ' on-demand pickers on the floor at once'];
      if (ctx.rt.gigSpend() + n * h * GIG.rate > GIG.maxSpend) return [false, 'over the ₹' + GIG.maxSpend.toLocaleString('en-IN') + ' on-demand budget for this shift'];
    }
    if (tool === 'extend_promise') return [false, 'the 10-minute promise is a hard limit and is never extended'];
    return [true, ''];
  }
  function gRelay(tool, a, ctx) {
    if (tool === 'set_pacing') {
      const bc = get(a, 'bench_cap', null), ps = get(a, 'pace_slack', null);
      if (bc !== null && !(3 <= pyInt(bc) && pyInt(bc) <= 10)) return [false, 'bench cap must be 3–10 bags'];
      if (ps !== null && !(45 <= pyInt(ps) && pyInt(ps) <= 180)) return [false, 'pace slack must be 45–180 s (never below the 45 s buffer)'];
    }
    if (tool === 'prioritise') {
      const o = ctx.state.order(get(a, 'order_id', null));
      if (o === null || !(o.status === 'pool' || o.status === 'picking')) return [false, 'order #' + pyStr(get(a, 'order_id', null)) + ' is not waiting to be picked'];
    }
    return [true, ''];
  }
  function gPromise(tool, a, ctx) {
    const w = ctx.state.w, oid = get(a, 'order_id', null), o = ctx.state.order(oid);
    if (o === null) return [false, 'unknown order #' + pyStr(oid)];
    if (tool === 'apply_swap' || tool === 'refund_item') {
      if (Ctx.findItem(o, get(a, 'sku', null)) === null) return [false, '#' + pyStr(oid) + ' has no unresolved ' + pyStr(get(a, 'sku', null))];
    }
    if (tool === 'apply_swap') {
      if (!(o.saved || o.chose)) return [false, 'this customer did not choose a swap; refund instead (no guessed swaps)'];
      const bad = ctx.state.sku(get(a, 'sku', null)), alt = ctx.state.sku(get(a, 'to_sku', null));
      if (alt === null || bad === null) return [false, 'unknown swap item'];
      if (alt.cat !== bad.cat || alt.price < bad.price) return [false, 'swaps must be same category and same-or-higher value'];
      if (alt.hidden || alt.trust < 0.7 || alt.record <= 0) return [false, alt.name + ' is not trusted to be on the shelf'];
    }
    if (tool === 'notify_customer' && [...pyStr(get(a, 'message', ''))].length > 220) return [false, 'customer message must be under 220 characters'];
    return [true, ''];
  }
  const CHECKS = { ledger: gLedger, captain: gCaptain, relay: gRelay, promise: gPromise };
  function guardCheck(agent, tool, args, ctx) {
    try { return CHECKS[agent](tool, args, ctx); }
    catch (e) { if (e.pyName === 'TypeError' || e.pyName === 'ValueError') return [false, 'bad arguments (' + e.pyName + ')']; throw e; }
  }

  // ================================================================ core/llm.py (shared pieces)
  class LLMUnavailable extends Error {}
  const CHARTER = 'You are one of four AI agents that jointly run SyncStore, the operating system of a quick-commerce dark store (MUM-114, Andheri East, Mumbai) during the evening peak. The agents are Ledger (inventory truth), Captain (shift-lead copilot), Relay (rider-first release) and Promise (customer swap choices). You coordinate only through a shared store state: you read the JSON view you are given and act ONLY by calling your tools. Conflict rules, in order: 1 safety and compliance (cold chain, labour limits); 2 the customer promise (the 10-minute promise is never extended); 3 completeness (full basket, or the swap the customer chose); 4 efficiency. Hard limits are enforced in code and any tool call that breaks them is rejected. Use only ids that appear in the input. Call every tool this event needs in one response. Every \'reason\' is one plain-English sentence of at most 25 words that a shift lead can read aloud. Do not reply with prose; reply with tool calls.';
  function tool(name, description, props, required) {
    props = Object.assign({}, props);
    props.reason = { type: 'string', description: 'One sentence a shift lead can read aloud.' };
    return { type: 'function', function: { name: name, description: description, parameters: { type: 'object', properties: props, required: (required || []).concat(['reason']) } } };
  }
  class NoLLM {
    constructor() { this.models = { smart: '—', fast: '—' }; this.calls = 0; this.errors = 0; this.last_error = null; this.last_ok = null; }
    get configured() { return false; }
    health() { return { configured: false, models: this.models, calls: 0, errors: 0, last_error: null, rpm_used: 0, rpm_limit: 25, rpd_used: 0, rpd_limit: 900, cooling: 0, last_ok: null }; }
    async decide() { throw new LLMUnavailable('no LLM configured'); }
  }

  // ================================================================ agents/base.py
  class Ctx {
    constructor(rt, event) { this.rt = rt; this.state = rt.state; this.event = event; this.llm = rt.llm; this.llm_on = rt.llm_on; this.dry_run = rt.layer === 'shadow'; }
    static findItem(o, sid) { for (const it of o.items) if (it.sku === sid && (it.st === 'missing' || it.st === 'open')) return it; return null; }
  }
  const now = () => (typeof performance !== 'undefined' ? performance.now() : Date.now());
  class Agent {
    constructor() { this.stats = { decisions: 0, llm: 0, rules: 0, fallbacks: 0, blocked: 0, actions: 0, ms_total: 0, last_fallback: null }; }
    sense() {}
    wantsLlm() { return true; }
    view() { return {}; }
    rules() { return []; }
    required() { return new Set(); }
    execute() { throw new Error('NotImplemented'); }
    post() {}
    get toolNames() { return new Set(this.tools.map(t => t.function.name)); }
    async handle(ev, ctx) {
      if (this.senses.has(ev.type)) { this.sense(ev, ctx); return null; }
      if (!this.triggers.has(ev.type)) return null;
      this.stats.decisions += 1;
      let plan = null, via = 'rules', meta = {};
      if (ctx.llm_on && this.wantsLlm(ev, ctx)) {
        try {
          ctx.rt.thinking = { agent: this.name, event: ev.type, tier: this.tier };
          const res = await ctx.llm.decide(this.prompt, this.view(ev, ctx), this.tools, this.tier);
          const calls = res[0]; meta = res[1];
          const names = this.toolNames;
          plan = calls.filter(c => names.has(c[0]) && c[1] && typeof c[1] === 'object' && !Array.isArray(c[1]));
          via = 'llm';
        } catch (e) {
          if (!(e instanceof LLMUnavailable)) throw e;
          this.stats.fallbacks += 1; this.stats.last_fallback = e.message; meta = { fallback: e.message };
        } finally { ctx.rt.thinking = null; }
      }
      const need = via === 'llm' ? this.required(ev, ctx) : new Set();
      if (plan === null) plan = this.rules(ev, ctx);
      if (via === 'llm') { this.stats.llm += 1; this.stats.ms_total += meta.ms || 0; } else this.stats.rules += 1;
      const t0 = now();
      let [done, blocked] = this._run(plan, via, meta, via === 'llm', ctx);
      const doneSet = new Set(done), missing = [...need].filter(x => !doneSet.has(x));
      if (missing.length) {
        const fill = this.rules(ev, ctx).filter(c => missing.includes(c[0]));
        meta.filled = missing.slice().sort();
        const [d2, b2] = this._run(fill, 'rules', meta, false, ctx);
        done = done.concat(d2); blocked = blocked.concat(b2);
      }
      this._via = via;
      if (!ctx.dry_run) this.post(ev, ctx);
      return { agent: this.name, via: via, actions: done, blocked: blocked, ms: get(meta, 'ms', null), model: get(meta, 'model', null), fallback: get(meta, 'fallback', null), filled: get(meta, 'filled', null), code_ms: Math.round((now() - t0) * 100) / 100 };
    }
    _run(plan, via, meta, reasonOn, ctx) {
      const done = [], blocked = [];
      for (const [name, args] of plan) {
        const [ok, why] = guardCheck(this.name, name, args, ctx);
        const reason = (args.reason === undefined ? '' : pyStr(args.reason)).trim();
        if (!ok) { this.stats.blocked += 1; blocked.push(name); ctx.state.log(this.name, 'Blocked ' + name + ': ' + why + '.', { via: 'guardrail', meta: { proposed_by: via } }); continue; }
        if (ctx.dry_run) { ctx.state.log(this.name, this.describe(name, args, ctx), { via: via, shadow: true, why: reasonOn && reason ? reason : null }); done.push(name); continue; }
        let out;
        try { out = this.execute(name, args, ctx); }
        catch (e) {
          if (!e.pyName) { if (e instanceof OwnershipError) throw e; e.pyName = 'TypeError'; }
          blocked.push(name); ctx.state.log(this.name, 'Could not run ' + name + ': ' + e.pyName + '.', { via: 'guardrail' }); continue;
        }
        this.stats.actions += 1; done.push(name);
        if (out) {
          let text, hi = null, story = null;
          if (Array.isArray(out)) { text = out[0]; hi = out[1] === undefined ? null : out[1]; story = out[2] === undefined ? null : out[2]; } else text = out;
          const m = {}; if ('model' in meta) m.model = meta.model; if ('ms' in meta) m.ms = meta.ms;
          ctx.state.log(this.name, text, { hi: hi, via: via, story: story, why: reasonOn && reason ? reason : null, meta: m });
        }
      }
      return [done, blocked];
    }
    describe(name, args) { return name + '(' + Object.keys(args).filter(k => k !== 'reason').map(k => k + '=' + pyStr(args[k])).join(', ') + ')'; }
    publicStats() {
      const s = Object.assign({}, this.stats);
      s.avg_ms = s.llm ? pyRound(s.ms_total / s.llm) : null;
      s.name = this.name; s.title = this.title; s.tier = this.tier;
      s.triggers = [...this.triggers].sort(); s.tools = [...this.toolNames].sort();
      return s;
    }
  }
  const req = (a, k) => { if (!(k in a)) throw KeyErr(k); return a[k]; };

  // ================================================================ agents/ledger.py
  const LEDGER_PROMPT = 'You are LEDGER, the inventory-truth agent. You own each item\'s trust score (0-0.99), whether\nit is visible in the customer app, its stock record, and count/refill tasks.\n\nEvents you handle:\n- pick_not_found: a picker found the slot empty or short while the record shows stock (phantom stock).\n  Expected: set_trust to 0.10 or lower; hide_item if it is not already hidden, so no new order takes it;\n  lower_aisle_trust for its neighbours the first time; create_count_task(mode="empty") unless a count is open.\n- trust_drift: an item\'s trust slipped below 0.60 with no recent count. Expected: create_count_task(mode="check").\n- count_result: an associate counted the shelf. Expected: correct_record to the counted number when it\n  differs from the record. If the count was for an empty slot: if counted > 0, restore_item and set_trust ~0.90;\n  if counted is 0 and the backroom has stock, trigger_refill (up to 16); if the backroom is empty, raise_reorder.\n  For a \'check\' count that matches the record (within 1), set_trust to 0.95.\nNever restore an item without a count or refill showing stock.';
  class Ledger extends Agent {
    constructor() {
      super(); this.name = 'ledger'; this.title = 'Inventory truth'; this.tier = 'fast';
      this.triggers = new Set(['pick_not_found', 'trust_drift', 'count_result', 'refill_done']); this.senses = new Set(['minute']); this.prompt = LEDGER_PROMPT;
      this.tools = [
        tool('set_trust', "Set an item's trust score.", { sku: { type: 'string' }, value: { type: 'number' } }, ['sku', 'value']),
        tool('hide_item', 'Hide the item in the customer app so no new order can take it.', { sku: { type: 'string' } }, ['sku']),
        tool('lower_aisle_trust', 'Lower trust of other items in the same aisle (likely the same cause).', { sku: { type: 'string' } }, ['sku']),
        tool('create_count_task', 'Send a 30-second shelf count to the nearest idle associate.', { sku: { type: 'string' }, mode: { type: 'string', enum: ['empty', 'check'] } }, ['sku', 'mode']),
        tool('correct_record', 'Set the stock record to the counted quantity.', { sku: { type: 'string' }, value: { type: 'integer' } }, ['sku', 'value']),
        tool('trigger_refill', 'Move stock from the backroom to the shelf (about 3 minutes).', { sku: { type: 'string' }, qty: { type: 'integer' } }, ['sku', 'qty']),
        tool('restore_item', 'Make the item visible in the app again.', { sku: { type: 'string' } }, ['sku']),
        tool('raise_reorder', 'The item is truly out: keep it hidden and send a reorder to the warehouse.', { sku: { type: 'string' } }, ['sku']),
      ];
    }
    sense(ev, ctx) {
      const w = ctx.state.w;
      for (const s of Object.values(w.skus)) {
        if (s.hidden || s.counting || s.status === 'out') continue;
        s.trust = pyRoundN(Math.max(0.3, s.trust - 0.004), 3);
        if (s.trust < 0.6 && w.t - (s.drift_at === undefined ? -999 : s.drift_at) > 300) { s.drift_at = w.t; w.emit('trust_drift', { sku: s.id, trust: s.trust }); }
      }
    }
    wantsLlm(ev) { return ev.type !== 'refill_done'; }
    view(ev, ctx) {
      const s = ctx.state.sku(ev.sku);
      const item = { sku: s.id, name: s.name, aisle: s.aisle, record: s.record, trust: s.trust, hidden: s.hidden, status: s.status, count_task_open: s.counting, backroom: s.backroom };
      const v = { event: ev.type, time: ctx.rt.clock(), item: item };
      if (ev.type === 'pick_not_found') { v.record_when_picked = ev.record; v.units_short = ev.misses.length; v.aisle_neighbours = Object.values(ctx.state.w.skus).filter(x => x.aisle === s.aisle && x !== s).map(x => ({ sku: x.id, trust: x.trust })); }
      if (ev.type === 'count_result') v.count = { mode: ev.mode, counted_on_shelf: ev.counted, record_at_count: ev.record, backroom: ev.backroom };
      return v;
    }
    rules(ev, ctx) {
      const s = ctx.state.sku(ev.sku), sid = s.id, typ = ev.type;
      if (typ === 'pick_not_found') {
        const plan = [['set_trust', { sku: sid, value: 0.1 }]];
        if (!s.hidden) plan.push(['hide_item', { sku: sid }], ['lower_aisle_trust', { sku: sid }]);
        if (!s.counting) plan.push(['create_count_task', { sku: sid, mode: 'empty' }]);
        return plan;
      }
      if (typ === 'trust_drift') return [['create_count_task', { sku: sid, mode: 'check' }]];
      if (typ === 'count_result') {
        const c = ev.counted, rec = ev.record, plan = [];
        if (c !== rec) plan.push(['correct_record', { sku: sid, value: c }]);
        if (ev.mode === 'check') plan.push(['set_trust', { sku: sid, value: c >= rec - 1 ? 0.95 : 0.9 }]);
        else if (c > 0) plan.push(['restore_item', { sku: sid }], ['set_trust', { sku: sid, value: 0.9 }]);
        else if (ev.backroom > 0) plan.push(['trigger_refill', { sku: sid, qty: Math.min(16, ev.backroom) }]);
        else plan.push(['raise_reorder', { sku: sid }]);
        return plan;
      }
      if (typ === 'refill_done') return [['set_trust', { sku: sid, value: 0.95 }], ['restore_item', { sku: sid }]];
      return [];
    }
    required(ev, ctx) {
      const s = ctx.state.sku(ev.sku), need = new Set();
      if (ev.type === 'pick_not_found') { if (!s.hidden) need.add('hide_item'); if (!s.counting) need.add('create_count_task'); return need; }
      if (ev.type === 'count_result') { if (ev.counted !== ev.record) need.add('correct_record'); if (ev.mode === 'empty' && ev.counted <= 0) need.add(ev.backroom > 0 ? 'trigger_refill' : 'raise_reorder'); return need; }
      return need;
    }
    execute(name, a, ctx) {
      const st = ctx.state, sid = req(a, 'sku'), s = st.sku(sid), ev = ctx.event;
      if (name === 'set_trust') {
        const old = s.trust; st.setTrust(this.name, sid, req(a, 'value'));
        if (ev.type === 'count_result' && ev.mode === 'check') {
          const c = ev.counted, rec = ev.record;
          if (c >= rec - 1) return 'Check on ' + s.name + ': record confirmed (' + c + ' on the shelf). Trust ' + f2(old) + ' → ' + f2(s.trust) + '.';
          return 'Check on ' + s.name + ' found ' + c + ' on the shelf, ' + (rec - c) + ' fewer than the record. Fixed before any order hit it. Trust ' + f2(old) + ' → ' + f2(s.trust) + '.';
        }
        if (ev.type === 'trust_drift' && Math.abs(old - s.trust) >= 0.005) return 'Trust for ' + s.name + ': ' + f2(old) + ' → ' + f2(s.trust) + '.';
        return null;
      }
      if (name === 'hide_item') {
        if (st.hide(this.name, sid)) return [s.name + ': a picker found the slot empty while the record shows ' + get(ev, 'record', s.record) + '. Hidden in the app, so no new order takes it.', s.name + ' का शेल्फ खाली है। इसे ऐप से छिपा दिया और गिनती का काम भेज दिया है।', 'empty'];
        return null;
      }
      if (name === 'lower_aisle_trust') { st.lowerAisleTrust(this.name, sid); return 'Neighbours of ' + s.name + ' in aisle A' + s.aisle + ' get a small trust cut (same likely cause).'; }
      if (name === 'create_count_task') {
        if (st.requestCount(this.name, sid, req(a, 'mode'))) {
          if (a.mode === 'check') return 'Trust for ' + s.name + ' fell to ' + f2(s.trust) + ' with no recent count. Sent a 30-second check before any order fails on it.';
          return '30-second count task for ' + s.name + ' sent to the nearest idle associate.';
        }
        return null;
      }
      if (name === 'correct_record') { const old = s.record; st.correctRecord(this.name, sid, req(a, 'value')); return ['Count for ' + s.name + ': ' + s.record + ' on the shelf, ' + get(ev, 'backroom', s.backroom) + ' in the backroom. Record corrected from ' + old + '.', null, 'count']; }
      if (name === 'trigger_refill') { st.requestRefill(this.name, sid, req(a, 'qty')); return 'Refill of ' + pyStr(a.qty) + ' × ' + s.name + ' from the backroom requested (about 3 minutes).'; }
      if (name === 'restore_item') { st.restore(this.name, sid); return [s.name + ' is live again with ' + s.shelf + ' units. Similar items get extra checks.', null, 'live']; }
      if (name === 'raise_reorder') { st.markOut(this.name, sid); return s.name + ' is truly out of stock: none in the backroom. It stays hidden and a reorder went to the warehouse.'; }
      throw ValErr(name);
    }
    post(ev, ctx) {
      const s = 'sku' in ev ? ctx.state.sku(ev.sku) : null;
      if (s === null) return;
      if (ev.type === 'count_result') {
        if (ev.mode === 'empty' && ev.counted > 0) ctx.state.w.kpi.falseFlags += 1;
        if (ev.mode === 'check' || (!s.hidden && s.status !== 'refilling')) ctx.state.finishCheck(this.name, s.id);
        if (ev.mode === 'check' && ev.counted < ev.record - 1) ctx.state.w.stats.fixed += 1;
      }
      if (ev.type === 'refill_done' && s.hidden) s.counting = false;
    }
    describe(name, a, ctx) {
      const s = ctx.state.sku(get(a, 'sku', '')), nm = s ? s.name : pyStr(get(a, 'sku', null));
      const m = { set_trust: 'Set trust for ' + nm + ' to ' + pyStr(get(a, 'value', null)) + '.', hide_item: 'Hide ' + nm + ' in the app.', lower_aisle_trust: 'Lower trust for ' + nm + "'s aisle.",
        create_count_task: 'Send a ' + pyStr(get(a, 'mode', null)) + ' count for ' + nm + '.', correct_record: 'Correct ' + nm + "'s record to " + pyStr(get(a, 'value', null)) + '.',
        trigger_refill: 'Refill ' + pyStr(get(a, 'qty', null)) + ' × ' + nm + '.', restore_item: 'Restore ' + nm + '.', raise_reorder: 'Reorder ' + nm + '.' };
      return m[name] || name;
    }
  }

  // ================================================================ agents/captain.py
  const MODE_HI = { trough: 'शांत', normal: 'सामान्य', peak: 'पीक', surge: 'सर्ज' };
  const CAPTAIN_PROMPT = "You are CAPTAIN, the shift-lead copilot. You own the store's operating mode and its limits,\nthe fast-mover front racks, staffing requests to the shift lead, and the Hindi voice briefing.\n\nModes: trough (discrete picking, 1 order per trolley, no hold), normal (cluster, up to 3, hold 30 s),\npeak (cluster, up to 4, hold 75 s), surge (zone pick-and-merge, up to 4, hold 90 s).\nOps bounds you can never exceed: at most 4 orders per trolley, hold cap at most 90 s.\nThresholds on utilisation: below 0.50 trough, below 0.80 normal, else peak; 0.92 now or a backlog growing\n3 minutes in a row means surge. Step down only one mode at a time and only after 3 calm minutes (the\ninput tells you when that is satisfied).\n\nOn mode_signal: decide with set_mode (and set_limits only if you want tighter limits than the mode\ndefault). Going into peak or surge: move_fast_movers to the front, request_staff floater_in_store (and\nfloater_borrow for surge). Going down to normal or trough: move_fast_movers back. Always end with\nbrief_shift_lead: a short spoken briefing in Hindi (Devanagari script) plus its English meaning.\nIf the 15-minute forecast is high (0.85 or more) and on-demand pickers are available, book_ondemand hourly pickers\nfor the peak (count 1-4, hours 1-3); the shift lead approves the spend. On shift_summary: call brief_shift_lead once with a 2-sentence summary using the numbers given.\nNever extend the 10-minute promise.";
  const STAFF = { floater_in_store: 'Call the in-store floater picker (Kiran) for the peak', floater_borrow: 'Borrow a floater picker from the nearby store (Neel, about 4 minutes away)' };
  // How many hourly pickers would bring the 15-minute forecast back to about 0.80 utilisation.
  function gigSuggest(w) {
    const n = Math.max(1, w.activePickers().length), room = Math.max(0, GIG.maxOnFloor - w.gigOnFloor());
    const need = Math.ceil(w.u_fc * n / 0.8 - n);
    return { count: Math.max(0, Math.min(room, need)), hours: w.u_fc >= 0.95 ? 2 : 1, uFc: w.u_fc, pickers: n };
  }
  class Captain extends Agent {
    constructor() {
      super(); this.name = 'captain'; this.title = 'Shift-lead copilot'; this.tier = 'smart';
      this.triggers = new Set(['mode_signal', 'shift_summary', 'demand_forecast']); this.senses = new Set(['minute']); this.prompt = CAPTAIN_PROMPT;
      this.tools = [
        tool('set_mode', "Switch the store's operating mode (also resets limits to that mode's defaults).", { mode: { type: 'string', enum: MODES } }, ['mode']),
        tool('set_limits', 'Tighten orders-per-trolley or the hold cap within ops bounds.', { max_batch: { type: 'integer' }, hold_s: { type: 'integer' } }, []),
        tool('move_fast_movers', 'Move chips, cola and popcorn to the front racks (true) or back (false).', { to_front: { type: 'boolean' } }, ['to_front']),
        tool('request_staff', 'Ask the shift lead to approve extra pickers.', { kind: { type: 'string', enum: ['floater_in_store', 'floater_borrow'] } }, ['kind']),
        tool('book_ondemand', 'Ask the shift lead to book on-demand pickers by the hour for the coming peak (they arrive in about 10 minutes).', { count: { type: 'integer' }, hours: { type: 'integer' } }, ['count', 'hours']),
        tool('brief_shift_lead', 'Speak a short briefing to the shift lead.', { hindi: { type: 'string', description: 'Devanagari, under 160 characters' }, english: { type: 'string' } }, ['hindi', 'english']),
      ];
    }
    sense(ev, ctx) {
      const w = ctx.state.w, b = ev.backlog;
      const grow = b.length === 4 && b[3] > b[2] && b[2] > b[1] && b[1] > b[0] && b[3] >= 6;
      const v = Math.max(ev.u_now, ev.u_fc);
      let target = v < 0.5 ? 'trough' : v < 0.8 ? 'normal' : 'peak';
      if (ev.u_now >= 0.92 || grow) target = 'surge';
      const ri = MODES.indexOf(w.mode), ti = MODES.indexOf(target);
      let why = null;
      if (ti > ri) { w.down = 0; why = (target === 'surge' && grow) ? 'backlog grew 3 minutes in a row' : 'load is above the threshold'; }
      else if (ti < ri) {
        const thr = MODE_UP[w.mode];
        w.down = v <= thr - 0.05 ? w.down + 1 : 0;
        if (w.down >= 3) { target = MODES[ri - 1]; why = 'load stayed 5 points below the threshold for 3 minutes'; }
      } else w.down = 0;
      if (why && (w.t - (this._last_sig === undefined ? -999 : this._last_sig) > 170 || (this._last_target === undefined ? null : this._last_target) !== target)) {
        this._last_sig = w.t; this._last_target = target;
        w.emit('mode_signal', { target: target, direction: MODES.indexOf(target) > ri ? 'up' : 'down', why: why, u_now: ev.u_now, u_fc: ev.u_fc, backlog: b, grow: grow });
      }
      // High predicted demand: offer on-demand hourly pickers before the rush lands.
      if (ctx.rt.ondemand && ev.u_fc >= 0.85 && w.t - (this._last_gig === undefined ? -99999 : this._last_gig) > 1200 && !w.approvals.some(a => a.ondemand && a.status === 'pending')) {
        const g = gigSuggest(w);
        if (g.count > 0 && ctx.rt.gigSpend() + g.count * g.hours * GIG.rate <= GIG.maxSpend) { this._last_gig = w.t; w.emit('demand_forecast', { u_fc: ev.u_fc, u_now: ev.u_now, count: g.count, hours: g.hours, pickers: g.pickers }); }
      }
    }
    view(ev, ctx) {
      const w = ctx.state.w;
      if (ev.type === 'shift_summary') return { event: 'shift_summary', time: ctx.rt.clock(), numbers: ev.numbers };
      if (ev.type === 'demand_forecast') return { event: 'demand_forecast', time: ctx.rt.clock(), forecast_15min: pyRoundN(ev.u_fc, 2), utilisation_now: pyRoundN(ev.u_now, 2), pickers_on_floor: w.activePickers().length, current_mode: w.mode,
        ondemand: { rate_per_hour: GIG.rate, arrive_in_min: GIG.leadS / 60, on_floor: w.gigOnFloor(), max_on_floor: GIG.maxOnFloor, spent: ctx.rt.gigSpend(), budget: GIG.maxSpend, suggested: { count: ev.count, hours: ev.hours } } };
      return { event: 'mode_signal', time: ctx.rt.clock(), current_mode: w.mode, current_limits: w.lim, suggested_mode: ev.target, direction: ev.direction, why: ev.why,
        utilisation_now: pyRoundN(ev.u_now, 2), forecast_15min: pyRoundN(ev.u_fc, 2), backlog_last_4_min: ev.backlog, pickers_on_floor: w.activePickers().length,
        calm_minutes_for_step_down: w.down, ops_bounds: OPS_BOUNDS, ondemand: ctx.rt.ondemand ? { rate_per_hour: GIG.rate, on_floor: w.gigOnFloor(), max_on_floor: GIG.maxOnFloor, spent: ctx.rt.gigSpend(), budget: GIG.maxSpend, suggested: gigSuggest(w) } : null, fast_movers_in_front: Object.values(w.skus).some(s => s.fwd), staff_already_requested: w.approvals.map(a => a.id) };
    }
    required(ev) {
      if (ev.type === 'shift_summary') return new Set(['brief_shift_lead']);
      if (ev.type === 'demand_forecast') return new Set();
      return ev.direction === 'up' ? new Set(['set_mode', 'brief_shift_lead']) : new Set();
    }
    rules(ev, ctx) {
      const w = ctx.state.w;
      if (ev.type === 'shift_summary') {
        const n = ev.numbers;
        return [['brief_shift_lead', {
          english: 'Shift summary: ' + n.wrong_records_caught + ' wrong stock records caught, ' + n.customer_chosen_swaps + ' customer-chosen swaps applied, orders shared a trolley ' + n.shared_trolley_trips + ' times, and about ' + n.walking_saved_m + ' m of walking saved against the static plan.',
          hindi: 'शिफ्ट सारांश: ' + n.wrong_records_caught + ' गलत स्टॉक रिकॉर्ड पकड़े गए, ' + n.customer_chosen_swaps + ' ग्राहकों की चुनी हुई अदला-बदली हुई, और लगभग ' + n.walking_saved_m + ' मीटर पैदल चलना बचा।' }]];
      }
      if (ev.type === 'demand_forecast') {
        const n = ev.count, h = ev.hours;
        return [['book_ondemand', { count: n, hours: h }], ['brief_shift_lead', {
          english: 'Demand forecast ' + f2(ev.u_fc) + ' in 15 minutes with ' + ev.pickers + ' pickers. I asked to book ' + n + ' on-demand picker' + (n > 1 ? 's' : '') + ' for ' + h + ' h; they arrive in 10 minutes.',
          hindi: 'अगले 15 मिनट में ऑर्डर बढ़ेंगे। ' + n + ' घंटे वाले पिकर ' + h + ' घंटे के लिए बुलाने की मंज़ूरी माँगी है।' }]];
      }
      const m = ev.target;
      const fc = 'utilisation ' + f2(ev.u_now) + ' now, ' + f2(ev.u_fc) + ' forecast in 15 min';
      const plan = [['set_mode', { mode: m }]];
      if (ev.direction === 'up') {
        if (m === 'peak' || m === 'surge') { plan.push(['move_fast_movers', { to_front: true }]); plan.push(['request_staff', { kind: 'floater_in_store' }]); }
        if (m === 'surge') plan.push(['request_staff', { kind: 'floater_borrow' }]);
        if (ctx.rt.ondemand && ev.u_fc >= 0.85 && (m === 'peak' || m === 'surge')) { const g = gigSuggest(w); if (g.count) plan.push(['book_ondemand', { count: g.count, hours: g.hours }]); }
        if (m === 'peak') plan.push(['brief_shift_lead', { english: 'Peak mode: ' + fc + '. Batches up to 4, hold cap 75 s. Chips, cola and popcorn to the front racks.', hindi: 'पीक मोड शुरू हो रहा है। फ्लोटर को तैयार रखिए, और चिप्स, कोला, पॉपकॉर्न आगे वाले रैक पर रखिए।' }]);
        else if (m === 'surge') plan.push(['brief_shift_lead', { english: 'Surge mode: ' + ev.why + '. Zone pick-and-merge is on. The 10-minute promise is not extended.', hindi: 'सर्ज मोड चालू है। ज़ोन पिकिंग शुरू। दस मिनट का वादा नहीं बदलेगा।' }]);
        else plan.push(['brief_shift_lead', { english: MODE_LABEL[m] + ' mode: ' + fc + '.', hindi: MODE_HI[m] + ' मोड।' }]);
      } else {
        if (m === 'normal' || m === 'trough') plan.push(['move_fast_movers', { to_front: false }]);
        plan.push(['brief_shift_lead', { english: MODE_LABEL[m] + ' mode: ' + ev.why + ', so the store steps down one mode (hysteresis).', hindi: 'लोड कम हो रहा है। अब ' + MODE_HI[m] + ' मोड।' }]);
      }
      return plan;
    }
    execute(name, a, ctx) {
      const st = ctx.state, w = st.w, ev = ctx.event;
      if (name === 'set_mode') {
        const prev = w.mode, mode = req(a, 'mode');
        if (mode === prev) return null;
        st.setMode(this.name, mode);
        const up = MODES.indexOf(mode) > MODES.indexOf(prev);
        const story = up ? (mode === 'surge' ? 'surge' : mode === 'peak' ? 'peak' : null) : 'winddown';
        const lim = LIMITS[mode];
        return [MODE_LABEL[prev] + ' → ' + MODE_LABEL[mode] + ' mode (' + ev.why + '). Up to ' + lim.max + ' orders per trolley, hold cap ' + lim.hold + ' s.', null, story];
      }
      if (name === 'set_limits') { st.setLimits(this.name, get(a, 'max_batch', null), get(a, 'hold_s', null)); return 'Limits tightened: up to ' + w.lim.max + ' per trolley, hold cap ' + w.lim.hold + ' s.'; }
      if (name === 'move_fast_movers') {
        const on = !!req(a, 'to_front');
        if (Object.values(w.skus).some(s => s.fwd) === on) return null;
        st.setFrontRacks(this.name, on);
        return on ? 'Asked for chips, cola and popcorn to move to the front racks.' : 'Fast movers go back to their home slots.';
      }
      if (name === 'request_staff') { const kind = req(a, 'kind'); if (st.requestApproval(this.name, kind, STAFF[kind])) return 'Above my limits, so I asked the shift lead: ' + STAFF[kind] + '.'; return null; }
      if (name === 'book_ondemand') {
        const n = pyInt(req(a, 'count')), h = pyInt(req(a, 'hours'));
        if (st.requestOnDemand(this.name, n, h, 'forecast ' + f2(ev.u_fc || 0) + ' in 15 min')) return 'Forecast is high (' + f2(ev.u_fc || 0) + ' in 15 min), so I asked the shift lead to book ' + n + ' on-demand picker' + (n > 1 ? 's' : '') + ' for ' + h + ' h at ₹' + GIG.rate + ' an hour.';
        return null;
      }
      if (name === 'brief_shift_lead') { st.setBrief(this.name, req(a, 'hindi'), req(a, 'english')); const story = ev.type === 'shift_summary' ? 'summary' : null; return [a.english, a.hindi, story]; }
      throw ValErr(name);
    }
    describe(name, a) {
      const m = { set_mode: 'Switch to ' + pyStr(get(a, 'mode', null)) + ' mode.', set_limits: 'Set limits ' + pyStr(get(a, 'max_batch', null)) + ' per trolley, hold ' + pyStr(get(a, 'hold_s', null)) + ' s.',
        move_fast_movers: get(a, 'to_front', null) ? 'Move fast movers to the front.' : 'Move fast movers back.',
        book_ondemand: 'Book ' + pyStr(get(a, 'count', null)) + ' on-demand pickers for ' + pyStr(get(a, 'hours', null)) + ' h.',
        request_staff: 'Ask the shift lead: ' + (STAFF[get(a, 'kind', null)] || pyStr(get(a, 'kind', null))) + '.', brief_shift_lead: 'Brief: ' + pyStr(get(a, 'english', null)) };
      return m[name] || name;
    }
  }

  // ================================================================ agents/relay.py
  const RELAY_PROMPT = 'You are RELAY, the rider-first release agent. You own the release policy (bench_cap: how many\nbags may wait at the packing bench before you hold back releases; pace_slack: orders with more buffer\nthan this are held while the bench is congested) and short priority boosts for specific orders.\nBounds: bench_cap 3-10, pace_slack 45-180 s. An order whose buffer is under 45 s is always released at once.\n\nEvents:\n- rider_late: a rider is now 2 minutes late. Usually prioritise the waiting order whose rider arrives\n  soonest (it should go first), and announce the change to the floor in one sentence.\n- bench_congested: bags are piling up at the bench. Use set_pacing (typically bench_cap 4-5, pace_slack\n  60-120: hold more when riders are not yet at the store, less when riders are already waiting) and announce.\nKeep announcements under 30 words and mention order numbers with #.';
  class Relay extends Agent {
    constructor() {
      super(); this.name = 'relay'; this.title = 'Rider-first release'; this.tier = 'fast';
      this.triggers = new Set(['rider_late', 'bench_congested', 'bench_cleared', 'eta_change']); this.senses = new Set(); this.prompt = RELAY_PROMPT;
      this.tools = [
        tool('prioritise', 'Boost one waiting order so the optimiser releases it first (3 minutes).', { order_id: { type: 'integer' } }, ['order_id']),
        tool('set_pacing', 'Set how releases are paced while the packing bench is congested.', { bench_cap: { type: 'integer' }, pace_slack: { type: 'integer' } }, []),
        tool('announce', 'Tell the floor what changed and why.', { message: { type: 'string' } }, ['message']),
      ];
    }
    wantsLlm(ev) { return ev.type !== 'bench_cleared'; }
    _waiting(ctx, exclude) { const w = ctx.state.w; return sortBy(w.activeOrders().filter(o => o.status === 'pool' && o.id !== exclude), o => o.rider_arrive); }
    view(ev, ctx) {
      const w = ctx.state.w;
      const v = { event: ev.type, time: ctx.rt.clock(), release_policy: Object.assign({}, w.release_policy), bench_queue: w.bench.q.length, bags_ready: w.bench.ready.length,
        riders_at_store: w.activeOrders().filter(o => o.rider_arrive <= w.t).length };
      v.waiting_orders = this._waiting(ctx, get(ev, 'order_id', null)).slice(0, 6).map(o => ({ order_id: o.id, rider_arrives_in_s: o.rider_arrive - w.t, buffer_s: pyRound(w.slackOf(o)) }));
      if (ev.type === 'eta_change') { const o = w.by_id.get(ev.order_id); v.eta_change = { order_id: o.id, rider_now_arrives_in_s: o.rider_arrive - w.t, moved_by_s: ev.delta, status: o.status }; }
      if (ev.type === 'rider_late') { const o = w.by_id.get(ev.order_id); v.late_order = { order_id: o.id, rider_now_arrives_in_s: o.rider_arrive - w.t, buffer_s: pyRound(w.slackOf(o)), status: o.status }; }
      return v;
    }
    rules(ev, ctx) {
      const w = ctx.state.w;
      if (ev.type === 'rider_late') {
        const list = this._waiting(ctx, ev.order_id), nxt = list.length ? list[0] : null;
        const msg = 'Rider for #' + ev.order_id + ' is running 2 min late. Its time buffer grew by 120 s, so ' + (nxt ? '#' + nxt.id + ' (rider ' + mmss(nxt.rider_arrive - w.t) + ' away) goes first and ' : '') + '#' + ev.order_id + ' can now share a trolley.';
        const plan = nxt ? [['prioritise', { order_id: nxt.id }]] : [];
        return plan.concat([['announce', { message: msg }]]);
      }
      if (ev.type === 'bench_congested') {
        const waiting = w.activeOrders().filter(o => o.rider_arrive <= w.t).length, slack = waiting >= 3 ? 60 : 90;
        return [['set_pacing', { bench_cap: 5, pace_slack: slack }], ['announce', { message: 'Packing bench has ' + ev.queue + ' bags waiting. Holding orders with more than ' + slack + ' s of buffer until it clears.' }]];
      }
      if (ev.type === 'bench_cleared') return [['set_pacing', { bench_cap: 5, pace_slack: 90 }]];
      if (ev.type === 'eta_change') return [['prioritise', { order_id: ev.order_id }], ['announce', { message: 'Rider for #' + ev.order_id + ' is now ' + mmss(ev.eta) + ' away (' + Math.abs(ev.delta) + ' s sooner), so #' + ev.order_id + ' moves up the pick queue.' }]];
      return [];
    }
    execute(name, a, ctx) {
      const st = ctx.state, ev = ctx.event;
      if (name === 'prioritise') { st.boost(this.name, pyInt(req(a, 'order_id'))); return null; }
      if (name === 'set_pacing') {
        const before = JSON.stringify(st.w.release_policy);
        st.setReleasePolicy(this.name, get(a, 'bench_cap', null), get(a, 'pace_slack', null));
        const after = st.w.release_policy;
        if (before === JSON.stringify(after) || ev.type === 'bench_cleared') return null;
        return 'Release pacing set: hold releases when ' + after.bench_cap + '+ bags wait, unless an order has under ' + after.pace_slack + ' s of buffer.';
      }
      if (name === 'announce') { const story = ev.type === 'rider_late' ? 'riderlate' : null; return [[...pyStr(req(a, 'message'))].slice(0, 300).join(''), null, story]; }
      throw ValErr(name);
    }
    describe(name, a) {
      const m = { prioritise: 'Release #' + pyStr(get(a, 'order_id', null)) + ' first.', set_pacing: 'Pace releases (bench cap ' + pyStr(get(a, 'bench_cap', null)) + ', slack ' + pyStr(get(a, 'pace_slack', null)) + ' s).', announce: pyStr(get(a, 'message', '')) };
      return m[name] || name;
    }
  }

  // ================================================================ agents/promise.py
  const PROMISE_PROMPT = 'You are PROMISE, the customer-promise agent. You own the items in live orders and messages to\ncustomers. An item just became unavailable. For EACH affected order line in the input:\n- if customer_choice is "swap" and a swap_option exists: apply_swap to that option;\n- otherwise refund_item (the customer gets an instant refund for that item).\nNever swap when the customer did not choose a swap. Never pick a swap other than swap_option.\nThen notify_customer once per affected order with one friendly sentence (under 25 words, no emojis),\ne.g. what was swapped or refunded. Resolve every line; do not skip any.';
  class Promise_ extends Agent {
    constructor() {
      super(); this.name = 'promise'; this.title = 'Customer swap choices'; this.tier = 'smart';
      this.triggers = new Set(['pick_not_found', 'sku_hidden']); this.senses = new Set(); this.prompt = PROMISE_PROMPT;
      this.tools = [
        tool('apply_swap', 'Replace the missing item with the swap the customer chose.', { order_id: { type: 'integer' }, sku: { type: 'string' }, to_sku: { type: 'string' } }, ['order_id', 'sku', 'to_sku']),
        tool('refund_item', 'Drop the missing item and refund it instantly.', { order_id: { type: 'integer' }, sku: { type: 'string' } }, ['order_id', 'sku']),
        tool('notify_customer', 'Send the customer a short update.', { order_id: { type: 'integer' }, message: { type: 'string' } }, ['order_id', 'message']),
      ];
    }
    _affected(ev, ctx) {
      const w = ctx.state.w, sid = ev.sku, rows = [];
      if (ev.type === 'pick_not_found') {
        for (const [oid, it] of ev.misses) { const o = w.by_id.get(oid); if (o && o.status !== 'cancelled' && it.st === 'missing') rows.push([o, it, get(ev, 'trip', null)]); }
      } else {
        for (const o of w.pool) { if (o.status === 'cancelled') continue; for (const it of o.items) if (it.sku === sid && it.st === 'open') rows.push([o, it, null]); }
      }
      return rows;
    }
    wantsLlm(ev, ctx) { return this._affected(ev, ctx).length > 0; }
    view(ev, ctx) {
      const w = ctx.state.w, s = w.skus[ev.sku], alt = w.swapCandidate(s);
      return { event: ev.type, time: ctx.rt.clock(), unavailable_item: { sku: s.id, name: s.name, price: s.price },
        swap_option: alt ? { sku: alt.id, name: alt.name, price: alt.price } : null,
        affected_lines: this._affected(ev, ctx).map(([o, it]) => ({ order_id: o.id, sku: it.sku, where: it.st === 'missing' ? 'mid_pick' : 'not_yet_picked', customer_choice: (o.saved || o.chose) ? 'swap' : 'refund' })) };
    }
    rules(ev, ctx) {
      const w = ctx.state.w, alt = w.swapCandidate(w.skus[ev.sku]), plan = [], seen = new Set();
      for (const [o, it] of this._affected(ev, ctx)) {
        let msg;
        if (alt && (o.saved || o.chose)) { plan.push(['apply_swap', { order_id: o.id, sku: it.sku, to_sku: alt.id }]); msg = w.skus[it.sku].name + ' ran out, so we packed ' + alt.name + ' as you chose. No extra charge.'; }
        else { plan.push(['refund_item', { order_id: o.id, sku: it.sku }]); msg = w.skus[it.sku].name + ' ran out. We refunded it instantly; the rest of your order is on its way.'; }
        if (!seen.has(o.id)) { seen.add(o.id); plan.push(['notify_customer', { order_id: o.id, message: msg }]); }
      }
      return plan;
    }
    async handle(ev, ctx) { this._tally = { swap: 0, drop: 0, cancel: 0, filled: 0 }; return super.handle(ev, ctx); }
    execute(name, a, ctx) {
      const st = ctx.state, ev = ctx.event, oid = pyInt(req(a, 'order_id'));
      if (name === 'notify_customer') { st.notify(this.name, oid, [...pyStr(req(a, 'message'))].slice(0, 220).join('')); return null; }
      const o = st.order(oid); if (o === null) throw new PyError('TypeError');
      const it = Ctx.findItem(o, req(a, 'sku'));
      let trip = null; for (const [, ii, tr] of this._affected(ev, ctx)) if (ii === it) { trip = tr; break; }
      if (name === 'apply_swap') { st.applySwap(this.name, oid, it, req(a, 'to_sku'), trip); this._tally.swap += 1; return null; }
      if (name === 'refund_item') { const r = st.refund(this.name, oid, it); this._tally.drop += 1; if (r === 'cancel') this._tally.cancel += 1; return null; }
      throw ValErr(name);
    }
    post(ev, ctx) {
      const left = this._affected(ev, ctx);
      if (left.length) {
        const alt = ctx.state.w.swapCandidate(ctx.state.w.skus[ev.sku]);
        for (const [o, it, trip] of left) {
          if (alt && (o.saved || o.chose)) { ctx.state.applySwap(this.name, o.id, it, alt.id, trip); this._tally.swap += 1; }
          else { if (ctx.state.refund(this.name, o.id, it) === 'cancel') this._tally.cancel += 1; this._tally.drop += 1; }
          this._tally.filled += 1;
        }
      }
      const tl = this._tally, total = tl.swap + tl.drop;
      if (!total) return;
      const name = ctx.state.w.skus[ev.sku].name, where = ev.type === 'pick_not_found' ? 'mid-pick' : 'waiting in the pool';
      let text = total + ' live order line' + (total > 1 ? 's' : '') + ' with ' + name + ' (' + where + '): ' + tl.swap + ' customer-chosen swap' + (tl.swap === 1 ? '' : 's') + ' applied, ' + tl.drop + ' item' + (tl.drop === 1 ? '' : 's') + ' refunded instantly' + (tl.cancel ? ' (' + tl.cancel + ' customer' + (tl.cancel > 1 ? 's' : '') + ' then cancelled)' : '') + '. No swap was guessed.';
      if (tl.filled) text += ' Rules resolved ' + tl.filled + ' line' + (tl.filled > 1 ? 's' : '') + ' the model skipped.';
      ctx.state.log(this.name, text, { via: this._via === undefined ? 'rules' : this._via, story: 'liveorders' });
    }
    describe(name, a) {
      const m = { apply_swap: 'Swap ' + pyStr(get(a, 'sku', null)) + ' → ' + pyStr(get(a, 'to_sku', null)) + ' in #' + pyStr(get(a, 'order_id', null)) + '.', refund_item: 'Refund ' + pyStr(get(a, 'sku', null)) + ' in #' + pyStr(get(a, 'order_id', null)) + '.', notify_customer: 'Tell #' + pyStr(get(a, 'order_id', null)) + ': ' + pyStr(get(a, 'message', null)) };
      return m[name] || name;
    }
  }

  // ================================================================ core/bus.py
  const ROUTES = { minute: ['ledger', 'captain'], pick_not_found: ['ledger', 'promise'], trust_drift: ['ledger'], count_result: ['ledger'], refill_done: ['ledger'],
    sku_hidden: ['promise'], mode_signal: ['captain'], demand_forecast: ['captain'], shift_summary: ['captain'], rider_late: ['relay'], eta_change: ['relay'], bench_congested: ['relay'], bench_cleared: ['relay'] };
  function summarise(ev, w) {
    const t = ev.type;
    if ('sku' in ev) {
      const nm = w.skus[ev.sku].name;
      if (t === 'pick_not_found') return nm + ': slot empty, ' + ev.misses.length + ' short';
      if (t === 'count_result') return nm + ': counted ' + ev.counted + ' (' + ev.mode + ')';
      if (t === 'trust_drift') return nm + ': trust ' + f2(ev.trust);
      return nm;
    }
    if (t === 'mode_signal') return 'suggest ' + ev.target + ' (' + ev.why + ')';
    if (t === 'demand_forecast') return 'forecast ' + f2(ev.u_fc) + ', suggest ' + ev.count + ' on-demand pickers';
    if (t === 'rider_late') return '#' + ev.order_id + ' rider +2 min';
    if (t === 'eta_change') return '#' + ev.order_id + ' rider ' + ev.delta + ' s';
    if (t === 'bench_congested') return ev.queue + ' bags queued';
    if (t === 'minute') return 'u=' + f2(ev.u_now) + ', fc=' + f2(ev.u_fc);
    return '';
  }
  class EventBus {
    constructor(rt) { this.rt = rt; this.trace = []; this.counts = new Map(); }
    async dispatch(events) {
      const rt = this.rt, q = events.slice();
      while (q.length) {
        const ev = q.shift();
        if (ev.type === 'log') { rt.log(ev.agent, ev.text, { via: get(ev, 'via', 'rules'), story: get(ev, 'story', null) }); continue; }
        if (rt.layer === 'off') continue;
        this.counts.set(ev.type, (this.counts.get(ev.type) || 0) + 1);
        for (const name of (ROUTES[ev.type] || [])) {
          const res = await rt.agents[name].handle(ev, new Ctx(rt, ev));
          if (res !== null) {
            this.trace.unshift(Object.assign({ t: rt.smart.t, event: ev.type, detail: summarise(ev, rt.smart) }, res, { shadow: rt.layer === 'shadow' }));
            if (this.trace.length > 80) this.trace.length = 80;
          }
          q.push(...rt.smart.drain());
        }
      }
    }
  }

  // ================================================================ core/runtime.py
  class Session {
    constructor(llm, seed, opts) {
      this.llm = llm; this.seed = seed === undefined ? 7 : seed; this.opts = opts || {}; this.optTimes = []; this.ondemand = !!this.opts.ondemand; this.etaDrift = !!this.opts.etaDrift; this.llm_on = llm.configured; this.layer = 'live'; this.speed = 10; this.playing = true;
      this.auto_approve = true; this.demo = false; this.spike_rng = new PyRandom(1234); this.user_seq = 9001; this.thinking = null;
      this._build();
    }
    _build() {
      const orders = genOrders(this.seed, this.opts.demand);
      this.smart = new World(orders, 'smart'); this.static = new World(orders, 'static');
      for (const w of [this.smart, this.static]) { if (this.opts.demand) w.demand = this.opts.demand; if (this.opts.shrink) w.shrinkPlan = this.opts.shrink; }
      if (this.opts.slotting) { this.smart.dynSlot = true; if (this.smart.levers.slotting) { this.smart.frontOn = true; this.smart.applyFront(); } }
      if (this.opts.levers) Object.assign(this.smart.levers, this.opts.levers);
      this.optTimes = [];
      this.smart.optimiser = (w) => { const t0 = now(); optimiserRun(w); this.optTimes.push(now() - t0); if (this.optTimes.length > 600) this.optTimes.shift(); };
      this.logs = []; this.story = {}; this.state = new StoreState(this.smart, (a, t, o) => this.log(a, t, o));
      this.agents = {}; for (const a of [new Ledger(), new Captain(), new Relay(), new Promise_()]) this.agents[a.name] = a;
      this.bus = new EventBus(this); this.summary_done = false; this.applyLayer(this.layer, true);
    }
    async reset(startAt, demo) { this.demo = !!demo; this._build(); await this.fastForward(startAt === undefined ? 840 : startAt); }
    async fastForward(to) { const keep = this.llm_on; this.llm_on = false; while (this.smart.t < to) await this.tick(); this.llm_on = keep; }
    clock() { return fmt(this.smart.t); }
    log(agent, text, o) {
      o = o || {};
      const hi = get(o, 'hi', null), via = get(o, 'via', 'rules'), story = get(o, 'story', null), shadow = !!o.shadow, why = get(o, 'why', null), meta = o.meta || {};
      this.logs.unshift({ t: this.smart.t, agent: agent, text: text, hi: hi, via: via, why: why, meta: meta, shadow: shadow || this.layer === 'shadow' });
      if (this.logs.length > 400) this.logs.length = 400;
      if (hi && !shadow && this.layer !== 'shadow') this.smart.brief = { t: this.smart.t, hi: hi, en: text, agent: agent };
      if (story && !(story in this.story) && !shadow) this.story[story] = this.smart.t;
    }
    async tick() {
      const s = this.smart;
      s.step(); this.static.step(); this.static.drain();
      if (this.demo && s.t === 2520) this.riderLate(null, true);
      if (this.etaDrift && s.t % 60 === 0) this.driftEtas();
      if (s.t === 4500 && !this.summary_done) { this.summary_done = true; s.emit('shift_summary', { numbers: this.summaryNumbers() }); }
      if (s.t % 60 === 0 && this.auto_approve) for (const a of s.approvals.slice()) if (a.status === 'pending' && s.t - a.t >= 20) this.approve(a.id, 'by voice');
      await this.bus.dispatch(s.drain());
      if (s.t >= HORIZON - 5) this.playing = false;
    }
    driftEtas() {
      const m = Math.floor(this.smart.t / 60);
      for (const w of [this.smart, this.static]) {
        for (const o of w.activeOrders()) {
          if (o.rider_arrive <= w.t + 40) continue;
          const h = (Math.imul(o.id, 2654435761) ^ Math.imul(m + 1, 40503)) >>> 0, r = (h % 10007) / 10007;
          if (r < 0.55) { o.eta_delta = 0; continue; }
          const d = Math.round((r - 0.775) / 0.225 * 50);
          o.rider_arrive += d; o.eta_delta = d;
          if (w === this.smart) { w.kpi.etaMoves += 1; if (d <= -35 && o.status === 'pool') w.emit('eta_change', { order_id: o.id, delta: d, eta: o.rider_arrive - w.t }); }
        }
      }
    }
    summaryNumbers() {
      const S = this.smart.stats, X = this.static.stats;
      const walkS = S.walk * PX_M / Math.max(1, S.pickN), walkX = X.walk * PX_M / Math.max(1, X.pickN);
      return { wrong_records_caught: S.hidden + S.fixed, customer_chosen_swaps: S.swaps, shared_trolley_trips: S.batchedOrders - S.batches,
        walking_saved_m: Math.max(0, pyRound((walkX - walkS) * S.pickN / 10) * 10), cancellations: S.cancels, cancellations_static_plan: X.cancels };
    }
    applyLayer(layer, quiet) {
      const prev = this.layer; this.layer = layer;
      this.smart.policy = layer === 'live' ? 'smart' : 'static'; this.smart.agents_on = layer !== 'off';
      if (quiet) return;
      if (layer === 'off') this.log('system', 'Agent layer offline. Fail-safe: the store fell back to today’s static picking, and orders keep flowing.');
      else if (layer === 'shadow') this.log('system', 'Shadow mode: the floor runs today’s static plan; the agents only log what they would have done.');
      else this.log('system', prev === 'off' ? 'Agent layer back online. Agents resume from the current store state.' : 'Live mode: agents act on the floor.');
    }
    approve(kind, how) {
      how = how || 'from the dashboard';
      const a = this.smart.approvals.find(x => x.id === kind);
      if (!a || a.status !== 'pending') return;
      a.status = 'approved'; a.at = this.smart.t;
      if (a.ondemand) { this.bookOnDemand(a.count, a.hours, how, true); return; }
      const [name, delay] = kind === 'floater_in_store' ? ['Kiran', 60] : ['Neel', 240];
      this.smart.addPicker(name, delay);
      this.log('captain', 'Shift lead approved ' + how + ': ' + name + ' joins the floor in ' + mmss(delay) + '.', { via: 'shift lead' });
    }
    gigSpend() { return this.smart.kpi.gigCost; }
    bookOnDemand(count, hours, how, approved) {
      const w = this.smart;
      count = Math.max(1, Math.min(GIG.maxOnFloor - w.gigOnFloor(), pyInt(count))); hours = Math.max(1, Math.min(3, pyInt(hours)));
      if (count < 1) return null;
      if (this.gigSpend() + count * hours * GIG.rate > GIG.maxSpend) return null;
      const ps = w.addGig(count, hours);
      this.log('captain', (approved ? 'Shift lead approved ' + (how || 'from the dashboard') + ': ' : 'Shift lead booked ' + (how || 'from the dashboard') + ': ') + ps.map(p => p.name).join(', ') + ' (on-demand, ' + hours + ' h, ₹' + (count * hours * GIG.rate).toLocaleString('en-IN') + ') ' + (ps.length > 1 ? 'join' : 'joins') + ' the floor in 10:00.', { via: 'shift lead' });
      return ps;
    }
    decline(kind) {
      const a = this.smart.approvals.find(x => x.id === kind);
      if (!a || a.status !== 'pending') return;
      a.status = 'declined'; a.at = this.smart.t;
      this.log('captain', 'Shift lead declined: ' + a.text + '. Captain keeps the current staffing.', { via: 'shift lead' });
    }
    emptyShelf(sid) { for (const w of [this.smart, this.static]) w.shrink(sid, 0); return this.smart.skus[sid].name; }
    riderLate(orderId, auto) {
      const s = this.smart, t = s.t;
      if (orderId === null || orderId === undefined) {
        let best = null;
        for (const o of s.activeOrders()) if ((o.status === 'pool' || o.status === 'picking') && o.rider_arrive > t + 20) if (best === null || o.rider_arrive < best.rider_arrive) best = o;
        if (best === null) return null;
        orderId = best.id;
      }
      for (const w of [this.smart, this.static]) { const o = w.by_id.get(orderId); if (o) o.rider_arrive += 120; }
      s.emit('rider_late', { order_id: orderId });
      return orderId;
    }
    spike() {
      const t = this.smart.t, extra = [];
      for (let i = 0; i < 14; i++) { const at = t + 5 + Math.trunc(this.spike_rng.random() * 360); const id = 8001 + Math.trunc(this.spike_rng.random() * 900) + i * 1000; extra.push(makeOrder(this.spike_rng, at, id)); }
      for (const w of [this.smart, this.static]) w.insertOrders(extra);
      this.log('system', 'Demand spike: 14 extra orders over the next 6 minutes (for example, a cricket match ending). The forecast did not expect it, so Captain reacts to live load.');
    }
    placeOrder(cart, choices) {
      const s = this.smart;
      cart = cart.filter(c => Object.prototype.hasOwnProperty.call(s.skus, c)).slice(0, 4);
      if (!cart.length) return null;
      const wantsSwap = (sid) => { const sk = s.skus[sid], pick = get(choices, sid, null); return (sk.hidden ? pick !== 'refund' : pick === 'swap') && s.swapCandidate(sk) !== null; };
      const anySwap = cart.some(wantsSwap);
      const o = { id: this.user_seq, placed: s.t + 1, items: cart.slice(), ride: 200, riderIn: 200, saved: false, chose: anySwap, forceChoice: anySwap, cancelIfMissing: false, user: true };
      this.user_seq += 1;
      for (const w of [this.smart, this.static]) w.insertOrders([o]);
      this.log('promise', 'Order #' + o.id + ' placed from the checkout with ' + cart.length + ' item' + (cart.length > 1 ? 's' : '') + (anySwap ? '; the customer chose a swap for a low-stock item.' : '; no swap chosen, so a missing item would be refunded.'));
      return o.id;
    }
  }

  // ================================================================ server/snapshot.py
  const CHECKOUT_ITEMS = ['milk', 'bread', 'breadb', 'eggs', 'curd', 'paneer', 'chips', 'popcorn', 'cola', 'biscuit', 'coffee', 'icv'];
  function sStats(w) {
    const s = Object.assign({}, w.stats);
    s.avgPick = pyRoundN(w.avgPick(), 1);
    s.walkPerOrder = pyRoundN(w.stats.walk * PX_M / Math.max(1, w.stats.pickN), 1);
    s.riderWaitAvg = w.stats.riderWaitN ? pyRoundN(w.stats.riderWait / w.stats.riderWaitN, 1) : 0;
    return s;
  }
  function sTrip(tr) {
    return { id: tr.id, picker: tr.p.name, zone: tr.zone, n: tr.orders.length, ids: tr.orders.map(o => o.id), start: tr.start, end: pyRoundN(tr.end, 1),
      stops: tr.stops.length, len: pyRound(tr.len), pts: tr.pts.map(p => [pyRoundN(p.x, 1), pyRoundN(p.y, 1), pyRoundN(p.t, 2)]) };
  }
  function stateRows(sess) {
    const w = sess.smart, t = w.t, skus = Object.values(w.skus);
    const low = minBy(skus, s => s.trust);
    const pool = w.pool.filter(o => o.status === 'pool');
    const tight = pool.length ? minBy(pool, o => w.slackOf(o)) : null;
    const aisles = new Array(9).fill(0);
    for (const tr of w.trips) if (!tr.done && tr.end > t) for (const a of tr.aisles) aisles[a] += 1;
    let busy = 1; for (let a = 2; a <= 8; a++) if (aisles[a] > aisles[busy]) busy = a;
    const saved = w.activeOrders().filter(o => o.saved || o.chose).length;
    const live = {
      'sku.trust': low.name + ' at ' + f2(low.trust) + ' (lowest)',
      'sku.visibility': skus.filter(s => s.hidden).length + ' hidden in the app',
      'sku.record': skus.filter(s => s.record > s.shelf).length + ' records above the real shelf',
      'count_and_refill': skus.filter(s => s.counting).length + ' tasks open',
      'mode_and_limits': sess.layer === 'live' ? MODE_LABEL[w.mode] + ' · ≤' + w.lim.max + ' per trolley · hold ≤' + w.lim.hold + ' s' : 'Agents not driving the floor',
      'front_racks': skus.some(s => s.fwd) ? 'Fast movers in front' : 'Home slots',
      'approvals_and_brief': w.approvals.filter(a => a.status === 'pending').length + ' awaiting the shift lead',
      'release_policy': 'bench cap ' + w.release_policy.bench_cap + ' · pace slack ' + w.release_policy.pace_slack + ' s',
      'priority': (tight ? '#' + tight.id + ' tightest at ' + pyRound(w.slackOf(tight)) + ' s' : 'No orders waiting') + (w.priority.size ? ' · ' + w.priority.size + ' boosted' : ''),
      'order_items': saved + ' live orders have a saved or chosen swap',
      'customer_messages': w.stats.notified + ' sent this shift',
    };
    return OWNERSHIP.map(([f, o, r]) => ({ field: f, owner: o, readers: r, live: live[f] })).concat([
      { field: 'trolleys_and_routes', owner: 'opt', readers: 'Captain, pickers', live: aisles[busy] ? 'Aisle A' + busy + ' busiest (' + aisles[busy] + ' trolleys)' : 'All aisles clear' }]);
  }
  function buildSnapshot(sess) {
    const w = sess.smart, X = sess.static, t = w.t;
    const pickers = w.pickers.filter(p => !(p.leave_at && t >= p.leave_at && !(p.trip && !p.trip.done))).map(p => { const o = { name: p.name, floater: p.floater, joining: p.join_at > t, trip: p.trip && !p.trip.done ? sTrip(p.trip) : null }; if (p.gig) { o.gig = true; o.join_at = p.join_at; o.leave_at = p.leave_at; } return o; });
    let orders = [];
    for (const o of w.activeOrders()) {
      const row = { id: o.id, user: o.user, status: o.status, riderIn: o.rider_arrive - t, items: o.items.filter(i => i.st !== 'dropped').length, swapped: o.items.filter(i => i.from).length, boost: w.priority.has(o.id) };
      if (o.status === 'pool' || o.status === 'picking') row.slack = pyRound(w.slackOf(o));
      orders.push(row);
    }
    orders = sortBy(orders, r => [r.slack === undefined ? 1e6 : r.slack, r.riderIn]);
    const skus = Object.values(w.skus).map(s => { const o = {}; for (const k of ['id', 'name', 'aisle', 'slot', 'temp', 'price', 'cat', 'shelf', 'record', 'backroom', 'trust', 'hidden', 'status', 'fwd', 'counting']) o[k] = s[k]; return o; });
    const swaps = {};
    for (const sid of CHECKOUT_ITEMS) { const alt = w.swapCandidate(w.skus[sid]); swaps[sid] = alt ? { id: alt.id, name: alt.name, price: alt.price } : null; }
    const busCounts = {}; for (const [k, v] of sess.bus.counts) busCounts[k] = v;
    const agents = {}; for (const n in sess.agents) agents[n] = sess.agents[n].publicStats();
    return {
      type: 'snap', t: t, clock: fmt(t), horizon: HORIZON, speed: sess.speed, playing: sess.playing, layer: sess.layer, llmOn: sess.llm_on, autoApprove: sess.auto_approve, demo: sess.demo,
      thinking: sess.thinking, llm: sess.llm.health(), mode: w.mode, lim: w.lim, limits: LIMITS, methods: MODE_METHOD, uNow: pyRoundN(w.u_now, 3), uFc: pyRoundN(w.u_fc, 3),
      N: w.activePickers().length, down: w.down, buffer: BUFFER, arrMin: w.arr_min.slice(0, Math.floor(t / 60) + 1), skus: skus, pickers: pickers,
      bench: { q: w.bench.q.length, ready: w.bench.ready.length }, riders: w.activeOrders().filter(o => o.rider_arrive <= t).length,
      orders: orders.slice(0, 40), activeCount: orders.length, pool: w.pool.length, stats: sStats(w), staticStats: sStats(X), log: sess.logs.slice(0, 150), decisions: w.decisions.slice(0, 10),
      approvals: w.approvals, brief: w.brief, story: sess.story, trace: sess.bus.trace.slice(0, 40), agents: agents, busCounts: busCounts,
      stateRows: stateRows(sess), releasePolicy: w.release_policy, swaps: swaps, checkout: CHECKOUT_ITEMS,
      riderFeed: w.activeOrders().filter(o => o.rider_arrive > t - 600).map(o => ({ id: o.id, eta: o.rider_arrive - t, delta: o.eta_delta || 0, status: o.status })).sort((a, b) => a.eta - b.eta).slice(0, 24),
      etaLive: sess.etaDrift, levers: w.levers,
      slotting: { on: w.dynSlot && w.levers.slotting, front: w.frontOn, list: w.frontList.map(id => ({ id: id, name: w.skus[id].name, aisle: w.skus[id].aisle })), savedM: Math.round(w.kpi.slotSaved * PX_M), savedPerOrder: w.stats.pickN ? pyRoundN(w.kpi.slotSaved * PX_M / w.stats.pickN, 1) : 0 },
      congestion: (function () { const a = [0, 0, 0, 0, 0, 0, 0, 0, 0]; for (const tr of w.trips) if (!tr.done && tr.end > t) for (const x of tr.aisles) a[x] += 1; return { aisles: a.slice(1), reroutes: w.stats.reroutes, savedS: Math.round(w.kpi.rerouteSaved) }; })(),
      gig: { auto: sess.ondemand, rate: GIG.rate, leadS: GIG.leadS, maxOnFloor: GIG.maxOnFloor, maxSpend: GIG.maxSpend, spent: w.kpi.gigCost, hours: w.kpi.gigHours, onFloor: w.gigOnFloor(), suggest: gigSuggest(w),
        crew: w.pickers.filter(p => p.gig).map(p => ({ name: p.name, join_at: p.join_at, leave_at: p.leave_at })) },
    };
  }

  const API = { GIG, SKU_DEFS, PX_M, START, fmt, makeOrder, Session, NoLLM, LLMUnavailable, CHARTER, buildSnapshot, HORIZON, genOrders, PyRandom, pyRound, pyRoundN, f2, World };
  if (typeof module !== 'undefined' && module.exports) module.exports = API; else root.SyncEngine = API;
})(typeof window !== 'undefined' ? window : globalThis);
