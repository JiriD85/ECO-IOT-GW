'use strict';
/**
 * Build a tb-gateway Modbus connector configuration from a site definition.
 *
 * Every physical meter expands into one slave entry per byte/word-order group in its
 * register map (see device-maps.js -- the D116 is mixed-endian and needs two).
 */

const { PFLOW_D116, TEMP_SENSOR } = require('./device-maps');

/** tb-gateway release this config shape targets. Matches the pinned image. */
const CONFIG_VERSION = '3.7.8';

/**
 * @param {object} site parsed site definition, see sites/example.json
 * @returns {{connectorName: string, connector: object}}
 */
function buildModbusConnector(site) {
  requireFields(site, ['gatewayName', 'hwid', 'serial']);

  const slaves = [];

  // P-Flow meters live on the external RS485 bus.
  for (const meter of site.pflows || []) {
    requireFields(meter, ['suffix', 'unitId'], `pflows[${meter.suffix || '?'}]`);
    slaves.push(...expand(site, meter, PFLOW_D116.registerGroups, PFLOW_D116.deviceType, site.serial));
  }

  // Temperature sensors are AIOX channels on the C4's INTERNAL link -- a different port,
  // and always unitId 1 (the AIOX module itself), not a per-sensor unit id.
  for (const sensor of site.tempSensors || []) {
    requireFields(sensor, ['suffix', 'channel'], `tempSensors[${sensor.suffix || '?'}]`);
    if (!site.internalSerial) {
      throw new Error(
        `Cannot generate config for ${sensor.suffix}: temperature sensors are AIOX channels ` +
        `on the C4's internal serial link, which is a different port from the P-Flow bus. ` +
        `Add "internalSerial" to the site file. See device-maps.js.`
      );
    }
    const groups = TEMP_SENSOR.registerGroupsFor(sensor.channel, sensor.kind || 'PT1000');
    slaves.push(...expand(
      site,
      { ...sensor, unitId: sensor.unitId ?? TEMP_SENSOR.unitId },
      groups,
      TEMP_SENSOR.deviceType,
      site.internalSerial
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
      configurationJson: { master: { slaves } },
    },
  };
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
    timeout: serial.timeout ?? 35,
    byteOrder: group.byteOrder,
    wordOrder: group.wordOrder,
    retries: true,
    retryOnEmpty: true,
    retryOnInvalid: true,
    pollPeriod: device.pollPeriod ?? site.pollPeriod ?? 30000,
    unitId: device.unitId,
    // Must match the fleet convention exactly or existing dashboards will not bind.
    deviceName: `ECO_${site.hwid}_${device.suffix}`,
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
