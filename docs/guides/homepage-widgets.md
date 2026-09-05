# Homepage widgets & dashboard tuning

Vulcan seeds two files in `stack/config/homepage/` on the first build and
**never overwrites them** — they're yours to edit. Homepage hot-reloads
on save; no restart needed.

| File | What it holds |
|------|---------------|
| `services.yaml` | the service tiles (name, icon, link) + optional per-service widgets |
| `widgets.yaml` | the info row at the top (resources, network, search) |
| `settings.yaml` | layout, columns, theme (create it yourself) |
| `bookmarks.yaml` | link groups (create it yourself) |

There is **no in-app editor** — Homepage is YAML only. Easiest options:

- **FileBrowser** — if you enable both `filebrowser` and `homepage`,
  Vulcan mounts `stack/config/homepage/` into FileBrowser at
  `homepage-config/` automatically. Open FileBrowser, click a `.yaml`
  file, edit in the browser, save — Homepage hot-reloads. Only the
  Homepage config is exposed, never the rest of `stack/config/` (Authelia
  secrets, VPN keys).
- **Portainer** — good for the *containers* (restart Homepage, read its
  logs, redeploy the stack) but it can't edit arbitrary config files.
- **SSH** — `nano stack/config/homepage/widgets.yaml`, or VS Code Remote.

Full reference: <https://gethomepage.dev/widgets/> and
<https://gethomepage.dev/configs/services/>.

## The top info row (`widgets.yaml`)

Only **info widgets** go here. Vulcan seeds:

```yaml
# without glances:
- resources:
    label: System
    cpu: true
    memory: true
    disk: /media          # the media array, mounted read-only into homepage
    uptime: true
- search:
    provider: duckduckgo
    target: _blank
```

```yaml
# with the glances service in the stack:
- resources:
    label: Array
    disk: /media
    cpu: false
    memory: false
- glances:                # the INFO widget - fixed CPU/RAM/temp view, NO metric:
    label: Host
    url: http://192.168.1.50:61208   # your host's LAN IP, NOT http://glances:61208
    version: 4
    cpu: true
    mem: true
    cputemp: true
    uptime: true
    expanded: true
- search:
    provider: duckduckgo
    target: _blank
```

`disk:` is a path **inside the homepage container**. `/media` is your
`MEDIA_PATH`, mounted `:ro`. Add more disks by repeating the block.

The glances info-widget's `url` does double duty: Homepage fetches data
through it *and* makes the whole widget a link to it (info-widgets have
no separate `href`). So it has to be reachable from your **browser**, not
just from inside the homepage container - use the host's LAN IP and the
published `:61208` port. Vulcan seeds this with the IP it detected; if
detection failed it falls back to `http://glances:61208` (the readout
still works, but clicking the widget goes nowhere - just fix the IP).

> **`calendar` and the metric-based `glances` widget are _service_
> widgets** (`services.yaml`), not info widgets — putting `type: calendar`
> or `metric:` in `widgets.yaml` renders a `Missing …` error. See
> [Release calendar](#release-calendar) and [Glances](#glances) below.

Add other info widgets by repeating the pattern:

```yaml
- resources:
    cpu: true
    memory: true
    disk: /media
    uptime: true
    label: System
- openmeteo:
    latitude: 40.71
    longitude: -74.01
    units: imperial
    cache: 5
```

## Per-service widgets (`services.yaml`)

Each tile can pull live stats from the service's own API. You need that
service's **API key** (usually Settings → General, or the app's config).
Add a `widget:` block under the tile:

```yaml
- Downloads:
    - qBittorrent:
        icon: qbittorrent.png
        href: https://qbittorrent.yourdomain.com
        widget:
          type: qbittorrent
          url: http://gluetun:8080      # "gluetun" not "qbittorrent" when VPN is on
          username: admin
          password: yourpassword

- Media Management:
    - Radarr:
        icon: radarr.png
        href: https://radarr.yourdomain.com
        widget:
          type: radarr
          url: http://radarr:7878
          key: YOUR_RADARR_API_KEY
    - Sonarr:
        icon: sonarr.png
        href: https://sonarr.yourdomain.com
        widget:
          type: sonarr
          url: http://sonarr:8989
          key: YOUR_SONARR_API_KEY
```

