#!/usr/bin/env node
'use strict';
/**
 * Read-only ThingsBoard inspector. Nothing here writes.
 *
 *   node provisioning/probe-tb.js profiles                 list device profiles
 *   node provisioning/probe-tb.js gateways                 every gateway-ish device + all its attributes
 *   node provisioning/probe-tb.js device <name>            telemetry keys, latest values, attributes
 *   node provisioning/probe-tb.js fleet <HWID>             the ECO_<HWID>_* device set
 *   node provisioning/probe-tb.js dump-attrs <dir>         save every gateway's big attributes to files
 *
 * This is how the P-Flow register map and the fleet's naming/telemetry conventions were
 * recovered in the first place -- tb-gateway stores connector configs as device
 * attributes, so a decommissioned gateway's config survives in ThingsBoard long after
 * the hardware is gone. See docs/RESI_MIGRATION.md.
 *
 * Credentials come from ../ECO-TB/.env (or .env.local, or $ECO_TB_ENV).
 */

const fs = require('fs');
const path = require('path');

const GATEWAY_PROFILES = ['IoT Gateway', 'Gateway', 'AS Gateway', 'Gateway VR', 'IoT Gateway Device'];
/** Produced by ThingsBoard rule chains, not by any gateway. */
const ALARM_KEYS = new Set(['criticalAlarmsCount', 'majorAlarmsCount', 'minorAlarmsCount', 'warningAlarmsCount']);

function loadEnv() {
  const candidates = [
    process.env.ECO_TB_ENV,
    path.resolve(__dirname, '../../ECO-TB/.env'),
    path.resolve(__dirname, '../.env.local'),
  ].filter(Boolean);
  for (const p of candidates) {
    if (!fs.existsSync(p)) continue;
    const env = {};
    for (const line of fs.readFileSync(p, 'utf8').split(/\r?\n/)) {
      const m = line.match(/^\s*([A-Z_]+)\s*=\s*(.*)$/);
      if (m) env[m[1]] = m[2].trim();
    }
    if (env.TB_BASE_URL && env.TB_USERNAME && env.TB_PASSWORD) return env;
  }
  throw new Error(`No ThingsBoard credentials found. Looked in:\n  ${candidates.join('\n  ')}`);
}

const env = loadEnv();
const BASE = env.TB_BASE_URL.replace(/\/+$/, '');
let TOKEN = null;

async function req(method, urlPath, body, retries = 4) {
  let lastErr;
  for (let i = 0; i < retries; i++) {
    try {
      const res = await fetch(`${BASE}${urlPath}`, {
        method,
        headers: {
          'Content-Type': 'application/json',
          ...(TOKEN ? { 'X-Authorization': `Bearer ${TOKEN}` } : {}),
        },
        body: body ? JSON.stringify(body) : undefined,
      });
      const text = await res.text();
      if (!res.ok) {
        const e = new Error(`HTTP ${res.status} ${urlPath}: ${text.slice(0, 300)}`);
        e.status = res.status;
        throw e;
      }
      return text ? JSON.parse(text) : null;
    } catch (e) {
      lastErr = e;
      if (e.status) throw e;
      await new Promise((r) => setTimeout(r, 700 * (i + 1)));   // transient DNS/network
    }
  }
  throw lastErr;
}

const login = async () => {
  TOKEN = (await req('POST', '/api/auth/login', {
    username: env.TB_USERNAME, password: env.TB_PASSWORD,
  })).token;
};

const allDevices = () => req('GET', '/api/tenant/devices?pageSize=1000&page=0');

