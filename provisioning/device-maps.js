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
// l/h the D116 reports on the volume-flow register vs the m3/h the fleet stores.
const LH_TO_M3H = 1000;

/**
 * Each register also carries the CANONICAL key + scaling the tb-gateway ("ECO GW")
 * pipeline emits directly, so the rename/normalize rule-chain layer is unnecessary.
 * `canonical: true` on the generator switches `tag`/`divider` to these. This keeps the
 * raw-CHC_* map and the canonical map in ONE place -- the addresses cannot drift apart.
 *
 * The RESI `Normalize Data` node was the reference for the names and conversions
 * (T_flow_C, Vdot_m3h = VolumeFlow/1000, E_th_kWh = Energy/3600, ...). Heating vs
 * cooling energy is NOT selected here -- the connector cannot read installationType, so
 * both totals are emitted and a `Measurement GW` calculated field picks E_th_kWh.
 */
const PFLOW_D116 = {
  deviceType: 'P-Flow D116',
  /** One entry per required byte/word-order combination. */
  registerGroups: [
    {
      byteOrder: 'BIG',
      wordOrder: 'BIG',
      timeseries: [
        { tag: 'CHC_S_VolumeFlow', type: '32float', functionCode: 3, objectsCount: 2, address: 5, canonicalTag: 'Vdot_m3h', canonicalDivider: LH_TO_M3H },
        { tag: 'CHC_S_Velocity', type: '32float', functionCode: 3, objectsCount: 2, address: 7, canonicalTag: 'v_ms' },
        { tag: 'CHC_S_TemperatureFlow', type: '32float', functionCode: 3, objectsCount: 2, address: 74, canonicalTag: 'T_flow_C' },
        { tag: 'CHC_S_TemperatureReturn', type: '32float', functionCode: 3, objectsCount: 2, address: 76, canonicalTag: 'T_return_C' },
      ],
    },
    {
      byteOrder: 'BIG',
      wordOrder: 'LITTLE',
      timeseries: [
        { tag: 'CHC_M_Volume', type: '32int', functionCode: 3, objectsCount: 2, address: 8, canonicalTag: 'V_m3' },
        { tag: 'CHC_M_Volume_Neg', type: '32int', functionCode: 3, objectsCount: 2, address: 11, canonicalTag: 'V_neg_m3' },
        { tag: 'CHC_M_Volume_Net', type: '32int', functionCode: 3, objectsCount: 2, address: 14, canonicalTag: 'V_net_m3' },
        // The recovered config had no divider here and would have reported raw kJ. The
        // fleet stores kWh, so the RESI firmware did this scaling. VERIFY against a
        // meter's own display before trusting the absolute value.
        { tag: 'CHC_M_Energy_Heating', type: '32int', functionCode: 3, objectsCount: 2, address: 77, divider: KJ_TO_KWH, canonicalTag: 'E_th_heating_kWh', canonicalDivider: KJ_TO_KWH },
        { tag: 'CHC_M_Energy_Cooling', type: '32int', functionCode: 3, objectsCount: 2, address: 80, divider: KJ_TO_KWH, canonicalTag: 'E_th_cooling_kWh', canonicalDivider: KJ_TO_KWH },
        // Exponent registers (one 16-bit signed register each) for the two energy totals,
        // datasheet-confirmed (GENTOS D116, see pflow-d116-register-map). The true total is
        // mantissa x 10^exponent, so the divider on the mantissa above is only correct while
        // these read 0 (they do on every meter seen so far). Exposed as raw keys so a
        // calculated field can apply 10^exp and keep E_th_kWh always in true kWh -- the
        // connector itself cannot combine two registers. Single register => word order N/A.
        { tag: 'CHC_M_Energy_Heating_Exp', type: '16int', functionCode: 3, objectsCount: 1, address: 79, canonicalTag: 'E_th_heating_exp' },
        { tag: 'CHC_M_Energy_Cooling_Exp', type: '16int', functionCode: 3, objectsCount: 1, address: 82, canonicalTag: 'E_th_cooling_exp' },
      ],
    },
  ],
};

/**
 * Rewrite register groups to emit canonical keys instead of raw CHC_* ones.
 * @param {Array} groups a device's `registerGroups`
 * @param {string} [tempTag] override for the single-key temperature tag (TS devices)
 * @returns {Array} groups with `tag`/`divider` swapped to their canonical form
 */
