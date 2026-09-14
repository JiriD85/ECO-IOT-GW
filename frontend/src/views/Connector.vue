<template>
  <v-container fluid>
    <div class="d-flex align-center flex-wrap mb-4" style="gap:12px">
      <h1 class="text-h4">Modbus</h1><v-spacer />
      <v-btn variant="tonal" :loading="busy" @click="load">Refresh</v-btn>
    </div>
    <v-alert v-if="error" type="error" class="mb-4">{{ error }}</v-alert>
    <v-alert v-if="message" type="info" class="mb-4" closable @click:close="message = ''">{{ message }}</v-alert>
    <p v-if="!busy && !connectors.length">No active Modbus connectors.</p>
    <v-card v-for="c in connectors" :key="c.name" class="mb-5">
      <v-card-title class="d-flex align-center flex-wrap" style="gap:12px">
        {{ c.name }}
        <v-chip v-if="c.temporary" color="warning" size="small">Temporary override</v-chip>
        <v-chip size="small" :color="c.application === 'loaded' ? 'success' : 'warning'">{{ c.application === 'loaded' ? 'Matches last loaded config' : 'Awaiting connector reload' }}</v-chip>
      </v-card-title>
      <v-card-actions class="flex-wrap" style="gap:8px">
        <v-btn :disabled="busy || c.type !== 'eco_modbus'" @click="edit(c)">Add device</v-btn>
        <v-btn :disabled="busy || !c.can_restore || c.type !== 'eco_modbus'" @click="restore(c)">Restore received cloud config</v-btn>
      </v-card-actions>
      <v-card-text>
        <p class="mb-4 text-medium-emphasis">Local changes work offline. ThingsBoard updates can replace them.</p>
        <div class="devices">
          <section v-for="d in devices(c)" :key="d.key" class="device">
            <div class="d-flex align-center flex-wrap" style="gap:8px">
              <strong>{{ d.name }}</strong><v-chip size="small">{{ d.profile }}</v-chip><v-spacer />
              <v-btn size="small" variant="text" :disabled="busy || c.type !== 'eco_modbus'" @click="edit(c, d)">Edit</v-btn>
            </div>
            <p class="text-medium-emphasis my-2">{{ d.groups[0].host || d.groups[0].port }} · Address {{ d.groups[0].unitId }} · {{ d.groups[0].pollPeriod / 1000 }} s read · {{ d.groups[0].timeout }} s timeout</p>
            <v-table density="compact" class="registers">
              <thead><tr><th>Telemetry</th><th>Register</th><th>Read</th><th>Type</th><th>Scale</th><th>Words</th></tr></thead>
              <tbody><template v-for="(g, gi) in d.groups" :key="gi"><tr v-for="(t, ti) in [...(g.timeseries || []), ...(g.attributes || [])]" :key="ti">
                <td>{{ t.tag }}</td><td>{{ t.address }}</td><td>FC{{ t.functionCode }}</td><td>{{ t.type }}</td><td>{{ t.divider ? '÷ ' + t.divider : t.multiplier ? '× ' + t.multiplier : '—' }}</td><td>{{ g.wordOrder }}</td>
              </tr></template></tbody>
            </v-table>
          </section>
        </div>
      </v-card-text>
    </v-card>
    <v-dialog v-model="dialog" max-width="1000" persistent>
      <v-card v-if="form">
        <v-card-title>{{ selected ? 'Edit device' : 'Add device' }}</v-card-title>
        <v-card-text>
          <v-alert type="info" variant="tonal" class="mb-4">Temporary local override. Addresses are existing device addresses; this does not reprogram a sensor.</v-alert>
          <v-alert v-if="formError" type="error" class="mb-4">{{ formError }}</v-alert>
          <div class="fields">
            <v-select v-if="!selected" label="Profile" v-model="form.profile" :items="['PFlow D116', 'PT1000 / AIOX', 'Manual']" />
            <v-text-field label="Device name" v-model="form.name" />
            <v-text-field label="Serial port" v-model="form.port" :disabled="form.transport !== 'serial'" />
            <v-text-field v-if="selected || form.profile !== 'PT1000 / AIOX'" label="Modbus address" type="number" v-model.number="form.address" min="1" max="255" />
            <p v-else>AIOX board · Address 255</p>
            <v-select v-if="!selected && form.profile === 'PT1000 / AIOX'" label="Input" v-model="form.slot" :items="[{title:'TS1 / IO01',value:0},{title:'TS2 / IO02',value:1}]" />
            <v-text-field label="Read interval (s)" type="number" v-model.number="form.seconds" min="1" max="86400" />
            <v-text-field label="Response timeout (s)" type="number" v-model.number="form.timeout" min="0.1" max="60" step="0.1" />
          </div>
          <details class="mb-4"><summary>Bus settings</summary><div class="fields mt-4">
            <v-text-field label="Baud rate" type="number" v-model.number="form.baudrate" />
            <v-select label="Parity" v-model="form.parity" :items="['N','E','O']" />
            <v-select label="Data bits" v-model="form.bytesize" :items="[7,8]" />
            <v-select label="Stop bits" v-model="form.stopbits" :items="[1,2]" />
          </div><p>Serial settings apply to every device on the selected port.</p></details>
          <div v-if="selected || form.profile === 'Manual'" class="register-editor">
            <section v-for="(g, gi) in form.groups" :key="gi" class="mb-4">
              <div class="fields"><v-select label="Byte order" v-model="g.byteOrder" :items="['BIG','LITTLE']" /><v-select label="Word order" v-model="g.wordOrder" :items="['BIG','LITTLE']" /></div>
              <div v-for="(t, ti) in g.timeseries" :key="ti" class="mapping">
                <v-text-field label="Telemetry" v-model="t.tag" hide-details />
                <v-text-field label="Register (0-based)" type="number" v-model.number="t.address" hide-details />
                <v-select label="FC" v-model="t.functionCode" :items="[1,2,3,4]" hide-details />
                <v-select label="Type" v-model="t.type" :items="['16int','16uint','32int','32uint','32float','64int','64uint','64float','bits','string']" hide-details />
                <v-text-field label="Count" type="number" v-model.number="t.objectsCount" hide-details />
                <v-text-field label="Divider" type="number" v-model.number="t.divider" hide-details />
                <v-btn class="remove-mapping" color="error" variant="text" size="large" @click="g.timeseries.splice(ti,1)" aria-label="Remove telemetry">×</v-btn>
              </div>
              <v-btn variant="text" @click="g.timeseries.push({tag:'value',address:0,functionCode:3,type:'16int',objectsCount:1})">Add telemetry</v-btn>
            </section>
            <details class="json-panel"><summary>Advanced device JSON</summary><p class="my-2">Preserves custom mappings. Changes here replace the device form.</p><label for="register-groups-json">Register groups</label><textarea id="register-groups-json" v-model="raw" rows="16" wrap="soft" spellcheck="false" aria-label="Register groups"></textarea><v-btn class="mt-3" variant="tonal" @click="applyRaw">Use JSON</v-btn></details>
          </div>
        </v-card-text>
        <v-card-actions class="flex-wrap"><v-btn v-if="selected" color="error" :disabled="busy" @click="save(true)">Remove device</v-btn><v-spacer /><v-btn :disabled="busy" @click="dialog=false">Cancel</v-btn><v-btn color="primary" :loading="busy" @click="save(false)">Apply temporarily</v-btn></v-card-actions>
      </v-card>
    </v-dialog>
  </v-container>
