'use strict';
/*
 * tui.js — guided RESI -> ECO migration wizard.
 *
 * A line-based, interactive installer that connects to a RESI box over Ethernet while
 * it is still running its factory software, and walks it all the way to the ECO stack -
 * OR re-runs against an already-migrated box and skips
 * every step it detects is already done. It orchestrates the same proven pieces the
 * RUNBOOK documents (setup-direct-ethernet.sh, migrate-box TB logic, box/*.sh,
 * build-gw-config.js) — it is a controller, not new install logic.
 *
 *   node tui.js --kit DBKIT24EU-0010 [--host <addr>] [--yes] [--skip-artifacts]
 *
 * Each phase has:
 *   detect(ctx) -> {done, detail}   idempotency probe; done=true => auto-skip
 *   run(ctx)                         perform it (streams box output live)
 *   gate                             true => ask before running (destructive-ish)
 *
 * Two-stage box auth (handled automatically): bootstrap as `resi` with the fleet
 * password, then use the `ecoadmin` key once phase 3 installs it.
 */
const path = require('path');
const fs = require('fs');
const os = require('os');
const crypto = require('crypto');
const readline = require('readline');
const { spawn } = require('child_process');
const cfgLib = require('./lib/config');
const ssh = require('./lib/ssh');
const { TB } = require('./lib/tb');
const release = require('./lib/release');
const connectorSync = require('./lib/connector-sync');
const RELEASE_FILE = path.join(__dirname, 'cache', 'webconsole-release.json');

// ---------- constants ----------
const REPO = path.join(__dirname, '..', '..');  // ECO-IOT-GW
const PROV = path.join(__dirname, '..');        // provisioning
const CACHE = path.join(__dirname, 'cache');
const OUT = path.join(__dirname, 'out');
const BOXDIR = path.join(__dirname, 'box');
const BYID_IF = 'if04';                          // meter-bus USB interface
const PRESENT_PROBE_UNITS = [88, 80, 81, 82];    // PF1..PF4 unit ids to probe

// ---------- ANSI ----------
const C = { r: '\x1b[0m', b: '\x1b[1m', dim: '\x1b[2m', red: '\x1b[31m', grn: '\x1b[32m', yel: '\x1b[33m', cyn: '\x1b[36m', mag: '\x1b[35m' };
const hdr = s => console.log(`\n${C.b}${C.cyn}${'─'.repeat(3)} ${s} ${'─'.repeat(Math.max(0, 60 - s.length))}${C.r}`);
const ok = s => console.log(`  ${C.grn}✓${C.r} ${s}`);
const skip = s => console.log(`  ${C.grn}⏭${C.r}  ${C.dim}${s}${C.r}`);
const info = s => console.log(`  ${C.dim}·${C.r} ${s}`);
const warn = s => console.log(`  ${C.yel}!${C.r} ${s}`);
const bad = s => console.log(`  ${C.red}✗${C.r} ${s}`);
const step = s => console.log(`  ${C.yel}→${C.r} ${s}`);
const dimw = s => process.stdout.write(C.dim + String(s).replace(/\r?\n/g, '\n    ') + C.r);

// ---------- readline ----------
let RL;
let RL_CLOSED = false;
// Non-interactive runs (piped stdin, CI) hit EOF and readline throws on the next
// question(). Treat a closed prompt as an empty answer so callers fall through to their
// safe default instead of dying with "readline was closed".
function ask(q) {
  if (RL_CLOSED || !RL) return Promise.resolve('');
  return new Promise(r => RL.question(q, r));
}
async function confirm(q, def = false) {
  const a = (await ask(`  ${C.mag}?${C.r} ${q} ${def ? '[Y/n]' : '[y/N]'} `)).trim().toLowerCase();
  if (!a) return def;
  return a === 'y' || a === 'yes';
}

// ---------- args ----------
function parseArgs(argv) {
  const a = { yes: false };
  for (let i = 2; i < argv.length; i++) {
    const t = argv[i];
    if (t === '--yes' || t === '-y') a.yes = true;
    else if (t === '--kit') a.kit = argv[++i];
    else if (t === '--host') a.host = argv[++i];
    else if (t === '--skip-artifacts') a.skipArtifacts = true;
    else if (t === '--skip-tb') a.skipTb = true;
    else if (t === '--wait') a.wait = parseInt(argv[++i], 10);
    else if (t === '--no-lte') a.noLte = true;
  }
  return a;
}

// ---------- shell helpers ----------
function shq(s) { return `'${String(s).replace(/'/g, "'\\''")}'`; }

// auth opts for the current box user (key for ecoadmin, password otherwise)
function authFor(ctx) {
  const box = ctx.box;
  if (box.user === 'ecoadmin' && ctx.cfg.box.keyPath && fs.existsSync(ctx.cfg.box.keyPath)) return { keyPath: ctx.cfg.box.keyPath };
  return { askpassPassword: ctx.cfg.box.password };
}
// wrap a command to run as root, bridging both auth stages
function asRoot(ctx, cmd) {
  if (ctx.box.user === 'ecoadmin') return `sudo -n bash -c ${shq(cmd)}`;
  return `echo ${shq(ctx.cfg.box.password)} | sudo -S -p '' bash -c ${shq(cmd)}`;
}
// quiet captured run (for detection). `extra` merges into ssh opts (e.g. {retries:0}).
function sh(ctx, cmd, boxOverride, extra) { return ssh.run(boxOverride || ctx.box, cmd, { ...authFor(ctx), ...extra }); }
// streaming run (for actions the operator should watch)
function stream(ctx, cmd, boxOverride) { return ssh.runStream(boxOverride || ctx.box, cmd, authFor(ctx), dimw); }
// scp a local file to the box
function scp(ctx, local, remote, boxOverride) {
  const r = ssh.put(boxOverride || ctx.box, local, remote, authFor(ctx));
  if (r.code !== 0) throw new Error(`scp ${path.basename(local)} failed: ${(r.stderr || '').trim().slice(0, 200)}`);
}

// ---------- multi-file upload: one overall progress bar + sha256 verify ----------
function sha256File(p) {
  const h = crypto.createHash('sha256');
  h.update(fs.readFileSync(p));
  return h.digest('hex');
}
function fmtBytes(n) {
  if (n >= 1024 * 1024) return (n / 1048576).toFixed(1) + ' MB';
  if (n >= 1024) return (n / 1024).toFixed(0) + ' KB';
  return n + ' B';
}
function fmtDur(sec) {
  if (!isFinite(sec) || sec < 0) return '--:--';
  sec = Math.round(sec);
  return String(Math.floor(sec / 60)).padStart(2, '0') + ':' + String(sec % 60).padStart(2, '0');
}
function drawBar(frac, doneBytes, total, mbps, etaSec) {
  const W = 24;
  frac = Math.max(0, Math.min(1, frac));
  const fill = Math.round(frac * W);
  const bar = '█'.repeat(fill) + '░'.repeat(W - fill);
  const line = `  ${C.yel}↑${C.r} [${C.cyn}${bar}${C.r}] ${String(Math.round(frac * 100)).padStart(3)}%  ` +
    `${fmtBytes(doneBytes)}/${fmtBytes(total)}  ${mbps.toFixed(1)} MB/s  ETA ${fmtDur(etaSec)}`;
  process.stdout.write('\x1b[2K\r' + line);
}
// Upload several files under a single overall bar, then verify every one by sha256.
// pairs: [{ local, remote }]. scp gives no byte-level progress without a TTY, so the bar
// interpolates the in-flight file from a running average speed (capped <100% until the
// file actually lands) — it always moves, so a stall is visible. Verify is one round trip.
async function putMany(ctx, pairs, label) {
  const box = ctx.box, auth = authFor(ctx);
  const sizes = pairs.map(p => { try { return fs.statSync(p.local).size; } catch { return 0; } });
  const total = sizes.reduce((a, b) => a + b, 0) || 1;
  if (label) step(label);
  let doneBytes = 0;
  const t0 = Date.now();
  let avgMbps = 4;                               // seed guess until we measure a real file
  for (let i = 0; i < pairs.length; i++) {
    const size = sizes[i];
    const fileT0 = Date.now();
    const estDur = Math.max(0.4, (size / 1048576) / avgMbps);
    const timer = setInterval(() => {
      const elapsed = (Date.now() - t0) / 1000;
      const fileFrac = Math.min(0.95, ((Date.now() - fileT0) / 1000) / estDur);
      const shown = doneBytes + fileFrac * size;
      const mbps = (shown / 1048576) / Math.max(0.1, elapsed);
      const eta = (total - shown) / 1048576 / Math.max(0.1, mbps);
      drawBar(shown / total, shown, total, mbps, eta);
    }, 200);
    const r = await ssh.putStream(box, pairs[i].local, pairs[i].remote, auth);
    clearInterval(timer);
    if (r.code !== 0) { process.stdout.write('\n'); throw new Error(`upload ${path.basename(pairs[i].local)} failed: ${(r.stderr || '').trim().slice(0, 200)}`); }
    doneBytes += size;
    const fileSec = (Date.now() - fileT0) / 1000;
    if (size > 256 * 1024 && fileSec > 0.3) avgMbps = (size / 1048576) / fileSec;   // refine from real transfers
    const elapsed = (Date.now() - t0) / 1000;
    drawBar(doneBytes / total, doneBytes, total, (doneBytes / 1048576) / Math.max(0.1, elapsed), 0);
  }
  process.stdout.write('\n');
  // verify: compare local sha256 to the box's sha256sum in one shot
  const want = pairs.map((p, i) => ({ remote: p.remote, name: path.basename(p.local), hash: sha256File(p.local) }));
  const res = sh(ctx, asRoot(ctx, 'sha256sum ' + want.map(w => shq(w.remote)).join(' ') + ' 2>/dev/null'));
  const got = {};
  res.stdout.trim().split(/\r?\n/).forEach(l => { const m = l.trim().match(/^([0-9a-f]{64})\s+(.+)$/i); if (m) got[m[2].trim()] = m[1].toLowerCase(); });
  const bad = want.filter(w => (got[w.remote] || '') !== w.hash);
  if (bad.length) throw new Error(`sha256 mismatch after upload: ${bad.map(b => b.name).join(', ')}`);
  ok(`uploaded + verified ${pairs.length} file${pairs.length === 1 ? '' : 's'} (${fmtBytes(total)}, sha256 OK)`);
}
// reachability check for a specific user/host/auth
function reachable(cfg, host, user, auth) {
  const r = ssh.run({ host, user }, 'true', { ...auth, retries: 0 });   // fast miss, no retry
  return r.code === 0;
}
// local (laptop) command, streamed
function local(cmd, args, cwd) {
  return new Promise(res => {
    const p = spawn(cmd, args, { cwd, shell: true, stdio: ['ignore', 'pipe', 'pipe'] });
    let out = '';
    const f = b => { out += b.toString(); dimw(b.toString()); };
    p.stdout.on('data', f); p.stderr.on('data', f);
    p.on('close', code => res({ code, out }));
    p.on('error', e => res({ code: 1, out: String(e.message) }));
  });
}

