# Lightweight console and local Modbus live view

This change is repository-only. The running kit was inspected over Tailscale/SSH;
no configuration, service, container, polling interval or firmware was changed.

## What changed

- Meters and temperature sensors are the overview. `/meters` redirects there.
- Native HTML/CSS and Vue render login, navigation and the dashboard. Vuetify
  management forms load only when opened. SVG icons replace the 403 KB WOFF2
  font; terminal code remains a separate lazy chunk. No external fonts/CDNs.
- One authenticated WebSocket sends an initial snapshot and subsequent patches.
  Patches contain changed fields/readings, including sample times; unchanged
  numeric values and units are omitted. Each client merges by device name/tag.
  Reconnect always receives a complete replacement snapshot.
- A 25-second heartbeat detects broken connections; the browser retries with
  backoff, refreshes an expired password token and closes the stream when hidden,
  paused or navigated away. Stale/unverified readings never appear as live.
- A single backend task observes local snapshots while viewers exist. It checks
  once per second, caches JSON by inode/mtime/size, and shares updates through
  bounded queues. A slow client cannot accumulate an unlimited backlog.
- Static hashed assets have one-year immutable caching; HTML revalidates.
  Build-time gzip files avoid compression CPU on the Pi. API data remains
  private. Selected configuration requests share a short session-memory cache,
  invalidated on writes and logout. System health is sampled on entry rather
  than continuously running expensive connectivity checks.
- Tailscale identity now trusts `X-Real-IP` only from a loopback proxy and fails
  closed when whois cannot resolve an identity. WebSockets require same origin
  and authenticate before sending telemetry. Tokens travel in the first frame,
  never in the URL. Authorization is rechecked at least every 25 seconds.

## Local data path

`gateway/extensions/eco_modbus/live_modbus.py` subclasses the **installed/pinned
3.7.8 AsyncModbusConnector implementation**. Its read hook observes existing
responses and calls the existing uplink decoder with the configured byte order,
word order and divider. It does not open a port or add a competing bus master.
The hook runs before conversion batching, report strategy filtering, storage and
MQTT. Cloud connectivity is not an input to local state.

One atomic JSON file per connector is written to a **shared tmpfs directory**.
Do not place these frequent snapshots on the SD card. The web backend reads
these snapshots and the active connector inventory; it does not parse logs.
INFO logging is sufficient. Debug-log dependence has been removed, rather than
silently falling back to an unreliable source.

Physical P-Flow groups with different word orders merge by device name. AIOX
channels with the same unit address remain separate by device name. Individual
readings retain their own sample time; a fresh temperature cannot make an old
flow reading look fresh. A failed poll retains last known numbers but changes
connection state. If observation stops, devices become unverified after
`max(15, 2.5 * poll_period_seconds + 10)` seconds. A complete failed poll changes
state on the next stream update, normally within one second.

The firmware-verified AIOX fault registers 6/7 are now included in generated
sensor maps, without temperature scaling. A successful board response alone
does not prove a probe is connected. Nonzero fault flags display **Sensor fault**;
missing/stale fault information leaves probe state unverified. P-Flow cumulative
energy/volume values retain the configured decoding: the previously documented
mantissa/exponent/unit limitation is not resolved by this UI change.

**Live means every completed configured Modbus poll**, not a faster sampling
frequency. This change does not alter poll periods. A stopped gateway cannot
produce new measurements, even though a cloud outage alone does not prevent
local observation.

## Prepare a future deployment (do not run against the kit yet)

Use the existing pinned image, not the untested root Compose file's `latest` tag.
The installed image inspected during this work has methods
`_AsyncModbusConnector__read_slave_data` and `_AsyncModbusConnector__poll_device`.
The observer was imported in memory against that installed implementation;
neither a connector nor a bus client was instantiated. Recheck these private
hooks before upgrading the ThingsBoard image.

1. Build locally: `cd frontend && npm ci && npm run build`. The build also checks
   that every gzip file exactly matches its final asset and that dashboard
   JS/CSS stays below 100 KB compressed.
2. Prepare a **local copy** of the kit's generated config and extension directory:
   `python tools/prepare-live-telemetry.py <staged-config-dir> <staged-extension-dir>`.
   It preserves `.pre-live` copies, changes Modbus connector registration to
   `type: modbus`, `class: AsyncModbusConnector`, copies the extension and adds
   the AIOX fault tags. It preserves serial/poll/upload settings. These config
   files can contain credentials: keep them in the existing ignored staging area.
3. During the separately approved rollout, install the staged extension beneath
   `/thingsboard_gateway/extensions/modbus/live_modbus.py` in the container
   (also mounted at the legacy `extensions/eco_modbus` path),
   and the staged config beneath `/thingsboard_gateway/config`. These underscore
   paths were verified on the kit; the old root Compose file uses different paths.
4. Create host `/run/eco-telemetry` with ownership allowing the gateway container
   to write and the backend to read (0750; use the actual container UID/GID).
   `/run` must be tmpfs. Arrange recreation on boot with systemd-tmpfiles **before
   the gateway container starts**. Bind the host directory to the same container
   path `/run/eco-telemetry`. Docker must use a host bind, not a private container
   tmpfs, so the host backend can read it. `ECO_LIVE_DIR` overrides the location.
5. Install the backend and complete `frontend/dist` together. Keep previous
   content-hashed assets during an upgrade until open old browser sessions have
   been refreshed; otherwise old lazy-route imports can 404. A failed deployment
   should restore the old frontend/backend and the `.pre-live` connector config.
6. Recreate/restart only during the approved maintenance window. A container
   mount change requires recreation. Retain all existing volumes, devices,
   environment and privileges; do not substitute the root Compose file.

