# Connecting to a Gateway On-Site (Ethernet)

How a field engineer reaches the gateway's web console with nothing but a laptop
and an Ethernet cable — no internet, no Wi-Fi, no ThingsBoard, no special software.

There are two ways to reach the same console:

| Path | Who | Auth |
|------|-----|------|
| **Tailscale** (remote) | Office / support, from anywhere | Your Tailscale SSO — no password prompt |
| **Ethernet** (on-site) | Field engineer, standing at the device | The device's `ecoadmin` login — required for **every** page, including meter readings |

This document covers the **Ethernet** path.

---

## Field tutorial (hand this to engineers)

**You need:** a laptop with an Ethernet port (or a USB-Ethernet adapter) and a
standard Ethernet cable. Nothing else.

1. **Plug the cable** from your laptop directly into the gateway's Ethernet port.
2. **Wait ~15 seconds.** The gateway gives your laptop an address automatically
   (you don't configure anything).
3. **Open a browser** and go to:
   - **`http://<gateway-name>.local/`** — the name is on the device label /
     provisioning sheet (e.g. `eco-gw-bench`), **or**
   - **`http://10.10.10.1/`** — the fixed address, the **same on every gateway**.
     Use this if the `.local` name doesn't resolve.
4. The page sends you to a **login** (on-site, every page requires it — meter
   readings included):
   - **Username:** `ecoadmin`
   - **Password:** the device's password from the **provisioning secrets sheet**
     (unique per gateway — it is *not* the same across devices).
5. After login the **Dashboard, Meters, Connector** and all configuration pages
   are available — check meter readings, connector health, system status, and
   make changes.
6. The built-in **Terminal** gives you a host shell as `ecoadmin` using the same
   login — no second password.

### Troubleshooting

- **Page won't load:** turn **Wi-Fi off** so the browser doesn't try to reach the
  device over the wrong network. Confirm the Ethernet link light is on. Try
  `http://10.10.10.1/` instead of the name.
- **`.local` name doesn't resolve** (older Windows / no mDNS): use `http://10.10.10.1/`.
- **Browser warns "Not secure":** expected. It's a local device over plain HTTP on
  an isolated cable. Proceed.
- **Laptop didn't get an address:** unplug/replug the cable, or check that your
  Ethernet adapter is set to *Obtain an IP address automatically* (DHCP), not a
  leftover static IP.
- **Forgot the password:** it's on the per-device provisioning secrets sheet. It is
  **not recoverable from the gateway** — the gateway only stores the hash.

---

## How access is decided

The backend classifies every request by where it came from:

- **Over Tailscale** (source IP in `100.64.0.0/10` / `fd7a:115c:a1e0::/48`): the
  tailnet already authenticated you → full access, no prompt. Requests carry the
  caller's SSO login, so actions are attributable to a person.
- **Over Ethernet** (any other IP, e.g. `10.10.10.x`): treated as **on-site** and
  **not pre-authenticated** — every page, telemetry included, requires the
  `ecoadmin` login.

There is **no anonymous read access** any more. The only endpoint reachable
without auth is `whoami` (it just reports whether you're logged in, so the UI
knows whether to show the login screen). This was tightened for NIS-2: leaving
meter data, connector config and gateway logs readable to anyone who plugs in a
cable was unauthenticated attack surface.

> **Why the on-site subnet is `10.x` and not `100.x`:** the backend treats
> `100.64.0.0/10` as "you're on Tailscale, skip the login." An on-site subnet in
> that range would be misclassified as trusted-remote and bypass the `ecoadmin`
> gate. `10.10.10.0/24` is memorable and safely outside that range.

---

## Technical setup (how the gateway makes this work)

The gateway's Ethernet port is configured so **the gateway owns the link** — it
takes a fixed address and runs its own DHCP + mDNS, so any laptop works on plug-in
without ICS, static IPs, or internet sharing.

Applied by [`provisioning/setup-direct-ethernet.sh`](../provisioning/setup-direct-ethernet.sh):

- NetworkManager connection **`eth0-direct`** on `eth0`, method **`shared`**:
  - fixed address **`10.10.10.1/24`**,
  - NetworkManager's built-in dnsmasq hands out `10.10.10.x` leases (no extra package),
  - **no default route** via eth0 (`ipv4.never-default yes`) — the device's real
    uplink (LTE/Tailscale) is untouched.
- **avahi-daemon** advertises the hostname over mDNS, so `http://<hostname>.local/`
  resolves from the engineer's laptop.
- **nginx** listens on `:80` on all interfaces; the console is served the same way
  over Ethernet as over Tailscale.
- **No internet passthrough.** `shared` mode would also NAT the device's SIM out to
  the cable, so a plugged-in laptop would pull *metered LTE data* through the
  gateway. The setup script blocks this (drops all forwarding from `eth0`, kept
  across reboots by an NM dispatcher). The laptop gets an address and the console,
  but **not** internet — the engineer keeps their own uplink (Wi-Fi) for that.

> **Engineer note:** while the cable is plugged in, your laptop will show the wired
> connection as "No internet" — that's intended. Keep Wi-Fi on for your own
> internet; the cable is only for reaching the gateway.

To (re)apply on a device:

```bash
sudo ./provisioning/setup-direct-ethernet.sh
```

> **Do not** set the port to a static IP inside the *laptop's* subnet (the earlier
> bench used `192.168.137.2` with the laptop running Internet Connection Sharing).
> That only works for one specific laptop and must be reverted before shipping.
