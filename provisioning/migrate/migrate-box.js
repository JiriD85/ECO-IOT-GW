'use strict';
/*
 * migrate-box — guided RESI -> ECO in-place migration over SSH.
 *
 * Usage:
 *   node migrate-box.js --kit DBKIT24EU-0010 [--host <ssh-target>] [--apply]
 *
 * Phases:
 *   1 preflight  (read-only) — SSH in, identify the box, snapshot RESI state
 *   2 resolve    (read-only) — resolve the kit in ThingsBoard -> devices + HWID
 *   3 plan       (read-only) — compute the exact TB + box changes, print them
 *   4+ apply      (writes)    — gated behind --apply; implemented incrementally
 *
 * Without --apply nothing is changed on TB or the box: it is a full dry-run.
 * Read-only phases need only TB creds + box reachability; --apply needs the rest.
 */
const path = require('path');
const fs = require('fs');
const cfgLib = require('./lib/config');
const ssh = require('./lib/ssh');
const { TB } = require('./lib/tb');

// ---------- tiny ANSI helpers (no dependency) ----------
const C = { r: '\x1b[0m', b: '\x1b[1m', dim: '\x1b[2m', red: '\x1b[31m', grn: '\x1b[32m', yel: '\x1b[33m', cyn: '\x1b[36m' };
const h1 = s => console.log(`\n${C.b}${C.cyn}== ${s} ==${C.r}`);
const ok = s => console.log(`  ${C.grn}✓${C.r} ${s}`);
const info = s => console.log(`  ${C.dim}·${C.r} ${s}`);
const warn = s => console.log(`  ${C.yel}!${C.r} ${s}`);
const bad = s => console.log(`  ${C.red}✗${C.r} ${s}`);
const change = s => console.log(`  ${C.yel}→${C.r} ${s}`);

function parseArgs(argv) {
  const a = { apply: false };
  for (let i = 2; i < argv.length; i++) {
    const t = argv[i];
    if (t === '--apply') a.apply = true;
    else if (t === '--kit') a.kit = argv[++i];
    else if (t === '--host') a.host = argv[++i];
    else if (t === '--user') a.user = argv[++i];
    else if (t === '--key') a.key = argv[++i];
    else if (t === '--phase') a.phase = argv[++i];
    else if (t === '--revert-tb') a.revertTb = true;
    else if (t === '--force') a.force = true;
    else if (t === '--yes') a.yes = true;
  }
  return a;
}

function boxAuthOpts(cfg, box) {
  // Two-stage auth: bootstrap connects as `resi` with the fleet password; only
  // after box-apply installs our key + `ecoadmin` do we switch to key auth.
  // So key auth is used ONLY when the target user is ecoadmin.
  if (box && box.user === 'ecoadmin' && cfg.box.keyPath && fs.existsSync(cfg.box.keyPath)) return { keyPath: cfg.box.keyPath };
  if (process.env.ECO_NONINTERACTIVE === '1') return { askpassPassword: cfg.box.password };
  return { password: cfg.box.password, interactive: true };
}

