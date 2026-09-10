export function applyMessage(previous, message) {
  if (message.type === 'snapshot') return message
  if (message.type !== 'delta' || !previous) return previous
  const devices = new Map(previous.devices.map(d => [d.name, d]))
  for (const name of message.removed || []) devices.delete(name)
  for (const patch of message.devices) {
    const old = devices.get(patch.name)
    if (!old) { devices.set(patch.name, patch); continue }
    const readings = new Map((old.readings || []).map(r => [r.tag, r]))
    for (const tag of patch.removed_readings || []) readings.delete(tag)
    for (const r of patch.readings || []) readings.set(r.tag, { ...readings.get(r.tag), ...r })
    devices.set(patch.name, { ...old, ...patch, readings: [...readings.values()] })
  }
  return { ...previous, ...message, devices: [...devices.values()] }
}
