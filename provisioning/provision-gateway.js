#!/usr/bin/env node
'use strict';
/**
 * Provision one gateway end-to-end against ThingsBoard.
 *
 *   node provisioning/provision-gateway.js sites/<site>.json            # dry run
 *   node provisioning/provision-gateway.js sites/<site>.json --apply    # write to TB
 *   node provisioning/provision-gateway.js sites/<site>.json --apply --out ./out
 *
 * Dry run is the default on purpose: --apply creates a real device in a live tenant
 * that has 700+ production devices.
 *
 * What --apply does, in order:
 *   1. create the gateway device (device profile "IoT Gateway", additionalInfo.gateway
 *      = true), following the schema of the existing pke_AT1100_iotgw01
 *   2. read back its access token
 *   3. push general_configuration + the Modbus connector + active_connectors as SHARED
 *      attributes, so the gateway pulls its config down via remoteConfiguration
 *   4. write tb_gateway.yaml and modbus.json locally for first boot
 *
 * Order matters. Provision ThingsBoard BEFORE first starting the gateway: with
 * remoteConfiguration on and the shared attributes empty, the gateway pushes its own
 * local (placeholder) config up and you have to clean it out again.
 */

const fs = require('fs');
const path = require('path');
const { buildModbusConnector, buildLocalConnectorFile } = require('./generate-connector');

const GATEWAY_PROFILE = 'IoT Gateway';
const MQTT_HOST = 'lb-mqtt.pke-iot.expert';
const MQTT_PORT = 1883;

// ---------------------------------------------------------------- credentials

function loadEnv() {
  // Reuse the ECO-TB credentials rather than adding a second copy to this repo.
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
  throw new Error(
    `No ThingsBoard credentials found. Looked in:\n  ${candidates.join('\n  ')}\n` +
    `Need TB_BASE_URL, TB_USERNAME, TB_PASSWORD.`
  );
}

// ---------------------------------------------------------------- REST client

class Tb {
  constructor(env) {
    this.base = env.TB_BASE_URL.replace(/\/+$/, '');
    this.env = env;
    this.token = null;
  }

  async login() {
    const r = await this._raw('POST', '/api/auth/login', {
      username: this.env.TB_USERNAME,
      password: this.env.TB_PASSWORD,
    });
    this.token = r.token;
  }

  async _raw(method, urlPath, body, retries = 3) {
    let lastErr;
    for (let i = 0; i < retries; i++) {
      try {
        const res = await fetch(`${this.base}${urlPath}`, {
          method,
          headers: {
            'Content-Type': 'application/json',
            ...(this.token ? { 'X-Authorization': `Bearer ${this.token}` } : {}),
          },
          body: body === undefined ? undefined : JSON.stringify(body),
        });
        const text = await res.text();
        if (!res.ok) {
          const err = new Error(`HTTP ${res.status} ${method} ${urlPath}: ${text.slice(0, 400)}`);
          err.status = res.status;
          throw err;   // do not retry a definite server rejection
        }
        return text ? JSON.parse(text) : null;
      } catch (e) {
        lastErr = e;
        if (e.status) throw e;          // 4xx/5xx: surface immediately
        await sleep(700 * (i + 1));     // transient network/DNS: retry
      }
    }
    throw lastErr;
  }

  get(p) { return this._raw('GET', p); }
  post(p, b) { return this._raw('POST', p, b); }

  async findDeviceByName(name) {
    try {
      return await this.get(`/api/tenant/devices?deviceName=${encodeURIComponent(name)}`);
    } catch (e) {
      if (e.status === 404) return null;
      throw e;
    }
  }