// ---------- phase 1: preflight ----------
function preflight(cfg, box) {
  h1('Phase 1 — preflight (read-only)');
  const auth = boxAuthOpts(cfg, box);
  // Tolerate boot/fsck flapping: retry the first contact until the box answers.
  const waitTries = parseInt(process.env.ECO_WAIT_TRIES || '15', 10);
  for (let i = 1; i <= waitTries; i++) {
    const t = ssh.run(box, 'true', auth);
    if (t.code === 0) break;
    if (i === 1) info(`waiting for ${box.host} to answer (boot/fsck can take a minute)…`);
    if (i === waitTries) { bad(`SSH to ${box.user}@${box.host} unreachable after ${waitTries} tries`); throw new Error(t.stderr || 'ssh unreachable'); }
    Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 8000); // portable 8s sleep
  }
  const probe = [
    'echo HOSTNAME=$(hostname)',
    'echo UPTIME=$(uptime -p 2>/dev/null | tr -d "\\n")',
    'echo ARCH=$(dpkg --print-architecture)',
    "echo MEMFREE=$(LC_ALL=C free -m | awk '/^Mem:/{print $7}')",
    "echo DISKFREE=$(LC_ALL=C df -m / | awk 'NR==2{print $4}')",
    'echo PY=$(python3 --version 2>&1)',
    'echo DOCKER=$(command -v docker || echo none)',
    'echo BUSHOLDER=$(sudo fuser /dev/ttyACM0 2>/dev/null | tr -d " \\n" || echo free)',
    'for s in apache2 ser2net pm2-resi grafana-server mariadb mosquitto snmpd; do echo SVC:$s=$(systemctl is-active $s 2>/dev/null); done',
  ].join('; ');
  const r = ssh.run(box, probe, auth);
  if (r.code !== 0) { bad(`SSH to ${box.user}@${box.host} failed (code ${r.code})`); throw new Error(r.stderr || 'ssh failed'); }
  const facts = {};
  const svc = {};
  for (const line of r.stdout.split(/\r?\n/)) {
    const m = line.match(/^([A-Z]+)=(.*)$/);
    if (m) facts[m[1]] = m[2];
    const s = line.match(/^SVC:([^=]+)=(.*)$/);
    if (s) svc[s[1]] = s[2];
  }
  facts.services = svc;
  ok(`reached ${C.b}${facts.HOSTNAME}${C.r} (${facts.ARCH}, ${facts.PY})`);
  info(`uptime ${facts.UPTIME || '?'} · mem free ${facts.MEMFREE}MB · disk free ${facts.DISKFREE}MB`);
  info(`docker: ${facts.DOCKER === 'none' ? C.yel + 'absent' + C.r : facts.DOCKER}`);
  const active = Object.entries(svc).filter(([, v]) => v === 'active').map(([k]) => k);
  if (active.length) warn(`RESI services active: ${active.join(', ')}`);
  if (facts.BUSHOLDER && facts.BUSHOLDER !== 'free') warn(`/dev/ttyACM0 (meter bus) held by PID ${facts.BUSHOLDER} — must stop the RESI app to free it`);
  return facts;
}

// ---------- phase 2: resolve ----------
const MAX_KIT_DEVICES = parseInt(process.env.ECO_MAX_KIT_DEVICES || '10', 10); // normal kit ~7; >10 signals a misconfigured/wrong asset

async function resolve(cfg, kitCode, opts = {}) {
  h1('Phase 2 — resolve kit in ThingsBoard (read-only)');
  const tb = new TB(cfg, { apply: false });
  await tb.login();
  const asset = await tb.findKit(kitCode);
  if (!asset) throw new Error(`kit asset ${kitCode} not found`);
  ok(`asset ${C.b}${asset.name}${C.r} (${asset.id.id})`);
  const devices = await tb.kitDevices(asset.id.id);
  // guardrail: too many child devices => likely the wrong/misconfigured asset
  if (devices.length > MAX_KIT_DEVICES) {
    bad(`kit ${kitCode} has ${devices.length} device entities (limit ${MAX_KIT_DEVICES}) — likely misconfigured or the wrong asset`);
    if (!opts.force) throw new Error(`refusing to proceed: ${devices.length} > ${MAX_KIT_DEVICES} devices under ${kitCode} (re-run with --force to override if you are sure)`);
    warn(`--force set: proceeding despite ${devices.length} devices`);
  }
  const hwidm = (devices.map(d => d.name).find(n => /_gw$/.test(n)) || '').match(/^ECO_(.+)_gw$/);
  const hwid = hwidm ? hwidm[1] : null;
  ok(`HWID ${C.b}${hwid || '??'}${C.r} · ${devices.length} child devices`);
  // annotate with profile names + gw creds
  for (const d of devices) d.profileName = await tb.deviceProfileName(d.profileId);
  const gw = devices.find(d => /_gw$/.test(d.name));
  let gwCred = null;
  if (gw) { try { const c = await tb.deviceCredentials(gw.id); gwCred = c.credentialsType; } catch {} }
  const pfGw = await tb.findProfile('P-Flow D116 GW');
  const tsGw = await tb.findProfile('Temperature Sensor GW');
  const ecoGw = await tb.findProfile('ECO GW');
  const cf = pfGw ? await tb.calculatedFields(pfGw.id.id) : [];
  console.log('');
  for (const d of devices) {
    const tag = /_gw$/.test(d.name) ? (d.gateway ? 'gateway' : C.yel + 'NOT gateway' + C.r) : '';
    console.log(`    ${d.name.padEnd(34)} ${String(d.profileName).padEnd(20)} ${tag}`);
  }
  info(`_gw credentials: ${gwCred || 'unknown'}`);
  info(`profile "ECO GW": ${ecoGw ? ecoGw.id.id : C.red + 'MISSING' + C.r}`);
  info(`profile "P-Flow D116 GW": ${pfGw ? pfGw.id.id + ` (${cf.length} calculated fields)` : C.red + 'MISSING' + C.r}`);
  info(`profile "Temperature Sensor GW": ${tsGw ? tsGw.id.id : C.red + 'MISSING' + C.r}`);
  return { asset, devices, hwid, gw, gwCred, pfGw, tsGw, ecoGw, calcFields: cf };
}

