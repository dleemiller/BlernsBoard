#!/usr/bin/env node
// Incremental refresh: serve the first 60% of every file, then the whole file, and check
// the merged result equals a single full read. Runs twice: server honours Range (206),
// server ignores Range (python http.server style, 200 + full body).
// Usage: node tools/check_tail.mjs LOGDIR
import fs from 'node:fs'; import path from 'node:path';
const logdir = path.resolve(process.argv[2] || 'demo_logs');
const html = fs.readFileSync(new URL('../blernsboard.html', import.meta.url), 'utf8');
const src = html.slice(html.indexOf('function workerMain()'), html.indexOf('/* ====', html.indexOf('function workerMain()')));
const ROOT = 'http://test/';
function listing(dir) { return fs.readdirSync(dir, { withFileTypes: true }).map(e => `<a href="${encodeURIComponent(e.name)}${e.isDirectory() ? '/' : ''}">x</a>`).join(''); }
const slice = (b) => b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength);
async function run(rangeOk, frac) {
  let phase = 0; // 0 = partial, 1 = full
  globalThis.fetch = async (url, opts = {}) => {
    const p = path.join(logdir, decodeURIComponent(url.slice(ROOT.length)));
    if (!fs.existsSync(p)) return { ok: false, status: 404, headers: { get: () => null }, text: async () => '' };
    const st = fs.statSync(p);
    if (st.isDirectory()) return { ok: true, status: 200, headers: { get: () => 'text/html' }, text: async () => listing(p) };
    const full = fs.readFileSync(p); const avail = phase === 0 ? Math.floor(full.length * frac) : full.length;
    if (opts.method === 'HEAD') return { ok: true, status: 200, headers: { get: () => String(avail) } };
    const m = /bytes=(\d+)-/.exec((opts.headers || {}).Range || '');
    if (m && rangeOk) {
      const s = +m[1];
      if (s >= avail) return { ok: true, status: 416, headers: { get: () => null }, arrayBuffer: async () => new ArrayBuffer(0) };
      return { ok: true, status: 206, headers: { get: () => null }, arrayBuffer: async () => slice(full.subarray(s, avail)) };
    }
    return { ok: true, status: 200, headers: { get: () => null }, arrayBuffer: async () => slice(full.subarray(0, avail)) };
  };
  const data = new Map(); let resolve; let idle = new Promise(r => resolve = r);
  globalThis.self = { postMessage(m) {
    if (m.type === 'scalar') { const k = m.run + '|' + m.tag; const s = data.get(k) || data.set(k, []).get(k); s.length = Math.min(s.length, m.truncateTo); for (let i = 0; i < m.steps.length; i++) s.push(m.steps[i] + ':' + m.values[i]); }
    else if (m.type === 'progress' && m.phase === 'idle') resolve();
  } };
  new Function(src + '\nworkerMain();')();
  self.onmessage({ data: { type: 'start', root: ROOT, intervalMs: 0, purge: true } });
  await idle;
  const partialPts = [...data.values()].reduce((a, s) => a + s.length, 0);
  phase = 1; idle = new Promise(r => resolve = r);
  self.onmessage({ data: { type: 'refresh' } });
  await idle;
  return { data, partialPts };
}
const full = await run(true, 1);
const ref = JSON.stringify([...full.data].sort());
const fullPts = [...full.data.values()].reduce((a, s) => a + s.length, 0);
let fail = 0;
for (const rangeOk of [true, false]) {
  const r = await run(rangeOk, 0.6);
  const same = JSON.stringify([...r.data].sort()) === ref;
  console.log(`${rangeOk ? 'Range honoured (206)' : 'Range ignored (200)'}: partial read ${r.partialPts} points, after refresh ${same ? `identical to a full read (${fullPts} points)` : 'DIFFERS from a full read'}`);
  if (!same) fail++;
}
process.exit(fail ? 1 : 0);
