# Migrating a RESI Doctor-Kit gateway — engineer guide

Convert a RESI C4 unit that is **still running its factory software** to the ECO stack,
in place, over a direct Ethernet cable, with one guided terminal tool. Worked example
throughout: kit `DBKIT24EU-0010`.

You need no knowledge of the migration internals. The wizard detects what is already
done and skips it, so it is safe to stop it and run it again.

> **Scope.** Nothing is reimaged and nothing is deleted. The RESI software is *disabled*
> (systemd units masked, reversible with one command), and the ECO stack is installed
> alongside it. The carrier board, meter wiring, SIM and SD card all stay as they are, so
> the unit keeps its hardware identity (HWID) and its ThingsBoard devices keep reporting
> under the same names.

> **The wizard never writes SD cards.** The RESI image in the archive is a restore image
> for one specific unit — it carries that box's hostname and HWID — so it must not be
> written onto a different one. Card restore is a separate, deliberate operation; see
> §9.

---

## 1. What you need

| | |
|---|---|
| Laptop | Windows, with the repo checked out |
| Gateway | A RESI C4 unit, powered on and **running its factory RESI software** |
| Cable | Ordinary Ethernet cable, laptop ↔ gateway. No switch or router needed |
| Credentials | The RESI fleet SSH login (`BOX_SSH_PASSWORD` in `.env`) — used once, then replaced by key auth |
| Access | Office internet on the laptop (Wi-Fi). The **gateway** needs almost none — see §5 |

Time: about **10–15 min**, mostly unattended.

---

## 2. One-time laptop preflight

Run these once; if they all pass, skip to §3.

```bash
node --version
```

Node 18+ is all the migration needs. (`usbipd-win` and WSL 2 are only used by the separate
SD-card tooling in §9, and play no part in this procedure.)

Then check the two things the wizard cannot invent:

```bash
cd provisioning/migrate && node -e "const c=require('./lib/config.js').load(); console.log('tb    :', c.tb.baseUrl); console.log('tskey :', c.tailscale.authkey ? 'set' : 'MISSING'); console.log('boxpw :', c.box.password ? 'set' : 'MISSING'); console.log('key   :', c.box.keyPath || 'MISSING')"
```

```bash
ls -la provisioning/migrate/cache
```

`cache/` must hold the offline artifacts (~240 MB: Docker, the tb-gateway image,
Tailscale, and the web-console wheelhouse/backend/dist). **These are what keep the SIM
out of it,** and they are not in git.

If the folder is empty or a file is missing, the wizard fetches it itself - pinned by
version and verified by sha256 from [artifacts.json](artifacts.json) - but that needs
**office internet and Docker Desktop running**, so do it before you travel, not on site:

```bash
cd provisioning/migrate && node tui.js --kit DBKIT24EU-0010 --skip-tb
```

See [ARTIFACTS.md](ARTIFACTS.md) for what the bundle holds and how to bump a version.

Copy `.env.example` to `.env` and fill it in if `.env` does not exist yet.

---

## 3. Step 1 — cable up and connect

1. Connect the Ethernet cable directly between laptop and gateway.
2. Set the laptop's Ethernet adapter to **automatic (DHCP)**.
3. Make sure the gateway is powered on and has finished booting.

The factory image carries **no Ethernet profile** — only the two GSM ones — so `eth0`
waits for DHCP, finds none, and falls back to a link-local address. Both ends self-assign,
and the unit is found by the mDNS name **`RESI-C4.local`** that its avahi daemon
advertises. `sshd` is enabled in the factory image, so it answers as soon as it is up.

Then start the wizard:

```bash
cd provisioning/migrate && node tui.js --kit DBKIT24EU-0010
```

Its first phase, `connect`, tries in order: `ecoadmin@10.10.10.1` by key (an
already-migrated box), `resi@10.10.10.1` by password (networking done, migration not),
then `RESI-C4.local` with the RESI fleet password. It retries for 5 minutes and prints a
countdown, so you do not have to time the boot.

Link-local **flaps badly** — that is precisely why the next phase pins the box to a
stable `10.10.10.1`. If auto-discovery fails, the wizard tells you how to find the
address by hand and you re-run with `--host <addr>`.

---

## 4. Step 2 — let it run

The wizard started in §3 carries on by itself. Each phase prints one of:

- `⏭ already done — …` — detected as complete, skipped
- `→ …` — running, with the box's own output streamed underneath
- `✓ …` — finished

Two phases ask before acting (they change ThingsBoard, and they stop the RESI software).
Answer `y`. Add `--yes` to accept everything up front and walk away.

If a phase fails it says so and asks whether to carry on. The only unrecoverable one is
`connect` — everything after it needs the box.

### The phases

| Phase | What it does |
|---|---|
| `connect` | Finds the box, picks password or key auth |
| `net` | Puts `eth0` on a fixed **10.10.10.1**, blocks SIM→cable forwarding, stops the box handing your laptop a useless default route |
| `tb` | Reprofiles the ThingsBoard devices and captures the gateway MQTT credentials |
| `ecoadmin` | Creates the `ecoadmin` login and installs your SSH key |
| `standdown` | **Disables, never deletes,** the RESI software (masked systemd units — fully reversible) |
| `scan` | Probes the meter bus for present P-Flow units and the stable `by-id` serial path |
| `artifacts` | Verifies the offline bundles on the laptop |
| `docker` | Installs Docker from the cached tarball, loads the tb-gateway image |
| `config` | Regenerates `tb_gateway.json` + `modbus.json` from the live scan |
| `deploy` | Starts the tb-gateway container |
| `tailscale` | Enrols the unit on the tailnet for remote access |
| `webconsole` | Installs the FastAPI + Vue console on port 80, with per-device secrets |
| `lte` | Restores the fleet's `LTE_*` telemetry (see §6) |
| `verify` | Health, container, live bus reads, LTE sample, access URLs |

