'use strict';
/**
 * Build a tb-gateway Modbus connector configuration from a site definition.
 *
 * Every physical meter expands into one slave entry per byte/word-order group in its
 * register map (see device-maps.js -- the D116 is mixed-endian and needs two).
 */

const { PFLOW_D116, TEMP_SENSOR, canonicalizeGroups } = require('./device-maps');

/** TS1 -> auxT1_C, TS2 -> auxT2_C; falls back to plain `temperature`. */
function canonicalTempTag(suffix) {
  const m = /TS(\d+)/i.exec(suffix || '');
  return m ? `auxT${m[1]}_C` : 'temperature';
}

/** tb-gateway release this config shape targets. Matches the pinned image. */
const CONFIG_VERSION = '3.7.8';

/**
 * @param {object} site parsed site definition, see sites/example.json
 * @returns {{connectorName: string, connector: object}}
 */
function buildModbusConnector(site) {
  requireFields(site, ['gatewayName', 'hwid', 'serial']);

  // Which telemetry keys the connector emits:
  //   'raw'       -> the fleet's CHC_* keys on the RESI device profiles.
  //   'canonical' -> the ECO GW keys (E_th_*, V_m3, T_flow_C, ...) on the "... GW" profiles.
  //   'both'      -> BOTH key sets, on the GW profiles. A fleet dashboard bound to CHC_*
  //                  AND the ECO GW pipeline (E_th_*) then both see data. Same registers and
  //                  scaling -- purely additive, no extra bus addresses read.
  // `site.emit` wins; the legacy `canonical: true` still maps to 'canonical'.
  const emit = site.emit || (site.canonical === true ? 'canonical' : 'raw');
  if (!['raw', 'canonical', 'both'].includes(emit)) throw new Error(`site.emit must be raw|canonical|both, got '${emit}'`);
  // GW device profiles whenever canonical keys are present (so a gateway-auto-created
  // device lands on the GW pipeline, not the RESI profile).
  const gwProfile = emit === 'canonical' || emit === 'both';

  const slaves = [];

  const pfType = gwProfile ? `${PFLOW_D116.deviceType} GW` : PFLOW_D116.deviceType;
  const tsType = gwProfile ? `${TEMP_SENSOR.deviceType} GW` : TEMP_SENSOR.deviceType;

  // P-Flow meters live on the external RS485 bus.
  for (const meter of site.pflows || []) {
    requireFields(meter, ['suffix', 'unitId'], `pflows[${meter.suffix || '?'}]`);
    slaves.push(...expand(site, meter, keyGroups(PFLOW_D116.registerGroups, emit), pfType, site.serial));
  }

  // Temperature sensors (TS1/TS2) are the onboard C4 AIOX, read as Modbus unit 255 on the
  // SAME external meter bus as the P-Flows (FC04 input registers). slot 0 = TS1/IO01,
  // slot 1 = TS2/IO02. See device-maps.js for the firmware-verified map.
  for (const sensor of site.tempSensors || []) {
    requireFields(sensor, ['suffix', 'slot'], `tempSensors[${sensor.suffix || '?'}]`);
    const groups = keyGroups(TEMP_SENSOR.registerGroupsFor(sensor.slot), emit, canonicalTempTag(sensor.suffix));
    slaves.push(...expand(
      site,
      { ...sensor, unitId: sensor.unitId ?? TEMP_SENSOR.unitId },
      groups,
      tsType,
      site.serial
    ));
  }

  if (slaves.length === 0) {
    throw new Error('Site defines no devices -- nothing to generate.');
  }

  return {
    connectorName: site.connectorName || 'RS485_PF',
    connector: {
      type: 'modbus',
      name: site.connectorName || 'RS485_PF',
      logLevel: site.logLevel || 'INFO',
      useDefaults: true,
      sendDataOnlyOnChange: false,
      configVersion: CONFIG_VERSION,
      configuration: 'modbus.json',
      // logLevel goes INSIDE configurationJson so it lands in the written
      // modbus.json (build-gw-config serialises configurationJson only). The web
      // console's Meters view decodes live values by pairing the connector's
      // DEBUG "Reading N registers…" / "Read with result…" lines, so a device
      // whose console should show per-tag values needs logLevel DEBUG.
      configurationJson: { logLevel: site.logLevel || 'INFO', master: { slaves } },
    },
  };
}

