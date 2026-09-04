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

There is **no in-app editor** — Homepage is YAML only. Edit over SSH
(`nano`, VS Code Remote), or point FileBrowser / a code editor at the
directory.

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
`MEDIA_PATH`, mounted `:ro`. Add more disks by repeating the block, or add
other widgets:

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
  `jellyseerr`, `authelia` (via its API), `traefik`, `netdata`,
  `uptimekuma`, `pihole`, `portainer`. Full list on the widgets page.

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
