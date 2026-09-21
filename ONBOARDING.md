# Onboarding — from `git clone` to a working setup

Written to be followed by a person **or** by an AI coding assistant. Every command is
literal; every step says how to tell whether it worked.

## 0. Understand that this repo is two things

Confusing these is the most common way to waste an afternoon.

| | Runs where | What it is |
|---|---|---|
| **The gateway console** — `backend/`, `frontend/` | *On* the gateway (a Raspberry Pi CM4 in a RESI C4 carrier) | FastAPI + Vue web UI for VPN, LTE modem, RS485/Modbus, Docker, diagnostics |
| **The provisioning tooling** — `provisioning/`, `tools/` | On *your laptop* (Windows) | Installs the console and the ThingsBoard gateway onto a unit, over a direct Ethernet cable |

If you are fixing a UI bug you only need §3. If you are commissioning hardware you need §4.

## 1. What the repo cannot give you

A clone alone is **not** enough to provision a gateway. Ask the team for:

| Thing | Why | Where it goes |
|---|---|---|
| ThingsBoard tenant login | The tooling creates/reprofiles devices | `TB_USERNAME` / `TB_PASSWORD` in `provisioning/migrate/.env` |
| Tailscale auth key (tagged, reusable, non-ephemeral) | Enrols the unit for remote access | `TS_AUTHKEY` |
| RESI fleet default SSH password | Used **once** to install our key on a factory unit | `BOX_SSH_PASSWORD` |
| An SSH keypair for the `ecoadmin` user | All access after bootstrap | `BOX_SSH_KEY` (points at the **private** key; `.pub` is read alongside) |
| Hardware | — | A RESI C4 unit running its factory software, and an Ethernet cable |

None of these are in git, and none should ever be committed. See §6.

## 2. Prerequisites

**These guides assume Windows x86-64**, which is what the team uses. Everything works on
Linux and macOS too *except* card flashing — see §9 for the differences.

Install only what your task needs.

Clone the branch containing the current provisioning and WebUI implementation:

```bash
git clone --branch feat/resi-migration-provisioning-v2 https://github.com/JiriD85/ECO-IOT-GW.git
cd ECO-IOT-GW
```

| Tool | Needed for | Check |
|---|---|---|
| Python 3.11 | backend | `python --version` |
| Node 18+ | frontend, all provisioning tooling | `node --version` |
| Docker Desktop | building the arm64 wheelhouse and pulling the gateway image | `docker version` |
| WSL 2 (Ubuntu) | reading/writing Linux SD cards | `wsl -l -v` |
| `usbipd-win` | passing the USB card reader into WSL | `usbipd --version`, else `winget install usbipd` |
| Git Bash | the shell all `.sh` helpers assume | — |

## 3. Path A — work on the console (no hardware needed)

```bash
cd backend && python -m venv venv && source venv/Scripts/activate && pip install -r requirements.txt
```

```bash
cd backend && uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

```bash
cd frontend && npm ci && npm run dev
```

The frontend serves on **port 3000** and proxies `/api` to `http://localhost:8000` (see
`frontend/vite.config.js`), so run both. Tests:

```bash
cd backend && pytest
```

`pyroute2` and `netifaces` are marked `sys_platform == "linux"` in `requirements.txt`, so
pip skips them on Windows — deliberate, since `netifaces` has no Windows wheels for Python
3.11+ and would try to compile. `network_service.py` import-guards both and falls back to
`psutil`. Do not remove those markers.

**Expect failures in device-facing features on Windows.** The backend shells out to
`systemctl`, `nmcli`, `mmcli`, `docker` and reads `/etc/…`; none of that exists on Windows.
Endpoints that only touch auth, audit or config work fine. For a realistic loop either run
the backend inside WSL, or point the frontend's proxy at a real gateway (`http://10.10.10.1`
on the cable, or its tailnet address) and develop the UI against live data.

Optional: `cp .env.local.example .env.local` — only needed for the "deploy to a Pi over
SSH" snippets in [CLAUDE.md](CLAUDE.md).

## 4. Path B — migrate a gateway

