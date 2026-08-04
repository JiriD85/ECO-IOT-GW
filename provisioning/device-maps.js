'use strict';
/**
 * Modbus register maps for the devices the ECO gateways poll.
 *
 * PROVENANCE — read before changing anything here.
 *
 * The P-Flow D116 map is recovered from the `3RS485_PF` connector configuration that
 * was stored as a device attribute on the `pke_AT1100_iotgw01` gateway in ThingsBoard
 * (tb-gateway 3.5.1, last active 2024-06). That is the only known-real map: the configs
 * named "RTU PFlow" on pkegw05, "Pflow" on bel_iotgw_resi01 and "RS485-1" on eco-gw-01
 * are all ThingsBoard's stock demo config (tags `8int_read`, `16uint_read`, ...) and
 * must not be used as a reference.
 *
 * MIXED ENDIANNESS: the D116 returns 32-bit floats word-order BIG but 32-bit integer
 * counters word-order LITTLE. tb-gateway sets byte/word order per *slave*, not per
 * register, so every physical meter needs TWO slave entries sharing one deviceName and
 * unitId. Collapsing them into one slave silently byte-swaps half the values.
 */

/** Divider that converts the D116 energy registers (kJ) to the kWh the fleet stores. */
const KJ_TO_KWH = 3600;

/**
 * P-Flow D116 heat meter.
 *
 * Covers 9 of the 19 CHC_* keys the existing fleet reports. The remaining 10 are NOT
 * in any recovered config and are not read here:
 *
 *   CHC_S_TemperatureDiff   = CHC_S_TemperatureFlow - CHC_S_TemperatureReturn.
 *                             Verified against live fleet data (28.51-28.89=-0.38 and
 *                             28.02-29.27=-1.25, both exact). Derive it server-side as
 *                             a ThingsBoard calculated field rather than reading a
 *                             register -- no register for it is known.
 *   CHC_S_Power_Heating     } observed 0 on every live device, so the source could not
 *   CHC_S_Power_Cooling     } be identified. Either unread registers or derived from
 *   CHC_M_Power_Heating     } flow and temperature difference. Needs a bus scan against
 *   CHC_M_Power_Cooling     } real hardware to settle.
 *   CHC_C_Energy_Heating    } a second counter set, 0 on every live device. Probably
 *   CHC_C_Energy_Cooling    } resettable "customer" counters. Register block unknown.
 *   CHC_C_Volume            }
 *   CHC_C_Volume_Net        }
 *   CHC_C_Volume_Neg        }
 *
 * REGISTER SPACING IS MANTISSA + EXPONENT. The 32-bit counters sit 3 registers apart
 * (8, 11, 14 and 77, 80) rather than 2. Recovered variable names from the RESI firmware
 * on the original SD card show why: every total exists as a _MANTISSA / _EXPONENT /
 * _UNIT triple --
 *
 *   PFLOW01_POSITIVE_TOTAL_MANTISSA / _EXPONENT        (+ _TOTAL_UNIT)
 *   PFLOW01_NEGATIVE_TOTAL_MANTISSA / _EXPONENT
 *   PFLOW01_NET_TOTAL_MANTISSA / _EXPONENT
 *   PFLOW01_HEATING_TOTAL_ENERGY_MANTISSA / _EXPONENT  (+ _ENERGY_UNIT)
 *   PFLOW01_COOLING_TOTAL_ENERGY_MANTISSA / _EXPONENT
 *
 * So the true value is mantissa scaled by an exponent, in a unit the meter also reports.
 * The two data registers are the mantissa; the third register is the exponent.
 *
 * CONSEQUENCE FOR THE `divider` BELOW: reading the mantissa as a bare 32-bit integer and
 * dividing by a constant is only correct while the exponent is 0 and the unit register
 * says kJ. That happens to hold for every meter observed so far, which is why the
 * recovered config and the live fleet data agree exactly. It is NOT robust: a meter
 * configured with a different exponent will be silently wrong by a power of ten.
 *
 * tb-gateway's Modbus connector cannot express mantissa x 10^exponent. Doing this
 * properly means reading the exponent registers as their own telemetry keys and applying
 * the scaling server-side (ThingsBoard calculated field), or shipping a custom uplink
 * converter. Until then, treat energy and volume totals as provisional and check them
 * against each meter's own display. Do not "tidy" the addresses.
 */
const PFLOW_D116 = {
  deviceType: 'P-Flow D116',
  /** One entry per required byte/word-order combination. */
  registerGroups: [
    {
      byteOrder: 'BIG',
      wordOrder: 'BIG',
      timeseries: [
        { tag: 'CHC_S_VolumeFlow', type: '32float', functionCode: 3, objectsCount: 2, address: 5 },
        { tag: 'CHC_S_Velocity', type: '32float', functionCode: 3, objectsCount: 2, address: 7 },
        { tag: 'CHC_S_TemperatureFlow', type: '32float', functionCode: 3, objectsCount: 2, address: 74 },
        { tag: 'CHC_S_TemperatureReturn', type: '32float', functionCode: 3, objectsCount: 2, address: 76 },
      ],
    },
    {
      byteOrder: 'BIG',
      wordOrder: 'LITTLE',
      timeseries: [
        { tag: 'CHC_M_Volume', type: '32int', functionCode: 3, objectsCount: 2, address: 8 },
        { tag: 'CHC_M_Volume_Neg', type: '32int', functionCode: 3, objectsCount: 2, address: 11 },
        { tag: 'CHC_M_Volume_Net', type: '32int', functionCode: 3, objectsCount: 2, address: 14 },
        // The recovered config had no divider here and would have reported raw kJ. The
        // fleet stores kWh, so the RESI firmware did this scaling. VERIFY against a
        // meter's own display before trusting the absolute value.
        { tag: 'CHC_M_Energy_Heating', type: '32int', functionCode: 3, objectsCount: 2, address: 77, divider: KJ_TO_KWH },
        { tag: 'CHC_M_Energy_Cooling', type: '32int', functionCode: 3, objectsCount: 2, address: 80, divider: KJ_TO_KWH },
      ],
    },
  ],
};

/**
 * Temperature sensor.
 *
 * NOT A MODBUS DEVICE -- this map will stay empty, and that is the correct answer.
 *
 * The original SD card's firmware exposes the temperature sensors only as
 * PT1000_CELSIUS / PT1000_FARENHEIT / PT1000_KELVIN. They are PT1000 resistance
 * thermometers wired into the RESI C4's onboard analog inputs, read through the C4's own
 * IO block -- not meters on the RS485 bus. That is why no Modbus register map for them
 * exists anywhere: there never was one.
 *
 * A Raspberry Pi has no equivalent analog input, so reproducing the fleet's
 * ECO_<HWID>_TS1 / _TS2 devices needs a hardware decision, not a config change:
 *   - an RTD interface board (e.g. MAX31865 over SPI), read by a small local service; or
 *   - a Modbus RTU RTD transmitter on the existing RS485 bus, which is the cheaper fit
 *     for this architecture since the connector then handles it like any other slave.
 *
 * Once that is decided, fill in `registerGroups` (Modbus route) or bypass this module
 * entirely (SPI route). Until then the generator refuses to emit a guessed config.
 */
const TEMP_SENSOR = {
  deviceType: 'Temperature Sensor',
  registerGroups: [],
};

module.exports = { PFLOW_D116, TEMP_SENSOR, KJ_TO_KWH };