Notes:

- **Use the internal container name + port** for `url:` (`http://radarr:7878`),
  not the public `https://radarr.yourdomain.com` — the request is made
  from inside the Docker network and skips Traefik/Authelia.
- **qBittorrent with Gluetun on** — its network namespace belongs to
  `gluetun`, so the widget URL is `http://gluetun:8080`.
- Widget types exist for most of the stack: `sonarr`, `radarr`, `lidarr`,
  `readarr`, `prowlarr`, `bazarr`, `qbittorrent`, `sabnzbd`, `jellyfin`,
  `jellyseerr`, `authelia` (via its API), `traefik`, `netdata`, `glances`,
  `uptimekuma`, `pihole`, `portainer`. Full list on the widgets page.

## Release calendar

Homepage's `calendar` is a **service widget** — it lives in
`services.yaml` under a group, not in `widgets.yaml`. It shows upcoming
movie/episode releases pulled from Radarr/Sonarr/Lidarr. Add a tile:

```yaml
- Media:
    - Upcoming Releases:
        icon: mdi-calendar-clock
        description: Movie & episode release calendar
        widget:
          type: calendar
          view: agenda          # or: monthly
          maxEvents: 12
          showTime: true
          previousDays: 2       # agenda view only
          integrations:
            - type: radarr
              service_group: Media Management   # must match the tile's group
              service_name: Radarr              # must match the tile's name
            - type: sonarr
              service_group: Media Management
              service_name: Sonarr
```

Each *arr `integration` points at a **tile that already has a working
`widget:` block** (same `type`, with its API key) in `services.yaml` — the
calendar reuses that widget's API connection, it has no `url`/`key` of its
own — so it stays empty until you fill those keys in. `service_group` /
`service_name` are the group heading and tile name exactly (case-sensitive)
as they appear in `services.yaml`.

For **maintenance windows / update schedules / anything non-*arr**, add an
`ical` integration pointing at any calendar feed (a Google Calendar's
"secret .ics address", a shared `.ics`, or an *arr app's own Calendar-page
iCal link):

```yaml
      - type: ical
        url: https://example.com/homelab-maintenance.ics
        name: Maintenance
        color: orange
```

Related: **Watchtower** (in the stack) is what actually applies container
updates on a schedule — point it at a notifier for a change log —, and
**Uptime Kuma** has real scheduled *maintenance windows* that suppress
alerts during planned downtime.

## Glances

