'use strict';
// Minimal .env loader (no dependency). Reads provisioning/migrate/.env, merges
// process.env over it, and validates the keys the tool needs.
const fs = require('fs');
const path = require('path');

function parseEnvFile(file) {
  const out = {};
  if (!fs.existsSync(file)) return out;
  for (const raw of fs.readFileSync(file, 'utf8').split(/\r?\n/)) {
    const line = raw.trim();
    if (!line || line.startsWith('#')) continue;
    const m = line.match(/^([A-Z0-9_]+)\s*=\s*(.*)$/);
    if (!m) continue;
    let v = m[2];
    if ((v.startsWith('"') && v.endsWith('"')) || (v.startsWith("'") && v.endsWith("'"))) v = v.slice(1, -1);
    out[m[1]] = v;
  }
  return out;
}

function load(opts = {}) {
  const envPath = opts.envPath || path.join(__dirname, '..', '.env');
  const fileEnv = parseEnvFile(envPath);
  const g = (k, d) => (process.env[k] !== undefined ? process.env[k] : (fileEnv[k] !== undefined ? fileEnv[k] : d));

  const cfg = {
    envPath,
    tb: { baseUrl: (g('TB_BASE_URL', '') || '').replace(/\/+$/, ''), username: g('TB_USERNAME', ''), password: g('TB_PASSWORD', '') },
    mqtt: { host: g('MQTT_HOST', 'lb-mqtt.pke-iot.expert'), port: parseInt(g('MQTT_PORT', '1883'), 10) },
    tailscale: { authkey: g('TS_AUTHKEY', '') },
    box: { user: g('BOX_SSH_USER', 'resi'), password: g('BOX_SSH_PASSWORD', ''), keyPath: g('BOX_SSH_KEY', '') },
    docker: { staticTgz: g('DOCKER_STATIC_TGZ', ''), imageTar: g('TBGW_IMAGE_TAR', ''), imageRef: g('TBGW_IMAGE_REF', 'thingsboard/tb-gateway:latest') },
  };
  return cfg;
}

// Validate only the keys a given phase needs, so read-only phases don't require
// e.g. the Tailscale key.
function requireKeys(cfg, keys) {
  const missing = [];
  const map = {
    'tb': () => cfg.tb.baseUrl && cfg.tb.username && cfg.tb.password,
    'box.password': () => cfg.box.password,
    'box.key': () => cfg.box.keyPath && fs.existsSync(cfg.box.keyPath) && fs.existsSync(cfg.box.keyPath + '.pub'),
    'tailscale': () => cfg.tailscale.authkey,
    'docker.tgz': () => cfg.docker.staticTgz && fs.existsSync(cfg.docker.staticTgz),
  };
  for (const k of keys) if (map[k] && !map[k]()) missing.push(k);
  return missing;
}

module.exports = { load, requireKeys, parseEnvFile };
