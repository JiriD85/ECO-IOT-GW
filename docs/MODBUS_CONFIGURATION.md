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

ThingsBoard's desired connector envelope should retain `type: eco_modbus` and
`class: EcoModbusConnector`. A stock-modbus cloud edit is normalized locally to
protect the live view, so its envelope can differ from ThingsBoard's desired
envelope even when the device mappings match. The platform's generic/advanced
connector editor may be needed for the custom type.

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
Subsequent installations skip initial seeding for the same gateway, preserving
later cloud edits and local overrides. Removing the marker explicitly requests
reseeding; do not do this casually.

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
