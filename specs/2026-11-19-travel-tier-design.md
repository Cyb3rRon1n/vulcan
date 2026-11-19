# Travel tier — design

**Part of:** the travel ("Vulcan Mobile") effort, sub-project 2 of 3. Order: 1 media assistant (shipped) → 2 Travel tier → 3 `vulcan media pack`. A per-architecture offline travel kit (2b) follows Travel v1 as a separate release.

## Goal

A Vulcan stack for people who carry their media: a small box (N100 mini PC or old laptop; Raspberry Pi 5 experimental) that plays from local drives with no internet, is found by name on any network, can drive a TV, and catches up on new media whenever it does get online.

## Decisions

| Area | Decision |
|---|---|
| Shape | A fourth tier, `travel`, chosen explicitly (`--tier travel`, both TUI tier menus). Never auto-recommended; excluded from the hardware ladder in `recommend_tier()` / `_next_tier_up`. |
| Sizing | Container limits sized from the host's detected CPU/RAM; `RESOURCE_LIMITS` gains a `travel` entry so `resource_limits_for` never raises. |
| Core services | Jellyfin (Quick Sync / VA-API on Intel via existing `/dev/dri` wiring), media assistant, Homepage, File Browser. |
| Optional (off by default) | Self-download: Sonarr, Radarr, Prowlarr, qBittorrent behind gluetun. Home sync: Tailscale + `vulcan travel sync`. Kodi kiosk (`--kiosk`). Readers/audiobooks stay ordinary optional services, off. |
| Excluded | Domain, Traefik, Authelia, CrowdSec, Cloudflared, Watchtower, anything home-only. |
| Hardware | x86-64 supported and verified in v1. Raspberry Pi 5 (arm64) documented as experimental until verified on a real Pi (no hardware encoder → direct-play guidance). |

## 1. Tier and services

- `installer/tiers.py`: `TierDefinition("travel", …)` with its own service list (not cumulative with Light/Medium/Heavy); minimums 2 cores / 4 GB / 64 GB.
- `installer/services.py`: `RESOURCE_LIMITS["travel"]` derived from detected cores/RAM.
- `installer/cli.py`: `--tier` help/validation includes `travel`; flags `--kiosk/--no-kiosk`, `--travel-ip IP`, `--hostname NAME` (default `vulcan`); `_SERVICE_DEPS` keeps qBittorrent → gluetun for the self-download group.
- `installer/menu.sh`: "Travel" in both tier menus, then a checklist: Self-download, Sync from home Vulcan, Kodi kiosk.
- State (`.vulcan-state.json`) records tier `travel` and the travel options so re-runs rebuild the same stack.

## 2. Finding the box

- Host: install and enable Avahi (`avahi-daemon`) so the box answers as `<hostname>.local` on any network; `--hostname` sets it (default `vulcan`).
- Homepage tiles and the setup summary link to `http://<hostname>.local:<port>` (no baked-in IP) for the travel tier.
- Optional `--travel-ip`: a second "by IP" link per tile; the guide shows reserving it on a GL.iNet router.
- Jellyfin's published server URL = `http://<hostname>.local:8096`.
- Kodi talks to `localhost:8096`.
- `vulcan doctor`: checks Avahi is running and `<hostname>.local` resolves; plain fix text if not.

## 3. Offline behaviour and catch-up

- Offline-safe stack: pinned image tags, `pull_policy: missing`, no Watchtower; nothing needs the internet to start.
- Media assistant: unchanged commands; new optional systemd timer (`vulcan-media-register.timer`, hourly) running `vulcan media register`, a no-op when nothing is queued.
- Self-download: as on other tiers, with gluetun health checks tolerant of no internet so dependent services idle instead of crash-looping or flooding logs.
- Home sync: Tailscale joins the tailnet (`TS_AUTHKEY`). `vulcan travel sync` pulls new files from the home Vulcan's media folders with rsync over Tailscale SSH — size cap, free-space floor, resumable — into the media assistant's import path; by hand or an optional timer that only acts when the home box is reachable. Watch-history sync is deferred to `media pack`.
- Guide leads with "set it up at home with internet first" (images and posters on the box before the trip).

## 4. Kodi kiosk (optional)

- Host packages: Kodi + the Jellyfin add-on (Debian/Ubuntu x86-64 in v1).
- A `vulcan-kiosk` systemd unit starts Kodi full-screen at boot on a dedicated kiosk user; the add-on is pre-configured for `localhost:8096` with a Jellyfin user Vulcan creates; CEC enabled.
- `--no-kiosk` removes the unit. Atomic/immutable OSes (already detected) get a clear refusal.

## Docs

`docs/guides/travel.md` (kit, set up at home first, finding the box, three ways to catch up, kiosk, Pi experimental) + mkdocs nav; tier table in `docs/tiers.md`; `docs/services-catalog.md` rows; README, ROADMAP, CHANGELOG.

## Testing

- pytest: tier definition and exclusion from recommendations, sizing, generated compose (services, `pull_policy`, no Watchtower), Homepage links (`.local`, optional IP), gluetun offline settings, sync command building (cap, floor, resume flags), kiosk unit content, state round-trip.
- bats: TUI travel entries and checklist.
- Real checks (required before release): generate and run a Travel stack online; cut the network and confirm no crash-loops and Jellyfin plays; `vulcan.local` resolves from another device; a real `vulcan travel sync` from the home Vulcan over Tailscale; Kodi kiosk on a real x86 box with a screen (owner provides).

## Out of scope

Offline travel kit (2b); `vulcan media pack` and watch-history sync (3); Pi 5 full support; the "tiers by purpose" public refresh.