// ---------- phase 3: plan ----------
function plan(cfg, facts, model) {
  h1('Phase 3 — plan (dry-run; nothing changed)');
  console.log(`  ${C.b}ThingsBoard changes:${C.r}`);
  if (model.gw && (model.gw.profileName !== 'ECO GW' || !model.gw.gateway)) change(`${model.gw.name}: reprofile → ECO GW + gateway=true, capture ${model.gwCred || 'MQTT_BASIC'} creds for tb-gateway`);
  for (const d of model.devices.filter(d => /_PF\d$/.test(d.name)))
    if (d.profileName !== 'P-Flow D116 GW') change(`${d.name}: reprofile ${d.profileName} → P-Flow D116 GW (enables ${model.calcFields.length} calculated fields)`);
  for (const d of model.devices.filter(d => /_TS[12]$/.test(d.name)))
    if (d.profileName !== 'Temperature Sensor GW') change(`${d.name}: reprofile ${d.profileName} → Temperature Sensor GW`);
  const ts3 = model.devices.find(d => /_TS3$/.test(d.name));
  if (ts3) warn(`${ts3.name}: stray (no physical sensor) — left unfed`);
  change(`push modbus connector + general_configuration (MQTT ${cfg.mqtt.host}:${cfg.mqtt.port}) to ${model.gw ? model.gw.name : 'gateway device'}`);
  warn('PF unit IDs: only PF1 known — PF2–4 need an on-site Modbus scan (tool can run it once the bus is free)');

  console.log(`\n  ${C.b}Box changes (over SSH):${C.r}`);
  change('install our SSH key (ecoadmin), switch to key auth');
  change('mask (not delete) RESI stack + stop the RESIvmachine app to free /dev/ttyACM0');
  change(`install Docker (static ${cfg.docker.staticTgz ? path.basename(cfg.docker.staticTgz) : 'aarch64 tgz — set DOCKER_STATIC_TGZ'}) + load tb-gateway image`);
  change('deploy tb-gateway (Docker) with the connector config + gateway MQTT creds');
  change('deploy our web console (FastAPI systemd serving the built Vue directly, no nginx), per-device secrets');
  change(`join Tailscale (${cfg.tailscale.authkey ? 'authkey set' : C.yel + 'TS_AUTHKEY not set' + C.r})`);
  change('write /usr/local/sbin/eco-downgrade.sh (reverse everything) then reboot');
  console.log('');
}

function outDir() { const d = path.join(__dirname, 'out'); fs.mkdirSync(d, { recursive: true }); return d; }

