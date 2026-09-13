// Display aliases only: raw values can use different units, so never copy them
// into canonical readings or change the connector's ThingsBoard mappings.
const aliases = {
  CHC_S_VolumeFlow: 'Vdot_m3h', CHC_S_Velocity: 'v_ms',
  CHC_S_TemperatureFlow: 'T_flow_C', CHC_S_TemperatureReturn: 'T_return_C',
  CHC_M_Volume: 'V_m3', CHC_M_Volume_Neg: 'V_neg_m3', CHC_M_Volume_Net: 'V_net_m3',
  CHC_M_Energy_Heating: 'E_th_heating_kWh', CHC_M_Energy_Cooling: 'E_th_cooling_kWh',
  CHC_M_Energy_Heating_Exp: 'E_th_heating_exp', CHC_M_Energy_Cooling_Exp: 'E_th_cooling_exp',
}

export function pflowSlot(device) {
  return (device.name || '').match(/(?:^|_)pf([1-4])$/i)?.[1]
    || (device.label || '').match(/^p[- ]?flow\s*([1-4])$/i)?.[1] || ''
}

export function displayReadings(device) {
  const readings = device.readings || []
  const tags = new Set(readings.map(r => r.tag))
  return readings.filter(r => !r.tag.endsWith('_error') && !(aliases[r.tag] && tags.has(aliases[r.tag])))
}