[Glances](https://nicolargo.github.io/glances/) is an optional Vulcan
service (`--services ...,glances`, or tick it in custom mode). It's a
single lightweight container exposing a REST API that Homepage's `glances`
widget reads for the things the native `resources` widget can't show —
**per-mount disk I/O, per-interface network throughput, hardware sensors,
GPU load, and a live top-processes list**.

The **info widget** (`widgets.yaml`, the CPU/RAM/temp/uptime row) is
seeded for you when glances is in the stack. Everything else is a
**service widget** in `services.yaml` — one tile per `metric:`. A good
"System Stats" group:

```yaml
- System Stats:
    - CPU:
        icon: mdi-cpu-64-bit
        widget: { type: glances, url: http://glances:61208, version: 4, metric: cpu, chart: true }
    - Memory:
        icon: mdi-memory
        widget: { type: glances, url: http://glances:61208, version: 4, metric: memory, chart: true }
    - Processes:
        icon: mdi-chart-gantt
        widget: { type: glances, url: http://glances:61208, version: 4, metric: process }
```

then in `settings.yaml`: `layout: { System Stats: { style: row, columns: 3 } }`.

Other `metric:` values need an id specific to *your* host — find them in
the Glances web UI (`http://<host>:61208`) or its API:

| `metric:` value | Shows | How to find the id |
|-----------------|-------|--------------------|
| `cpu` / `memory` / `process` / `containers` | host-agnostic, always work | — |
| `disk:sda` / `disk:nvme0n1` | read/write rate for that block device | `lsblk`, or the Glances "DISK I/O" panel |
| `fs:/` / `fs:/media` | filesystem usage for a mountpoint | `df -h` |
| `network:eth0` | up/down rate for that interface | `ip -br link` |
| `sensor:Package id 0` | temperature / fan for a named sensor | Glances "SENSORS" panel |
| `gpu:0` | GPU load + memory | one per GPU id |

Add `chart: false` to any block for a compact number-only readout.

**What works in the default routed setup:** `cpu`, `memory`, `process`,
`containers`, all host **disk I/O** (`disk:<dev>` — `/proc/diskstats` is
host-global via `pid: host`), and the **info widget's `cputemp`**
(`/sys` is mounted read-only by Docker; use `cpuSensorLabel:` to pick the
sensor, e.g. `Core 0` or `Package id 0`). **`sensor:` service tiles,
`network:` and `fs:` do _not_ work** here — Homepage's proxy blocks the
`/api/4/sensors` endpoint, and the container has its own network namespace
so `network:`/`fs:` see only the container. For per-NIC WAN throughput or
`sensor:` tiles, add `network_mode: host` to the `glances:` service in
`stack/docker-compose.yml` (you then lose the Traefik route, same
trade-off netdata makes).

`version: 4` matches the `nicolargo/glances:latest` image Vulcan pins (the
widget defaults to the older v3 API and silently shows nothing against a
v4 server). Swap the image tag to `:latest-full` in
`stack/docker-compose.yml` if you want GPU (`py3nvml`) or disk-SMART
sensors — it's ~200 MB larger.

## Layout, tabs & theme (`settings.yaml`)

Create `stack/config/homepage/settings.yaml` to control how the groups
from `services.yaml` are arranged. Group **order**, **column count**, and
**which tab** a group sits on are all set here — not in `services.yaml`.

```yaml
---
title: My Media Server
theme: dark
color: slate                # slate gray zinc blue teal cyan indigo violet …
headerStyle: boxedWidgets    # underlined (default) | boxed | clean | boxedWidgets
useEqualHeights: true
hideVersion: true

background:                  # a URL or a file under a mounted /app/config/images
  image: https://images.unsplash.com/photo-1502790671504-542ad42d5189?auto=format&fit=crop&w=2560&q=80
  blur: sm                   # none xs sm md lg xl 2xl 3xl
  brightness: 40             # 0 50 75 90 100 …
cardBlur: sm

layout:
  # a group gets a `tab:` -> shows only on that tab. Tabs appear once any
  # group has one. Groups with no `tab:` show on every tab.
  Media:            { tab: Media,  style: row, columns: 3 }
  Media Management: { tab: Media,  style: row, columns: 4 }
  Downloads:        { tab: Media,  style: row, columns: 3 }
  System Stats:     { tab: System, style: row, columns: 3, header: false }
  Monitoring:       { tab: System, style: row, columns: 3 }
  Security:         { tab: Admin,  style: row, columns: 3 }
  Infrastructure:   { tab: Admin,  style: row, columns: 3 }
```

`style: row` + `columns: N` makes a group tile N-wide instead of a tall
stack. `header: false` hides a group's heading. Every group name here must
match a group in `services.yaml` (or a bookmark group in `bookmarks.yaml`).

## Docker status dots (optional)

To show running/stopped on each tile, mount the socket read-only —
add to the `homepage:` service in `stack/docker-compose.yml`:

```yaml
      - /var/run/docker.sock:/var/run/docker.sock:ro
```

then per tile:

```yaml
        docker: radarr        # the container_name
```

## Applying changes

`widgets.yaml` / `services.yaml` edits reload live. If you added the
socket mount (a compose change), recreate the container:

```
docker compose -f stack/docker-compose.yml --env-file stack/.env up -d homepage
```