// ---------- phase 4a: TB apply (reprofile + gateway flag) — reversible ----------
async function applyTB(cfg, model, kitCode) {
  h1('Phase 4a — ThingsBoard apply (reprofile + gateway flag)');
  if (!model.pfGw || !model.tsGw) throw new Error('GW profiles missing — cannot reprofile');
  const tb = new TB(cfg, { apply: true, onWrite: s => change(s) });
  await tb.login();

  // record revert state BEFORE changing anything — CUMULATIVE across re-runs so
  // the earliest-seen original profile is never lost by a second apply.
  const revertPath = path.join(outDir(), `${kitCode}.tb-revert.json`);
  const revert = fs.existsSync(revertPath) ? JSON.parse(fs.readFileSync(revertPath, 'utf8')) : { kit: kitCode, devices: [] };
  if (!revert.devices) revert.devices = [];
  const recorded = new Set(revert.devices.map(d => d.id));
  const targets = [];
  for (const d of model.devices) {
    if (/_PF\d$/.test(d.name) && d.profileName !== 'P-Flow D116 GW') targets.push({ d, profileId: model.pfGw.id.id, profileName: 'P-Flow D116 GW' });
    else if (/_TS[12]$/.test(d.name) && d.profileName !== 'Temperature Sensor GW') targets.push({ d, profileId: model.tsGw.id.id, profileName: 'Temperature Sensor GW' });
  }
  for (const t of targets) if (!recorded.has(t.d.id)) revert.devices.push({ id: t.d.id, name: t.d.name, origProfileId: t.d.profileId, origProfileName: t.d.profileName });
  if (model.gw) {
    if (!revert.gw) revert.gw = { id: model.gw.id, name: model.gw.name, origGateway: model.gw.gateway };
    if (revert.gw.origProfileId === undefined) { revert.gw.origProfileId = model.gw.profileId; revert.gw.origProfileName = model.gw.profileName; }
  }
  revert.when = new Date().toISOString();
  fs.writeFileSync(revertPath, JSON.stringify(revert, null, 2));
  info(`revert state saved: ${path.relative(process.cwd(), revertPath)} (${revert.devices.length} device originals)`);

  for (const t of targets) await tb.setDeviceProfile(t.d, t.profileId, t.profileName);
  // _gw: make it a gateway on the "ECO GW" profile
  if (model.gw) {
    if (!model.ecoGw) throw new Error('profile "ECO GW" not found — cannot reprofile the gateway device');
    if (model.gw.profileName !== 'ECO GW') await tb.setDeviceProfile(model.gw, model.ecoGw.id.id, 'ECO GW');
    if (!model.gw.gateway) await tb.setGatewayFlag(model.gw, true);
    // capture the gateway's MQTT credentials for the box's tb-gateway config
    const cred = await tb.deviceCredentials(model.gw.id);
    const gwmqtt = { deviceName: model.gw.name, credentialsType: cred.credentialsType, credentialsId: cred.credentialsId };
    if (cred.credentialsType === 'MQTT_BASIC' && cred.credentialsValue) {
      try { const v = JSON.parse(cred.credentialsValue); Object.assign(gwmqtt, { clientId: v.clientId || null, userName: v.userName || null, password: v.password || null }); } catch {}
    } else if (cred.credentialsType === 'ACCESS_TOKEN') {
      gwmqtt.accessToken = cred.credentialsId;
    }
    const credPath = path.join(outDir(), `${kitCode}.gw-mqtt.json`);
    fs.writeFileSync(credPath, JSON.stringify(gwmqtt, null, 2));
    try { fs.chmodSync(credPath, 0o600); } catch {}
    ok(`captured _gw ${cred.credentialsType} credentials → ${path.relative(process.cwd(), credPath)} (clientId=${gwmqtt.clientId || 'n/a'}, user=${gwmqtt.userName ? 'set' : 'n/a'}, pass=${gwmqtt.password ? 'set' : 'n/a'})`);
  }

  // verify
  console.log('');
  const dv = await tb.kitDevices(model.asset.id.id);
  let good = true;
  for (const d of dv) {
    const pn = await tb.deviceProfileName(d.profileId);
    const want = /_gw$/.test(d.name) ? 'ECO GW' : /_PF\d$/.test(d.name) ? 'P-Flow D116 GW' : /_TS[12]$/.test(d.name) ? 'Temperature Sensor GW' : null;
    if (want && pn !== want) { bad(`${d.name}: profile is ${pn}, expected ${want}`); good = false; }
    if (/_gw$/.test(d.name) && !d.gateway) { bad(`${d.name}: gateway flag not set`); good = false; }
  }
  if (good) ok('TB verify passed — profiles reassigned, gateway flag set');
  else throw new Error('TB verify failed');
  info(`to undo: node migrate-box.js --kit ${kitCode} --revert-tb`);
}

