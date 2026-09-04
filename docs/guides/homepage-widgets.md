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

Vulcan's default:

```yaml
- resources:
    cpu: true
    memory: true
    disk: /media          # the media array, mounted read-only into homepage
- search:
    provider: duckduckgo
    target: _blank
```

`disk:` is a path **inside the homepage container**. `/media` is your
`MEDIA_PATH`, mounted `:ro`. Add more disks by repeating the block.

Vulcan also seeds two extra blocks when the matching services are in your
stack:

- **an upcoming-releases `calendar`** when Radarr/Sonarr/Lidarr are
  enabled (see [Release calendar](#release-calendar) below — it stays
  empty until you add those services' API keys in `services.yaml`);
- **Glances blocks** (`metric: info` + `metric: process`) when the
  `glances` service is enabled (see [Glances](#glances)).

Add other widgets by repeating the pattern:

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

Homepage's `calendar` widget (an info-row widget, so it lives in
`widgets.yaml`) shows upcoming movie/episode releases pulled from
Radarr/Sonarr/Lidarr. Vulcan seeds it automatically when any of those are
enabled:

```yaml
- calendar:
    firstDayInWeek: monday
    view: monthly           # or: agenda
    maxEvents: 10
    integrations:
      - type: sonarr
        service_group: Media Management   # must match the tile's group
        service_name: Sonarr              # must match the tile's name
      - type: radarr
        service_group: Media Management
        service_name: Radarr
```

Each *arr `integration` points at a **tile that already has a working
`widget:` block** (same `type`, with its API key) in `services.yaml` — so
the calendar stays empty until you fill those keys in. `service_group` /
`service_name` are the group heading and tile name exactly as they appear
in `services.yaml`.

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

Enable it, then add blocks to `widgets.yaml`. Vulcan seeds the two
host-agnostic ones for you:

```yaml
- glances:
    url: http://glances:61208
    version: 4
    metric: info            # combined CPU / RAM / swap / load quick-look
- glances:
    url: http://glances:61208
    version: 4
    metric: process         # top processes by CPU
```

The rest need an id that's specific to *your* host — find them in the
Glances web UI (`http://<host>:61208`) or its API, then add one block per
metric:

| `metric:` value | Shows | How to find the id |
|-----------------|-------|--------------------|
| `disk:sda` / `disk:nvme0n1` | read/write rate for that block device | `lsblk`, or the Glances "DISK I/O" panel |
| `fs:/` / `fs:/media` | filesystem usage for a mountpoint | `df -h` |
| `network:eth0` | up/down rate for that interface | `ip -br link`, or Glances "NETWORK" panel |
| `sensor:Package id 0` | temperature / fan for a named sensor | Glances "SENSORS" panel |
| `gpu:0` | GPU load + memory | one per GPU id |
| `cpu` / `memory` | single-stat gauges | — |

Add `chart: false` to any block for a compact number-only readout.

**What works out of the box:** CPU, RAM, load, top processes (via
`pid: host`), all host **disk I/O** (`/proc/diskstats` is host-global),
and **hardware sensors** (Docker mounts `/sys` read-only by default) — all
without extra config. **Host network interfaces and host filesystem usage
do _not_ show** in this routed setup — the container has its own network
namespace, so `network:` sees only `eth0`. If you need per-NIC WAN
throughput, add `network_mode: host` to the `glances:` service in
`stack/docker-compose.yml` (you then lose the Traefik route, same trade-off
netdata makes) — otherwise use the native `resources` widget for array
space and skip `network:`/`fs:`.

`version: 4` matches the `nicolargo/glances:latest` image Vulcan pins (the
widget defaults to the older v3 API and silently shows nothing against a
v4 server). Swap the image tag to `:latest-full` in
`stack/docker-compose.yml` if you want GPU (`py3nvml`) or disk-SMART
sensors — it's ~200 MB larger.

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