  async findProfileIdByName(name) {
    const page = await this.get(
      `/api/deviceProfileInfos?pageSize=200&page=0&textSearch=${encodeURIComponent(name)}`
    );
    const hit = (page.data || []).find((p) => p.name === name);
    if (!hit) throw new Error(`Device profile "${name}" not found in this tenant.`);
    return hit.id;
  }
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ---------------------------------------------------------------- config bodies

function generalConfiguration(accessToken) {
  // Mirrors the verified general_configuration of the existing fleet.
  return {
    host: MQTT_HOST,
    port: MQTT_PORT,
    remoteShell: false,
    remoteConfiguration: true,
    checkConnectorsConfigurationInSeconds: 60,
    statistics: {
      enable: true,
      enableCustom: false,
      statsSendPeriodInSeconds: 3600,
      customStatsSendPeriodInSeconds: 3600,
      commands: [],
    },
    maxPayloadSizeBytes: 8196,
    minPackSendDelayMS: 50,
    minPackSizeToSend: 500,
    handleDeviceRenaming: true,
    checkingDeviceActivity: {
      checkDeviceInactivity: false,
      inactivityTimeoutSeconds: 300,
      inactivityCheckPeriodSeconds: 10,
    },
    security: { type: 'accessToken', accessToken },
    qos: 1,
    reportStrategy: { type: 'ON_RECEIVED', reportPeriod: 10000, ttl: 86400 },
  };
}

function tbGatewayYaml(accessToken, connectorName) {
  return `# Generated by provisioning/provision-gateway.js -- do not edit by hand.
thingsboard:
  host: ${MQTT_HOST}
  port: ${MQTT_PORT}
  remoteShell: false
  remoteConfiguration: true
  statistics:
    enable: true
    statsSendPeriodInSeconds: 3600
  deviceFiltering:
    enable: false
  maxPayloadSizeBytes: 8196
  minPackSendDelayMS: 50
  minPackSizeToSend: 500
  checkConnectorsConfigurationInSeconds: 60
  handleDeviceRenaming: true
  qos: 1
  security:
    accessToken: ${accessToken}

storage:
  type: memory
  read_records_count: 100
  max_records_count: 100000

grpc:
  enabled: false
  serverPort: 9595

connectors:
  - name: ${connectorName}
    type: modbus
    configuration: modbus.json
`;
}

// ---------------------------------------------------------------- main

async function main() {
  const args = process.argv.slice(2);
  const sitePath = args.find((a) => !a.startsWith('--'));
  const apply = args.includes('--apply');
  const outIdx = args.indexOf('--out');
  const outDir = outIdx >= 0 ? args[outIdx + 1] : path.resolve(__dirname, 'out');

  if (!sitePath) {
    console.error('usage: node provision-gateway.js <site.json> [--apply] [--out <dir>]');
    process.exit(2);
  }

  const resolvedSite = path.isAbsolute(sitePath) ? sitePath : path.resolve(process.cwd(), sitePath);
  const site = JSON.parse(fs.readFileSync(resolvedSite, 'utf8'));

  // Build the connector first: a bad site file should fail before anything is created.
  const { connectorName, connector } = buildModbusConnector(site);
  const deviceNames = connector.configurationJson.master.slaves
    .map((s) => s.deviceName)
    .filter((v, i, a) => a.indexOf(v) === i);

  console.log(`site file        : ${resolvedSite}`);
  console.log(`gateway device   : ${site.gatewayName}`);
  console.log(`inherited HWID   : ${site.hwid}`);
  console.log(`connector        : ${connectorName}`);
  console.log(`serial           : ${site.serial.port} @ ${site.serial.baudrate} ` +
              `${site.serial.bytesize ?? 8}${site.serial.parity ?? 'N'}${site.serial.stopbits ?? 1}`);
  console.log(`slave entries    : ${connector.configurationJson.master.slaves.length} ` +
              `(${deviceNames.length} physical devices x endianness groups)`);
  console.log(`child devices    :`);
  for (const n of deviceNames) console.log(`                   ${n}`);
  console.log();

  const { env, source } = loadEnv();
  console.log(`credentials from : ${source}`);
  console.log(`thingsboard      : ${env.TB_BASE_URL}`);
  console.log(`mqtt endpoint    : ${MQTT_HOST}:${MQTT_PORT}`);
  console.log();

  const tb = new Tb(env);
  await tb.login();

  const existing = await tb.findDeviceByName(site.gatewayName);
  if (existing) {
    console.log(`NOTE: device "${site.gatewayName}" already exists (id ${existing.id.id}).`);
    console.log(`      Its shared attributes would be overwritten; the device itself is reused.`);
  }

  if (!apply) {
    fs.mkdirSync(outDir, { recursive: true });
    const preview = path.join(outDir, `${site.gatewayName}.modbus.preview.json`);
    fs.writeFileSync(preview, buildLocalConnectorFile(connector));
    console.log('DRY RUN -- nothing was written to ThingsBoard.');
    console.log(`Connector preview: ${preview}`);
    console.log('Re-run with --apply to create the device and push its configuration.');
    return;
  }

  // ---- 1. device
  let device = existing;
  if (!device) {
    const profileId = await tb.findProfileIdByName(GATEWAY_PROFILE);
    device = await tb.post('/api/device', {
      name: site.gatewayName,
      deviceProfileId: profileId,
      additionalInfo: { gateway: true, description: site.description || '' },
    });
    console.log(`created device   : ${device.id.id}`);
  }

  // ---- 2. access token
  const creds = await tb.get(`/api/device/${device.id.id}/credentials`);
  if (creds.credentialsType !== 'ACCESS_TOKEN') {
    throw new Error(`Device uses ${creds.credentialsType}; this script only handles ACCESS_TOKEN.`);
  }
  const accessToken = creds.credentialsId;
  console.log(`access token     : ${accessToken}`);

  // ---- 3. shared attributes (what remoteConfiguration pulls down)
  await tb.post(`/api/plugins/telemetry/DEVICE/${device.id.id}/SHARED_SCOPE`, {
    general_configuration: generalConfiguration(accessToken),
    [connectorName]: connector,
    active_connectors: [connectorName],
    mode: 'advanced',
  });
  console.log(`shared attrs     : general_configuration, ${connectorName}, active_connectors, mode`);

  // ---- 4. local files for first boot
  fs.mkdirSync(outDir, { recursive: true });
  const yamlPath = path.join(outDir, `${site.gatewayName}.tb_gateway.yaml`);
  const jsonPath = path.join(outDir, `${site.gatewayName}.modbus.json`);
  fs.writeFileSync(yamlPath, tbGatewayYaml(accessToken, connectorName));
  fs.writeFileSync(jsonPath, buildLocalConnectorFile(connector));

  console.log();
  console.log('Wrote, for copying to the Pi at /etc/thingsboard-gateway/config/:');
  console.log(`  ${yamlPath}  -> tb_gateway.yaml`);
  console.log(`  ${jsonPath}  -> modbus.json`);
  console.log();
  console.log('These contain a live access token. Do not commit them.');
}

main().catch((e) => {
  console.error(`\nFAILED: ${e.message}`);
  process.exit(1);
});
