#!/usr/bin/env node
// Runs the page's worker (extracted from blernsboard.html) against a logdir on disk
// with a fake fetch that mimics python -m http.server, then compares every scalar
// series with the ground truth written by make_demo_logs.py.
// Usage: node tools/check_parser.mjs LOGDIR
import fs from 'node:fs';
import path from 'node:path';

const logdir = path.resolve(process.argv[2] || 'demo_logs');
const html = fs.readFileSync(new URL('../blernsboard.html', import.meta.url), 'utf8');
const src = html.slice(html.indexOf('function workerMain()'), html.indexOf('/* ====', html.indexOf('function workerMain()')));

const ROOT = 'http://test/';
function listing(dir) {
  const ents = fs.readdirSync(dir, { withFileTypes: true }).sort((a, b) => a.name.localeCompare(b.name));
  return '<!DOCTYPE HTML><html><body><ul>' + ents.map(e => {
    const n = e.name + (e.isDirectory() ? '/' : '');
    return `<li><a href="${encodeURIComponent(e.name).replace(/%2F/g, '/')}${e.isDirectory() ? '/' : ''}">${n}</a></li>`;
  }).join('\n') + '</ul></body></html>';
}
let requests = 0;
globalThis.fetch = async (url, opts = {}) => {
  requests++;
  const rel = decodeURIComponent(url.slice(ROOT.length));
  const p = path.join(logdir, rel);
  if (!fs.existsSync(p)) return { ok: false, status: 404, headers: new Map(), text: async () => 'not found' };
  const st = fs.statSync(p);
  if (st.isDirectory()) return { ok: true, status: 200, headers: { get: (k) => k.toLowerCase() === 'content-type' ? 'text/html; charset=utf-8' : null }, text: async () => listing(p) };
  if (opts.method === 'HEAD') return { ok: true, status: 200, headers: { get: (k) => k.toLowerCase() === 'content-length' ? String(st.size) : null } };
  // like python's server: ignore Range, return everything
  const buf = fs.readFileSync(p);
  return { ok: true, status: 200, headers: { get: () => null }, arrayBuffer: async () => buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength) };
};

const runs = new Map();
const msgs = [];
let done;
const idle = new Promise(r => { done = r; });
globalThis.self = {
  postMessage(m) {
    msgs.push(m.type);
    if (m.type === 'scalar') {
      const run = runs.get(m.run) || runs.set(m.run, { scalars: new Map(), hists: new Map(), texts: new Map(), warnings: [] }).get(m.run);
      const s = run.scalars.get(m.tag) || run.scalars.set(m.tag, []).get(m.tag);
      s.length = Math.min(s.length, m.truncateTo);
      for (let i = 0; i < m.steps.length; i++) s.push([m.steps[i], m.values[i], m.walls[i]]);
    } else if (m.type === 'hist' || m.type === 'text') {
      const run = runs.get(m.run) || runs.set(m.run, { scalars: new Map(), hists: new Map(), texts: new Map(), warnings: [] }).get(m.run);
      const map = m.type === 'hist' ? run.hists : run.texts;
      const s = map.get(m.tag) || map.set(m.tag, []).get(m.tag);
      s.length = Math.min(s.length, m.truncateTo); s.push(...m.items);
    } else if (m.type === 'runstat') {
      const run = runs.get(m.run) || runs.set(m.run, { scalars: new Map(), hists: new Map(), texts: new Map(), warnings: [] }).get(m.run);
      run.warnings = m.warnings; run.ignored = m.ignored;
    } else if (m.type === 'progress' && m.phase === 'idle') done(m);
    else if (m.type === 'rootError' || m.type === 'rootEmpty') { console.log(m); done(m); }
    else if (m.type === 'log') console.log('[worker log]', m.level, m.msg);
  },
  onmessage: null,
};
const t0 = Date.now();
new Function(src + '\nworkerMain();')();
self.onmessage({ data: { type: 'start', root: ROOT, intervalMs: 0, purge: true } });
const prog = await idle;
console.log(`parsed in ${Date.now() - t0} ms, ${requests} requests, ${prog.done}/${prog.total} files`);

// compare
const truthPath = path.join(logdir, '_truth.json');
let fail = 0, checked = 0;
if (fs.existsSync(truthPath)) {
  const truth = JSON.parse(fs.readFileSync(truthPath, 'utf8').replace(/\bNaN\b/g, 'null').replace(/-?\bInfinity\b/g, 'null'));
  for (const [run, tags] of Object.entries(truth)) {
    const got = runs.get(run);
    if (!got) { console.log(`FAIL run missing: ${run}`); fail++; continue; }
    for (const [tag, series] of Object.entries(tags)) {
      if (tag === '_note') { console.log(`  note ${run}: ${series} · got ${got.scalars.get('loss/train')?.length} · warnings: ${got.warnings.join(' | ')}`); continue; }
      const g = got.scalars.get(tag) || [];
      checked++;
      if (run === 'corrupt') {
        const ok = g.length < series.length && g.length > 0 && g.every((p, i) => p[0] === series[i][0]) && got.warnings.some(w => /CRC/.test(w));
        if (!ok) { fail++; console.log(`FAIL ${run}/${tag}: corrupt handling (got ${g.length}, truth ${series.length}, warnings=${got.warnings})`); }
        continue;
      }
      if (g.length !== series.length) { fail++; console.log(`FAIL ${run}/${tag}: ${g.length} points, expected ${series.length}`); continue; }
      for (let i = 0; i < g.length; i++) {
        const [s, v, w] = series[i], [gs, gv, gw] = g[i];
        const same = s === gs && (Object.is(v, gv) || (v === null && !Number.isFinite(gv)) || Math.abs(v - gv) <= 1e-6 * Math.max(1, Math.abs(v))) && Math.abs(w - gw) < 1e-6;
        if (!same) { fail++; console.log(`FAIL ${run}/${tag}[${i}]: got ${gs},${gv},${gw} expected ${s},${v},${w}`); break; }
      }
    }
  }
  console.log(`${checked} scalar series checked, ${fail} failures`);
}
for (const [name, r] of [...runs].sort()) {
  const n = [...r.scalars.values()].reduce((a, s) => a + s.length, 0);
  console.log(`  ${name.padEnd(16)} scalars=${String(r.scalars.size).padStart(2)} pts=${String(n).padStart(7)} hists=${r.hists.size}(${[...r.hists.values()].map(h => h.length).join(',')}) texts=${r.texts.size}${r.warnings.length ? '  ⚠ ' + r.warnings.join(' | ') : ''}${r.ignored && Object.keys(r.ignored).length ? '  ignored=' + JSON.stringify(r.ignored) : ''}`);
}
const h = runs.get('baseline')?.hists.get('weights/layer1')?.[0];
if (h) console.log(`  baseline hist[0]: ${h.counts.length} buckets, edges ${h.edges[0].toFixed(3)}..${h.edges[h.edges.length - 1].toFixed(3)}, total ${h.counts.reduce((a, b) => a + b, 0)}`);
const h2 = runs.get('tf2-style')?.hists.get('weights/layer1')?.[0];
if (h2) console.log(`  tf2 hist[0]:      ${h2.counts.length} buckets, edges ${h2.edges[0].toFixed(3)}..${h2.edges[h2.edges.length - 1].toFixed(3)}, total ${h2.counts.reduce((a, b) => a + b, 0)}`);
const t = runs.get('baseline')?.texts.get('samples/decoded');
if (t) console.log(`  baseline text: ${t.length} items, last = ${JSON.stringify(t[t.length - 1].text)}`);
process.exit(fail ? 1 : 0);