</template>
<script setup>
import { ref, onMounted } from 'vue'
import api from '../services/api'
import { groupDevices, buildGroups, replaceDevice } from '../services/modbusConfig'
const connectors=ref([]), profiles=ref({}), busy=ref(false), error=ref(''), message=ref('')
const dialog=ref(false), form=ref(null), raw=ref(''), formError=ref('')
let current=null, selected=null
const clone=v=>JSON.parse(JSON.stringify(v))
const devices=c=>groupDevices(c.configuration.master.slaves)
async function load(){busy.value=true;error.value='';try{const {data}=await api.get('/api/modbus/config',{params:{force_refresh:true}});connectors.value=data.connectors;profiles.value=data.profiles}catch(e){error.value=e.response?.data?.detail||'Could not read Modbus configuration'}finally{busy.value=false}}
function edit(c,d=null){current=c;selected=d;const s=d?.groups[0]||c.configuration.master.slaves.find(s=>s.type==='serial')||{};form.value={profile:d?.profile||'PFlow D116',name:d?.name||'',port:s.port||'/dev/meterbus',transport:s.type||'serial',address:d?s.unitId:1,seconds:(s.pollPeriod||60000)/1000,baudrate:s.baudrate||9600,parity:s.parity||'N',bytesize:s.bytesize||8,stopbits:s.stopbits||1,timeout:s.timeout||2,slot:0,groups:clone(d?.groups||[{byteOrder:'BIG',wordOrder:'BIG',timeseries:[]}]).map(g=>({...g,timeseries:g.timeseries||[]}))};raw.value=JSON.stringify(form.value.groups,null,2);formError.value='';dialog.value=true}
function applyRaw(){try{const groups=JSON.parse(raw.value);if(!Array.isArray(groups)||!groups.length)throw Error('Expected an array of register groups');form.value.groups=groups;formError.value=''}catch(e){formError.value=e.message}}
async function save(remove){busy.value=true;formError.value='';try{const groups=remove?[]:buildGroups(form.value,profiles.value,!!selected);const slaves=replaceDevice(current.configuration.master.slaves,selected,groups,form.value);await api.put('/api/modbus/config/'+encodeURIComponent(current.name),{revision:current.revision,slaves});dialog.value=false;message.value='Saved locally. The gateway reloads configuration on its next check (normally within 60 seconds).';await load()}catch(e){formError.value=e.response?.data?.detail||e.message||'Could not apply configuration'}finally{busy.value=false}}
async function restore(c){busy.value=true;error.value='';try{await api.post('/api/modbus/config/'+encodeURIComponent(c.name)+'/restore',{revision:c.revision});message.value='Restored the last cloud configuration received by this gateway. Awaiting reload.';await load()}catch(e){error.value=e.response?.data?.detail||'Could not restore configuration'}finally{busy.value=false}}
onMounted(load)
</script>
<style scoped>
.devices{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,440px),1fr));gap:16px}.device{min-width:0;border:1px solid rgba(var(--v-theme-on-surface),.15);border-radius:8px;padding:14px}.registers{overflow:auto}.registers td{white-space:nowrap}.fields{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px}.register-editor{max-width:100%;overflow-x:auto;padding:6px 0 8px}.register-editor>section,.register-editor>details{min-width:760px}.register-editor>section>.fields{margin-bottom:16px}.mapping{display:grid;grid-template-columns:2fr repeat(5,minmax(82px,1fr)) 48px;align-items:center;gap:6px;margin-bottom:18px}.remove-mapping{min-width:44px!important;height:44px!important;font-size:26px!important;font-weight:700;line-height:1}.json-panel{padding-bottom:12px}.json-panel label{display:block;margin:8px 0 6px;color:rgba(var(--v-theme-on-surface),.7);font-size:12px}.json-panel textarea{display:block;width:100%;min-height:320px;padding:14px;border:1px solid rgba(var(--v-theme-on-surface),.25);border-radius:7px;resize:vertical;overflow:auto;background:rgb(var(--v-theme-surface));color:rgb(var(--v-theme-on-surface));font:12px/1.55 ui-monospace,SFMono-Regular,Consolas,monospace;tab-size:2}summary{cursor:pointer;padding:10px 0}
</style>