// ---------- interactive menu ----------
async function menu(title, items, render) {
  if (!items.length) return null;
  console.log(`  ${C.b}${title}${C.r}`);
  items.forEach((it, i) => console.log(`    ${C.cyn}${String(i + 1).padStart(2)}${C.r}) ${render(it)}`));
  const a = (await ask(`  choose [1-${items.length}], or blank to skip: `)).trim();
  const n = parseInt(a, 10);
  if (!Number.isInteger(n) || n < 1 || n > items.length) return null;
  return items[n - 1];
}

// ---------- quiet local capture (no streaming, for parsing) ----------
function capture(cmd, args) {
  const r = require('child_process').spawnSync(cmd, args, { encoding: 'utf8', maxBuffer: 8 * 1024 * 1024 });
  return { code: r.status == null ? 1 : r.status, stdout: r.stdout || '', stderr: r.stderr || '' };
}
function psJson(script) {
  const r = capture('powershell', ['-NoProfile', '-Command', script]);
  const t = r.stdout.trim();
  if (!t) return [];
  try { const j = JSON.parse(t); return Array.isArray(j) ? j : [j]; } catch { return []; }
}

// ---------- IPv6 link-local box discovery ----------
// The factory RESI image ships no Ethernet profile, so on a direct cable the box only
// self-assigns an IPv6 link-local (fe80::…) address, reachable only *with its interface
// zone id*. mDNS (RESI-C4.local) often fails to resolve. So: let the operator pick the
// cable adapter, solicit neighbours on it (ping ff02::1), then probe each fe80 neighbour
// for a live sshd — no credentials needed to identify the box (see ssh.probe).
function listAdapters() {
  if (os.platform() === 'win32') {
    return psJson("@(Get-NetAdapter | Where-Object {$_.Status -eq 'Up'} | Select-Object Name,ifIndex,InterfaceDescription) | ConvertTo-Json")
      .map(a => ({ name: a.Name, zone: String(a.ifIndex), desc: a.InterfaceDescription || '' }));
  }
  const r = capture('sh', ['-c', "ip -o link show up 2>/dev/null | awk -F': ' '{print $2}'"]);
  return r.stdout.split(/\r?\n/).map(s => s.trim().replace(/@.*$/, '')).filter(s => s && s !== 'lo')
    .map(n => ({ name: n, zone: n, desc: '' }));
}
function linkLocalNeighbours(adapter) {
  const zone = adapter.zone;
  if (os.platform() === 'win32') {
    capture('ping', ['-6', '-n', '2', '-w', '800', 'ff02::1%' + zone]);   // best-effort solicit
    // Include ALL fe80 states (even Unreachable): if Windows Firewall drops the ICMPv6
    // multicast solicit, a real box stays cached as Unreachable/Stale — but SSH-probing it
    // sends a *unicast* Neighbor Solicitation that revives it. Exclude only Permanent
    // (multicast-group) entries. PS $_ built by concatenation to dodge JS ${} interpolation.
    const ps = '@(Get-NetNeighbor -AddressFamily IPv6 -InterfaceIndex ' + zone +
      " -ErrorAction SilentlyContinue | Where-Object {$_.IPAddress -like 'fe80::*' -and $_.State -ne 'Permanent'}" +
      ' | Select-Object IPAddress,State) | ConvertTo-Json';
    return psJson(ps).map(x => {
      const addr = String(x.IPAddress).split('%')[0];
      return { addr, host: addr + '%' + zone, state: x.State };
    });
  }
  capture('sh', ['-c', 'ping6 -c2 -W1 ff02::1%' + zone + ' >/dev/null 2>&1 || ping -6 -c2 -W1 ff02::1%' + zone + ' >/dev/null 2>&1']);
  const r = capture('sh', ['-c', "ip -6 neigh show dev " + zone + " 2>/dev/null | grep -i '^fe80:'"]);
  return r.stdout.split(/\r?\n/).map(s => s.trim()).filter(Boolean).map(line => {
    const addr = line.split(/\s+/)[0];
    return { addr, host: `${addr}%${zone}`, state: (line.match(/\b(REACHABLE|STALE|DELAY|PROBE|FAILED|INCOMPLETE)\b/i) || [])[1] || '' };
  });
}
// A neighbour is "fresh" if NDP resolved it recently — probe those first. Windows encodes
// State as a number (5=Reachable 4=Stale 3=Delay 2=Probe 1=Incomplete 0=Unreachable);
// Linux as a word.
function isFresh(state) {
  if (typeof state === 'number') return state >= 2 && state <= 5;
  const s = String(state).toUpperCase();
  return ['5', '4', '3', '2'].includes(s) || /REACHABLE|STALE|DELAY|PROBE/.test(s);
}
// only physical/wired adapters — the cable is never on WSL/Hyper-V/WiFi/VPN/Bluetooth
function wiredAdapters() {
  return listAdapters().filter(a => !/(WSL|Default Switch|Hyper-?V|Tailscale|WLAN|Wi-?Fi|Wireless|Bluetooth|Loopback|VPN|OpenVPN|\bTAP\b|Virtual)/i.test(a.name + ' ' + a.desc));
}
// SSH-probe a candidate list: fresh neighbours first; only fall back to reviving stale ones
// (capped) if nothing fresh answered. Returns the ones running sshd.
function probeCandidates(cands, label) {
  const seen = new Set(); const uniq = [];
  for (const c of cands) if (!seen.has(c.host)) { seen.add(c.host); uniq.push(c); }
  const fresh = uniq.filter(c => isFresh(c.state));
  const stale = uniq.filter(c => !isFresh(c.state));
  const order = [...fresh, ...stale.slice(0, 8)];
  const alive = [];
  for (const c of order) {
    if (alive.length && !isFresh(c.state)) break;   // got a fresh hit → don't chase stale
    process.stdout.write(`    ${C.dim}·${C.r} ${c.host}${label ? ' ' + C.dim + '(' + label + ')' + C.r : ''} … `);
    if (ssh.probe({ host: c.host, user: 'resi' }, { connectTimeout: 5 }).alive) { console.log(`${C.grn}sshd answering${C.r}`); alive.push(c); }
    else console.log(`${C.dim}no ssh${C.r}`);
  }
  return alive;
}
// Automatically scan every wired adapter for the box. Returns {host,user:'resi'} or null.
async function autoDiscover(ctx) {
  const ads = wiredAdapters();
  if (!ads.length) { info('no wired adapters found to scan'); return null; }
  const found = [];
  for (const a of ads) {
    step(`scanning ${C.b}${a.name}${C.r} for the box (IPv6 link-local)…`);
    const cands = linkLocalNeighbours(a);
    if (!cands.length) { info(`  no link-local neighbours on ${a.name}`); continue; }
    for (const c of probeCandidates(cands, a.name)) found.push({ ...c, adapter: a.name });
    if (found.length) break;   // first adapter carrying the box wins
  }
  if (!found.length) return null;
  if (found.length === 1) { ok(`box found: ${C.b}${found[0].host}${C.r} on ${found[0].adapter}`); return { host: found[0].host, user: 'resi' }; }
  const chosen = await menu('multiple hosts answered SSH — pick the box', found, c => `${c.host}  ${C.dim}${c.adapter}${C.r}`);
  return chosen ? { host: chosen.host, user: 'resi' } : null;
}
// scan one specific adapter (manual path), return the chosen box or null
async function discoverOnAdapter(ctx, adapter) {
  step(`scanning ${C.b}${adapter.name}${C.r} (IPv6 link-local)…`);
  const cands = linkLocalNeighbours(adapter);
  if (!cands.length) { warn('no link-local neighbours on that adapter (cable in? box booted?)'); return null; }
  const alive = probeCandidates(cands, adapter.name);
  if (!alive.length) { warn('no host on that adapter answered SSH'); return null; }
  let chosen = alive[0];
  if (alive.length > 1) chosen = await menu('pick the box', alive, c => `${c.host}  ${C.dim}state=${c.state}${C.r}`) || alive[0];
  return { host: chosen.host, user: 'resi' };
}

// Interactive menu after the auto-scan misses. Returns a box, null (retry), or false (abort).
async function interactiveConnect(ctx) {
  const pwAuth = { askpassPassword: ctx.cfg.box.password };
  const keyAuth = ctx.cfg.box.keyPath && fs.existsSync(ctx.cfg.box.keyPath) ? { keyPath: ctx.cfg.box.keyPath } : null;
  const choice = await menu('How should I find the box?', [
    { k: 'rescan', label: 'Re-scan all wired adapters (link-local)' },
    { k: 'adapter', label: 'Scan a specific adapter I choose' },
    { k: 'manual', label: 'Enter its address by hand (IP, *.local, or fe80::…%zone)' },
    { k: 'wait', label: 'Wait for it to finish booting, retrying automatically' },
    { k: 'abort', label: 'Abort' },
  ], x => x.label);
  if (!choice || choice.k === 'abort') return false;

  if (choice.k === 'rescan') return await autoDiscover(ctx);

  if (choice.k === 'adapter') {
    const adapters = listAdapters();
    if (!adapters.length) { warn('no "up" adapters found'); return null; }
    const adapter = adapters.length === 1 ? adapters[0]
      : await menu('which adapter is the cable on?', adapters, a => `${C.b}${a.name}${C.r}${a.desc ? '  ' + C.dim + a.desc + C.r : ''}  ${C.dim}[zone ${a.zone}]${C.r}`);
    if (!adapter) return null;
    return await discoverOnAdapter(ctx, adapter);
  }

  if (choice.k === 'manual') {
    const manual = (await ask('  address: ')).trim();
    if (!manual) return null;
    if (keyAuth && reachable(ctx.cfg, manual, 'ecoadmin', keyAuth)) { ok(`reached ${C.b}ecoadmin@${manual}${C.r} (key)`); return { host: manual, user: 'ecoadmin' }; }
    if (reachable(ctx.cfg, manual, 'resi', pwAuth)) { ok(`reached ${C.b}resi@${manual}${C.r}`); return { host: manual, user: 'resi' }; }
    if (ssh.probe({ host: manual, user: 'resi' }).alive) { ok(`sshd answering at ${C.b}${manual}${C.r} — using it (auth happens next phase)`); return { host: manual, user: 'resi' }; }
    warn(`nothing answered SSH at ${manual}`);
    return null;
  }

  // wait: retry the quick paths (box may still be booting)
  const waitMin = Number.isFinite(ctx.args.wait) ? ctx.args.wait : 5;
  const deadline = Date.now() + waitMin * 60000;
  step(`retrying for up to ${waitMin} min (Ctrl-C to stop)…`);
  while (Date.now() < deadline) {
    await sleep(10000);
    try { await bootstrap(ctx, false); return { host: ctx.box.host, user: ctx.box.user }; } catch (_) {}
    const box = await autoDiscover(ctx);
    if (box) return box;
    info(`still not up… ${Math.round((deadline - Date.now()) / 1000)}s left`);
  }
  warn('gave up waiting');
  return null;
}

// ---------- offline artifact manifest ----------
// cache/ holds ~240 MB of vendor binaries that are deliberately NOT in git (ARTIFACTS.md
// explains why). artifacts.json pins the exact versions, URLs and hashes so the bundle is
// reproducible on any laptop with office internet.
const MANIFEST = path.join(__dirname, 'artifacts.json');
function manifest() { return JSON.parse(fs.readFileSync(MANIFEST, 'utf8')); }