async function showDevice(name) {
  let dev;
  try {
    dev = await req('GET', `/api/tenant/devices?deviceName=${encodeURIComponent(name)}`);
  } catch (e) {
    if (e.status === 404) { console.log(`${name}: NOT FOUND`); return; }
    throw e;
  }
  console.log(`## ${name}`);
  console.log(`   profile: ${dev.type}   id: ${dev.id.id}   created: ${new Date(dev.createdTime).toISOString()}`);
  console.log(`   additionalInfo: ${JSON.stringify(dev.additionalInfo)}`);

  const keys = await req('GET', `/api/plugins/telemetry/DEVICE/${dev.id.id}/keys/timeseries`);
  const real = keys.filter((k) => !ALARM_KEYS.has(k));
  console.log(`   telemetry: ${real.length} real keys (+${keys.length - real.length} rule-chain alarm counters)`);
  if (real.length) {
    const vals = await req(
      'GET',
      `/api/plugins/telemetry/DEVICE/${dev.id.id}/values/timeseries?keys=${encodeURIComponent(real.join(','))}`
    );
    for (const k of real) {
      const v = vals[k] && vals[k][0];
      console.log(`     ${k.padEnd(28)} = ${String(v && v.value).padEnd(22)} @ ${v ? new Date(v.ts).toISOString() : '-'}`);
    }
  }
  const attrs = await req('GET', `/api/plugins/telemetry/DEVICE/${dev.id.id}/values/attributes`);
  console.log(`   attributes: ${attrs.length}`);
  for (const a of attrs) {
    const s = typeof a.value === 'string' ? a.value : JSON.stringify(a.value);
    console.log(`     ${a.key} = ${s.length > 160 ? `<${s.length} chars>` : s}`);
  }
  console.log();
}

const isGatewayish = (d) => (d.additionalInfo || {}).gateway || GATEWAY_PROFILES.includes(d.type);

async function showGateways(dumpDir) {
  const all = await allDevices();
  const gws = all.data.filter(isGatewayish);
  console.log(`# ${all.totalElements} devices total, ${gws.length} gateway-ish\n`);
  if (dumpDir) fs.mkdirSync(dumpDir, { recursive: true });

  for (const d of gws) {
    console.log(`########## ${d.name}  [profile: ${d.type}]`);
    console.log(`   id: ${d.id.id}   created: ${new Date(d.createdTime).toISOString()}`);
    for (const scope of ['CLIENT_SCOPE', 'SERVER_SCOPE', 'SHARED_SCOPE']) {
      let attrs;
      try {
        attrs = await req('GET', `/api/plugins/telemetry/DEVICE/${d.id.id}/values/attributes/${scope}`);
      } catch (e) { console.log(`   ${scope}: error ${e.message.slice(0, 80)}`); continue; }
      if (!attrs.length) { console.log(`   ${scope}: (none)`); continue; }
      console.log(`   ${scope}: ${attrs.length} attrs`);
      for (const a of attrs) {
        const s = typeof a.value === 'string' ? a.value : JSON.stringify(a.value);
        if (s.length > 200) {
          console.log(`     - ${a.key}  <${s.length} chars>`);
          if (dumpDir) {
            const f = path.join(dumpDir, `${d.name.replace(/[^\w.-]/g, '_')}__${scope}__${a.key.replace(/[^\w.-]/g, '_')}.json`);
            fs.writeFileSync(f, s);
            console.log(`         -> ${path.basename(f)}`);
          }
        } else {
          console.log(`     - ${a.key} = ${s}`);
        }
      }
    }
    console.log();
  }
  if (dumpDir) console.log(`Attribute dumps written to ${dumpDir}`);
}

async function main() {
  const [cmd, arg] = process.argv.slice(2);
  await login();

  switch (cmd) {
    case 'profiles': {
      const page = await req('GET', '/api/deviceProfileInfos?pageSize=200&page=0');
      console.log(`# ${page.totalElements} device profiles`);
      for (const p of page.data) console.log(`  ${p.name}`);
      break;
    }
    case 'gateways':
      await showGateways(null);
      break;
    case 'dump-attrs':
      if (!arg) throw new Error('dump-attrs needs an output directory');
      await showGateways(path.resolve(arg));
      break;
    case 'device':
      if (!arg) throw new Error('device needs a device name');
      await showDevice(arg);
      break;
    case 'fleet': {
      if (!arg) throw new Error('fleet needs a HWID');
      for (const sfx of ['PF1', 'PF2', 'PF3', 'PF4', 'TS1', 'TS2', 'gw', 'LTE']) {
        await showDevice(`ECO_${arg}_${sfx}`);
      }
      break;
    }
    default:
      console.error('usage: node probe-tb.js <profiles|gateways|dump-attrs <dir>|device <name>|fleet <HWID>>');
      process.exit(2);
  }
}

main().catch((e) => { console.error(`FAILED: ${e.message}`); process.exit(1); });
