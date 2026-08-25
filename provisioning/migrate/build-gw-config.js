'use strict';
// Build the tb-gateway LOCAL config (tb_gateway.json + modbus.json) for a site,
// using the gateway device's captured MQTT_BASIC credentials. Output goes to
// out/<kit>/config/ for scp to the box's /thingsboard_gateway/config.
//
//   node build-gw-config.js <kit> <site.json>
const fs = require('fs');
const path = require('path');
const { buildModbusConnector } = require('../generate-connector');

const kit = process.argv[2];
const sitePath = process.argv[3];
if (!kit || !sitePath) { console.error('usage: node build-gw-config.js <kit> <site.json>'); process.exit(2); }

const site = JSON.parse(fs.readFileSync(sitePath, 'utf8'));

// Override the serial port with a reboot-stable name. The host ttyACMx can renumber
// across reboots; we map the udev by-id device to a fixed /dev/meterbus inside the
// container (see the docker run --device mapping), so the connector's port is stable.
if (process.env.ECO_MODBUS_PORT) site.serial.port = process.env.ECO_MODBUS_PORT;

// Deploy only the meters actually present on the bus (from the live scan). Unwired
// slaves make tb-gateway's modbus connector CLOSE the serial connection after a few
// failed polls, which starves the wired meters. Pass a CSV of present unit IDs as
// argv[4]; the site file keeps the full intended set for when kits are wired.
const presentCsv = process.argv[4];
if (presentCsv) {
  const present = new Set(presentCsv.split(',').map(s => parseInt(s.trim(), 10)));
  const before = site.pflows.length;
  site.pflows = site.pflows.filter(p => present.has(p.unitId));
  console.log(`filtered pflows to present units [${[...present].join(',')}]: ${before} -> ${site.pflows.length}`);
}

const { connectorName, connector } = buildModbusConnector(site);

const credPath = path.join(__dirname, 'out', `${kit}.gw-mqtt.json`);
if (!fs.existsSync(credPath)) { console.error(`missing captured creds: ${credPath} (run TB apply first)`); process.exit(2); }
const cred = JSON.parse(fs.readFileSync(credPath, 'utf8'));

const MQTT_HOST = process.env.MQTT_HOST || 'lb-mqtt.pke-iot.expert';
const MQTT_PORT = parseInt(process.env.MQTT_PORT || '1883', 10);

let security;
if (cred.credentialsType === 'ACCESS_TOKEN') security = { type: 'accessToken', accessToken: cred.accessToken };
else security = { type: 'usernamePassword', clientId: cred.clientId || undefined, username: cred.userName || undefined, password: cred.password || undefined };

const tbGateway = {
  thingsboard: {
    host: MQTT_HOST,
    port: MQTT_PORT,
    remoteShell: false,
    remoteConfiguration: false,      // local config for a deterministic first deploy
    checkConnectorsConfigurationInSeconds: 60,
    statistics: { enable: true, statsSendPeriodInSeconds: 3600 },
    deviceFiltering: { enable: false },
    maxPayloadSizeBytes: 8196,
    minPackSendDelayMS: 50,
    minPackSizeToSend: 500,
    handleDeviceRenaming: true,
    security,
    qos: 1,
  },
  storage: { type: 'memory', read_records_count: 100, max_records_count: 100000 },
  grpc: { enabled: false },
  connectors: [{ name: connectorName, type: 'modbus', configuration: 'modbus.json' }],
};

const outDir = path.join(__dirname, 'out', kit, 'config');
fs.mkdirSync(outDir, { recursive: true });
fs.writeFileSync(path.join(outDir, 'tb_gateway.json'), JSON.stringify(tbGateway, null, 2));
fs.writeFileSync(path.join(outDir, 'modbus.json'), JSON.stringify(connector.configurationJson, null, 2));
console.log(`wrote ${path.relative(process.cwd(), outDir)}/tb_gateway.json + modbus.json`);
console.log(`security: ${security.type}  clientId=${security.clientId || 'n/a'}  user=${security.username ? 'set' : 'n/a'}  pass=${security.password ? 'set' : 'n/a'}`);
console.log(`connector: ${connectorName}  slaves=${connector.configurationJson.master.slaves.length}  port=${site.serial.port}`);