// streamed, so a 100 MB image tar is not slurped into memory
function sha256File(f) {
  const h = require('crypto').createHash('sha256');
  const fd = fs.openSync(f, 'r');
  const buf = Buffer.alloc(1 << 20);
  try {
    let n;
    while ((n = fs.readSync(fd, buf, 0, buf.length, null)) > 0) h.update(buf.subarray(0, n));
  } finally { fs.closeSync(fd); }
  return h.digest('hex');
}

// Download to <dest>.part, verify, then rename - so an interrupted or corrupt download
// never leaves something that looks like a good artifact.
async function fetchVerified(entry, dest) {
  const tmp = dest + '.part';
  const r = await local('curl', ['-fsSL', '--retry', '3', '-o', tmp, entry.url]);
  if (r.code !== 0 || !fs.existsSync(tmp)) throw new Error('download failed: ' + entry.url);
  const got = sha256File(tmp);
  if (entry.sha256) {
    if (got !== entry.sha256) {
      fs.unlinkSync(tmp);
      throw new Error('sha256 mismatch for ' + entry.file + '\n  expected ' + entry.sha256 + '\n  got      ' + got);
    }
    ok('sha256 verified: ' + entry.file);
  } else {
    warn('no sha256 pinned for ' + entry.file + ' - paste this into artifacts.json: ' + got);
  }
  fs.renameSync(tmp, dest);
}

// ---------- bootstrap: find + connect to the box ----------
async function bootstrap(ctx, allowPrompt = true) {
  const cfg = ctx.cfg;
  const keyAuth = cfg.box.keyPath && fs.existsSync(cfg.box.keyPath) ? { keyPath: cfg.box.keyPath } : null;
  const pwAuth = { askpassPassword: cfg.box.password };

  // 1) already fully provisioned? ecoadmin key on the stable cable IP
  if (keyAuth && reachable(cfg, '10.10.10.1', 'ecoadmin', keyAuth)) {
    ctx.box = { host: '10.10.10.1', user: 'ecoadmin' };
    ok(`reached ${C.b}ecoadmin@10.10.10.1${C.r} (key) — box already provisioned`);
    return;
  }
  // 2) networking done but not yet ecoadmin: resi on the cable IP
  if (reachable(cfg, '10.10.10.1', 'resi', pwAuth)) {
    ctx.box = { host: '10.10.10.1', user: 'resi' };
    ok(`reached ${C.b}resi@10.10.10.1${C.r} (password)`);
    return;
  }
  // 3) fresh box: try the operator-supplied host, else common RESI mDNS names
  const candidates = [];
  if (ctx.args.host) candidates.push(ctx.args.host);
  candidates.push('RESI-C4.local', 'raspberrypi.local');
  for (const h of candidates) {
    info(`probing resi@${h} …`);
    if (reachable(cfg, h, 'resi', pwAuth)) {
      ctx.box = { host: h, user: 'resi' };
      ok(`reached ${C.b}resi@${h}${C.r} (fresh box)`);
      return;
    }
  }
  if (!allowPrompt) throw new Error('box not reachable yet');
  const manual = (await ask('  could not auto-find the box. Enter its address (IP / *.local), or blank to abort: ')).trim();
  if (manual && reachable(cfg, manual, 'resi', pwAuth)) {
    ctx.box = { host: manual, user: 'resi' };
    ok(`reached ${C.b}resi@${manual}${C.r}`);
    return;
  }
  throw new Error('box unreachable on every path (10.10.10.1 / mDNS / manual).\n' +
    '  The box must be powered on, cabled directly, and still running RESI.\n' +
    '  Find it by hand, then re-run with --host <addr>:\n' +
    '    Windows: ping -6 ff02::1%<iface>  then  netsh interface ipv6 show neighbors\n' +
    '    Linux:   ping6 -c2 ff02::1%<iface>  then  ip -6 neigh');
}

// ---------- Windows helpers ----------
// True only when the process is elevated (`net session` succeeds only for Administrators).
function isElevatedWin() {
  if (os.platform() !== 'win32') return true;
  try { return require('child_process').spawnSync('net', ['session'], { stdio: 'ignore' }).status === 0; }
  catch { return false; }
}
// Run a PowerShell script with a HARD timeout, args passed cleanly (no shell, no fragile
// quoting) so a bad string can never leave PowerShell blocked on stdin. Returns {out,timedOut,code}.
function localPS(script, timeoutMs = 30000) {
  const r = require('child_process').spawnSync('powershell',
    ['-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-Command', script],
    { encoding: 'utf8', timeout: timeoutMs, input: '' });
  const out = (r.stdout || '') + (r.stderr || '');
  if (out.trim()) dimw(out);
  const timedOut = !!(r.error && (r.error.code === 'ETIMEDOUT' || /timed?\s*out/i.test(String(r.error.message))));
  return { out, timedOut, code: r.status };
}

// ---------- laptop cable-adapter DHCP renew (Windows) ----------
// The box's dnsmasq (NM `ipv4.method shared`) leases the laptop a 10.10.10.x address.
// Nudge Windows to pick it up promptly by renewing the exact adapter we reached the box
// through. Needs Administrator (ipconfig /release+/renew); if we're not elevated or it
// times out, we just fall through — Windows leases 10.10.10.x on its own within ~30-60s.
async function renewCableAdapter(ctx) {
  if (os.platform() !== 'win32') { info('(non-Windows) ensure the cable adapter takes a 10.10.10.x lease'); return; }
  if (!isElevatedWin()) { warn('not elevated — skipping adapter renew; Windows will lease 10.10.10.x on its own (a bit slower). Re-run elevated to speed this up.'); return; }
  const zone = (String(ctx && ctx.box && ctx.box.host).match(/%(\d+)$/) || [])[1];
  step('renewing the laptop cable adapter so it leases 10.10.10.x…');
  const pick = zone
    ? `Get-NetAdapter -InterfaceIndex ${zone} -ErrorAction SilentlyContinue`
    : `Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue | Where-Object {$_.IPAddress -like '169.254.*' -or $_.IPAddress -like '10.10.10.*'} | ForEach-Object {Get-NetAdapter -InterfaceIndex $_.InterfaceIndex} | Select-Object -First 1`;
  const script = `$a=(${pick}).Name; if($a){ipconfig /release $a *> $null; ipconfig /renew $a *> $null; Write-Output ('renewed '+$a)} else {Write-Output 'no cable adapter found'}`;
  const r = localPS(script, 45000);
  if (r.timedOut) warn('adapter renew timed out — Windows will still lease 10.10.10.x shortly; continuing');
}

