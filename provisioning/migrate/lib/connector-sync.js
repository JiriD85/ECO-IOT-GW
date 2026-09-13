'use strict';
// Desired/reported comparison intentionally ignores transport/UI envelope metadata.
// The Modbus device configuration, including mappings and timing, must match.
const crypto = require('crypto');
function stable(v) {
  if (Array.isArray(v)) return v.map(stable);
  if (v && typeof v === 'object') return Object.fromEntries(Object.keys(v).sort().map(k => [k, stable(v[k])]));
  return v;
}
function equal(a,b) { return JSON.stringify(stable(a)) === JSON.stringify(stable(b)); }
function payload(snapshot, timestamp=Date.now()) {
  const config = snapshot.gateway;
  if (!config.connectors?.length) throw Error('No active connectors to synchronize');
  const names = config.connectors.map(c => c.name);
  if (new Set(names).size !== names.length) throw Error('Duplicate connector names');
  const out = {general_configuration:{...config.thingsboard,remoteConfiguration:true,ts:timestamp},active_connectors:names};
  for(const [key,value] of [['storage_configuration',config.storage],['grpc_configuration',config.grpc],['logs_configuration',snapshot.logs]]) {
    if(value) out[key]={...value,ts:timestamp};
  }
  for (const c of config.connectors) {
    const data = structuredClone(snapshot.files[c.configuration]);
    if (!data) throw Error('Missing active connector configuration');
    if (['modbus','eco_modbus'].includes(c.type) && (c.type !== 'eco_modbus' || c.class !== 'EcoModbusConnector')) throw Error('Install the local observer before cloud synchronization');
    const id = data.id || c.id || crypto.randomUUID();
    data.id = id; data.name = c.name;
    out[c.name] = {...c,id,configurationJson:data,logLevel:data.logLevel || 'INFO',enableRemoteLogging:!!data.enableRemoteLogging,configVersion:data.configVersion || '3.7.8',ts:timestamp};
  }
  return out;
}
function acknowledged(desired, attributes, since) {
  const attrs = Object.fromEntries(attributes.map(a => [a.key,a]));
  if (!equal(attrs.active_connectors?.value, desired.active_connectors) || attrs.active_connectors.lastUpdateTs < since) return false;
  if (!attrs.general_configuration?.value?.remoteConfiguration || attrs.general_configuration.lastUpdateTs < since) return false;
  return desired.active_connectors.every(name => {
    const a = attrs[name], want=desired[name];
    if (!a || a.lastUpdateTs < since || a.value.type !== want.type || a.value.class !== want.class) return false;
    const actual=a.value.configurationJson;
    if (want.configurationJson.master) return equal(actual?.master,want.configurationJson.master);
    // Non-Modbus connectors may move these root settings into the envelope.
    const omit = v => Object.fromEntries(Object.entries(v || {}).filter(([k])=>!['id','name','logLevel','enableRemoteLogging','configVersion','reportStrategy'].includes(k)));
    return equal(omit(actual),omit(want.configurationJson));
  });
}
function credentialsMatch(security, credentials) {
  if(credentials.credentialsType === 'ACCESS_TOKEN') return security?.accessToken === credentials.credentialsId;
  if(credentials.credentialsType === 'MQTT_BASIC') {
    let expected;try {expected=JSON.parse(credentials.credentialsValue);}catch{return false;}
    return !!security && ['username','password','clientId'].every(key =>
      (security[key] || '') === (expected[key === 'username' ? 'userName' : key] || ''));
  }
  return false;
}
module.exports={payload,acknowledged,equal,credentialsMatch};