function canonicalizeGroups(groups, tempTag) {
  return groups.map((g) => ({
    ...g,
    timeseries: g.timeseries.map((e) => {
      const { canonicalTag, canonicalDivider, divider, ...rest } = e;
      const tag = e.tag === 'temperature' && tempTag ? tempTag : (canonicalTag || e.tag);
      const out = { ...rest, tag };
      if (canonicalDivider !== undefined) out.divider = canonicalDivider;
      return out;
    }),
  }));
}

/**
 * Temperature sensors -- the RESI C4's onboard AIOX analog inputs (TS1/TS2).
 *
 * FIRMWARE-VERIFIED MAP (decoded from RESI's production SI-BASIC program
 * MCS.DoctorKit.instance -> MB.Handle2RTDSensors, for this exact HWID, 2026-08).
 * This SUPERSEDES the earlier guess (unitId 1 / internal port / holding regs 41064 / x100),
 * which came from a generic Node-RED demo and was NEVER how the field firmware read temps.
 *
 * The two aux RTD sensors are the ONBOARD AIOX, reached as Modbus unit 255 (the C4
 * mainboard's own address) on the SAME external RS485 meter bus as the P-Flows -- NOT a
 * second internal serial port. The firmware issues ONE read:
 *
 *   FC04 (read INPUT registers), unit 255, start address 0, count 8, signed 16-bit
 *
 * and unpacks the 8 registers as two INTERLEAVED sensors (slot 0 = IO01/TS1, slot 1 = IO02/TS2):
 *
 *   reg[0], reg[1]  = T_ACT    (instantaneous degC, value/10)  <- the temperature we publish
 *   reg[2], reg[3]  = T_REAL   (degC, value/10)
 *   reg[4], reg[5]  = T_AVG    (averaged degC, value/10)
 *   reg[6], reg[7]  = T_ERRORS (raw int, non-zero = fault; NOT scaled, NOT sign-extended)
 *
 * So temperature degC = int16(reg[slot]) / 10  (0.1 degC resolution -- divide by 10, NOT 100).
 * There is no sentinel/clamp for a missing sensor; validity is inferred from T_ERRORS.
 *
 * CHANNEL TYPING: the firmware only READS here -- it never sets the AIOX channel type. The
 * channels must already be in RTD/resistance mode (persisted in the mainboard, or set once
 * out-of-band). If reg[0]/reg[1] read as zero/garbage on live hardware, the channels need
 * typing once -- see provisioning/aiox-console-probe.py (Cx console `#255,SIOTYPS:`) or the
 * Modbus TYPE-register path; otherwise no bring-up is needed and TS1/TS2 are just another
 * slave on the existing meter-bus connector. Confirm live with provisioning/aiox-modbus-probe.py.
 */
const AIOX_UNIT_ID = 255;   // C4 mainboard's own Modbus address, on the external meter bus
const RTD_SLOTS = 2;        // slot 0 = IO01/TS1, slot 1 = IO02/TS2
const RTD_DIVIDER = 10;     // firmware scales signed16 / 10 -> degC

const TEMP_SENSOR = {
  deviceType: 'Temperature Sensor',
  unitId: AIOX_UNIT_ID,
  slots: RTD_SLOTS,

  /**
   * Register group for one aux RTD sensor slot, matching MB.Handle2RTDSensors.
   * The T_ACT temperature for slot N is FC04 input register N (0-based).
   * @param {number} slot 0-based sensor slot: 0 = IO01/TS1, 1 = IO02/TS2
   */
  registerGroupsFor(slot) {
    if (!Number.isInteger(slot) || slot < 0 || slot >= RTD_SLOTS) {
      throw new Error(`TS slot must be an integer 0..${RTD_SLOTS - 1} (0=TS1/IO01, 1=TS2/IO02), got ${slot}`);
    }
    return [
      {
        // Single 16-bit register per key, so word order is irrelevant.
        byteOrder: 'BIG',
        wordOrder: 'BIG',
        timeseries: [
          // T_ACT instantaneous temperature. canonicalDivider keeps the /10 through
          // canonicalizeGroups (which otherwise strips a plain `divider`).
          {
            tag: 'temperature',
            type: '16int',
            functionCode: 4,
            objectsCount: 1,
            address: slot,
            divider: RTD_DIVIDER,
            canonicalDivider: RTD_DIVIDER,
          },
        ],
      },
    ];
  },
};

module.exports = { PFLOW_D116, TEMP_SENSOR, KJ_TO_KWH, LH_TO_M3H, AIOX_UNIT_ID, canonicalizeGroups };
