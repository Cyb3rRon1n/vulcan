# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## Unreleased
### Added
- `vulcan uninstall --prune-docker` — runs `docker system prune -a` after stack
  teardown (opt-in; affects the whole Docker host, not just vulcan's containers)
- Cloudflare Tunnel (`cloudflared` custom-mode service, requires `traefik`) —
  reach the stack from the internet with no forwarded ports at all; points at
  Traefik as its single upstream via a new internal-only entrypoint, additive
  alongside the existing direct port-forward path (28 services total, up from 27)

### Changed
- Development status bumped Pre-Alpha → Beta; version `0.1.0-alpha` → `0.1.0`
- Repo cleanup: removed a stale session-scratch file, trimmed CLAUDE.md's
  Project Status to real architecture facts, fixed malformed README markup

### Fixed
- CI: removed an unused import that had been failing `ruff check .` on every run

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