// =====================================================================
// PHASES
// =====================================================================
const PHASES = [
  // ---------------- 0. Connect ----------------
  // A phase rather than a pre-loop step so it can retry: first contact is over the
  // link-local address while the box still runs RESI, and link-local flaps badly (see
  // RUNBOOK phase 1) - which is exactly why the next phase pins it to 10.10.10.1.
  {
    id: 'connect', title: 'Connect - find the box and pick an auth path', fatal: true,
    async detect(ctx) {
      if (ctx.connected) return { done: true, detail: ctx.box.user + '@' + ctx.box.host };
      return { done: false, detail: 'probing cable / mDNS' };
    },
    async run(ctx) {
      // Fast path: quick silent probes (10.10.10.1 key/pw, --host, mDNS names). On a
      // fresh factory box these miss fast (no route to 10.10.10.1 yet, mDNS unresolved);
      // on a re-run of a provisioned box they hit 10.10.10.1 immediately.
      try { await bootstrap(ctx, false); ctx.connected = true; return; } catch (_) {}

      // A fresh factory box is on an IPv6 link-local address, NOT 10.10.10.1 — that only
      // exists after the `net` phase. And its eth0 sits in NetworkManager's DHCP-retry
      // loop, so link-local *flaps* every ~30-60s. Auto-scan on a short retry loop to
      // catch an "up" window; the very next phase (`net`) pins it to a stable 10.10.10.1.
      info('not at 10.10.10.1 / mDNS yet — auto-scanning for the box (link-local flaps, so retrying)…');
      for (let attempt = 1; attempt <= (RL_CLOSED ? 1 : 8); attempt++) {
        const box = await autoDiscover(ctx);
        if (box) { ctx.box = box; ok(`using ${C.b}resi@${box.host}${C.r}`); ctx.connected = true; return; }
        if (!RL_CLOSED && attempt < 8) { info(`no answer this pass (${attempt}/8) — link may be mid-DHCP-cycle, retrying in 8s…`); await sleep(8000); }
      }

      // Non-interactive (piped stdin / CI): timed silent retry (box may be booting),
      // then the by-hand prompt which throws with the manual-discovery hints.
      if (RL_CLOSED) {
        const waitMin = Number.isFinite(ctx.args.wait) ? ctx.args.wait : 5;
        const deadline = Date.now() + waitMin * 60000;
        for (let attempt = 1; Date.now() < deadline; attempt++) {
          info('box not up yet (attempt ' + attempt + ') — retrying, ' + Math.round((deadline - Date.now()) / 1000) + 's left');
          await sleep(10000);
          try { await bootstrap(ctx, false); ctx.connected = true; return; } catch (_) {}
          const b = await autoDiscover(ctx);
          if (b) { ctx.box = b; ctx.connected = true; return; }
        }
        await bootstrap(ctx, true);
        ctx.connected = true;
        return;
      }

      // Interactive: auto-scan missed — offer rescan / specific adapter / manual / wait,
      // and keep offering until we connect or the operator aborts.
      warn('auto-scan did not find the box.');
      for (;;) {
        const b = await interactiveConnect(ctx);
        if (b === false) throw new Error('aborted at connect (no box)');
        if (b) { ctx.box = b; ctx.connected = true; return; }
        // null: a choice missed or "wait" timed out — offer the menu again.
      }
    },
  },

  // ---------------- 1. Networking ----------------
  {
    id: 'net', title: 'Networking — WAN (Ethernet/LTE auto) + 10.10.10.1 console',
    async detect(ctx) {
      // Idempotency is about the CONFIG being laid down, not the current runtime IP: in
      // the field eth0 may be a DHCP WAN client (no 10.10.10.1) and that is still "done".
      // Done when both eth0 profiles exist, the mode-aware guard dispatcher is present,
      // and the LTE raw_ip boot fix is installed.
      const r = sh(ctx, 'nmcli -t -f NAME con show 2>/dev/null | grep -qx eth0-wan && echo WAN; ' +
        'nmcli -t -f NAME con show 2>/dev/null | grep -qx eth0-direct && echo DIRECT; ' +
        'test -f /etc/NetworkManager/dispatcher.d/50-eco-eth0-guard.sh && echo GUARD; ' +
        'test -f /etc/udev/rules.d/99-eco-wwan-rawip.rules && echo RAWIP');
      const lines = r.stdout.split(/\r?\n/).map(s => s.trim());
      const has = k => lines.includes(k);
      const done = has('WAN') && has('DIRECT') && has('GUARD') && has('RAWIP');
      return { done, detail: done ? 'eth0-wan + eth0-direct + guard + LTE raw_ip fix in place'
                                  : (ctx.box.host === '10.10.10.1' ? 'partial config — will (re)apply' : `box at ${ctx.box.host} — will lay down the WAN model`) };
    },
    async run(ctx) {
      const netSrc = path.join(PROV, 'setup-networking.sh');
      const rawipSrc = path.join(PROV, 'box', 'install-lte-rawip.sh');
      // The link still flaps here (eth0 DHCP-retry loop), so the first copy can hit a
      // down-moment — retry until a window opens. Push both scripts now (we need the raw_ip
      // one after eth0 is reconfigured, when the link may be briefly unavailable).
      let pushed = false;
      for (let i = 1; i <= 12 && !pushed; i++) {
        try { scp(ctx, netSrc, '/tmp/setup-networking.sh'); scp(ctx, rawipSrc, '/tmp/install-lte-rawip.sh'); pushed = true; }
        catch (e) { info(`link down this pass (${i}/12) — ${String(e.message).split('\n')[0].slice(0, 60)}; retrying in 6s…`); await sleep(6000); }
      }
      if (!pushed) throw new Error('could not copy the networking scripts — link-local never held (box eth0 flapping?)');
      step('applying WAN model (eth0-wan DHCP → eth0-direct 10.10.10.1 fallback → LTE) — detached, drops eth0…');
      // run detached so dropping the current link doesn't kill our SSH mid-write
      await stream(ctx, asRoot(ctx, 'chmod +x /tmp/setup-networking.sh && nohup /tmp/setup-networking.sh >/tmp/eco-net.log 2>&1 & echo started'));
      const fe80Host = ctx.box.host;   // keep the link-local as a fallback
      info('waiting 20s for eth0 to re-evaluate (WAN DHCP attempt → falls back to 10.10.10.1)…');
      await sleep(20000);
      await renewCableAdapter(ctx);
      await sleep(4000);
      // reconnect on the cable IP; the laptop's DHCP lease from the box can take a while,
      // so retry for ~90s before giving up.
      ctx.box.host = '10.10.10.1';
      const tryReconnect = async (n, everySec) => {
        for (let i = 1; i <= n; i++) {
          if (sh(ctx, 'true', null, { retries: 0 }).code === 0) { ok('reconnected on 10.10.10.1'); return true; }
          if (i % 5 === 0) info(`still waiting for the 10.10.10.x lease / route… (${i * everySec}s)`);
          await sleep(everySec * 1000);
        }
        return false;
      };
      let linked = await tryReconnect(30, 3);
      if (!linked) {
        // The switch sometimes leaves the laptop NIC on a stale link state that only a
        // physical re-plug clears (Windows re-runs DHCP + resets the adapter on link-up).
        // Ask ONCE for a cable re-plug, then renew + retry before falling back.
        warn('box not answering on 10.10.10.1 after the switch — the cable adapter may be on a stale link.');
        await ask(`  ${C.mag}?${C.r} Unplug the Ethernet cable, wait ~3s, plug it back in — then press ${C.b}Enter${C.r}. `);
        info('re-plug acknowledged — renewing the adapter and retrying…');
        await renewCableAdapter(ctx);
        await sleep(4000);
        linked = await tryReconnect(20, 3);
      }
      if (!linked) {
        // last resort: fall back to the link-local we came in on (if it still answers)
        ctx.box.host = fe80Host;
        if (fe80Host !== '10.10.10.1' && sh(ctx, 'true', null, { retries: 0 }).code === 0) {
          warn('no 10.10.10.x lease on the laptop — continuing over link-local (set a static 10.10.10.2/24 on the cable adapter for a stable link)');
          linked = true;
        }
      }
      if (!linked) throw new Error('box did not come back on 10.10.10.1 (laptop got no 10.10.10.x lease). Set the cable adapter to DHCP or a static 10.10.10.2/24, then re-run.');

      // LTE reboot-proofing + immediate bring-up. Idempotent; also fixes raw_ip=N now so
      // telemetry resumes without waiting for a reboot.
      step('installing LTE raw_ip boot fix + bringing the modem up…');
      const r = await stream(ctx, asRoot(ctx, 'chmod +x /tmp/install-lte-rawip.sh && /tmp/install-lte-rawip.sh'));
      if (r.code !== 0) warn('LTE raw_ip fix reported an issue — see /tmp/install-lte-rawip on the box (continuing)');
      ok('networking applied — Ethernet-WAN/LTE auto-failover + 10.10.10.1 console fallback');
    },
  },

  // ---------------- 2. ThingsBoard ----------------
  {
    id: 'tb', title: 'ThingsBoard — reprofile + capture gateway creds',
    async detect(ctx) {
      if (ctx.args.skipTb) return { done: true, detail: '--skip-tb' };
      const tb = new TB(ctx.cfg, { apply: false });
      await tb.login();
      const asset = await tb.findKit(ctx.kit);
      if (!asset) return { done: false, detail: `kit ${ctx.kit} not found yet` };
      ctx.store.asset = asset;
      const devices = await tb.kitDevices(asset.id.id);
      for (const d of devices) d.profileName = await tb.deviceProfileName(d.profileId);
      ctx.store.devices = devices;
      const gw = devices.find(d => /_gw$/.test(d.name));
      ctx.store.gw = gw;
      const hwidm = (gw ? gw.name : '').match(/^ECO_(.+)_gw$/);
      ctx.store.hwid = hwidm ? hwidm[1] : null;
      const credFile = path.join(OUT, `${ctx.kit}.gw-mqtt.json`);
      const gwOk = gw && gw.profileName === 'ECO GW' && gw.gateway;
      const pfOk = devices.filter(d => /_PF\d$/.test(d.name)).every(d => d.profileName === 'P-Flow D116 GW');
      const tsOk = devices.filter(d => /_TS[12]$/.test(d.name)).every(d => d.profileName === 'Temperature Sensor GW');
      const done = gwOk && pfOk && tsOk && fs.existsSync(credFile);
      return { done, detail: done ? `_gw=ECO GW+gateway, PF/TS profiled, creds cached` : `needs reprofile (gw:${gwOk} pf:${pfOk} ts:${tsOk} creds:${fs.existsSync(credFile)})` };
    },
    async run(ctx) {
      // reuse migrate-box's apply via a child process so there's one code path
      step('running TB apply (reprofile + gateway flag + capture creds)…');
      const r = await local('node', ['migrate-box.js', '--kit', ctx.kit, '--phase', 'tb', '--apply'], __dirname);
      if (r.code !== 0) throw new Error('TB apply failed (see output above)');
      ok('TB apply complete');
    },
  },

  // ---------------- 3. ecoadmin ----------------
  {
    id: 'ecoadmin', title: 'Box — create ecoadmin + install key',
    async detect(ctx) {
      const keyAuth = ctx.cfg.box.keyPath && fs.existsSync(ctx.cfg.box.keyPath) ? { keyPath: ctx.cfg.box.keyPath } : null;
      if (keyAuth && reachable(ctx.cfg, ctx.box.host, 'ecoadmin', keyAuth)) {
        ctx.box.user = 'ecoadmin';   // switch all later phases to key auth
        return { done: true, detail: 'ecoadmin key login works' };
      }
      return { done: false, detail: 'ecoadmin not present / key not installed' };
    },
    async run(ctx) {
      const pub = ctx.cfg.box.keyPath + '.pub';
      if (!fs.existsSync(pub)) throw new Error(`public key missing: ${pub}`);
      scp(ctx, pub, '/tmp/eco-authorized_key');
      scp(ctx, path.join(BOXDIR, 'ecoadmin.sh'), '/tmp/ecoadmin.sh');
      step('creating ecoadmin (sudo, dialout, docker groups) + installing key…');
      const r = await stream(ctx, asRoot(ctx, 'chmod +x /tmp/ecoadmin.sh && /tmp/ecoadmin.sh'));
      if (r.code !== 0) throw new Error('ecoadmin.sh failed');
      // switch to key auth and verify
      ctx.box.user = 'ecoadmin';
      if (sh(ctx, 'sudo -n id -u').stdout.trim() !== '0') throw new Error('ecoadmin key/sudo verify failed');
      ok('ecoadmin ready — switched to key auth');
    },
  },

  // ---------------- 3b. Lock the factory accounts ----------------
  // Only after ecoadmin key auth is proven (above) — so we can never lock ourselves out.
  {
    id: 'harden', title: 'Box — disable factory RESI logins (resi, resivm)',
    async detect(ctx) {
      // requires key auth (ecoadmin); if we're still on resi, ecoadmin hasn't run yet
      if (ctx.box.user !== 'ecoadmin') return { done: false, detail: 'runs after ecoadmin key auth' };
      const r = sh(ctx, asRoot(ctx, 'echo __OK__; for u in resi resivm; do id "$u" >/dev/null 2>&1 && passwd -S "$u" 2>/dev/null; done'));
      // Distinguish "probe succeeded, no factory accounts" from "probe failed" (dropped
      // link / sudo error): a failed probe returns empty stdout, which must NOT be read as
      // "already hardened". The __OK__ sentinel proves the command actually ran.
      if (r.code !== 0 || !r.stdout.includes('__OK__')) return { done: false, detail: 'could not verify factory accounts (will run)' };
      const lines = r.stdout.trim().split(/\r?\n/).filter(l => l && l !== '__OK__');
      const factory = lines.map(l => ({ u: l.split(/\s+/)[0], st: l.split(/\s+/)[1] })).filter(x => x.u === 'resi' || x.u === 'resivm');
      if (!factory.length) return { done: true, detail: 'no factory accounts present' };
      const open = factory.filter(x => x.st !== 'L').map(x => x.u);
      return { done: open.length === 0, detail: open.length ? `still enabled: ${open.join(', ')}` : `locked: ${factory.map(x => x.u).join(', ')}` };
    },
    async run(ctx) {
      if (ctx.box.user !== 'ecoadmin') throw new Error('refusing to lock factory users before ecoadmin key auth is confirmed');
      scp(ctx, path.join(BOXDIR, 'harden-users.sh'), '/tmp/harden-users.sh');
      step('locking passwords + SSH for resi and resivm (reversible)…');
      const r = await stream(ctx, asRoot(ctx, 'chmod +x /tmp/harden-users.sh && /tmp/harden-users.sh'));
      if (r.code !== 0) throw new Error('harden-users.sh failed');
      ok('factory logins disabled (reverse: sudo passwd -u resi / resivm)');
    },
  },

  // ---------------- 4. Stand down RESI ----------------
  {
    id: 'standdown', title: 'Box — stand down RESI (reversible)',
    async detect(ctx) {
      const r = sh(ctx, 'systemctl is-enabled apache2 2>/dev/null; echo "|"; ' +
        'for p in /proc/[0-9]*/exe; do readlink "$p" 2>/dev/null; done | grep -qi RESIvmachine && echo RUNNING || echo STOPPED');
      const masked = /masked/.test(r.stdout);
      const stopped = /STOPPED/.test(r.stdout);
      const done = masked && stopped;
      return { done, detail: done ? 'RESI services masked, RESIvmachine not running' : `apache2=${masked ? 'masked' : 'active'}, RESIvmachine=${stopped ? 'stopped' : 'RUNNING'}` };
    },
    async run(ctx) {
      scp(ctx, path.join(BOXDIR, 'standdown-resi.sh'), '/tmp/standdown-resi.sh');
      step('masking RESI stack + freeing the meter bus…');
      const r = await stream(ctx, asRoot(ctx, 'chmod +x /tmp/standdown-resi.sh && /tmp/standdown-resi.sh'));
      if (r.code !== 0) throw new Error('standdown-resi.sh failed');
      ok('RESI stood down (reverse later with /usr/local/sbin/eco-downgrade.sh)');
    },
  },

  // ---------------- 5. Discover the bus ----------------
  {
    id: 'scan', title: 'Box — discover meter bus (present units + by-id path)',
    async detect(ctx) {
      // NEVER probe while tb-gateway holds the serial device — a concurrent open
      // corrupts the live bus. If it's running, keep the cached scan (or default).
      const running = sh(ctx, asRoot(ctx, 'docker inspect -f "{{.State.Running}}" tb-gateway 2>/dev/null')).stdout.trim() === 'true';
      // always capture the by-id path (safe, read-only)
      const byid = sh(ctx, `ls /dev/serial/by-id/ 2>/dev/null | grep -- '-${BYID_IF}$' | head -1`).stdout.trim();
      if (byid) ctx.store.byId = `/dev/serial/by-id/${byid}`;
      if (running) {
        const cache = path.join(OUT, `${ctx.kit}.scan.json`);
        if (fs.existsSync(cache)) { try { ctx.store.presentUnits = JSON.parse(fs.readFileSync(cache, 'utf8')).presentUnits; } catch {} }
        if (!ctx.store.presentUnits) ctx.store.presentUnits = [88];
        return { done: true, detail: `bus held by running tb-gateway — keeping units ${ctx.store.presentUnits.join(',')} (${ctx.store.byId || '/dev/ttyACM2'})` };
      }
      return { done: false, detail: 'bus free — will probe for wired meters' };
    },
    async run(ctx) {
      const byid = ctx.store.byId || (() => { const b = sh(ctx, `ls /dev/serial/by-id/ 2>/dev/null | grep -- '-${BYID_IF}$' | head -1`).stdout.trim(); return b ? `/dev/serial/by-id/${b}` : null; })();
      if (byid) { ctx.store.byId = byid; ok(`meter bus: ${byid}`); }
      else warn('no -if04 by-id path found — falling back to /dev/ttyACM2');
      const dev = byid ? sh(ctx, `readlink -f ${byid}`).stdout.trim() : '/dev/ttyACM2';
      scp(ctx, path.join(BOXDIR, 'bus-probe.py'), '/tmp/bus-probe.py');
      step(`probing PF units ${PRESENT_PROBE_UNITS.join(',')} on ${dev} …`);
      const out = sh(ctx, `python3 /tmp/bus-probe.py ${dev} 9600 ${PRESENT_PROBE_UNITS.join(',')} 2>&1`).stdout;
      const present = [...out.matchAll(/PRESENT (\d+)/g)].map(m => parseInt(m[1], 10));
      if (/OPENFAIL|NOSERIAL/.test(out)) warn(`probe could not open the bus: ${out.trim().split('\n')[0]}`);
      if (!present.length) { warn('no PF units answered — defaulting to PF1 (88)'); present.push(88); }
      ctx.store.presentUnits = present;
      ok(`present PF units: ${present.join(', ')}`);
      fs.mkdirSync(OUT, { recursive: true });
      fs.writeFileSync(path.join(OUT, `${ctx.kit}.scan.json`), JSON.stringify({ byId: ctx.store.byId || null, dev, presentUnits: present, when: new Date().toISOString() }, null, 2));
    },
  },

  // ---------------- 6. Laptop artifacts ----------------
  {
    id: 'artifacts', fatal: true, title: 'Laptop — build/verify offline artifacts',
    async detect(ctx) {
      const need = artifactPaths(ctx);
      const missing = Object.entries(need).filter(([, p]) => !fs.existsSync(p)).map(([k]) => k);
      const current = release.validArtifacts(RELEASE_FILE, release.sourceRevision(REPO), need);
      return { done: !missing.length && current, detail: current ? 'verified current source artifacts' : 'artifacts missing or outdated for this source' };
    },
    async run(ctx) {
      const need = artifactPaths(ctx);
      if (ctx.args.skipArtifacts) throw new Error('--skip-artifacts requires verified artifacts for the current source; rerun without it');
      fs.mkdirSync(CACHE, { recursive: true });
      step('building current frontend (npm run build)…');
      await mustLocal('npm', ['ci', '--no-audit', '--no-fund'], path.join(REPO, 'frontend'), 'npm ci');
      await mustLocal('npm', ['run', 'build'], path.join(REPO, 'frontend'), 'npm run build');
      await packTgz(need.dist, path.join(REPO, 'frontend', 'dist'), [], ['.'], 'pack dist');
      // backend tgz (cheap, always fine)
      step('packing backend…');
      await packTgz(need.backend, path.join(REPO, 'backend'),
        ['--exclude=__pycache__', '--exclude=*.pyc'], ['app'], 'pack backend');
      // wheelhouse
      if (!fs.existsSync(need.wheels)) {
        const wh = path.join(CACHE, 'wheelhouse');
        if (!fs.existsSync(path.join(wh, 'fastapi')) && !dirHasWheels(wh)) {
          step('building arm64 wheelhouse in python:3.11 container…');
          fs.mkdirSync(wh, { recursive: true });
          writeLeanReq(path.join(CACHE, 'requirements-lean.txt'));
          await local('docker', ['run', '--rm', '-v', `${CACHE}:/out`, 'python:3.11-slim', 'bash', '-c',
            shq('pip download -d /out/wheelhouse --only-binary=:all: --platform manylinux_2_17_aarch64 --platform manylinux_2_28_aarch64 --python-version 3.11 --implementation cp --abi cp311 -r /out/requirements-lean.txt')]);
        }
        fs.copyFileSync(path.join(CACHE, 'requirements-lean.txt'), path.join(wh, 'requirements-lean.txt'));
        step('packing wheelhouse…');
        await packTgz(need.wheels, wh, [], ['.'], 'pack wheelhouse');
      }
      const m = manifest();
      fs.mkdirSync(CACHE, { recursive: true });
      // tailscale
      if (!fs.existsSync(need.tailscale)) {
        step(`downloading tailscale ${m.tailscale.version} arm64…`);
        await fetchVerified(m.tailscale, need.tailscale);
      }
      // docker static engine (aarch64)
      if (!fs.existsSync(need.docker)) {
        step(`downloading docker ${m.docker_static.version} static aarch64…`);
        await fetchVerified(m.docker_static, need.docker);
      }
      // tb-gateway image: pull by immutable digest, then save+gzip locally. `docker save`
      // output is not byte-reproducible, so the digest is what is pinned, not a file hash.
      if (!fs.existsSync(need.image)) {
        const img = m.tb_gateway_image;
        const byDigest = img.ref.split(':')[0] + '@' + img.digest;
        step(`pulling ${byDigest} (${img.platform})…`);
        let r = await local('docker', ['pull', '--platform', img.platform, byDigest]);
        if (r.code !== 0) throw new Error('docker pull failed - is Docker Desktop running?');
        r = await local('docker', ['tag', byDigest, img.ref]);
        if (r.code !== 0) throw new Error('docker tag failed');
        const tar = path.join(CACHE, 'tbgw-image.tar');
        step('saving image…');
        r = await local('docker', ['save', '-o', tar, img.ref]);
        if (r.code !== 0) throw new Error('docker save failed');
        step('compressing image…');
        await new Promise((res, rej) => {
          const gz = require('zlib').createGzip({ level: 6 });
          fs.createReadStream(tar).pipe(gz).pipe(fs.createWriteStream(need.image))
            .on('finish', res).on('error', rej);
        });
        fs.unlinkSync(tar);
        ok(`image bundled: ${path.basename(need.image)}`);
      }
      const stillMissing = Object.entries(need).filter(([, f]) => !fs.existsSync(f)).map(([k]) => k);
      if (stillMissing.length) throw new Error('artifacts still missing after build: ' + stillMissing.join(', '));
      fs.writeFileSync(RELEASE_FILE, JSON.stringify({ revision: release.sourceRevision(REPO), files: Object.fromEntries(Object.entries(need).map(([k, f]) => [k, release.sha(f)])) }, null, 2));
      ok('artifacts ready and tied to current source');
    },
  },

  // ---------------- 7. Docker ----------------
  {
    id: 'docker', title: 'Box — install Docker + load tb-gateway image',
    async detect(ctx) {
      const r = sh(ctx, asRoot(ctx, 'docker version --format "{{.Server.Arch}}" 2>/dev/null; docker image ls --format "{{.Repository}}:{{.Tag}}" 2>/dev/null | grep -c tb-gateway'));
      const done = /arm64/.test(r.stdout) && /(^|\n)[1-9]/.test(r.stdout.trim());
      return { done, detail: done ? 'docker (arm64) up, tb-gateway image loaded' : 'docker/image not ready' };
    },
    async run(ctx) {
      const need = artifactPaths(ctx);
      step('uploading docker + image tarballs (over the cable)…');
      scp(ctx, need.docker, '/tmp/docker-static.tgz');
      scp(ctx, need.image, '/tmp/tbgw-image.tar.gz');
      scp(ctx, path.join(BOXDIR, 'install-docker-static.sh'), '/tmp/install-docker-static.sh');
      step('installing Docker (nft-only: --iptables=false --bridge=none) + loading image…');
      const r = await stream(ctx, asRoot(ctx, 'chmod +x /tmp/install-docker-static.sh && /tmp/install-docker-static.sh /tmp/docker-static.tgz /tmp/tbgw-image.tar.gz'));
      if (r.code !== 0) throw new Error('install-docker-static.sh failed');
      ok('docker installed + image loaded');
    },
  },

  // ---------------- 8. Build config ----------------
  {
    id: 'config', title: 'Laptop — build gateway config (configured devices)',
    async detect() { return { done: false, detail: 'regenerate the intended site inventory' }; },
    async run(ctx) {
      const site = path.join(PROV, 'sites', `${ctx.kit}.json`);
      if (!fs.existsSync(site)) throw new Error(`site file missing: ${site}`);
      step('generating tb_gateway.json + modbus.json for all configured devices…');
      const env = { ...process.env, ECO_MODBUS_PORT: '/dev/meterbus', MSYS_NO_PATHCONV: '1' };
      const built = await new Promise(res => {
        const p = spawn('node', ['build-gw-config.js', ctx.kit, site], { cwd: __dirname, shell: true, env, stdio: ['ignore', 'pipe', 'pipe'] });
        p.stdout.on('data', dimw); p.stderr.on('data', dimw); p.on('close', code => res(code));
        p.on('error', () => res(1));
      });
      if (built !== 0) throw new Error('Gateway config generation failed');
      const cfgDir = path.join(OUT, ctx.kit, 'config');
      if (!fs.existsSync(path.join(cfgDir, 'tb_gateway.json'))) throw new Error('build-gw-config produced no output');
      ok('gateway config built');
    },
  },

  // ---------------- 9. Deploy container ----------------
  {
    id: 'deploy', title: 'Box — deploy tb-gateway container',
    async detect(ctx) {
      const r = sh(ctx, asRoot(ctx, 'docker inspect -f "{{.State.Running}}" tb-gateway 2>/dev/null; grep -o "usernamePassword\\|accessToken" /opt/eco/tb-gateway/config/tb_gateway.json 2>/dev/null | head -1'));
      const running = /true/.test(r.stdout);
      // treat as done only if running AND our config is present
      const configured = /usernamePassword|accessToken/.test(r.stdout);
      return { done: running && configured, detail: running ? (configured ? 'container running with our config' : 'running but config unverified — will redeploy') : 'not deployed' };
    },
    async run(ctx) {
      const cfgDir = path.join(OUT, ctx.kit, 'config');
      const byId = ctx.store.byId || sh(ctx, `ls /dev/serial/by-id/ 2>/dev/null | grep -- '-${BYID_IF}$' | head -1`).stdout.trim().replace(/^/, '/dev/serial/by-id/');
      step('uploading connector config…');
      await stream(ctx, asRoot(ctx, 'mkdir -p /opt/eco/tb-gateway/config /opt/eco/tb-gateway/logs'));
      // scp needs a writable path; drop in /tmp then move as root
      scp(ctx, path.join(cfgDir, 'tb_gateway.json'), '/tmp/tb_gateway.json');
      scp(ctx, path.join(cfgDir, 'modbus.json'), '/tmp/modbus.json');
      await stream(ctx, asRoot(ctx, 'cp /tmp/tb_gateway.json /tmp/modbus.json /opt/eco/tb-gateway/config/ && touch /opt/eco/tb-gateway/config/.firstlaunch'));
      step('starting container (--network host, by-id → /dev/meterbus)…');
      const run = `docker rm -f tb-gateway 2>/dev/null; docker run -d --name tb-gateway --restart unless-stopped --network host ` +
        `--device ${byId}:/dev/meterbus ` +
        `-v /opt/eco/tb-gateway/config:/thingsboard_gateway/config -v /opt/eco/tb-gateway/logs:/thingsboard_gateway/logs ` +
        `${ctx.cfg.docker.imageRef}`;
      const r = await stream(ctx, asRoot(ctx, run));
      if (r.code !== 0) throw new Error('docker run failed');
      info('waiting 20s for the connector to come up…');
      await sleep(20000);
      ok('tb-gateway deployed');
    },
  },

  {
    id: 'live-telemetry', fatal: true, title: 'Box — upgrade local telemetry observer',
    async detect(ctx) {
      const expected = release.sha(path.join(REPO, 'gateway/extensions/eco_modbus/live_modbus.py'));
      const r = sh(ctx, asRoot(ctx, `docker exec tb-gateway sha256sum /thingsboard_gateway/extensions/eco_modbus/live_modbus.py 2>/dev/null; docker inspect -f '{{range .Mounts}}{{println .Destination}}{{end}}' tb-gateway 2>/dev/null; cat /opt/eco/tb-gateway/.live-release 2>/dev/null`));
      return { done: r.stdout.includes(expected) && r.stdout.split(/\r?\n/).includes('/run/eco-telemetry') && r.stdout.includes(release.sourceRevision(REPO)), detail: 'observer code, shared memory mount and installer release checked' };
    },
    async run(ctx) {
      await putMany(ctx, [
        { local: path.join(BOXDIR, 'install-live-telemetry.py'), remote: '/tmp/install-live-telemetry.py' },
        { local: path.join(REPO, 'tools/prepare-live-telemetry.py'), remote: '/tmp/prepare-live-telemetry.py' },
        { local: path.join(REPO, 'gateway/extensions/eco_modbus/live_modbus.py'), remote: '/tmp/live_modbus.py' },
      ], 'uploading local telemetry observer…');
      const r = await stream(ctx, asRoot(ctx, 'python3 /tmp/install-live-telemetry.py /tmp/prepare-live-telemetry.py /tmp/live_modbus.py'));
      if (r.code !== 0) throw new Error('Observer upgrade failed; inspect rollback output before continuing');
      const marked = await stream(ctx, asRoot(ctx, `printf '%s' ${shq(release.sourceRevision(REPO))} > /opt/eco/tb-gateway/.live-release`));
      if (marked.code !== 0) throw new Error('Could not record observer release');
    },
  },

  {
    id: 'connector-sync', fatal: true, title: 'ThingsBoard — synchronize installed connectors',
    async detect(ctx) {
      const id = ctx.store.gw?.id;
      if (!id) throw new Error('Gateway device identity is missing');
      const r = sh(ctx, asRoot(ctx, 'cat /opt/eco/tb-gateway/config/.eco-sync.json 2>/dev/null'));
      let marker; try { marker = JSON.parse(r.stdout); } catch (_) {}
      return {done: marker?.deviceId === id && marker?.version === 1, detail: marker?.deviceId === id ? 'initial cloud synchronization already verified; preserving later cloud/local edits' : 'initial synchronization not yet verified'};
    },
    async run(ctx) {
      const id = ctx.store.gw?.id;
      if (!id) throw new Error('Gateway device identity is missing');
      const tb = new TB(ctx.cfg, {apply:true});
      await tb.login();
      await putMany(ctx, [{local:path.join(BOXDIR,'connector-sync.py'),remote:'/tmp/connector-sync.py'}], 'uploading configuration synchronizer…');
      const captured = sh(ctx, asRoot(ctx, 'python3 /tmp/connector-sync.py export'));
      if (captured.code !== 0) throw new Error('Could not read installed connector configuration');
      // Contains MQTT credentials: never send this through stream()/dimw().
      const snapshot = JSON.parse(captured.stdout);
      if (!connectorSync.credentialsMatch(snapshot.gateway.thingsboard.security, await tb.deviceCredentials(id))) {
        throw new Error('Installed MQTT credentials do not match the selected ThingsBoard gateway. Reconcile the kit identity before synchronizing.');
      }
      const desired = connectorSync.payload(snapshot);
      const attrPath = `/api/plugins/telemetry/DEVICE/${id}/values/attributes/`;
      const previous = await tb.get(attrPath + 'SHARED_SCOPE');
      fs.mkdirSync(OUT,{recursive:true});
      fs.writeFileSync(path.join(OUT,`${ctx.kit}.connector-sync-backup-${Date.now()}.json`),JSON.stringify(previous,null,2),{mode:0o600});
      await tb.postSharedAttributes(id,desired);
      const since = Date.now();
      try {
        const enabled = await stream(ctx,asRoot(ctx,'python3 /tmp/connector-sync.py enable && docker restart tb-gateway'));
        if (enabled.code !== 0) throw new Error('Could not enable gateway remote configuration');
        let matched = false;
        for (let i=0;i<36;i++) {
          if (connectorSync.acknowledged(desired,await tb.get(attrPath+'CLIENT_SCOPE'),since)) {matched=true;break;}
          if (i%6===0) info('waiting for matching gateway configuration acknowledgement…');
          await sleep(5000);
        }
        if (!matched) throw new Error('Gateway did not acknowledge matching configuration within 180 seconds');
        const marked = await stream(ctx,asRoot(ctx,'python3 /tmp/connector-sync.py complete '+shq(id)));
        if (marked.code !== 0) throw new Error('Could not record completed synchronization');
        ok('Installed configuration and ThingsBoard report match');
      } catch (error) {
        const paused = await stream(ctx,asRoot(ctx,'python3 /tmp/connector-sync.py disable && docker restart tb-gateway'));
        if(paused.code !== 0) warn('Could not disable remote configuration after sync failure; inspect the gateway before continuing');
        throw error;
      }
    },
  },

  // ---------------- 10. Tailscale ----------------
  {
    id: 'tailscale', title: 'Box — join Tailscale (remote SSH + web)',
    async detect(ctx) {
      // one round trip for both the address and the node name (first status line is self)
      const out = sh(ctx, asRoot(ctx, 'tailscale ip -4 2>/dev/null | head -1; tailscale status 2>/dev/null | head -1 | awk "{print \\$2}"')).stdout.trim().split(/\r?\n/);
      const ip = (out[0] || '').trim();
      if (/^100\./.test(ip)) {
        ctx.store.tsIp = ip;
        ctx.store.tsName = (out[1] || '').trim();
        return { done: true, detail: `tailnet IP ${ip}${ctx.store.tsName ? ' (' + ctx.store.tsName + ')' : ''}` };
      }
      return { done: false, detail: 'not enrolled' };
    },
    async run(ctx) {
      if (!ctx.cfg.tailscale.authkey) throw new Error('TS_AUTHKEY not set in .env');
      const tgz = artifactPaths(ctx).tailscale;
      await putMany(ctx, [
        { local: tgz, remote: '/tmp/tailscale.tgz' },
        { local: path.join(BOXDIR, 'install-tailscale.sh'), remote: '/tmp/install-tailscale.sh' },
      ], 'uploading tailscale bundle…');
      const hn = `eco-${ctx.kit.toLowerCase()}`;
      step('installing tailscale + enrolling (Tailscale SSH off — real sshd + key)…');
      const r = await stream(ctx, asRoot(ctx, `chmod +x /tmp/install-tailscale.sh && /tmp/install-tailscale.sh /tmp/tailscale.tgz ${shq(ctx.cfg.tailscale.authkey)} ${shq(hn)}`));
      if (r.code !== 0) throw new Error('install-tailscale.sh failed');
      const ip = sh(ctx, asRoot(ctx, 'tailscale ip -4 2>/dev/null | head -1')).stdout.trim();
      ctx.store.tsIp = ip;
      ok(`tailscale up — ${ip}`);
    },
  },

  // ---------------- 11. Web console ----------------
  {
    id: 'webconsole', title: 'Box — install web console (FastAPI + Vue)',
    async detect(ctx) {
      const r = sh(ctx, asRoot(ctx, 'systemctl is-active eco-iot-gw-backend 2>/dev/null; grep -q "change-me-in-production" /etc/eco-iot-gw/secrets.env 2>/dev/null && echo DEFAULTSECRET || echo SECRETOK'));
      // `systemctl is-active` prints "inactive" for a stopped unit — a bare /active/ regex
      // matches that substring and would falsely report the console installed. Match the
      // first line exactly instead.
      const active = r.stdout.split(/\r?\n/)[0].trim() === 'active';
      const secretOk = /SECRETOK/.test(r.stdout);
      const revision = sh(ctx, 'cat /opt/eco/webui/release 2>/dev/null').stdout.trim();
      return { done: active && secretOk && revision === release.sourceRevision(REPO), detail: active ? (secretOk ? 'backend active, per-device secrets set' : 'active but on default secrets') : 'not installed' };
    },
    async run(ctx) {
      const need = artifactPaths(ctx);
      if (!release.validArtifacts(RELEASE_FILE, release.sourceRevision(REPO), need)) throw new Error('Current source artifacts were not verified');
      await putMany(ctx, [{local:path.join(BOXDIR,'requirements-webconsole.txt'),remote:'/tmp/webconsole-requirements.txt'}], 'checking installed Python dependencies…');
      const reuse = sh(ctx, asRoot(ctx, '/opt/eco/webui/venv/bin/python -m pip install --dry-run --no-index -r /tmp/webconsole-requirements.txt >/dev/null 2>&1')).code === 0;
      if (reuse) info('installed dependencies satisfy this release; skipping wheelhouse upload');
      await putMany(ctx, [
        { local: path.join(PROV, 'setup-secrets.sh'), remote: '/tmp/setup-secrets.sh' },
        { local: path.join(BOXDIR, 'install-webconsole.sh'), remote: '/tmp/install-webconsole.sh' },
        { local: need.backend, remote: '/tmp/webconsole-backend.tgz' },
        ...(!reuse ? [{ local: need.wheels, remote: '/tmp/webconsole-wheelhouse.tgz' }] : []),
        { local: need.dist, remote: '/tmp/webconsole-dist.tgz' },
      ], 'uploading secrets script + console artifacts…');
      step('generating per-device secrets…');
      await stream(ctx, asRoot(ctx, 'chmod +x /tmp/setup-secrets.sh && /tmp/setup-secrets.sh'));
      step('installing web console (systemd, 0.0.0.0:80)…');
      const r = await stream(ctx, asRoot(ctx, 'chmod +x /tmp/install-webconsole.sh && /tmp/install-webconsole.sh /tmp/webconsole-backend.tgz ' + (reuse ? '-' : '/tmp/webconsole-wheelhouse.tgz') + ' /tmp/webconsole-dist.tgz ' + shq(release.sourceRevision(REPO)) + ' /tmp/webconsole-requirements.txt'));
      if (r.code !== 0) throw new Error('install-webconsole.sh failed');
      await stream(ctx, asRoot(ctx, 'systemctl restart eco-iot-gw-backend'));
      await ensureEcoadminPassword(ctx);
      ok('web console installed');
    },
  },

  // ---------------- 12. LTE telemetry ----------------
  // Restores the fleet's LTE_RSSI/RSRQ/RSRP/SN_RATIO/IP keys on ECO_<HWID>_gw, which
  // stopped when RESI was stood down. See box/install-lte-telemetry.sh for the mechanism.
  {
    id: 'lte', title: 'Box - restore LTE_* telemetry on the gateway device',
    async detect(ctx) {
      if (ctx.args.noLte) return { done: true, detail: 'skipped (--no-lte)' };
      const active = sh(ctx, asRoot(ctx, 'systemctl is-active eco-lte-signal.timer 2>/dev/null || true')).stdout.trim();
      const wired = sh(ctx, asRoot(ctx, 'grep -q "statistics/eco_lte.json" /opt/eco/tb-gateway/config/tb_gateway.json 2>/dev/null && echo YES || echo NO')).stdout.trim();
      // exact match: "inactive" contains "active", so /active/ would be a false positive
      const good = active === 'active' && /YES/.test(wired);
      return { done: good, detail: good ? 'sampler timer active, gateway statistics wired'
                                       : 'timer=' + (active || 'absent') + ' wired=' + /YES/.test(wired) };
    },
    async run(ctx) {
      scp(ctx, path.join(BOXDIR, 'install-lte-telemetry.sh'), '/tmp/install-lte-telemetry.sh');
      step('installing LTE sampler + wiring tb-gateway custom statistics...');
      const r = await stream(ctx, asRoot(ctx, 'sh /tmp/install-lte-telemetry.sh'));
      if (r.code !== 0) throw new Error('install-lte-telemetry.sh failed');
      ok('LTE telemetry installed');
    },
  },

  // ---------------- 13. Verify ----------------
  {
    id: 'verify', title: 'Verify — reachability + live telemetry',
    async detect() { return { done: false, detail: 'always run' }; },
    async run(ctx) {
      // web console health on the cable IP
      const h = sh(ctx, 'curl -s -m 5 -o /dev/null -w "%{http_code}" http://127.0.0.1/api/health').stdout.trim();
      h === '200' ? ok(`web console health: 200`) : warn(`web console health: ${h}`);
      // container running?
      const running = sh(ctx, asRoot(ctx, 'docker inspect -f "{{.State.Running}}" tb-gateway 2>/dev/null')).stdout.trim();
      running === 'true' ? ok('tb-gateway container running') : bad('tb-gateway not running');
      // telemetry = the connector actually polling the bus (auth-free ground truth:
      // count recent DEBUG reads + the last publish stats in the container log).
      const logq = asRoot(ctx, 'LP=$(docker inspect tb-gateway --format "{{.LogPath}}"); ' +
        'tail -c 400000 "$LP" 2>/dev/null | grep -a -c "Read with result"');
      const reads = parseInt(sh(ctx, logq).stdout.trim() || '0', 10);
      reads > 0 ? ok(`bus polling: ${reads} recent register reads (connector active)`) : warn('no recent bus reads in the container log (connector may still be starting, or logLevel != DEBUG)');
      // LTE sample files - what the gateway publishes on its next statistics push
      if (!ctx.args.noLte) {
        const lte = sh(ctx, asRoot(ctx, 'for k in LTE_RSSI LTE_RSRQ LTE_RSRP LTE_SN_RATIO LTE_IP; do printf "%s=%s " "$k" "$(cat /opt/eco/tb-gateway/config/lte/$k 2>/dev/null || echo -)"; done')).stdout.trim();
        if (lte && !/=-9999/.test(lte) && !/=- /.test(lte)) ok('LTE telemetry: ' + lte);
        else warn('LTE telemetry incomplete: ' + (lte || 'no sample files yet'));
      }
      if (ctx.store.tsIp) {
        ok(`remote:  ssh ecoadmin@${ctx.store.tsIp}   ·   http://${ctx.store.tsIp}/`);
      }
      ok(`on-site: ssh ecoadmin@10.10.10.1   ·   http://10.10.10.1/`);
      if (recordCredentials(ctx)) ok(`credentials ledger updated: out/credentials.csv (row "${ctx.kit}")`);
    },
  },
];

