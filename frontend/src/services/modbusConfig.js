const clone = value => JSON.parse(JSON.stringify(value))
export function groupDevices(slaves) {
  const groups = new Map()
  slaves.forEach((s, index) => {
    const key = JSON.stringify([s.deviceName, s.type, s.host, s.port, s.unitId])
    if (!groups.has(key)) groups.set(key, {key, name:s.deviceName, groups:[], indexes:[]})
    groups.get(key).groups.push(s); groups.get(key).indexes.push(index)
  })
  return [...groups.values()].sort((a,b)=>a.name.localeCompare(b.name,undefined,{numeric:true})).map(d => ({...d, profile: d.groups.some(g => /p.?flow/i.test(g.deviceType)) ? 'PFlow D116' : d.groups.some(g => g.unitId === 255 && (g.timeseries || []).some(t => t.functionCode === 4 && [0,1].includes(t.address))) ? 'PT1000 / AIOX' : 'Manual'}))
}
export function buildGroups(form, profiles, editing) {
  if (!form.name.trim()) throw Error('Device name is required')
  const preset = !editing && form.profile !== 'Manual'
  const source = preset ? form.profile === 'PFlow D116' ? profiles.pflow : profiles.pt1000[form.slot] : form.groups
  return clone(source).map(g => {
    const out = {...(!editing ? {type:'serial',method:'rtu',retries:0,retryOnEmpty:false,retryOnInvalid:false,connectAttemptTimeMs:5000,connectAttemptCount:1,waitAfterFailedAttemptsMs:5000} : {}), ...g,
      deviceName:form.name.trim(), deviceType:g.deviceType || (form.profile === 'PFlow D116' ? 'P-Flow D116 GW' : form.profile === 'PT1000 / AIOX' ? 'Temperature Sensor GW' : 'Modbus device'),
      type:g.type || form.transport, unitId:!editing && form.profile === 'PT1000 / AIOX' ? 255 : Number(form.address),pollPeriod:Number(form.seconds)*1000,timeout:Number(form.timeout)}
    if (out.type === 'serial') Object.assign(out,{port:form.port,baudrate:Number(form.baudrate),parity:form.parity,bytesize:Number(form.bytesize),stopbits:Number(form.stopbits),method:'rtu'})
    for (const t of out.timeseries || []) if (t.divider === '' || t.divider == null) delete t.divider
    return out
  })
}
export function replaceDevice(slaves, selected, groups, form) {
  const indexes = new Set(selected?.indexes || [])
  const remaining = clone(slaves).filter((s,i) => !indexes.has(i))
  if (groups.length && remaining.some(s => s.deviceName === groups[0].deviceName)) throw Error('Device name already exists')
  const result = [...remaining,...groups]
  // One physical serial bus must use one framing configuration.
  if (groups.length && groups[0].type === 'serial') for (const s of result) if (s.type === 'serial' && s.port === form.port) {
    Object.assign(s,{baudrate:Number(form.baudrate),parity:form.parity,bytesize:Number(form.bytesize),stopbits:Number(form.stopbits)})
  }
  return result
}