/** Strip the canonical-only annotations, leaving clean raw (CHC_*) timeseries entries. */
function rawGroups(groups) {
  return groups.map((g) => ({
    ...g,
    timeseries: g.timeseries.map((e) => { const { canonicalTag, canonicalDivider, ...rest } = e; return rest; }),
  }));
}

/**
 * Register groups (→ slaves) for the requested emit mode.
 *
 * 'both' returns the raw groups AND the canonical groups as SEPARATE groups (each becomes
 * its own slave sharing the device's name/unitId). They must be separate slaves because
 * tb-gateway's Modbus connector collapses duplicate register addresses WITHIN one slave to
 * a single tag (last wins) — so two tags on the same address in one slave would drop one.
 * As separate slaves the two key sets are read independently and merge on the shared
 * deviceName. Cost: the shared registers are read twice per poll (fine at this bus rate).
 */
function keyGroups(groups, emit, tempTag) {
  if (emit === 'canonical') return canonicalizeGroups(groups, tempTag);
  if (emit === 'raw') return rawGroups(groups);
  return [...rawGroups(groups), ...canonicalizeGroups(groups, tempTag)];
}

/** Expand one physical device into its per-endianness slave entries. */
function expand(site, device, registerGroups, deviceType, serial) {
  requireFields(serial, ['port', 'baudrate'], 'serial config');

  return registerGroups.map((group) => ({
    type: 'serial',
    method: 'rtu',
    port: serial.port,
    baudrate: serial.baudrate,
    stopbits: serial.stopbits ?? 1,
    bytesize: serial.bytesize ?? 8,
    parity: serial.parity ?? 'N',
    strict: true,
    // Short per-slave timeout: a missing address must fail fast (~2s), not stall
    // the shared RS485 bus for 35s and desync the real meters' frames. The 35s
    // that used to live here was never a RESI value -- the RESI stack used ~1s.
    // See memory: modbus-connector-tuning.
    timeout: serial.timeout ?? 2,
    byteOrder: group.byteOrder,
    wordOrder: group.wordOrder,
    // One cheap retry recovers a single noisy/CRC frame within the cycle;
    // do NOT retry on empty (an empty address = no meter, retrying just stalls).
    retries: serial.retries ?? 1,
    retryOnEmpty: false,
    retryOnInvalid: true,
    pollPeriod: device.pollPeriod ?? site.pollPeriod ?? 30000,
    unitId: device.unitId,
    // Must match the fleet convention exactly or existing dashboards will not bind.
    // `deviceName` override exists only for pointing a test connector at a scratch device.
    deviceName: device.deviceName || `ECO_${site.hwid}_${device.suffix}`,
    deviceType,
    sendDataOnlyOnChange: false,
    connectAttemptTimeMs: 5000,
    connectAttemptCount: 5,
    waitAfterFailedAttemptsMs: 5000,
    timeseries: group.timeseries,
  }));
}

function requireFields(obj, fields, where = 'site') {
  if (!obj || typeof obj !== 'object') throw new Error(`${where}: expected an object`);
  const missing = fields.filter((f) => obj[f] === undefined || obj[f] === null);
  if (missing.length) throw new Error(`${where}: missing required field(s): ${missing.join(', ')}`);
}

/** The `connectors:` entry and standalone file the gateway reads locally. */
function buildLocalConnectorFile(connector) {
  return JSON.stringify(connector.configurationJson, null, 2);
}

module.exports = { buildModbusConnector, buildLocalConnectorFile, CONFIG_VERSION };
