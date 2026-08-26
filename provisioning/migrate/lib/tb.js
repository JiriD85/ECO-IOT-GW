'use strict';
// ThingsBoard REST client for migrate-box. Read ops are always allowed; write
// ops throw unless the client was created with {apply:true}, so a dry-run can
// call the same code path and just log intended changes.
const DIAGNOSTICKIT_PROFILE = '207a4c30-bfac-11ee-80de-5de32813ef75';

class TB {
  constructor(cfg, opts = {}) {
    this.base = cfg.tb.baseUrl;
    this.cred = { username: cfg.tb.username, password: cfg.tb.password };
    this.apply = !!opts.apply;
    this.token = null;
    this.onWrite = opts.onWrite || (() => {});
  }

  async _req(method, p, body) {
    const res = await fetch(`${this.base}${p}`, {
      method,
      headers: { 'Content-Type': 'application/json', ...(this.token ? { 'X-Authorization': `Bearer ${this.token}` } : {}) },
      body: body ? JSON.stringify(body) : undefined,
    });
    const text = await res.text();
    if (!res.ok) { const e = new Error(`HTTP ${res.status} ${method} ${p}: ${text.slice(0, 300)}`); e.status = res.status; throw e; }
    return text ? JSON.parse(text) : null;
  }
  get(p) { return this._req('GET', p); }
  // guarded write: in dry-run it records intent and returns null instead of calling TB
  _write(method, p, body, describe) {
    this.onWrite(describe || `${method} ${p}`);
    if (!this.apply) return Promise.resolve(null);
    return this._req(method, p, body);
  }

  async login() { this.token = (await this._req('POST', '/api/auth/login', this.cred)).token; return this.token; }

  // --- reads ---
  async findKit(code) {
    const page = await this.get(`/api/assetInfos/all?pageSize=20&page=0&includeCustomers=true&assetProfileId=${DIAGNOSTICKIT_PROFILE}&textSearch=${encodeURIComponent(code)}`);
    return (page.data || []).find(a => a.name === code) || (page.data || [])[0] || null;
  }
  // list every DiagnosticKit asset (paged), for the interactive kit picker
  async listKits(limit = 500) {
    const out = [];
    for (let page = 0; page < 50; page++) {
      const p = await this.get(`/api/assetInfos/all?pageSize=50&page=${page}&includeCustomers=true&assetProfileId=${DIAGNOSTICKIT_PROFILE}&sortProperty=name&sortOrder=ASC`);
      for (const a of (p.data || [])) out.push({ id: a.id.id, name: a.name, customer: a.customerTitle || a.customerName || '' });
      if (!p.hasNext || out.length >= limit) break;
    }
    return out;
  }
  async kitDevices(assetId) {
    const rel = await this.get(`/api/relations/info?fromId=${assetId}&fromType=ASSET`);
    const contains = (rel || []).filter(r => r.type === 'Contains' && r.to.entityType === 'DEVICE');
    const out = [];
    for (const r of contains) {
      const d = await this.get(`/api/device/${r.to.id}`);
      out.push({ id: d.id.id, name: d.name, type: d.type, profileId: d.deviceProfileId.id, gateway: !!(d.additionalInfo && d.additionalInfo.gateway) });
    }
    out.sort((a, b) => a.name.localeCompare(b.name));
    return out;
  }
  async deviceCredentials(deviceId) { return this.get(`/api/device/${deviceId}/credentials`); }
  async deviceProfileName(profileId) { try { return (await this.get(`/api/deviceProfile/${profileId}`)).name; } catch { return profileId; } }
  async findProfile(name) {
    const page = await this.get(`/api/deviceProfileInfos?pageSize=100&page=0&textSearch=${encodeURIComponent(name)}`);
    return (page.data || []).find(p => p.name === name) || null;
  }
  async calculatedFields(profileId) {
    try { const r = await this.get(`/api/DEVICE_PROFILE/${profileId}/calculatedFields?pageSize=100&page=0`); return r.data || r || []; }
    catch { return []; }
  }
  async sharedAttributes(deviceId) {
    try { return await this.get(`/api/plugins/telemetry/DEVICE/${deviceId}/values/attributes/SHARED_SCOPE`); } catch { return []; }
  }

  // --- writes (guarded) ---
  async setDeviceProfile(device, profileId, profileName) {
    // TB requires PUT of the full device object with the new deviceProfileId
    const full = await this.get(`/api/device/${device.id}`);
    full.deviceProfileId = { entityType: 'DEVICE_PROFILE', id: profileId };
    return this._write('POST', '/api/device', full, `reprofile ${device.name} -> ${profileName}`);
  }
  async setGatewayFlag(device, on = true) {
    const full = await this.get(`/api/device/${device.id}`);
    full.additionalInfo = { ...(full.additionalInfo || {}), gateway: on };
    return this._write('POST', '/api/device', full, `set gateway=${on} on ${device.name}`);
  }
  async postSharedAttributes(deviceId, obj, label) {
    return this._write('POST', `/api/plugins/telemetry/DEVICE/${deviceId}/SHARED_SCOPE`, obj, label || `push shared attrs to ${deviceId} (${Object.keys(obj).join(', ')})`);
  }
}

module.exports = { TB, DIAGNOSTICKIT_PROFILE };
