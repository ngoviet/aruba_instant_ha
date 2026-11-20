# Aruba Instant for Home Assistant

<!-- readme-axi type=ha -->

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz/docs/faq/custom_repositories/)
[![GitHub release](https://img.shields.io/github/v/release/ngoviet/aruba_instant_ha)](https://github.com/ngoviet/aruba_instant_ha/releases)
[![Validate](https://github.com/ngoviet/aruba_instant_ha/actions/workflows/validate.yml/badge.svg)](https://github.com/ngoviet/aruba_instant_ha/actions/workflows/validate.yml)
[![Test](https://github.com/ngoviet/aruba_instant_ha/actions/workflows/test.yml/badge.svg)](https://github.com/ngoviet/aruba_instant_ha/actions/workflows/test.yml)
[![License: MIT](https://img.shields.io/github/license/ngoviet/aruba_instant_ha)](LICENSE)

**English** · [Tiếng Việt](README.vi.md)

See every Wi-Fi device of an **Aruba Instant** (IAP) cluster in Home Assistant: which access point it is on,
signal, band, SSID, PHY speed. Also the client count and channel utilization of each AP.

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=ngoviet&repository=aruba_instant_ha&category=integration)

> 🇻🇳 Built and maintained by one person in Việt Nam — if it saves you time, please
> [support the project](#support-the-project).

## Features

- Reads the same API the Instant web UI uses (`https://<ap>:4343/swarm.cgi`) — **the REST API does not need to
  be enabled** and nothing is changed on the cluster (read-only).
- Finds the cluster **master** by itself among the APs you list (member APs only see their own clients) and
  follows it when the cluster elects a new master.
- Reuses one admin session and logs out on unload (Instant limits the number of admin sessions).
- Optional: if [routeros_ha](https://github.com/ngoviet/routeros_ha) is installed, device names come from the
  **DHCP lease comments** on your MikroTik router instead of Wi-Fi host names like `wlan0` or `espressif`.
- No extra dependencies, UI setup, re-authentication, options, diagnostics, English and Vietnamese UI.

## Supported devices

Tested on a cluster of 3 × **IAP-335**, Instant 8.x. Requires **Home Assistant 2026.9** or newer.

## Installation

**HACS**: HACS → ⋮ → *Custom repositories* → `https://github.com/ngoviet/aruba_instant_ha`, type
*Integration* → install **Aruba Instant** → restart Home Assistant.

**Manual**: copy `custom_components/aruba_instant_ha` into `/config/custom_components/` and restart.

## Configuration

**Settings → Devices & services → Add integration → Aruba Instant**

| Field | Description |
|---|---|
| AP addresses | IP of the APs, comma-separated (e.g. `192.168.10.51, 192.168.10.52, 192.168.10.53`). One is enough if it is always the master; listing all of them survives a master change |
| Port | `4343` (Instant web UI) |
| Verify SSL certificate | Leave off for the default self-signed certificate |
| Username / Password | The Instant web UI admin account |

Options: update interval (default 60 s, 30–600 s).

## Entities

| Entity | Type | Notes |
|---|---|---|
| **Aruba Instant · Clients** | sensor | Total Wi-Fi devices. Attributes: `clients` (list below), `ssids` (`{ssid: count}`), `aps` (per AP: IP, client count, radios), `conductor` (master IP). The list attributes are **not recorded** |
| **&lt;AP&gt; · Clients** | sensor | Devices on that AP |
| **&lt;AP&gt; · 2.4 GHz / 5 GHz utilization** | sensor (%) | Channel busy time of the radio. Attributes: `channel`, `power_dbm`, `noise_dbm` |

Each item of `clients`: `name` (DHCP lease comment if available, else host name), `hostname`, `ip`, `mac`, `os`,
`essid`, `ap`, `channel`, `band` (`2.4` / `5`), `phy` (`GN`, `AC`…), `signal`, `quality` (`good` / `ok` / `poor`),
`speed_mbps`.

### Per-AP and per-device detail (every 5 minutes)

Every 5 minutes the integration also asks each AP (through the master, `ip=` parameter, still read-only)
for its client table, virtual beacon report, radio statistics, BSS table, ap-env and neighbour list. One
failing AP never fails the main update: it keeps its previous numbers with `stale: true`. The keys below
are **additive** and may be missing (other firmware, failing AP); existing keys are unchanged.

- Added to each client: `retry_pct` (retransmit share since association), `retry_5m` (last 5 minutes,
  from counter deltas), `tx_rate` / `rx_rate` (Mbps), `tx_kbps` / `rx_kbps` (traffic over the last
  5 minutes), `health` (raw `Client health (C/R)` from the AP), `stuck_24` (5 GHz-capable device on 2.4 GHz
  of an SSID that offers 5 GHz), `louder_ap` + `louder_gain` (another AP hears this weak device ≥ 10 dB
  louder — "heard louder", not where it will necessarily go).
- Added to each radio in `aps.*.radios`: `busy_64s`, `retry_pct`, `retry_5m`, `resets`, `resets_per_day`,
  `bcmc_pct`, `pinned`, `set_channel`, `set_power`, `cochannel` (foreign BSS on the same channel),
  `cochannel_loudest` (dBm). Added to each AP: `uptime_s`, `stale`.
- New sensor attributes: `alerts` (list of `{code, …}`: `radio_resets`, `radio_retry`, `open_network`,
  `louder_ap`, `stuck_24`, `detail_failed`) and `detail_updated` (when the detail was read). Not recorded.

## Wi-Fi card (bundled since 0.3.0)

Installing the integration also gives you `custom:aruba-wifi-card`: the integration serves the JS file and loads it
into the frontend itself, **no resource to add**, and the card always matches the integration version (reload the
page after upgrading).

```yaml
type: custom:aruba-wifi-card
entity: sensor.aruba_instant_clients   # the cluster's "Clients" sensor
title: Wi-Fi
group_by: ap      # ap | ssid | band
sort: name        # name | signal (weakest first) | speed
```

- Per AP: channel and channel-busy % of each radio, `↻ %` retry, `⟳ resets/day`, uptime, warning when two APs share
  a channel. Chips filter by SSID / band.
- Cluster alert row (radio resets often, high retry, strong open network, devices on a far AP…).
- Per device: signal bars, band, speed, SNR; at most 2 badges (`→T3 +37` another AP hears it louder, `↻44%` retry
  over the last 5 minutes ≥ 30 %, `5G?` 5 GHz-capable device on 2.4 GHz). **Tap a tile** for the detail panel.
- Other keys: `ssid`, `band` (initial filter), `collapse` (`auto` / `true` / `false`), `language`.

This card used to live in [lan-topo-card](https://github.com/ngoviet/lan-topo-card) as `custom:lan-wifi-card`; the
old name keeps working there for a while — switch dashboards to `custom:aruba-wifi-card`.

## Troubleshooting

- **Only part of the clients show up** — member APs only see their own clients; the integration needs to reach
  the cluster master. List all APs in *AP addresses* so it can follow a master change.
- **SSL errors** — the Instant web UI uses a self-signed certificate by default; leave *Verify SSL certificate* off.
- **Device names look like `wlan0` or `espressif`** — those are Wi-Fi host names; install
  [routeros_ha](https://github.com/ngoviet/routeros_ha) to use the DHCP lease comments from your MikroTik router.
- **Admin sessions** — Instant limits the number of admin sessions; the integration reuses one session and logs
  out on unload.
- When reporting an issue, attach the integration's **diagnostics** (*Devices & services → Aruba Instant → ⋮ →
  Download diagnostics*).

## Development

```bash
pip install -r requirements_test.txt
pytest
```

Tests run on Linux (Home Assistant does not run on Windows).

<!-- support:start -->
## Support the project

<p align="center">
  <img src="https://raw.githubusercontent.com/ngoviet/.github/main/assets/support/banner-v2.svg" width="560" alt="Built and maintained by one person in Việt Nam">
</p>

<p align="center">Free and open source. Your support pays for new device support, faster fixes and every release.</p>

<p align="center">
  <a href="https://buymeacoffee.com/ngoviet"><img src="https://raw.githubusercontent.com/ngoviet/.github/main/assets/support/btn-coffee.svg" height="56" alt="Buy me a coffee"></a>
  &nbsp;
  <a href="https://github.com/sponsors/ngoviet"><img src="https://raw.githubusercontent.com/ngoviet/.github/main/assets/support/btn-sponsors.svg" height="56" alt="GitHub Sponsors"></a>
</p>

<p align="center">
  <img src="https://raw.githubusercontent.com/ngoviet/.github/main/assets/support/vietqr-card.svg" width="300" alt="VietQR — MB Bank — NGO DUC VIET — 911051212">
  &nbsp;
  <img src="https://raw.githubusercontent.com/ngoviet/.github/main/assets/support/crypto-card.svg" width="300" alt="Crypto — BNB Smart Chain (BEP20) — 0xcbf0402b232cb24b4d998f09a4884f87b5f74750">
</p>

<p align="center"><b>Crypto wallet, BNB Smart Chain (BEP20) only:</b><br><code>0xcbf0402b232cb24b4d998f09a4884f87b5f74750</code></p>

<p align="center">🇻🇳 VietQR: scan with any Vietnamese banking app, transfer note <code>Ung ho aruba_instant_ha</code>. Thank you for keeping this project alive!</p>
<!-- support:end -->

## License

[MIT](LICENSE) © Ngô Đức Việt. Not affiliated with HPE Aruba Networking; the icon is an original design.
