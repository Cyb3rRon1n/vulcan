# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## Unreleased

### Added
- **`vulcan userdata export` / `restore`** — rebuild-proof snapshots of every Jellyfin user's favorites, 👍/👎, watched status and resume points (keyed by TMDb/TVDb/IMDb ids), plus Seerr requests; restore is a dry run unless `--apply`. Needs `JELLYFIN_API_KEY` in `stack/.env`.
- **Off-box backups** — set `BACKUP_OFFSITE_TARGET` (rsync over SSH) and `vulcan backup` also copies `backups/` + `exports/userdata/` there; a failed copy exits 2 without touching the local backup.
- **Byparr** (optional) — maintained, Firefox-based drop-in FlareSolverr replacement; Suwayomi prefers it automatically. Runs fully hardened (verified solving a real Cloudflare challenge under `cap_drop: ALL`).
- **Whisper** (optional, requires Bazarr) — faster-whisper speech-to-text so Bazarr can generate subtitles when no provider has any.
- **Reading** service category with **Komga** (comic/manga/ebook reader + OPDS), **Suwayomi** (self-hosted Tachiyomi/Mihon — browse + download manga), **Mylar3** (comic/manga PVR), and **LazyLibrarian** (ebook/audiobook PVR, the maintained Readarr alternative). Kavita moved into it.
- **slskd** (Soulseek music client) — searchable from Lidarr via the `Lidarr.Plugin.Slskd` plugin (needs Lidarr on the `nightly` tag), or standalone. Pre-seeded `slskd.yml` with a generated web password + Lidarr-plugin API key.
- **Guacamole** (optional) — browser-based RDP/VNC/SSH gateway: web app, guacd, its own Postgres (runs as PUID so `vulcan backup` captures your connections) on a private internal network, and a one-shot schema writer; admin-only behind Authelia, generated DB password kept across rebuilds.
- Homepage tiles open the right sub-path (`/guacamole/`, Threadfin's `/web/`), and qBittorrent's tile uses its domain route behind Gluetun.
- 47 known services.

### Fixed
- **Intel GPU false positive on servers.** Detection matched "intel" and "vga" anywhere in `lspci`, so a Xeon board (Intel chipset + ASPEED BMC video, no transcoding hardware) was treated as an Intel GPU — passing a useless `/dev/dri` to Jellyfin and skipping its no-GPU CPU scaling. Now the VGA/3D/display line itself must be Intel.
- **CrowdSec was blind.** Hardened Traefik (`cap_drop: ALL`) couldn't open its PUID-owned access log and failed silently, so CrowdSec read nothing; Traefik now gets `DAC_OVERRIDE` when CrowdSec is enabled. Through a Cloudflare Tunnel every visitor also looked like the cloudflared container's private IP: the tunnel entrypoint now trusts `X-Forwarded-For` from private (container) addresses and the bouncer reads the real client IP. The bouncer tolerates 2 failed decision pulls (`updatemaxfailure=2`) instead of blocking all traffic whenever CrowdSec restarts.

### Changed
- **Walkthrough overhaul** — fixed three wrong instructions (Jellyfin has no built-in 2FA; *arr apps are connected from Prowlarr's Settings > Apps, not "Sync with Prowlarr"; qBittorrent's first login is a temporary password in its log) and two wrong host paths (MeTube/Downtify). Exact root folders, download-client host (`gluetun` behind the VPN), Seerr/Bazarr/Jellyfin setup that actually works, and new steps for music & reading, monitoring (incl. verifying CrowdSec reads traffic), and backups.
- **Jellyfin gets CPU headroom for software transcoding** on hosts without a GPU: a quarter of the logical CPUs, never below the tier value, capped at 12.
- **Netdata is reachable at `netdata.<domain>`** — it runs on the host network, which Traefik's docker provider can't route, so vulcan now generates a Traefik file-provider route (`config/traefik/dynamic/netdata.yml`, rewritten every build).
- **Watchtower's metrics API is on** (token generated into `stack/.env` as `WATCHTOWER_API_TOKEN`) for Homepage's watchtower widget — see the widgets guide.
- **Lidarr uses the `nightly` image when slskd is enabled** — the slskd plugin needs Lidarr's plugins branch. Back up `config/lidarr` before switching an existing Lidarr (one-way DB migration).
- **Vulcan now honours `stack/docker-compose.override.yml`** everywhere it runs Compose (`start`, `update`, `restore`, `pull`, `export-images`, the menu's per-service restart) and in the start command `build` prints. Before, every call passed `-f stack/docker-compose.yml` alone, which makes Compose skip the override — so `vulcan update` recreated containers without your local changes and could orphan override-only services.
- **Watchtower no longer auto-updates stateful/infra services** — Jellyfin, Vaultwarden, Authelia, Traefik, Cloudflared, CrowdSec, Gluetun, Unbound and Pi-hole carry `com.centurylinklabs.watchtower.enable=false`; update them with `vulcan update`.
- **qBittorrent (behind Gluetun) and Pi-hole are routed through Traefik again** — their routers now live on `gluetun`/`unbound`, since Traefik skips containers that share another's network namespace. Pi-hole gets a Homepage tile (Infrastructure).
- **`vulcan backup` includes `docker-compose.override.yml` and `.vulcan-state.json`** when present, so a restore brings back local changes and saved install choices.
- **Netdata's Docker collector is disabled** via a seeded `config/netdata/config/go.d.conf` — it kept `dockerd`+`containerd` at ~6 cores on a 45-container host; per-container charts are unaffected.
- Walkthrough: keeping local changes in `stack/docker-compose.override.yml` (and starting without `-f` so it loads), and checking what a rebuild changes before applying it.
- Gluetun gains a `CHOWN` capability (silences a `/tmp/gluetun/forwarded_port` chown error; required by the port-forwarding service) and a commented-out ProtonVPN/PIA port-forwarding block in the template — uncomment it if torrents stall at "downloading metadata" on a connected tunnel. Walkthrough documents the fix.
- Mylar3 is pre-seeded so it listens on all interfaces (LSIO default binds loopback only, making the published port unreachable).
- Kavita drops `authelia@docker` (crowdsec only), same as Komga — its own multi-user auth + OPDS feed break a browser forward-auth redirect.
- FlareSolverr setup note points at Byparr as a drop-in swap for indexers it can't solve (see `docs/integrations.md`).

## v0.2.0 - 2026-08-18
### Added
- `vulcan uninstall --prune-docker` — runs `docker system prune -a` after stack
  teardown (opt-in; affects the whole Docker host, not just vulcan's containers)
- Cloudflare Tunnel (`cloudflared` custom-mode service, requires `traefik`) —
  reach the stack from the internet with no forwarded ports at all; points at
  Traefik as its single upstream via a new internal-only entrypoint, additive
  alongside the existing direct port-forward path (28 services total, up from 27)

### Changed
- Development status bumped Pre-Alpha → Beta
- Repo cleanup: removed a stale session-scratch file, trimmed CLAUDE.md's
  Project Status to real architecture facts, fixed malformed README markup
- README simplified (185 → 132 lines): dropped the test-count badge and the
  whole "Known Issues" section (redundant with CONTRIBUTING.md, one claim
  was stale), removed a fully-duplicate services listing, added a Main Menu
  screenshot
- About tagline no longer names Jellyfin/*arr specifically (pyproject.toml,
  mkdocs.yml, GitHub's About field, docs/index.md) — "self-hosted media
  homelab" instead, functional docs left untouched since those need the
  real service names

### Fixed
- CI: removed an unused import that had been failing `ruff check .` on every run
- `menu.sh`'s NEWT_COLORS: unfocused buttons/checkboxes/list rows used the
  same color as the dialog background (invisible), fixed for every
  interactive whiptail element
- Gluetun's walkthrough section had no real VPN provider setup steps; added
  ProtonVPN/NordVPN/Mullvad/Surfshark (sourced from gluetun-wiki), plus a
  new optional `WIREGUARD_ADDRESSES` var some providers need
- Restored per-browser Bitwarden extension install links, lost when the
  root `walkthrough.md` was deleted during the docs-site split
- Cloudflare DNS record + API token setup steps were entirely missing from
  the walkthrough despite the CLI flags being documented; added real steps
- README's CI badge rendered a different size than License/Python (mismatched
  shields.io style param); main-menu.svg mockup was missing a real menu item

## v0.1.0
### Added
- Guided install with system detection
- Tier determination (Light/Medium/Heavy)
- Docker Compose stack generation
- Port conflict resolution (SABnzbd/MeTube 8081→8082)
- Prune clean feature (`docker system prune -a` at install start)
- 17 services configured and enabled by tier
- Optional services: Gluetun VPN, SABnzbd, Recyclarr, Decluttarr, Maintainerr
- Homepage/Dashy dashboards, MeTube, Downtify, Netdata
- Vaultwarden password manager
- Progress panels for every menu operation
- Interactive RAID level picker
- Disk space measurement against real media filesystem

### Changed
- Media server terminology throughout documentation
- Repository branding and README cleanup
- Documentation simplification (5 files, ~800 lines removed)
- vulcan CLI `--version` flag added
- Project URLs (homepage, repository) in pyproject.toml

### Fixed
- Chown media mount after provisioning (write_stack permission denied)
- Test isolation documentation (3 env-state tests excluded)

### Deprecated
- None

### Removed
- None

### Security
- None

## Future Versions
- v0.2.0 planned features: GPU passthrough automation, web config editor,
  Traefik reverse proxy with Authentik/CrowdSec, plugin system

