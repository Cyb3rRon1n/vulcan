# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

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

