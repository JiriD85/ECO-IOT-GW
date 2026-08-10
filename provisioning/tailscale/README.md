# Fleet remote access — Tailscale

Remote SSH into ECO gateways over the SIM (CGNAT) via Tailscale, scaling to a commercial
fleet. Traffic is end-to-end WireGuard; the tailnet is used **only** for your ops/SSH —
device telemetry still goes to the MQTT broker directly over the SIM.

## One-time tailnet setup (Admin console — the account owner does this)

1. **Company tailnet**, not a personal account (ownership, DPA, SSO). Enterprise/Business plan.
2. **Access Controls** → paste [`acl.hujson`](acl.hujson). Edit `group:ops` to list your
   colleagues' SSO emails. This defines the `tag:eco-gw` tag, ops→gateway access, gateway
   isolation, and Tailscale SSH.
3. Enable **Tailscale SSH** for the tailnet (Settings) if not already on.

## Enrolling devices

### Test / one-off device
Admin console → **Settings → Keys → Generate auth key**: set **Tags = `tag:eco-gw`**
(reusable optional for a single test). Then on the device:
```bash
sudo ./enroll-gateway.sh <TS_AUTHKEY>
```

### Fleet (per-device keys — DSGVO / customer-device safe)
**Never bake one shared key into customer images.** Instead, hold an **OAuth client** only on
your provisioning infrastructure and mint a **unique, single-use, tagged** key per device:

1. Admin console → **Settings → OAuth clients** → new client with scope
   `auth_keys` (write) and tag `tag:eco-gw`. Store the client id/secret in your secrets
   store (e.g. `.env.local`) — **never commit it**.
2. At provisioning, exchange the OAuth client for a token and create a one-use key:
   ```bash
   TOKEN=$(curl -s -d "client_id=$TS_OAUTH_ID" -d "client_secret=$TS_OAUTH_SECRET" \
     https://api.tailscale.com/api/v2/oauth/token | jq -r .access_token)
   AUTHKEY=$(curl -s -H "Authorization: Bearer $TOKEN" \
     "https://api.tailscale.com/api/v2/tailnet/-/keys" \
     -d '{"capabilities":{"devices":{"create":{"reusable":false,"ephemeral":false,"preauthorized":true,"tags":["tag:eco-gw"]}}}}' \
     | jq -r .key)
   sudo ./enroll-gateway.sh "$AUTHKEY"
   ```
   The key is consumed at join; nothing shared or long-lived remains on the device. Each
   gateway is its own node, individually revocable.

## De-provisioning (kit returned / re-lent / lost)

Run on the device if reachable, then remove it centrally:
```bash
sudo tailscale logout && sudo tailscale down
```
Then Admin console → Machines → remove that node (or via API by node id). This revokes only
that device — the rest of the fleet is unaffected. Do this before a lent kit is re-issued so
the next customer starts clean and the previous device loses all tailnet access.

## Accessing a gateway
From any `group:ops` tailnet node:
```bash
ssh eco@eco-gw-<serial>      # MagicDNS name; or use the 100.x tailscale IP
```

## DSGVO / data protection notes
- Tailscale's coordination server processes device **metadata** (public IPs, node keys,
  hostnames) — **not** traffic content (E2E WireGuard). Sign Tailscale's **DPA**.
- Per-device identity + individual revocation + de-provisioning-on-return cover the
  customer-device lifecycle.
- If EU data-residency forbids US-SaaS metadata processing entirely, self-host **Headscale**
  in the EU — same client + `enroll-gateway.sh` (point `--login-server` at it), you run the
  coordinator.