If deploying behind nginx, forward WebSocket Upgrade/Connection headers for
`/api/meters/stream`, preserve Host/Origin, and use a timeout longer than the
heartbeat. The current direct Uvicorn deployment needs no reverse proxy changes.

## Validation

Run from repo root:

```text
backend/.venv/Scripts/python -m pytest tools/tests/test_live_ui.py -q
npm --prefix frontend test
npm --prefix frontend run build
```

The targeted tests avoid starting the existing Linux-only terminal/watchdog
services. They cover zero readings, disconnect/reconnect, stale samples, shared
addresses, fault flags, partial deltas, cache invalidation, auth/origin checks,
one shared observer task, and compressed conditional responses. They are not a
substitute for the untouched inherited suite or hardware acceptance.

`tools/preview-ui.py` runs a loopback-only simulation on port 4173 using the real
meter WebSocket router. It is explicitly labelled as simulated, uses synthetic
values and overrides auth **only inside that preview process**. Never deploy it.
The production bundle contains no demo data or anonymous-auth bypass.

Before hardware rollout is accepted:

- Check fresh P-Flow values against the meter display, including zero flow and
  both word-order groups. Compare timestamps against bus poll completion.
- Unplug/replug a meter; verify no-response, retained stale values and recovery.
- Disconnect each RTD probe while its AIOX board remains online; verify the
  correct channel's fault flag and recovery, with no cross-channel mixing.
- Interrupt ThingsBoard connectivity while leaving the bus running; verify
  fresh local values continue and recover cloud transport without a UI reload.
- Stop/restart the connector and backend; verify stale state and stream recovery.
- Test a slow/metred connection and two viewers. Confirm one shared watcher,
  no repeated `/api/meters/latest` requests, and no asset transfers on warm navigation.
- Verify password expiry/logout and Tailscale identity checks on the real host.
- Measure Pi CPU, memory and actual LTE byte counts; local build sizes are not a
  hardware performance measurement.

## Company branding and download budget

The default logo is a local 479-byte company SVG supplied by the user; no company-site/CDN requests occur at runtime. The light/dark palette follows report-hub frontend/app/globals.css at commit c4d694db03b5716a757f43337801999b6938f4f9: neutral surfaces, blue controls and a white default SVG in dark mode. Kit name, custom logo and favicon remain editable in System administration. The small SVG is bundled into the hashed JavaScript and shares its immutable asset cache.

The dashboard code and CSS are about 74.1 KB gzip, including the bundled SVG logo (rounded) (excluding API data and HTTP overhead). The original entry JS/CSS were 697/826 KB uncompressed plus a 403 KB icon font, about 1.9 MB with the old non-gzip serving configuration. Management screens load additional cached chunks on first use. These are build measurements, not Pi CPU or live cellular traffic measurements.

## Browser telemetry history

Dashboard trends retain up to 30 minutes of received numeric readings in tab memory and sessionStorage on navigation/pagehide. Storage is scoped to the gateway origin and tab; closing the tab normally discards it. History is limited to 6 devices, 32 tags each and 360 points per tag (5-second buckets). No history API, polling, server storage or chart dependency is added. Stale/disconnected samples are not recorded; long sampling gaps break the line. Each trend auto-scales to its observed range; hover exposes range and duration. Fault registers remain represented by sensor status rather than charts. Serial configuration and system metrics are available in their management pages.

The local preview emits simulated samples once per 60 seconds; this does not change hardware polling configuration. Flow and return temperatures share one compact column and graph, leaving volume total in the same row.

## Management preview audit

Browser-checked Network failover/VPN, Modem/Serial, ThingsBoard, System settings/NTP/Backup/Admin, Monitoring diagnostics/audit/SMS, Connector, Containers and Terminal. Restored the shell-provided notification callback used by six legacy management pages. Verified a rejected Serial save shows its error and the simulated Terminal connects. The preview now overrides the meter HTTP authentication dependency consistently with its simulated WebSocket identity; this fixes the Connector redirect to Login without changing production authentication. Preview fixture APIs provide correctly shaped empty/demo data. Mutation endpoints return 501; the terminal never executes commands. Real device operations and real password login remain hardware integration checks.


## Installing release 2.0.0 with the migration TUI

Use the current checkout and run `node provisioning/migrate/tui.js --kit <kit-name>` when the kit is connected for maintenance. Do not use `--skip-artifacts` with old cached bundles: it now refuses archives not verified against the current source. The normal artifact phase rebuilds the frontend and backend archive when the source changes; npm dependencies and missing vendor bundles are obtained on the laptop. The Pi install uses the transferred offline artifacts.

On an existing kit, the new `live-telemetry` phase prepares a copy of its actual active configuration, preserves polling/cloud/statistics settings, installs the observer, and recreates the container with the same image ID, device mappings, environment, volumes (including anonymous volumes), resource limits and restart policy. It requires the provisioned host-network layout and a tmpfs `/run`. A tmpfiles rule recreates the shared directory at boot. A failed recreation restores the original configuration and container. A successful upgrade retains the stopped previous container with restart disabled and a protected configuration backup beside the active config directory.

The web console upgrade retains `/opt/eco/webui/previous` and existing hashed frontend assets. It records `/opt/eco/webui/release` after `/api/health` succeeds. A failing application check restores the prior backend/dist. The Python environment is shared; this is application-file rollback, not a complete OS/dependency rollback. No firmware, OS image or gateway image update is included.

Local verification: targeted Python service/stream/installer tests, Node UI/cache/history/artifact tests, production build/gzip budget and shell syntax checks. The inherited `backend/tests` collection is blocked in this Windows environment by missing Docker Python dependency; its terminal module also requires Linux `fcntl`/PTY. Real daemon behavior and hardware acceptance remain the checklist above.