```bash
cd provisioning/migrate && cp .env.example .env
```

Fill `.env` using the table in §1, then confirm the tooling can see everything:

```bash
cd provisioning/migrate && node -e "const c=require('./lib/config.js').load(); console.log('tb    :', c.tb.baseUrl || 'MISSING'); console.log('tbuser:', c.tb.username ? 'set' : 'MISSING'); console.log('tskey :', c.tailscale.authkey ? 'set' : 'MISSING'); console.log('boxpw :', c.box.password ? 'set' : 'MISSING'); console.log('key   :', c.box.keyPath || 'MISSING')"
```

Then build the offline bundle **while you still have office internet** — this is what keeps
the unit's metered SIM out of the install:

```bash
cd provisioning/migrate && node tui.js --kit <KIT> --skip-tb
```

That populates `cache/` (~240 MB) from pinned sources. It is not in git on purpose —
[ARTIFACTS.md](provisioning/migrate/ARTIFACTS.md) explains why and how to bump a version.

From here follow **[ENGINEER-GUIDE.md](provisioning/migrate/ENGINEER-GUIDE.md)**: cable up to
a box still running its factory RESI software and run the wizard. It self-detects what is
already done, so it is safe to stop and re-run.

The wizard never writes SD cards. Card images are per-box restore images (they carry that
unit's hostname and HWID), handled separately by [tools/sd.ps1](tools/sd.ps1).

## 5. Repo map — where to look for what

| Path | What |
|---|---|
| [CLAUDE.md](CLAUDE.md) | Architecture, build commands, deployment paths. **Read first.** |
| [docs/RESI_MIGRATION.md](docs/RESI_MIGRATION.md) | The register map and endpoints. **Read before touching Modbus or ThingsBoard config** — it holds facts that silently corrupt data if guessed. |
| [provisioning/migrate/ENGINEER-GUIDE.md](provisioning/migrate/ENGINEER-GUIDE.md) | Step-by-step install procedure |
| [provisioning/migrate/RUNBOOK.md](provisioning/migrate/RUNBOOK.md) | *Why* each install step exists; verified ground truth |
| [provisioning/migrate/ARTIFACTS.md](provisioning/migrate/ARTIFACTS.md) | The offline bundle, and why it is not committed |
| [provisioning/README.md](provisioning/README.md) | Per-gateway provisioning workflow and device naming |
| [tools/sd.ps1](tools/sd.ps1) | Mount/flash Linux SD cards from Windows |
| [TELEMETRY_KEY_MAP.md](TELEMETRY_KEY_MAP.md), [TELEMETRY_PIPELINE.md](TELEMETRY_PIPELINE.md) | Telemetry keys and where derived values are computed |

## 6. Conventions that will bite you

- **Never commit secrets.** `.env`, `provisioning/migrate/out/`, `cache/`, `credentials.csv`,
  `*.secrets.json` and `*.img` are gitignored. Two checks before proposing a commit — first,
  that no sensitive path is about to be added:

  ```bash
  git ls-files --cached --others --exclude-standard | grep -E '\.env$|credentials\.csv|\.secrets\.json|/cache/|\.img$' && echo "PROBLEM: the paths above must not be committed" || echo "OK - no sensitive paths staged"
  ```

  second, that no key-shaped string sits in a tracked file:

  ```bash
  git grep -nE "tskey-auth-[A-Za-z0-9]{10}|BEGIN [A-Z ]*PRIVATE KEY" -- . || echo "OK - no key-shaped strings"
  ```

  Both are cheap sanity checks over *tracked* files, not a substitute for a real scanner
  (`gitleaks`) if this repo ever goes public.
- **Customer naming.** Only customers named **ECO** or **PKE** may appear in this repo. Real
  kit ids (e.g. `DBKIT24EU-0010`) and hardware IDs are fine. Genericize anything else.
- **The gateway has no WiFi hardware.** The WLAN AP feature was removed; do not reintroduce
  it. `config/dnsmasq/` and `config/nodogsplash/` are leftovers.
- **Line endings are CRLF** on most tracked files. Multi-line search-and-replace that
  assumes `\n` will silently match nothing — use `\r?\n`.
- **GNU tar and Windows paths.** `tar -czf C:/…` fails with `Cannot connect to C: resolve
  failed`, because tar reads `host:path` as a remote archive. Pass relative paths with `cwd`.
- **Windows may be German-locale.** Prefix commands whose output you parse with `LC_ALL=C`.
- **`wsl --mount` cannot use the built-in PCIe card reader.** Use a USB reader; `tools/sd.ps1`
  handles the rest.

## 7. If you are an AI assistant

Read [CLAUDE.md](CLAUDE.md), then [docs/RESI_MIGRATION.md](docs/RESI_MIGRATION.md) before
any change touching Modbus, ThingsBoard or telemetry. Facts there are **not derivable from
this codebase** and guessing them corrupts data silently — for example the MQTT endpoint is
not the ThingsBoard REST host, the P-Flow D116 is mixed-endian and needs two slave entries
per meter, and its totals are mantissa+exponent rather than a constant divider.

Two more habits that matter here: prefer verifying against the live unit over reasoning from
the code (the tooling has a read-only `verify` phase for exactly this), and only publish
changes when the repository owner has explicitly requested it.

## 8. Confirm your setup

```bash
node --version && git --version
```

```bash
cd backend && pytest -q 2>&1 | tail -3
```

```bash
cd frontend && npm run build 2>&1 | tail -3
```

For Path B, the preflight command in §4 should print no `MISSING`, and `cache/` should hold
six files. If a gateway is cabled up, this is the read-only end-to-end check — it changes
nothing on the unit:

```bash
cd provisioning/migrate && node tui.js --kit <KIT> --yes
```

Everything already done reports `⏭ already done`; the final `verify` block prints the
console health, the container state, live Modbus read counts and the access URLs.

## 9. On Linux or arm64 instead of Windows

The migration itself works unchanged. The wizard shells out only to `curl`, `docker`,
`node`, `npm`, `tar`, `ssh` and `scp`, all native on Linux; PowerShell is used in exactly
one place (the laptop's cable-adapter DHCP renew) and it already handles a non-Windows host
by printing the equivalent advice.

What changes:

- **The separate SD-card tooling is Windows-only.** `tools/sd.ps1` and
  `win/Restore-Card.ps1` are PowerShell, and on Linux you do not need them — the kernel
  sees the card directly, so `mount` and `dd` do the job:

  ```bash
  lsblk -o NAME,SIZE,TYPE,MODEL
  ```

  ```bash
  sudo dd if=<that-box>.img of=/dev/sdX bs=4M status=progress conv=fsync && sync
  ```

  Two guards `Restore-Card.ps1` gives you that `dd` does not: make sure the target is the
  card and not your system disk, and write to the **whole device** (`/dev/sdb`), never a
  partition (`/dev/sdb1`). And remember a card image belongs to **one** box.

- **The tar and path traps in §6 do not apply.** They are artifacts of GNU tar on Windows
  drive letters.

On an **arm64** builder (a Raspberry Pi, an Apple-silicon Linux VM) two artifact steps get
simpler rather than harder: the tb-gateway image is a native `docker pull` with no
`--platform` cross-pull, and the wheelhouse is a native build.

**The one real trap on arm64:** the gateway runs Debian 12 / **Python 3.11**, so the wheels
must be `cp311`. A bare `pip download` on a newer distro silently produces `cp312`/`cp313`
wheels that the gateway's venv rejects at install time. Keep the explicit flags — they do
not depend on the host interpreter:

```bash
docker run --rm -v "$PWD/cache:/out" python:3.11-slim bash -c "pip download -d /out/wheelhouse --only-binary=:all: --platform manylinux_2_17_aarch64 --platform manylinux_2_28_aarch64 --python-version 3.11 --implementation cp --abi cp311 -r /out/requirements-lean.txt"
```

No Docker on the builder? `skopeo copy docker://thingsboard/tb-gateway@sha256:<digest> docker-archive:tbgw.tar:thingsboard/tb-gateway:3.7-stable` produces an archive `docker load`
accepts. Docker is the tested path.
