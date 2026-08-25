'use strict';
/*
 * tui.js — guided RESI -> ECO migration wizard.
 *
 * A line-based, interactive installer that walks a fresh (reflashed) RESI box all
 * the way to the ECO stack, OR re-runs against an already-migrated box and skips
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
const readline = require('readline');
const { spawn } = require('child_process');
const cfgLib = require('./lib/config');
const ssh = require('./lib/ssh');
const { TB } = require('./lib/tb');

// ---------- constants ----------
const REPO = path.join(__dirname, '..', '..');  // ECO-IOT-GW
const PROV = path.join(__dirname, '..');        // provisioning
const CACHE = path.join(__dirname, 'cache');
const OUT = path.join(__dirname, 'out');
const BOXDIR = path.join(__dirname, 'box');
const SD_PS1 = path.join(REPO, 'tools', 'sd.ps1');
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
    else if (t === '--flash') a.flash = true;
    else if (t === '--image') a.image = argv[++i];
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
// quiet captured run (for detection)
function sh(ctx, cmd, boxOverride) { return ssh.run(boxOverride || ctx.box, cmd, authFor(ctx)); }
// streaming run (for actions the operator should watch)
function stream(ctx, cmd, boxOverride) { return ssh.runStream(boxOverride || ctx.box, cmd, authFor(ctx), dimw); }
// scp a local file to the box
function scp(ctx, local, remote, boxOverride) {
  const r = ssh.put(boxOverride || ctx.box, local, remote, authFor(ctx));
  if (r.code !== 0) throw new Error(`scp ${path.basename(local)} failed: ${(r.stderr || '').trim().slice(0, 200)}`);
}
// reachability check for a specific user/host/auth
function reachable(cfg, host, user, auth) {
  const r = ssh.run({ host, user }, 'true', { ...auth });
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

// Run a PowerShell script with literal argv (no shell:true - that mangles paths/quotes).
function ps(args) {
  return new Promise(res => {
    const proc = spawn('powershell.exe', ['-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', ...args],
      { stdio: ['ignore', 'pipe', 'pipe'] });
    let out = '';
    const f = b => { out += b.toString(); dimw(b.toString()); };
    proc.stdout.on('data', f); proc.stderr.on('data', f);
    proc.on('close', code => res({ code, out }));
    proc.on('error', e => res({ code: 1, out: String(e.message) }));
  });
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

function resiImage(ctx) {
  const p = ctx.args.image || ctx.cfg.resiImage || '';
  if (!p) throw new Error('no RESI image configured - set RESI_IMAGE in .env or pass --image <path>');
  return p;
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
  throw new Error('box unreachable on every path (cable/mDNS/manual)');
}

// ---------- laptop cable-adapter DHCP renew (Windows) ----------
async function renewCableAdapter() {
  if (os.platform() !== 'win32') { info('renew the laptop cable adapter (DHCP) so it drops any stale default route'); return; }
  step('renewing laptop cable adapter (drops stale default route)…');
  const psl = [
    "$if = Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -like '10.10.10.*' } | Select-Object -First 1",
    "if ($if) { $a=(Get-NetAdapter -InterfaceIndex $if.InterfaceIndex).Name; ipconfig /release $a | Out-Null; ipconfig /renew $a | Out-Null; Write-Output ('renewed '+$a) } else { Write-Output 'no 10.10.10.x adapter' }",
  ].join('; ');
  await local('powershell', ['-NoProfile', '-Command', shq(psl).replace(/^'|'$/g, '"')]);
}

// =====================================================================
// PHASES
// =====================================================================
const PHASES = [
  // ---------------- 0a. Flash the card ----------------
  // Opt-in only: without --flash this is skipped, so re-running the wizard against a
  // live box can never wipe it. Delegates to tools/sd.ps1 -Action flash, which releases
  // the reader from WSL, picks the one disk big enough for the image, and drives
  // win/Restore-Card.ps1 (system/boot-disk guards; its typed prompt bypassed with -Yes
  // because this phase already made the operator type ERASE).
  {
    id: 'flash', title: 'Laptop - write the RESI image to the SD card (DESTRUCTIVE)',
    async detect(ctx) {
      if (!ctx.args.flash) return { done: true, detail: 'not requested (pass --flash to reimage the card)' };
      const img = resiImage(ctx);
      if (!fs.existsSync(img)) throw new Error('image not found: ' + img);
      const gb = (fs.statSync(img).size / 1e9).toFixed(1);
      return { done: false, detail: 'will overwrite the card with ' + img + ' (' + gb + ' GB)' };
    },
    async run(ctx) {
      if (os.platform() !== 'win32') throw new Error('--flash is Windows-only (uses tools/sd.ps1)');
      const img = resiImage(ctx);

      // Show what is about to be destroyed, read off the card itself, so the operator
      // confirms against real content rather than just a disk number.
      step('inspecting the card currently in the reader...');
      await ps([SD_PS1, '-Action', 'attach']);
      const st = await ps([SD_PS1, '-Action', 'status']);
      const host = (st.out.match(/card hostname:\s*(\S+)/) || [])[1];
      warn(host ? 'the card in the reader is "' + host + '" - it will be ERASED'
                : 'could not identify the card contents');

      if (!ctx.args.yes) {
        const t = (await ask('  type ERASE to overwrite the card with the RESI image: ')).trim();
        if (t !== 'ERASE') throw new Error('aborted by operator');
      }
      const r = await ps([SD_PS1, '-Action', 'flash', '-Image', img, '-Yes']);
      if (r.code !== 0) throw new Error('flash failed');
      ok('RESI image written to the card');
    },
  },

  // ---------------- 0b. Connect ----------------
  // Was a pre-loop step; it is a phase now so it can run *after* a flash and wait for
  // the freshly imaged box to finish booting instead of failing immediately.
  {
    id: 'connect', title: 'Connect - find the box and pick an auth path', fatal: true,
    async detect(ctx) {
      if (ctx.connected) return { done: true, detail: ctx.box.user + '@' + ctx.box.host };
      return { done: false, detail: 'probing cable / mDNS' };
    },
    async run(ctx) {
      const waitMin = Number.isFinite(ctx.args.wait) ? ctx.args.wait : (ctx.args.flash ? 10 : 2);
      if (ctx.args.flash && !ctx.args.yes) {
        await ask('  move the card into the gateway, connect Ethernet, power it on, then press Enter... ');
      }
      const deadline = Date.now() + waitMin * 60000;
      for (let attempt = 1; ; attempt++) {
        try {
          await bootstrap(ctx, false);
          ctx.connected = true;
          return;
        } catch (e) {
          const left = Math.round((deadline - Date.now()) / 1000);
          if (left <= 0) {
            // out of patience: let the operator name the address by hand
            await bootstrap(ctx, true);
            ctx.connected = true;
            return;
          }
          info('box not up yet (attempt ' + attempt + ') - retrying, ' + left + 's left');
          await sleep(10000);
        }
      }
    },
  },

  // ---------------- 1. Networking ----------------
  {
    id: 'net', title: 'Networking — stable 10.10.10.1 cable link',
    async detect(ctx) {
      // done when eth0 carries 10.10.10.1, the SIM-forward guard is present, and the
      // no-gateway dnsmasq conf exists (so the laptop keeps its own route).
      const r = sh(ctx, 'ip -4 addr show eth0 2>/dev/null | grep -q "10.10.10.1/" && echo IP; ' +
        (ctx.box.user === 'ecoadmin' ? 'sudo -n ' : `echo ${shq(ctx.cfg.box.password)} | sudo -S -p '' `) +
        'nft list table inet eco_guard >/dev/null 2>&1 && echo NFT; ' +
        'test -f /etc/NetworkManager/dnsmasq-shared.d/eco-no-gateway.conf && echo CONF');
      const done = /IP/.test(r.stdout) && /NFT/.test(r.stdout) && /CONF/.test(r.stdout);
      return { done, detail: done ? `eth0=10.10.10.1, SIM-forward blocked, no-gateway DHCP` : (ctx.box.host === '10.10.10.1' ? 'partial config on 10.10.10.1 — will reapply' : `box at ${ctx.box.host} — will lay down 10.10.10.1`) };
    },
    async run(ctx) {
      const src = path.join(PROV, 'setup-direct-ethernet.sh');
      scp(ctx, src, '/tmp/setup-direct-ethernet.sh');
      step('applying networking (detached — it drops eth0 as it switches over)…');
      // run detached so dropping the current link doesn't kill our SSH mid-write
      await stream(ctx, asRoot(ctx, 'chmod +x /tmp/setup-direct-ethernet.sh && nohup /tmp/setup-direct-ethernet.sh >/tmp/eco-net.log 2>&1 & echo started'));
      info('waiting 20s for eth0 to settle on 10.10.10.1 …');
      await sleep(20000);
      await renewCableAdapter();
      await sleep(4000);
      // reconnect on the cable IP (same user)
      ctx.box.host = '10.10.10.1';
      for (let i = 1; i <= 10; i++) {
        if (sh(ctx, 'true').code === 0) { ok('reconnected on 10.10.10.1'); return; }
        await sleep(3000);
      }
      throw new Error('box did not come back on 10.10.10.1 after networking apply');
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
    gate: true,
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

  // ---------------- 4. Stand down RESI ----------------
  {
    id: 'standdown', title: 'Box — stand down RESI (reversible)', gate: true,
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
    id: 'artifacts', title: 'Laptop — build/verify offline artifacts',
    async detect(ctx) {
      if (ctx.args.skipArtifacts) return { done: true, detail: '--skip-artifacts' };
      const need = artifactPaths(ctx);
      const missing = Object.entries(need).filter(([, p]) => !fs.existsSync(p)).map(([k]) => k);
      return { done: missing.length === 0, detail: missing.length ? `missing: ${missing.join(', ')}` : 'all artifacts cached' };
    },
    async run(ctx) {
      const need = artifactPaths(ctx);
      // frontend build -> dist tgz
      if (!fs.existsSync(need.dist)) {
        if (!fs.existsSync(path.join(REPO, 'frontend', 'dist', 'index.html'))) {
          step('building frontend (npm run build)…');
          await mustLocal('npm', ['run', 'build'], path.join(REPO, 'frontend'), 'npm run build');
        }
        step('packing dist…');
        await packTgz(need.dist, path.join(REPO, 'frontend', 'dist'), [], ['.'], 'pack dist');
      }
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
      ok('artifacts ready');
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
    id: 'config', title: 'Laptop — build gateway config (present units)',
    async detect() { return { done: false, detail: 'always regenerate from the live scan' }; },
    async run(ctx) {
      const site = path.join(PROV, 'sites', `${ctx.kit}.json`);
      if (!fs.existsSync(site)) throw new Error(`site file missing: ${site}`);
      const present = (ctx.store.presentUnits || [88]).join(',');
      step(`generating tb_gateway.json + modbus.json (units ${present}, DEBUG)…`);
      const env = { ...process.env, ECO_MODBUS_PORT: '/dev/meterbus', MSYS_NO_PATHCONV: '1' };
      await new Promise(res => {
        const p = spawn('node', ['build-gw-config.js', ctx.kit, site, present], { cwd: __dirname, shell: true, env, stdio: ['ignore', 'pipe', 'pipe'] });
        p.stdout.on('data', dimw); p.stderr.on('data', dimw); p.on('close', res);
      });
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
      scp(ctx, tgz, '/tmp/tailscale.tgz');
      scp(ctx, path.join(BOXDIR, 'install-tailscale.sh'), '/tmp/install-tailscale.sh');
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
      const active = /active/.test(r.stdout);
      const secretOk = /SECRETOK/.test(r.stdout);
      return { done: active && secretOk, detail: active ? (secretOk ? 'backend active, per-device secrets set' : 'active but on default secrets') : 'not installed' };
    },
    async run(ctx) {
      const need = artifactPaths(ctx);
      step('uploading secrets script + console artifacts…');
      scp(ctx, path.join(PROV, 'setup-secrets.sh'), '/tmp/setup-secrets.sh');
      scp(ctx, path.join(BOXDIR, 'install-webconsole.sh'), '/tmp/install-webconsole.sh');
      scp(ctx, need.backend, '/tmp/webconsole-backend.tgz');
      scp(ctx, need.wheels, '/tmp/webconsole-wheelhouse.tgz');
      scp(ctx, need.dist, '/tmp/webconsole-dist.tgz');
      step('generating per-device secrets…');
      await stream(ctx, asRoot(ctx, 'chmod +x /tmp/setup-secrets.sh && /tmp/setup-secrets.sh'));
      step('installing web console (systemd, 0.0.0.0:80)…');
      const r = await stream(ctx, asRoot(ctx, '/tmp/install-webconsole.sh /tmp/webconsole-backend.tgz /tmp/webconsole-wheelhouse.tgz /tmp/webconsole-dist.tgz'));
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
      const good = /active/.test(active) && /YES/.test(wired);
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
  fs.writeFileSync(p, ['fastapi>=0.109.0', 'uvicorn[standard]>=0.27.0', 'python-multipart>=0.0.6',
    'python-jose[cryptography]>=3.3.0', 'bcrypt>=4.1.0', 'pydantic>=2.5.0', 'pydantic-settings>=2.1.0',
    'aiosqlite>=0.19.0', 'docker>=7.0.0', 'pyyaml>=6.0.1', 'websockets>=12.0', 'httpx>=0.26.0', 'phonenumbers>=8.13.0'].join('\n') + '\n');
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
    info('ecoadmin web-login password already recorded');
    recordCredentials(ctx);   // refresh the shared ledger anyway
    return;
  }
  const pw = Array.from({ length: 16 }, () => 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghikmnpqrstuvwxyz23456789'[Math.floor(Math.random() * 54)]).join('');
  await stream(ctx, asRoot(ctx, `echo 'ecoadmin:${pw}' | chpasswd`));
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
async function mainWizard() {
  const args = parseArgs(process.argv);
  if (!args.kit) { console.error('usage: node tui.js --kit <DBKIT..> [--flash [--image <img>]] [--host <addr>] [--wait <min>] [--yes] [--skip-artifacts] [--skip-tb] [--no-lte]'); process.exit(2); }
  const cfg = cfgLib.load();
  const miss = cfgLib.requireKeys(cfg, ['tb']);
  if (miss.length) { console.error(`missing config: ${miss.join(', ')} (see .env.example)`); process.exit(2); }

  RL = readline.createInterface({ input: process.stdin, output: process.stdout });
  RL.on('close', () => { RL_CLOSED = true; });
  const ctx = { cfg, kit: args.kit, args, box: { host: '10.10.10.1', user: 'ecoadmin' }, store: {} };

  console.log(`${C.b}${C.mag}ECO migration wizard${C.r}  kit=${C.b}${args.kit}${C.r}  ${args.yes ? C.yel + '(auto-yes)' + C.r : ''}`);
  console.log(`${C.dim}Each phase self-detects: already-done steps are skipped automatically.${C.r}`);

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
      if (ph.fatal) { bad('cannot continue without a connection to the box'); break; }
      if (!await confirm('Continue with the remaining phases anyway?', false)) break;
    }
  }

  hdr('Summary');
  for (const [id, st] of summary) {
    const c = st === 'FAILED' ? C.red : st === 'declined' ? C.yel : C.grn;
    console.log(`  ${c}${st.padEnd(8)}${C.r} ${id}`);
  }
  RL.close();
}

mainWizard().catch(e => { console.error(`\n${C.red}FATAL:${C.r} ${e.message}`); try { RL && RL.close(); } catch {} process.exit(1); });
