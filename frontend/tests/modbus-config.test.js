import test from 'node:test'
import assert from 'node:assert/strict'
import {createRequire} from 'node:module'
import {groupDevices,buildGroups,replaceDevice} from '../src/services/modbusConfig.js'
const require=createRequire(import.meta.url)
const {payload,acknowledged,credentialsMatch}=require('../../provisioning/migrate/lib/connector-sync.js')
test('installer refuses to seed a different gateway identity',()=>{
 assert.ok(credentialsMatch({accessToken:'test'},{credentialsType:'ACCESS_TOKEN',credentialsId:'test'}))
 assert.ok(!credentialsMatch({accessToken:'wrong'},{credentialsType:'ACCESS_TOKEN',credentialsId:'test'}))
 assert.ok(credentialsMatch({username:'test',password:'test',clientId:'id'},{credentialsType:'MQTT_BASIC',credentialsValue:JSON.stringify({userName:'test',password:'test',clientId:'id'})}))
})
const profiles=require('../../backend/app/services/modbus_profiles.json')
test('local profiles match the provisioning source of register maps',()=>{
 const m=require('../../provisioning/device-maps.js')
 assert.deepEqual(profiles.pflow,m.canonicalizeGroups(m.PFLOW_D116.registerGroups))
 for(let i=0;i<2;i++) assert.deepEqual(profiles.pt1000[i],m.canonicalizeGroups(m.TEMP_SENSOR.registerGroupsFor(i),'auxT'+(i+1)+'_C'))
})
const form={profile:'PFlow D116',name:'PF1',port:'/dev/meterbus',transport:'serial',address:88,seconds:60,baudrate:9600,parity:'N',bytesize:8,stopbits:1,timeout:2}
test('profiles group a physical meter and preserve both byte orders',()=>{
  const groups=buildGroups(form,profiles,false)
  assert.equal(groups.length,2);assert.equal(groupDevices(groups).length,1)
  assert.deepEqual(groups.map(g=>g.wordOrder),['BIG','LITTLE'])
  const ts=buildGroups({...form,profile:'PT1000 / AIOX',name:'TS2',slot:1},profiles,false)
  assert.equal(ts[0].unitId,255);assert.equal(ts[0].timeseries[1].address,7)
})
test('editing preserves manual fields and applies shared serial framing',()=>{
 const groups=buildGroups(form,profiles,false);groups[0].rpc=[{tag:'keep'}]
 const manual={...groups[0],deviceName:'manual',unitId:9,timeseries:[{tag:'custom'}]}
 const d=groupDevices(groups)[0], edited=buildGroups({...form,baudrate:19200,groups},profiles,true)
 const result=replaceDevice([...groups,manual],d,edited,{...form,baudrate:19200})
 assert.equal(result[0].timeseries[0].tag,'custom');assert.equal(result[0].baudrate,19200)
 assert.deepEqual(result[1].rpc,[{tag:'keep'}])
})
test('initial synchronization requires fresh matching reports and observer',()=>{
 const snapshot={gateway:{thingsboard:{host:'example',remoteConfiguration:false},connectors:[{name:'RS485',type:'eco_modbus',class:'EcoModbusConnector',configuration:'modbus.json'}]},files:{'modbus.json':{master:{slaves:buildGroups(form,profiles,false)}}}}
 const desired=payload(snapshot,100)
 const attributes=Object.entries(desired).map(([key,value])=>({key,value:structuredClone(value),lastUpdateTs:101}))
 assert.ok(acknowledged(desired,attributes,100))
 assert.ok(!acknowledged(desired,attributes,102))
 attributes.find(a=>a.key==='RS485').value.configurationJson.master.slaves[0].timeout=35
 assert.ok(!acknowledged(desired,attributes,100))
 snapshot.gateway.connectors[0].type='modbus'
 assert.throws(()=>payload(snapshot),/observer/)
})
