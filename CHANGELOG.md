# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## Unreleased

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

