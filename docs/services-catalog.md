# Services Catalog

Every service Vulcan knows how to deploy, one row each, grouped by category. This is the reference for `--services` (custom mode) and the "Customize Services" picker — pick any combination regardless of tier, and Vulcan generates the compose file, resource limits, and (where relevant) Traefik/Homepage wiring for it.

**Tier** below is the lowest tier that includes a service by default; **core** services are on by default at that tier, **optional** ones are opt-in at every tier via custom mode. See [Tiers & Custom Mode](tiers.md).

36 services total, all exercised together on a real 34+ service live-hardware run (see [ROADMAP.md](../ROADMAP.md)) — this list grows as new services are added and verified; open an issue or PR to propose one.

## Media Server

| Service | Tier | Type | What it does |
|---|---|---|---|
| Jellyfin | Light | core | Streams your movie/TV/music library to any device. |
| Seerr | Medium | core | Lets other household members request new movies/shows without touching the management apps directly. |

## Media Management

| Service | Tier | Type | What it does |
|---|---|---|---|
| Radarr | Light | core | Finds and organizes movies. |
| Sonarr | Light | core | Finds and organizes TV. |
| Prowlarr | Light | core | Indexer manager shared by every library-management app below. |
| Recyclarr | Light | optional | Syncs community-maintained quality-profile presets into the library apps. |
| Decluttarr | Light | optional | Clears stalled/failed downloads and retriggers a search. |
| Maintainerr | Light | optional | Cleans up unwatched/unwanted media on your own rules. |
| Bazarr | Medium | core | Finds and manages subtitles. |
| FlareSolverr | Medium | core | Solves CAPTCHA/anti-bot challenges some indexers put up. |
| Lidarr | Heavy | optional | Finds and organizes music. |
| Readarr | Heavy | optional | Finds and organizes books/ebooks. |
| Sportarr | Heavy | optional | Sports PVR — monitors leagues, downloads events/highlights. |

## Downloaders

| Service | Tier | Type | What it does |
|---|---|---|---|
| qBittorrent | Light | core | Torrent client. |
| SABnzbd | Light | optional | Usenet client. |
| MeTube | Light | optional | On-demand downloader for YouTube and hundreds of other sites. |
| Downtify | Light | optional | On-demand Spotify track/playlist downloader (no Premium needed). |

## Live TV

| Service | Tier | Type | What it does |
|---|---|---|---|
| Threadfin | Medium | optional | M3U/IPTV proxy — emulates a tuner so your media server gets live TV. |

## Monitoring

| Service | Tier | Type | What it does |
|---|---|---|---|
| Netdata | Light | optional | Deep real-time host + per-container metrics, its own official recommended config. |
| Glances | Light | optional | Lightweight system monitor; powers per-metric dashboard widgets (CPU/RAM/disk I/O/temp/processes). |
| Tracearr | Medium | optional | Stream analytics for your media server — sessions, bandwidth, watch history. |
| Uptime Kuma | Medium | optional | Uptime monitoring + status pages for every service in the stack. |

## Security

| Service | Tier | Type | What it does |
|---|---|---|---|
| Vaultwarden | Light | optional | Self-hosted password manager. |
| Authelia | Heavy | optional | Login wall (SSO) in front of every routed service, with role-based access. |
| CrowdSec | Heavy | optional | Blocks IPs with a bad reputation at the reverse proxy, before they reach a login page. |

## Infrastructure

| Service | Tier | Type | What it does |
|---|---|---|---|
| Gluetun | Light | optional | VPN client (WireGuard/OpenVPN) — routes a download client's traffic through it. |
| Pi-hole + Unbound | Light | optional | Network-wide DNS ad-blocking with a private recursive resolver. |
| AdGuard Home | Light | optional | Alternative to Pi-hole — DNS ad-blocking with built-in per-client stats. |
| Traefik | Heavy | optional | Reverse proxy — domain-based routing, automatic HTTPS. |
| Tailscale | Heavy | optional | Private mesh VPN for remote access without exposing anything publicly. |
| Cloudflare Tunnel | Heavy | optional | Reach the stack from outside with zero forwarded router ports. |

## Dashboards

| Service | Tier | Type | What it does |
|---|---|---|---|
| Homepage | Light | optional | Pre-seeded start page with a live tile for every other enabled service. |
| Dashy | Light | optional | Second, differently-styled pre-seeded dashboard option. |

## Utilities

| Service | Tier | Type | What it does |
|---|---|---|---|
| FileBrowser | Light | core | Browser-based file manager for the media library (and, with Homepage enabled, its config). |
| Portainer | Light | optional | Web UI for the containers themselves — logs, exec, restart. |
| Watchtower | Medium | optional | Automatic container image updates on a schedule. |