The bus scan **refuses to probe while tb-gateway is running**, because two processes on one
RS485 line corrupts live readings. That is deliberate, not a failure.

---

## 5. What actually crosses the SIM

Everything large moves over the Ethernet cable from `cache/`. Over the mobile link the
gateway only does:

- the Tailscale enrolment handshake (a few hundred KB, once);
- its normal MQTT telemetry to `lb-mqtt.pke-iot.expert`;
- the LTE signal telemetry, roughly **40 KB/day**;
- NTP.

**Do not run `apt update` / `apt upgrade` on the gateway.** That is the one easy way to
burn the data allowance, and nothing in this install needs it.

---

## 6. The LTE telemetry

The old RESI software published five keys on the gateway device `ECO_<HWID>_gw` —
`LTE_RSSI`, `LTE_RSRQ`, `LTE_RSRP`, `LTE_SN_RATIO`, `LTE_IP` — and the fleet dashboards
bind to them. They stopped when RESI was stood down. The `lte` phase restores them.

How, in one paragraph: a systemd timer on the host samples `mmcli` every minute and writes
one value per file into the gateway's config directory; tb-gateway's *custom statistics*
feature runs a `cat` on each file inside the container and publishes the results as
telemetry on the gateway device. No second MQTT client, no new bind mount. `-9999` is the
fleet's no-signal sentinel. Pushes go out every 15 minutes; change that with
`LTE_STATS_PERIOD` if needed. Skip the whole thing with `--no-lte`.

---

## 7. Verify

`verify` prints the checks, but to confirm by hand:

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://10.10.10.1/api/health
```

Then open **http://10.10.10.1/** and log in as `ecoadmin`. The password was generated for
this unit and written to two places:

- `provisioning/migrate/out/<KIT>.secrets.json` — everything about this one unit;
- `provisioning/migrate/out/credentials.csv` — **one row per kit**, so doing several units
  back to back leaves a single file to hand over. Re-running a kit refreshes its row
  instead of adding a duplicate.

Both are gitignored. Over Tailscale the console recognises you and needs no login.

In ThingsBoard, the `_PF*` devices should show fresh `CHC_*` values and `ECO_<HWID>_gw`
should show the five `LTE_*` keys within about 15 minutes.

---

## 8. Troubleshooting

**The box is not found.**
Give it 90 s after power-on, then check the cable and that the laptop's Ethernet is on
DHCP. Confirm the unit is actually up and still running RESI (its VNC/Grafana would
answer). You can name the address yourself with `--host RESI-C4.local` or `--host <ip>`.

If mDNS is not resolving, find the link-local address directly — the wizard prints these
same commands when it gives up:

```bash
ping -6 ff02::1%<iface>
```

```bash
netsh interface ipv6 show neighbors
```

Then re-run with `--host "[fe80::...%<iface>]"`. Expect link-local to be flaky — that is
why the `net` phase moves the box to a stable `10.10.10.1` as its very first action.

**The laptop loses internet, or Tailscale goes offline, once connected to the box.**
The box used to hand the laptop a default route it could not use. The `net` phase prevents
this now. If you see it, release and renew the cable adapter:
`ipconfig /release <adapter>` then `ipconfig /renew <adapter>`.

**SSH over Tailscale is refused although `tailscale ping` works.**
Tailscale's own SSH is intentionally left **off** — it would intercept port 22 and needs a
tailnet ACL for the tagged device. The box's real `sshd` plus your key is the supported
path. Do not enable `--ssh`.

**The console's Meters page shows devices as pending, with no values.**
The Modbus connector must run at `DEBUG`, and the setting has to be *inside*
`configurationJson` so it reaches `modbus.json`. Check `provisioning/sites/<KIT>.json`.

---

## 9. Rolling back

The RESI software is **disabled, not deleted** — its systemd units are masked and its files
are untouched, so a unit goes back to factory behaviour without reflashing anything:

```bash
ssh ecoadmin@10.10.10.1 'sudo /usr/local/sbin/eco-downgrade.sh && sudo reboot'
```

That unmasks every service at its original enable-state and restores the root crontab that
launches `RESIvmachine`. ThingsBoard changes from the `tb` phase are recorded in
`out/<KIT>.tb-revert.json`.

### Restoring a card (separate, per-box)

A card image is the last resort, and it is **specific to the unit it came from** — it
carries that box's hostname and the HWID every ThingsBoard device name is built from.
Never write one unit's image onto another. Each archived image has its own README next to
it recording the MBR signature, so cards of the same size can be told apart:

```bash
powershell -File tools/sd.ps1 -Action flash -Image "C:/path/to/<that-box>.img"
```

That needs a **USB** card reader (the laptop's built-in PCIe reader cannot be passed
through to WSL). If a flash reports `Device busy (exported)`, Windows re-mounted the card
first — unplug the reader and plug it back in. If it reports several candidate disks, run
`powershell -File tools/sd.ps1 -Action disks` and pass `-DiskNumber N`.

---

## 10. Handling secrets

`.env` and everything under `out/` and `cache/` hold credentials and are git-ignored.
Never commit them, and do not paste `out/<KIT>.secrets.json` into tickets or chat — pass
the console password to whoever needs it by whatever your team uses for secrets.
