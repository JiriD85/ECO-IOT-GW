#!/usr/bin/env node
'use strict';
/**
 * Clone an existing ThingsBoard IoT Gateway device's configuration onto a new one.
 *
 *   node provisioning/clone-gateway.js <source> <target>            # dry run
 *   node provisioning/clone-gateway.js <source> <target> --apply    # write to TB
 *
 * Copies the SOURCE device's SHARED-scope attributes (general_configuration, the connector
 * configs, active_connectors, logs/storage/grpc configuration, RemoteLoggingLevel, ...) onto
 * a newly created (or existing) TARGET device with device profile "IoT Gateway" and
 * additionalInfo.gateway = true -- i.e. a faithful clone of a working gateway like
 * pke_AT1100_iotgw01.
 *
 * The only value rewritten is the access token embedded in general_configuration.security:
 * it is set to the TARGET's own token (a clone must authenticate as itself, not the source).
 *
 * Dry run is the default on purpose: --apply writes to a live tenant with 700+ devices.
 */

const fs = require('fs');
const path = require('path');

const GATEWAY_PROFILE = 'IoT Gateway';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ---------------------------------------------------------------- credentials
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
    if (env.TB_BASE_URL && env.TB_USERNAME && env.TB_PASSWORD) return { env, source: p };
  }
  throw new Error(`No ThingsBoard credentials found. Looked in:\n  ${candidates.join('\n  ')}`);
}

// ---------------------------------------------------------------- REST client
class Tb {
  constructor(env) { this.base = env.TB_BASE_URL.replace(/\/+$/, ''); this.env = env; this.token = null; }
  async login() {
    const r = await this._raw('POST', '/api/auth/login', { username: this.env.TB_USERNAME, password: this.env.TB_PASSWORD });
    this.token = r.token;
  }
  async _raw(method, urlPath, body, retries = 3) {
    let lastErr;
    for (let i = 0; i < retries; i++) {
      try {
        const res = await fetch(`${this.base}${urlPath}`, {
          method,
          headers: { 'Content-Type': 'application/json', ...(this.token ? { 'X-Authorization': `Bearer ${this.token}` } : {}) },
          body: body === undefined ? undefined : JSON.stringify(body),
        });
        const text = await res.text();
        if (!res.ok) { const err = new Error(`HTTP ${res.status} ${method} ${urlPath}: ${text.slice(0, 400)}`); err.status = res.status; throw err; }
        return text ? JSON.parse(text) : null;
      } catch (e) { lastErr = e; if (e.status) throw e; await sleep(700 * (i + 1)); }
    }
    throw lastErr;
  }
  get(p) { return this._raw('GET', p); }
  post(p, b) { return this._raw('POST', p, b); }
  async findDeviceByName(name) {
    try { return await this.get(`/api/tenant/devices?deviceName=${encodeURIComponent(name)}`); }
    catch (e) { if (e.status === 404) return null; throw e; }
  }
  async findProfileIdByName(name) {
    const page = await this.get(`/api/deviceProfileInfos?pageSize=200&page=0&textSearch=${encodeURIComponent(name)}`);
    const hit = (page.data || []).find((p) => p.name === name);
    if (!hit) throw new Error(`Device profile "${name}" not found in this tenant.`);
    return hit.id;
  }
  async sharedAttributes(deviceId) {
    const arr = await this.get(`/api/plugins/telemetry/DEVICE/${deviceId}/values/attributes/SHARED_SCOPE`);
    const obj = {};
    for (const a of arr || []) obj[a.key] = a.value;
    return obj;
  }
  async accessToken(deviceId) {
    const creds = await this.get(`/api/device/${deviceId}/credentials`);
    if (creds.credentialsType !== 'ACCESS_TOKEN') throw new Error(`Device uses ${creds.credentialsType}, not ACCESS_TOKEN.`);
    return creds.credentialsId;
  }
}

// ---------------------------------------------------------------- main
async function main() {
  const args = process.argv.slice(2);
  const positionals = args.filter((a) => !a.startsWith('--'));
  const [sourceName, targetName] = positionals;
  const apply = args.includes('--apply');
  if (!sourceName || !targetName) {
    console.error('usage: node clone-gateway.js <sourceDevice> <targetDevice> [--apply]');
    process.exit(2);
  }

  const { env, source } = loadEnv();
  console.log(`credentials from : ${source}`);
  console.log(`thingsboard      : ${env.TB_BASE_URL}`);
  console.log(`clone            : "${sourceName}"  ->  "${targetName}"`);
  console.log();

  const tb = new Tb(env);
  await tb.login();

  const src = await tb.findDeviceByName(sourceName);
  if (!src) throw new Error(`Source device "${sourceName}" not found.`);
  const srcGateway = !!(src.additionalInfo && src.additionalInfo.gateway);
  console.log(`source device    : ${src.id.id}  (profile via id; gateway=${srcGateway})`);

  const srcShared = await tb.sharedAttributes(src.id.id);
  const keys = Object.keys(srcShared);
  console.log(`source SHARED    : ${keys.length} attributes`);
  for (const k of keys) {
    const v = srcShared[k];
    const size = typeof v === 'string' ? `${v.length} chars` : `${JSON.stringify(v).length} chars json`;
    console.log(`                   ${k}  (${size})`);
  }
  console.log();

  let existingTarget = await tb.findDeviceByName(targetName);
  if (existingTarget) console.log(`NOTE: target "${targetName}" already exists (id ${existingTarget.id.id}); it will be reused and its shared attrs overwritten.`);

  if (!apply) {
    console.log('\nDRY RUN -- nothing written. general_configuration that would be pushed');
    console.log('(access token will be replaced with the target device\'s own token):');
    console.log(JSON.stringify(srcShared.general_configuration, null, 2));
    console.log('\nRe-run with --apply to create the clone.');
    return;
  }

  // ---- create target device (or reuse)
  let target = existingTarget;
  if (!target) {
    const profileId = await tb.findProfileIdByName(GATEWAY_PROFILE);
    target = await tb.post('/api/device', {
      name: targetName,
      deviceProfileId: profileId,
      additionalInfo: { gateway: true, description: `clone of ${sourceName}` },
    });
    console.log(`created target   : ${target.id.id}`);
  }

  // ---- target's own access token
  const token = await tb.accessToken(target.id.id);
  console.log(`target token     : ${token}`);

  // ---- build the shared payload: copy source verbatim, rewrite only the per-gateway
  //      identity. Preserve the fleet's MQTT auth model (usernamePassword pke/<shared pw>);
  //      only the access token and clientId are unique per gateway.
  const payload = JSON.parse(JSON.stringify(srcShared));
  if (payload.general_configuration && payload.general_configuration.security) {
    const sec = payload.general_configuration.security;
    sec.accessToken = token;
    if ('clientId' in sec) sec.clientId = targetName.replace(/[^a-z0-9]/gi, '').toLowerCase();
  }
  // do not carry the source's own runtime bookkeeping if any slipped into SHARED
  for (const k of ['active', 'lastConnectTime', 'lastDisconnectTime', 'lastActivityTime', 'inactivityAlarmTime']) delete payload[k];

  await tb.post(`/api/plugins/telemetry/DEVICE/${target.id.id}/SHARED_SCOPE`, payload);
  console.log(`pushed SHARED    : ${Object.keys(payload).join(', ')}`);
  console.log('\nClone complete. Next: build docker-compose with this token and the right serial ports.');
}

main().catch((e) => { console.error(`\nFAILED: ${e.message}`); process.exit(1); });