async function revertTB(cfg, kitCode) {
  h1('Revert ThingsBoard changes');
  const revertPath = path.join(outDir(), `${kitCode}.tb-revert.json`);
  if (!fs.existsSync(revertPath)) throw new Error(`no revert file: ${revertPath}`);
  const revert = JSON.parse(fs.readFileSync(revertPath, 'utf8'));
  const tb = new TB(cfg, { apply: true, onWrite: s => change(s) });
  await tb.login();
  for (const d of revert.devices) await tb.setDeviceProfile({ id: d.id, name: d.name }, d.origProfileId, d.origProfileName);
  if (revert.gw && revert.gw.origProfileId) await tb.setDeviceProfile({ id: revert.gw.id, name: revert.gw.name }, revert.gw.origProfileId, revert.gw.origProfileName);
  if (revert.gw && revert.gw.origGateway === false) await tb.setGatewayFlag({ id: revert.gw.id, name: revert.gw.name }, false);
  ok('reverted to recorded profiles/gateway flag');
}

async function main() {
  const args = parseArgs(process.argv);
  if (!args.kit) { console.error('usage: node migrate-box.js --kit <DBKIT..> [--host <ssh-target>] [--apply]'); process.exit(2); }
  const cfg = cfgLib.load();
  if (args.user) cfg.box.user = args.user;
  if (args.key) cfg.box.keyPath = args.key;
  // default to the stable direct-cable IP that setup-direct-ethernet.sh establishes
  const box = { host: args.host || process.env.ECO_BOX_HOST || '10.10.10.1', user: cfg.box.user };

  const missTb = cfgLib.requireKeys(cfg, ['tb']);
  if (missTb.length) { bad(`missing TB config: ${missTb.join(', ')} (see .env.example)`); process.exit(2); }

  // revert path — independent of the box
  if (args.revertTb) { await revertTB(cfg, args.kit); return; }

  console.log(`${C.b}migrate-box${C.r}  kit=${C.b}${args.kit}${C.r}  box=${box.user}@${box.host}  mode=${args.apply ? C.red + 'APPLY' + C.r : C.grn + 'dry-run' + C.r}`);

  const phase = args.phase || 'all';
  // preflight touches the box; skip it for TB-only work
  const facts = (phase === 'tb') ? null : preflight(cfg, box);
  if (phase === 'tb') info('phase=tb → skipping box preflight (not needed for ThingsBoard changes)');
  const model = await resolve(cfg, args.kit, { force: args.force });
  plan(cfg, facts, model);

  if (!args.apply) {
    console.log(`${C.dim}Dry-run complete. Re-run with --apply (optionally --phase tb) to execute.${C.r}`);
    return;
  }

  if (phase === 'tb' || phase === 'all') await applyTB(cfg, model, args.kit);
  if (phase === 'box' || phase === 'all') {
    h1('Phase 4b+ — box apply');
    warn('Box apply (key, mask RESI, Docker + tb-gateway + backend, Tailscale, connector push) is the next milestone.');
  }
}

main().catch(e => { console.error(`\n${C.red}FAILED:${C.r} ${e.message}`); process.exit(1); });