// ---------- helpers used by phases ----------
function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

function artifactPaths(ctx) {
  // .env may point at files kept elsewhere; otherwise use the manifest's filenames so
  // what the fetcher writes and what the install phases read can never drift apart.
  const m = manifest();
  return {
    docker: ctx.cfg.docker.staticTgz || path.join(CACHE, m.docker_static.file),
    image: ctx.cfg.docker.imageTar || path.join(CACHE, m.tb_gateway_image.file),
    wheels: path.join(CACHE, 'webconsole-wheelhouse.tgz'),
    backend: path.join(CACHE, 'webconsole-backend.tgz'),
    dist: path.join(CACHE, 'webconsole-dist.tgz'),
    tailscale: path.join(CACHE, m.tailscale.file),
  };
}
// tar on Windows (bsdtar via cmd.exe) mangles backslash paths - it reported
// "Cannot write: Broken pipe" on C:\...\file.tgz. Forward slashes work on both platforms.
function px(v) { return String(v).replace(/\\/g, '/'); }

// Pack a .tgz without ever handing tar an absolute Windows path. GNU tar reads "C:/x" as
// a remote host:path spec ("Cannot connect to C: resolve failed"), so run it with cwd set
// to the source directory and refer to the archive by a relative path - no drive letter,
// no colon, works with both GNU tar and bsdtar.
async function packTgz(destFile, srcDir, opts, members, what) {
  const rel = px(path.relative(srcDir, destFile));
  await mustLocal('tar', ['-czf', rel, ...opts, ...members], srcDir, what);
  if (!fs.existsSync(destFile)) throw new Error(what + ': bundle not created (' + destFile + ')');
}

