# Reinstalling a RESI Doctor-Kit gateway — engineer guide

Take a RESI C4 unit back to its **original factory SD card image**, then reinstall the ECO
software stack on it with one guided terminal tool. Worked example throughout: kit
`DBKIT24EU-0010`.

You need no knowledge of the migration internals. The wizard detects what is already
done and skips it, so it is safe to stop it and run it again.

> **Scope.** This replaces only the SD card. The RESI C4 carrier board, the meter wiring
> and the SIM stay as they are, so the unit keeps its hardware identity (HWID) and its
> ThingsBoard devices keep receiving data under the same names.

---

## 1. What you need

| | |
|---|---|
| Laptop | Windows, with the repo checked out |
| Card reader | **USB** reader — a hub with an SD slot is ideal. The laptop's *built-in* PCIe reader does not work for this (see Troubleshooting) |
| SD card | ≥ 32 GB, same size or larger than the image. **Its contents are destroyed.** |
| Image | The RESI backup, e.g. `C:\Users\<you>\sdcard\sd-card.img` (~29.7 GB raw) |
| Cable | Ordinary Ethernet cable, laptop ↔ gateway. No switch or router needed |
| Access | Office internet on the laptop (Wi-Fi). The **gateway** needs almost none — see §6 |

Time: about **15 min of flashing** plus **10–15 min of install**, mostly unattended.

---

## 2. One-time laptop preflight

Run these once; if they all pass, skip to §3.

```bash
node --version
```

```bash
usbipd --version
```

```bash
wsl -l -v
```

Node 18+, `usbipd-win`, and a running WSL 2 distro are all required. Install the middle
one with `winget install usbipd` if it is missing.

Then check the two things the wizard cannot invent:

```bash
cd provisioning/migrate && node -e "const c=require('./lib/config.js').load(); console.log('image :', c.resiImage); console.log('tb    :', c.tb.baseUrl); console.log('tskey :', c.tailscale.authkey ? 'set' : 'MISSING'); console.log('boxpw :', c.box.password ? 'set' : 'MISSING')"
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

## 3. Step 1 — flash the card

Put the card in the USB reader, then:

```bash
cd provisioning/migrate && node tui.js --kit DBKIT24EU-0010 --flash
```

The wizard will:

1. mount the card and **tell you what is currently on it** (its hostname), so you can
   confirm you are erasing the right card;
2. ask you to type `ERASE` — nothing is written before that;
3. pick the target disk automatically (a multi-slot hub reports its empty slots as 0-byte
   disks; those are ignored), refusing anything too small for the image;
4. ask for one **UAC prompt**, then write the image (several minutes — the system/boot
   disk can never be selected).

You can also flash on its own, without starting an install:

```bash
powershell -File tools/sd.ps1 -Action flash -Image "C:/Users/<you>/sdcard/sd-card.img"
```

---

## 4. Step 2 — cable and power

When the wizard says the image is written:

1. move the card into the gateway;
2. connect the Ethernet cable directly between laptop and gateway;
3. make sure the laptop's Ethernet adapter is set to **automatic (DHCP)**;
4. power the gateway on;
5. press Enter in the wizard.

The factory image ships **no Ethernet profile** — only the two GSM ones — so on first boot
`eth0` waits for DHCP, finds none, and falls back to a link-local address. The unit is
found by its mDNS name **`RESI-C4.local`**, which its avahi daemon advertises; `sshd` is
enabled in the image, so it answers immediately.

Allow **60–90 s** after power-on. The wizard retries for 10 minutes and prints the
countdown, so you do not have to time anything.

---

## 5. Step 3 — let it run

The wizard already started in §3 continues on its own. If you flashed separately, start it
with:

```bash
cd provisioning/migrate && node tui.js --kit DBKIT24EU-0010
```

Each phase prints one of:

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
| `flash` | Writes the RESI image (only with `--flash`) |
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
| `lte` | Restores the fleet's `LTE_*` telemetry (see §7) |
| `verify` | Health, container, live bus reads, LTE sample, access URLs |

The bus scan **refuses to probe while tb-gateway is running**, because two processes on one
RS485 line corrupts live readings. That is deliberate, not a failure.

---

## 6. What actually crosses the SIM

Everything large moves over the Ethernet cable from `cache/`. Over the mobile link the
gateway only does:

- the Tailscale enrolment handshake (a few hundred KB, once);
- its normal MQTT telemetry to `lb-mqtt.pke-iot.expert`;
- the LTE signal telemetry, roughly **40 KB/day**;
- NTP.

**Do not run `apt update` / `apt upgrade` on the gateway.** That is the one easy way to
burn the data allowance, and nothing in this install needs it.

---

## 7. The LTE telemetry

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

## 8. Verify

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

## 9. Troubleshooting

**"No USB mass-storage reader found", or the card never appears in WSL.**
The laptop's **built-in Realtek PCIe reader cannot be used** — neither `wsl --mount` nor
usbipd can pass it through. Use a USB reader.

**`Device busy (exported)` when attaching the card.**
Windows re-mounted the card first. **Unplug the reader and plug it back in**; the tooling
waits for it and then attaches. (Deliberately not solved with `usbipd bind --force`, which
would take the reader away from Windows entirely.)

**"several candidate disks — pass -DiskNumber".**
Two cards are readable. Run `powershell -File tools\sd.ps1 -Action disks`, identify the
right one, and pass `-DiskNumber N`.

**The box is not found after power-on.**
Give it 90 s. Then check the cable and that the laptop's Ethernet is on DHCP. You can name
the address yourself with `--host RESI-C4.local` or `--host <ip>`; the wizard also prompts
for it once it runs out of patience.

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

## 10. Rolling back

The RESI software is **disabled, not deleted** — its systemd units are masked and its files
are untouched, so a unit can be returned to factory behaviour without reflashing.
ThingsBoard changes made by the `tb` phase are recorded in
`out/<KIT>.tb-revert.json`. And the card image itself is the ultimate fallback: reflash and
start again.

---

## 11. Handling secrets

`.env` and everything under `out/` and `cache/` hold credentials and are git-ignored.
Never commit them, and do not paste `out/<KIT>.secrets.json` into tickets or chat — pass
the console password to whoever needs it by whatever your team uses for secrets.
