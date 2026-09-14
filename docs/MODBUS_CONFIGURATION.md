# Modbus configuration

The `/connector` page reads active connector files from `TB_GATEWAY_CONFIG_DIR`.
It groups PFlow byte-order entries into physical devices and exposes register
tables, profile-based additions, manual mappings, and temporary local changes.
The dashboard still uses the existing gateway poller; this editor never opens
the serial port. No tenant credentials or external website dependencies are
added to the Raspberry Pi or browser.

## Local overrides

The local device editor exposes the read interval and response timeout. Changes apply to every register group for that physical device, so both PFlow byte-order groups remain synchronized.

Saving validates the complete device list, checks the revision read by the
editor, retains unrelated configuration, backs up the previous file, and writes
atomically. The gateway's existing file watcher reloads it (normally within 60s),
including when MQTT is unavailable. The UI distinguishes a pending file from
the last configuration loaded by the observer. Matching a previous load is not
proof that the container is currently running or the sensor is connected.

PFlow profiles keep separate BIG/LITTLE word-order groups. PT1000 profiles refer
specifically to the kit's AIOX inputs at address 255, FC4 registers 0/1 and fault
registers 6/7. Choosing an address does not change the physical device's address.
Profile data in `backend/app/services/modbus_profiles.json` is generated from
`provisioning/device-maps.js`; tests ensure both stay identical. Existing PFlow
total exponent/unit limitations described in that source still apply.

The guard in `EcoModbusConnector` wraps Gateway 3.7.8's remote connector handler.
Accepted Modbus updates always use the installed observer class, including new
cloud-created Modbus connectors. After application it caches the cloud config in
`.eco-cloud-<file-hash>.json`. The local editor can restore that last received
configuration offline. It does not fetch a newer cloud configuration itself.
Changes from ThingsBoard may replace local overrides under the gateway's native
timestamp rules; newer cloud edits win. Local saves do not write shared attributes.
The native active-connectors list remains cloud-controlled.

The observer also carries two compatibility fixes for the pinned Gateway and
Pymodbus versions. Serial reconnects close a stale asyncio transport under the
shared master lock before reopening `/dev/meterbus`, preventing the connector
from competing with its own exclusive port handle after an unanswered address.
Standard integer and floating-point registers use Pymodbus's supported
`convert_from_registers` API; uncommon manual types retain the Gateway decoder.
Keep the associated runtime tests when upgrading either dependency.

ThingsBoard's connector envelope uses `type: modbus` and the standard class name
`AsyncModbusConnector`, enabling its Basic/Master Connections editor. The pinned
gateway loader searches `extensions/modbus` before bundled connectors; that
directory exports our observer under the standard class name. Cloud edits that
omit `class` therefore retain local readings and runtime fixes. The legacy
`extensions/eco_modbus` mount remains available during migration. Do not deploy
the new registration without the Modbus extension mount.

## Initial installation

After installing the observer, `tui.js` runs a fatal `connector-sync` phase:

1. Export the actual installed files privately over SSH. Do not regenerate them
   from a stale site file or use a cloud clone as the installed-state reference.
   Verify its MQTT credentials match the selected ThingsBoard gateway device.
2. Back up existing shared attributes in ignored provisioning output (contains
   credentials), then publish installed connector envelopes, the active list,
   general configuration and available storage/gRPC/logging configuration.
3. Enable remote configuration and restart the existing container.
4. Wait up to 180 seconds for fresh client-attribute reports with matching active
   connectors, observer type/class and device mappings.
5. Only after acknowledgement write `.eco-sync.json` with the gateway device ID.

Observer staging disables remote configuration on the first installation, before
old shared attributes can replace the prepared files. If acknowledgement fails,
the wizard attempts to disable remote configuration again and stops. It leaves
the published desired configuration for inspection/retry and retains the backup.
Subsequent installations with the same gateway marker verify that ThingsBoard
still has an active, remotely controlled connector configuration and that Modbus
uses the native Modbus type. Missing or incomplete cloud configuration is backed up
and synchronized again. Valid later ThingsBoard edits remain authoritative. The
initial synchronization still requires an exact, fresh client report before the
marker is accepted. This ensures that the first run after setting `gateway=true`
creates the connector attributes instead of merely trusting the device flag.

The following fatal `gateway-relations` phase resolves the device names in active
Modbus mappings and creates missing gateway → device `Created`/`COMMON` relations.
It is idempotent, preserves asset `Contains` relations, and refuses devices already
linked to another gateway. Only configured devices are linked, excluding unused
legacy kit devices such as TS3. Existing device IDs and telemetry history remain.

The marker also carries a connector schema version. Version 2 performs a one-time
migration from the early duplicated raw/canonical mappings to canonical-only
telemetry and installs the standard inventory: PFlow 1–4 at addresses 88/80/81/82
and the two onboard temperature inputs. The installer backs up the active connector
directory before this migration. Once version 2 is acknowledged, later runs again
preserve cloud and local edits.

New site config builds retain configured devices even when discovery cannot see
them. Existing deployed inventories are preserved during upgrades; use the editor
to add missing devices. Unplugged-device recovery and shared-bus behavior still
require hardware acceptance testing before production rollout.

## Verification

For remote updates, `tui.js` first uploads the small requirements file and runs
pip's offline dry-run against the installed environment. When all dependencies
(including requested extras) are already satisfied, it skips the wheelhouse SCP
transfer. The installer repeats that check before replacing application files.
Missing/incompatible dependencies retain the full offline-wheelhouse path.
The install script accepts `-` as its wheelhouse argument for verified reuse;
its fifth argument is the release's requirements file.

Local tests cover profile parity, four PFlows/two inputs, manual-field retention,
revision conflicts, invalid writes, offline restoration, cloud guard application,
observer preservation and initial-sync acknowledgement. The loopback preview has
an isolated temporary configuration sandbox. No hardware or cloud writes are
performed by these tests.

Remote acceptance on RESI-C4 (2026-09-13) verified dependency reuse, service health,
Tailscale authentication, matching ThingsBoard connector acknowledgement, a fresh
local Modbus WebSocket delta and continued ThingsBoard PFlow telemetry using the
kit's existing gateway image and device mappings. One PFlow responded; the two
AIOX temperature inputs reported fault codes 129 and 1. The legacy configuration
also exposes both raw CHC and canonical PFlow fields. The dashboard now recognizes
fleet `_PF1` through `_PF4` names and hides a legacy field when its canonical
equivalent is present, without changing values or ThingsBoard mappings.
Physical unplug/reconnect recovery and simultaneous operation of all four PFlows
still require hardware acceptance testing.