// local() returns a code but callers were ignoring it, so a failed pack still printed
// "artifacts ready" and left the install to fail later on a missing file. Always check.
async function mustLocal(cmd, args, cwd, what) {
  const r = await local(cmd, args, cwd);
  if (r.code !== 0) throw new Error(what + ' failed (exit ' + r.code + ')\n' + r.out.trim().slice(-500));
  return r;
}

function dirHasWheels(dir) { try { return fs.readdirSync(dir).some(f => f.endsWith('.whl')); } catch { return false; } }
function writeLeanReq(p) {
  fs.copyFileSync(path.join(BOXDIR,'requirements-webconsole.txt'), p);
}
// ---------- credential ledger ----------
// One CSV for the whole fleet, keyed by kit, so doing several units back to back leaves a
// single file to hand over. Gitignored (it lives under out/, and the filename is ignored
// explicitly too). Upserted rather than appended, so re-running a kit refreshes its row
// instead of leaving stale duplicates.
const CRED_CSV = path.join(OUT, 'credentials.csv');
const CRED_COLS = ['kit', 'gateway_name', 'web_user', 'web_password',
  'url_cable', 'url_tailscale', 'tailscale_name', 'box_ssh_user', 'recorded_utc'];

function csvEsc(v) {
  const t = (v === undefined || v === null) ? '' : String(v);
  return /[",\r\n]/.test(t) ? '"' + t.replace(/"/g, '""') + '"' : t;
}
// Minimal RFC4180 line parser - enough to read the key column back for the upsert.
// Values we write never contain newlines (the password alphabet excludes quotes and
// commas), so splitting the file by line first is safe.
function csvParseLine(line) {
  const out = []; let cur = '', q = false;
  for (let i = 0; i < line.length; i++) {
    const c = line[i];
    if (q) {
      if (c === '"') { if (line[i + 1] === '"') { cur += '"'; i++; } else q = false; }
      else cur += c;
    } else if (c === '"') q = true;
    else if (c === ',') { out.push(cur); cur = ''; }
    else cur += c;
  }
  out.push(cur);
  return out;
}

// Write/refresh this kit's row. password may be omitted on a re-run - it is then read
// back from the per-kit secrets.json so the ledger can still pick up newly-known values
// such as the tailnet address.
function recordCredentials(ctx, password) {
  let pw = password;
  const secFile = path.join(OUT, ctx.kit + '.secrets.json');
  if (!pw && fs.existsSync(secFile)) {
    try { pw = JSON.parse(fs.readFileSync(secFile, 'utf8')).webconsole_login.password; } catch (_) {}
  }
  if (!pw) return false;  // nothing recorded for this kit yet

  const row = {
    kit: ctx.kit,
    gateway_name: (ctx.store.gw && ctx.store.gw.name) || '',
    web_user: 'ecoadmin',
    web_password: pw,
    url_cable: 'http://10.10.10.1/',
    url_tailscale: ctx.store.tsIp ? 'http://' + ctx.store.tsIp + '/' : '',
    tailscale_name: ctx.store.tsName || '',
    box_ssh_user: 'ecoadmin',
    recorded_utc: new Date().toISOString().replace(/\.\d{3}Z$/, 'Z'),
  };

  fs.mkdirSync(OUT, { recursive: true });
  let kept = [];
  if (fs.existsSync(CRED_CSV)) {
    const lines = fs.readFileSync(CRED_CSV, 'utf8').split(/\r?\n/).filter(l => l.trim() !== '');
    // drop the old header and any previous row for this kit
    kept = lines.slice(1).filter(l => csvParseLine(l)[0] !== ctx.kit);
  }
  // keep an existing row's non-empty value when this run does not know it
  const merged = CRED_COLS.map(c => csvEsc(row[c])).join(',');
  const body = kept.concat([merged]);
  fs.writeFileSync(CRED_CSV, CRED_COLS.join(',') + '\n' + body.join('\n') + '\n');
  try { fs.chmodSync(CRED_CSV, 0o600); } catch (_) {}
  return true;
}

async function ensureEcoadminPassword(ctx) {
  const secFile = path.join(OUT, `${ctx.kit}.secrets.json`);
  if (fs.existsSync(secFile)) {
    let saved;
    try { saved = JSON.parse(fs.readFileSync(secFile, 'utf8')).webconsole_login.password; } catch (_) {}
    if (!saved) throw new Error(`Invalid ${ctx.kit}.secrets.json: webconsole_login.password is missing`);
    // A card reinstall recreates (and may lock) the Linux account while this operator-side
    // file survives. Reapply the recorded value so the credential ledger remains truthful.
    const changed = await stream(ctx, asRoot(ctx, `echo 'ecoadmin:${saved}' | chpasswd`));
    if (changed.code !== 0) throw new Error('Could not restore the recorded ecoadmin password');
    info('recorded ecoadmin web-login password restored on box');
    recordCredentials(ctx, saved);   // refresh the shared ledger anyway
    return;
  }
  const existing = sh(ctx, asRoot(ctx, "passwd -S ecoadmin | awk '{print $2}'")).stdout.trim();
  if (existing === 'P') { info('existing ecoadmin password retained; no local credential copy available'); return; }
  const alphabet = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghikmnpqrstuvwxyz23456789';
  const pw = Array.from({ length: 16 }, () => alphabet[crypto.randomInt(alphabet.length)]).join('');
  const changed = await stream(ctx, asRoot(ctx, `echo 'ecoadmin:${pw}' | chpasswd`));
  if (changed.code !== 0) throw new Error('Could not set ecoadmin password');
  fs.mkdirSync(OUT, { recursive: true });
  fs.writeFileSync(secFile, JSON.stringify({
    kit: ctx.kit, gatewayName: ctx.store.gw ? ctx.store.gw.name : null,
    webconsole_login: { user: 'ecoadmin', password: pw },
    access: { cable: 'http://10.10.10.1/', tailscale_ip: ctx.store.tsIp || null, tailscale_name: ctx.store.tsName || null },
  }, null, 2));
  try { fs.chmodSync(secFile, 0o600); } catch {}
  recordCredentials(ctx, pw);
  ok(`ecoadmin web-login password set + recorded (out/${ctx.kit}.secrets.json, out/credentials.csv)`);
}

// =====================================================================
// ---------- preflight ----------
function checkRow(state, label, detail) {
  const mark = state === 'ok' ? `${C.grn}✓${C.r}` : state === 'warn' ? `${C.yel}!${C.r}` : `${C.red}✗${C.r}`;
  console.log(`  ${mark} ${label}${detail ? '  ' + C.dim + detail + C.r : ''}`);
}
// Environment + repo sanity before anything touches a box. Returns false on a blocking
// problem. Missing-but-recoverable things (cache, optional keys) are warnings, not blocks.
function preflight(cfg) {
  hdr('Preflight — environment & repo');
  let fatal = 0, warns = 0;

  const nodeMajor = parseInt(process.versions.node.split('.')[0], 10);
  if (nodeMajor >= 18) checkRow('ok', `Node ${process.versions.node}`);
  else { checkRow('bad', `Node ${process.versions.node} — need ≥ 18`); fatal++; }

  // Elevation: the `net` phase renews the laptop's cable adapter (ipconfig /release+/renew),
  // which needs Administrator on Windows. Verified: without it, provisioning stalls.
  if (os.platform() === 'win32') {
    if (isElevatedWin()) checkRow('ok', 'terminal is elevated (Administrator)');
    else { checkRow('warn', 'terminal NOT elevated', 'run this terminal as Administrator — the net phase renews the cable adapter (needs admin)'); warns++; }
  }

  // Paths are anchored to this file (__dirname), so cwd doesn't matter — but a broken or
  // partial checkout would miss the scripts the wizard scps to the box.
  const need = [
    [path.join(PROV, 'setup-direct-ethernet.sh'), 'setup-direct-ethernet.sh'],
    [path.join(BOXDIR, 'ecoadmin.sh'), 'box/ecoadmin.sh'],
    [path.join(BOXDIR, 'standdown-resi.sh'), 'box/standdown-resi.sh'],
    [path.join(BOXDIR, 'harden-users.sh'), 'box/harden-users.sh'],
    [MANIFEST, 'artifacts.json'],
    [path.join(PROV, 'sites'), 'sites/'],
  ];
  const missing = need.filter(([p]) => !fs.existsSync(p)).map(([, n]) => n);
  if (!missing.length) checkRow('ok', 'repo layout intact', `migrate: ${__dirname}`);
  else { checkRow('bad', 'repo layout broken — missing ' + missing.join(', '), 'run from a full checkout'); fatal++; }
  if (path.resolve(process.cwd()) !== path.resolve(__dirname)) checkRow('ok', 'run location', `cwd=${process.cwd()} — paths anchored, so this is fine`);

  if (fs.existsSync(cfg.envPath)) checkRow('ok', '.env present', cfg.envPath);
  else { checkRow('bad', '.env missing', `copy .env.example → ${cfg.envPath}`); fatal++; }

  if (cfg.tb.baseUrl && cfg.tb.username && cfg.tb.password) checkRow('ok', 'ThingsBoard credentials', cfg.tb.baseUrl);
  else { checkRow('bad', 'ThingsBoard credentials incomplete', 'need TB_BASE_URL / TB_USERNAME / TB_PASSWORD'); fatal++; }

  const sshv = ((capture('ssh', ['-V']).stderr || '') + (capture('ssh', ['-V']).stdout || '')).trim();
  if (/OpenSSH/i.test(sshv)) checkRow('ok', 'OpenSSH client', sshv.split(/\r?\n/)[0]);
  else { checkRow('bad', 'ssh/scp not on PATH', 'install the Windows OpenSSH client'); fatal++; }

  if (cfg.box.password) checkRow('ok', 'box SSH password set', 'for factory-box bootstrap');
  else { checkRow('warn', 'box SSH password not set', 'only needed to bootstrap a factory box'); warns++; }

  const kp = cfg.box.keyPath;
  if (kp && fs.existsSync(kp) && fs.existsSync(kp + '.pub')) checkRow('ok', 'ecoadmin SSH keypair', kp);
  else { checkRow('warn', 'ecoadmin SSH keypair missing (private + .pub)', kp || 'set BOX_SSH_KEY'); warns++; }

  if (cfg.tailscale.authkey) checkRow('ok', 'Tailscale auth key set');
  else { checkRow('warn', 'Tailscale auth key not set', 'the tailscale phase needs TS_AUTHKEY'); warns++; }

  try {
    const man = manifest();
    const pinned = Object.keys(man).filter(k => k !== '_comment').map(k => man[k].file);
    const wc = ['webconsole-backend.tgz', 'webconsole-dist.tgz', 'webconsole-wheelhouse.tgz'];
    const cacheMissing = [...pinned, ...wc].filter(f => !fs.existsSync(path.join(CACHE, f)));
    if (!cacheMissing.length) checkRow('ok', 'offline artifacts cached', `${pinned.length + wc.length} files in cache/`);
    else { checkRow('warn', 'offline artifacts incomplete', 'missing ' + cacheMissing.join(', ') + ' — the artifacts phase rebuilds these (needs office internet)'); warns++; }
  } catch (e) { checkRow('warn', 'could not read artifacts.json', e.message); warns++; }

  if (fatal) { bad(`${fatal} blocking problem(s) — fix the ✗ item(s) above and re-run.`); return false; }
  if (warns) info(`${warns} warning(s) above — not blocking.`);
  else ok('all checks passed');
  return true;
}

// interactive kit picker — used when --kit is not given
async function pickKit(cfg) {
  step('fetching kits from ThingsBoard…');
  const tb = new TB(cfg, { apply: false });
  try { await tb.login(); }
  catch (e) { bad('ThingsBoard login failed: ' + e.message); return null; }
  const kits = await tb.listKits();
  if (!kits.length) { bad('no DiagnosticKit assets found in ThingsBoard'); return null; }
  info(`${kits.length} kit(s) found. (Tip: skip this next time with --kit <name>.)`);
  const chosen = await menu('pick the kit to provision', kits,
    k => `${C.b}${k.name}${C.r}${k.customer ? '  ' + C.dim + k.customer + C.r : ''}`);
  return chosen ? chosen.name : null;
}

async function mainWizard() {
  const args = parseArgs(process.argv);
  const cfg = cfgLib.load();

  RL = readline.createInterface({ input: process.stdin, output: process.stdout });
  RL.on('close', () => { RL_CLOSED = true; });

  if (!preflight(cfg)) { RL.close(); process.exit(2); }

  if (!args.kit) {
    args.kit = await pickKit(cfg);
    if (!args.kit) { bad('no kit selected — pass --kit <name> or pick from the list.'); RL.close(); process.exit(2); }
  }

  const ctx = { cfg, kit: args.kit, args, box: { host: '10.10.10.1', user: 'ecoadmin' }, store: {} };

  console.log(`\n${C.b}${C.mag}ECO migration wizard${C.r}  kit=${C.b}${args.kit}${C.r}  ${args.yes ? C.yel + '(auto-yes)' + C.r : ''}`);
  console.log(`${C.dim}Each phase self-detects: already-done steps are skipped automatically, so re-running is safe.${C.r}`);

  const summary = [];
  for (const ph of PHASES) {
    hdr(ph.title);
    let det;
    try { det = await ph.detect(ctx); }
    catch (e) { bad(`detect failed: ${e.message}`); det = { done: false, detail: 'detect error — will attempt' }; }
    if (det.done) { skip(`already done — ${det.detail}`); summary.push([ph.id, 'skipped']); continue; }
    if (det.detail) info(det.detail);
    if (ph.gate && !args.yes) {
      if (!await confirm(`Run "${ph.title}"?`, true)) { warn('skipped by operator'); summary.push([ph.id, 'declined']); continue; }
    }
    try {
      await ph.run(ctx);
      summary.push([ph.id, 'done']);
    } catch (e) {
      bad(`${ph.id} failed: ${e.message}`);
      summary.push([ph.id, 'FAILED']);
      // every later phase talks to the box, so a failed connect cannot be worked around
      if (ph.fatal) { bad('cannot safely continue past this failed phase'); break; }
      if (!await confirm('Continue with the remaining phases anyway?', false)) break;
    }
  }

  hdr('Summary');
  for (const [id, st] of summary) {
    const c = st === 'FAILED' ? C.red : st === 'declined' ? C.yel : C.grn;
    console.log(`  ${c}${st.padEnd(8)}${C.r} ${id}`);
  }
  const failed = summary.filter(([, st]) => st === 'FAILED').length;
  const acted = summary.filter(([, st]) => st === 'done').length;
  // On a re-run of a fully-provisioned kit only connect/config/verify act (config is
  // laptop-side regeneration, verify is read-only) — so nothing on the box changed.
  const boxActed = summary.some(([id, st]) => st === 'done' && !['connect', 'config', 'verify'].includes(id));
  console.log('');
  if (failed) bad(`${failed} phase(s) failed — see above.`);
  else if (!boxActed) ok(`kit ${ctx.kit} was already fully provisioned — nothing on the box changed.`);
  else ok(`kit ${ctx.kit}: ${acted} phase(s) applied.`);
  RL.close();
}

mainWizard().catch(e => { console.error(`\n${C.red}FATAL:${C.r} ${e.message}`); try { RL && RL.close(); } catch {} process.exit(1); });
