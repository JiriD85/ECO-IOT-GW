# The offline install bundle — and why it is not in git

The wizard installs a gateway without the unit downloading anything over its metered SIM.
That means ~240 MB of binaries have to be on the laptop before you go on site. They live in
`provisioning/migrate/cache/`, which is **gitignored**.

## What is in the bundle

| File | Size | Where it comes from | Pinned by |
|---|---|---|---|
| `tbgw-3.7-stable-arm64.tar.gz` | 93 MB | `docker pull` + `docker save` of `thingsboard/tb-gateway:3.7-stable` | **image digest** |
| `docker-29.7.2.tgz` | 74 MB | download.docker.com static aarch64 engine | sha256 |
| `tailscale_1.102.2_arm64.tgz` | 35 MB | pkgs.tailscale.com | sha256 |
| `webconsole-wheelhouse.tgz` | 17 MB | `pip download` of arm64 wheels from PyPI | `requirements-lean.txt` |
| `webconsole-dist.tgz` | 3 MB | `npm run build` of this repo's frontend | this repo |
| `webconsole-backend.tgz` | 0.1 MB | `backend/app` from this repo | this repo |

## The decision: do not commit them

Four reasons, in order of how much they would hurt:

1. **Git history is forever.** Every re-cached version adds another full copy of a ~90 MB
   binary that can never be removed without rewriting history and breaking every clone. Bump
   the tb-gateway image three times and the repo is a permanent ~400 MB download for
   everyone, including CI.
2. **GitHub's hard limit is 100 MB per file.** `tbgw-3.7-stable-arm64.tar.gz` is already
   93 MB. The next image version very plausibly exceeds it, and the push would simply be
   rejected — a bad thing to discover mid-release.
3. **This repo is public.** Committing vendor binaries republishes Docker's, Tailscale's and
   ThingsBoard's builds under our name. Pointing at the upstream URL is both cleaner and
   always current on security fixes.
4. **They are all reproducible.** Four come from pinned public sources, two are built from
   this repo. Nothing in the bundle is unique to us.

## What we do instead

[`artifacts.json`](artifacts.json) pins the exact version, URL and hash of every external
piece, and the wizard's `artifacts` phase fetches whatever is missing:

```bash
cd provisioning/migrate && node tui.js --kit <KIT> --skip-tb
```

It downloads to a `.part` file, checks sha256, and only then renames — so an interrupted
download can never masquerade as a good artifact. The tb-gateway image is pulled **by
digest** (`thingsboard/tb-gateway@sha256:7cb0f3a6…`) because `docker save` output is not
byte-reproducible: the digest is the immutable thing, not a file hash.

Requirements: office internet and Docker Desktop running (needed for the image pull and for
the arm64 wheelhouse, which is built inside a `python:3.11-slim` container).

### Bumping a version

1. Edit the version/URL in `artifacts.json` and set its `sha256` to `null`.
2. Delete the old file from `cache/`.
3. Run the wizard's artifacts phase. It prints the hash it downloaded.
4. Paste that hash into `artifacts.json` and commit **the manifest only**.

## If you do want the bundle versioned

Sometimes you want a frozen bundle an engineer can grab without Docker or a build
toolchain. In that case, still not git — pick one of:

| Option | Good for | Watch out for |
|---|---|---|
| **GitHub Releases** *(recommended)* | A tagged, downloadable `field-kit-vN.zip`; assets up to 2 GB; does not touch clone size | Manual upload step per release |
| **Git LFS** | Keeping it feeling like part of the repo | On a public repo LFS bandwidth is metered (1 GB/month free) and every clone pulls it; adds a hard `git lfs` dependency for anyone cloning |
| **Shared drive / SharePoint** | Field engineers who just want a folder to copy | Not versioned with the code, drifts silently |

If you take the Releases route: zip `cache/` after a successful fetch, attach it to a tag
matching the manifest versions, and note the tag in the engineer guide. Reproducibility
still comes from `artifacts.json`; the release is only a convenience mirror.

## Before you travel

`cache/` is the thing you cannot rebuild without internet. Copy it to the field laptop (or
a USB stick) along with the repo, and confirm it is populated:

```bash
ls -la provisioning/migrate/cache
```

## Also gitignored, for the same "never commit" reasons

- `provisioning/migrate/.env` — TB, Tailscale and box credentials
- `provisioning/migrate/out/` — per-kit generated configs, `*.secrets.json`, and
  `credentials.csv` (the fleet credential ledger)
- `*.img`, `*.img.zst` — raw SD card images; the RESI backup alone is 29.7 GB
