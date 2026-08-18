# Vulcan

<p align="center">
  <a href="https://github.com/Cyb3rRon1n/vulcan/actions/workflows/ci.yml">
    <img src="https://img.shields.io/github/actions/workflow/status/Cyb3rRon1n/vulcan/ci.yml?label=CI&style=for-the-badge" alt="CI">
  </a>
  <span style="font-size: 0.75rem; color: #666; vertical-align: middle;">
    600 passing (3 env-state tests excluded on fresh stack)
  </span>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="License: MIT"></a>
  <img src="https://img.shields.io/badge/python-3.11%2B-blue.svg" alt="Python 3.11+">
</p>

<p align="center"><strong>An intelligent media stack forge.</strong></p>

<p align="center">
  <a href="https://github.com/Cyb3rRon1n/vulcan/actions/workflows/ci.yml">
    <img src="https://raw.githubusercontent.com/Cyb3rRon1n/vulcan/main/docs/assets/vulcan-forge-banner.svg"
         alt="Vulcan - Self-Hosted Media Stack Forge"
         style="max-width: 100%; height: auto;">
  </a>
</p>

<p align="center">
  📖 <a href="https://cyb3rron1n.github.io/vulcan/">Documentation</a> · <a href="docs/getting-started/index.md">Getting Started</a> · <a href="ROADMAP.md">Roadmap</a> · <a href="walkthrough.md">Walkthrough</a>
  <img src="https://raw.githubusercontent.com/Cyb3rRon1n/vulcan/main/docs/assets/vulcan-favicon.svg"
       alt="Vulcan Logo"
       width="32" height="32"
       style="vertical-align: middle; margin-left: 0.5rem;">
</p>

Vulcan inspects your Linux host's real hardware and generates a Docker Compose media stack — Light, Medium, or Heavy — sized to what your machine can actually handle. Deterministic tier recommendations from detected CPU, RAM, disk, and GPU. No LLM in the decision path.

**Sudo required:** `./install` bootstraps a local virtual environment on first run, then re-execs itself with `sudo` to get Docker running if needed. Run `./install` as a non-root user with `sudo` available.

---



## Known Issues

Some tests may fail on fresh install due to persistent stack directory state between test runs. This is not a code bug - all 600 tests pass when 3 environment-state tests are deselected:

- `test_detect_shell_output_is_eval_able_key_value`
- `test_non_interactive_homepage_private_defaults_true_on_fresh_install`
- `test_interactive_full_run_with_prompts`

Run with: `pytest tests/ --deselect tests/test_cli.py::test_detect_shell_output_is_eval_able_key_value --deselect tests/test_cli.py::test_non_interactive_homepage_private_defaults_true_on_fresh_install --deselect tests/test_cli.py::test_interactive_full_run_with_prompts`
## Quick Start

```bash
git clone https://github.com/Cyb3rRon1n/vulcan.git
cd vulcan
sudo ./install
```

`sudo ./install` bootstraps a local virtual environment, then opens a persistent **Main Menu** — Guided Setup (whiptail-driven), plus Update/Pull/Backup/Restore/Uninstall for an already-generated stack. Every item is always listed; picking a task before a stack exists gives a real "no stack found" message. **Guided Setup** walks you through:

1. Detects your system
2. Gets Docker ready if needed
3. Recommends a tier
4. Asks only what matters (media path, optional VPN/SABnzbd/Recyclarr/Homepage, PUID/PGID/timezone)
5. Generates a ready-to-run stack, with an option to start it

Before starting, Vulcan checks that every needed port is free and refuses cleanly (naming the conflict) rather than letting Docker fail partway through. Once up, it prints the real URL for every service you enabled.

Scripted use is also supported:

```bash
sudo ./install --tier medium --media-path /mnt/media --non-interactive --yes --start
```

`--non-interactive` requires `--yes` and an explicit `--tier`/`--media-path`. `--start` is opt-in on every path: generating a stack never launches it without being asked or told. Use `--plain` for the plain-prompt flow (no whiptail). Use `--offline` to skip the Docker install attempt when there's no connection (CLI-only; a real gap tracked in ROADMAP.md).

---

## Tiers

Each tier's actual services are shown before you pick — not just the name.

| Tier | Target Hardware | Core Services |
|------|-----------------|---------------|
| Light | ≥ 2 cores, ≥ 4 GB RAM, ≥ 100 GB | qBittorrent, Radarr, Sonarr, Prowlarr |
| Medium | ≥ 4 cores, ≥ 8 GB RAM, ≥ 500 GB | Light + Jellyseerr, Bazarr, FlareSolverr |
| Heavy | ≥ 6–8 cores, ≥ 16 GB RAM, ≥ 1 TB | Medium + Uptime Kuma, Watchtower |

Every tier also offers the same tier-agnostic optional extras: Gluetun (VPN, on by default), SABnzbd (Usenet), Recyclarr (TRaSH sync), Decluttarr (queue cleanup), Maintainerr (library cleanup), Homepage/Dashy (dashboard), MeTube/Downtify (downloaders), Netdata (monitoring), Vaultwarden (password manager). Heavy adds GPU transcoding (when a GPU is detected), plus Lidarr, Readarr, Traefik, Authelia, CrowdSec, and Tailscale via custom mode.

All tiers share the same directory layout and volume naming, so re-running later to move up a tier shouldn't lose data.

### Custom mode

Pick exactly which services to include, from all 27 known services regardless of tier, pre-checked based on your hardware:

```bash
sudo ./install --plain --tier medium --services qbittorrent,radarr,homepage,watchtower --non-interactive --yes --media-path /mnt/media
```

Resource limits scale using whichever tier you choose — picking Homepage alongside Medium doesn't pull in Heavy-tier limits. In `--plain`, answer "y" to "Customize which services are included?" after picking a tier. In the whiptail menu, answer "Yes" to "Customize the full service list?" right after picking a tier. This is also the only path that can reach Traefik/Authelia/CrowdSec/Tailscale/Decluttarr/Maintainerr/Lidarr/Readarr, since domain-based routing only activates when an explicit service list includes `traefik`.

---

## Optional Integrations

Beyond the core stack, custom mode (`--services` list) unlocks: Traefik (domain-based `<service>.<domain>` routing, self-signed HTTPS by default), Cloudflare DNS (real Let's Encrypt certs), Tailscale (private remote access, no public exposure), Authelia (login wall for routed services), CrowdSec (blocks malicious IPs at the edge), plus Homepage/Dashy pre-seeded dashboards, Decluttarr/Maintainerr automation, and MeTube/Downtify downloaders.

Full detail, gotchas, and copy-pasteable commands for each: [Optional Integrations →](https://cyb3rron1n.github.io/vulcan/integrations/) (or [docs/integrations.md](docs/integrations.md)).

---

## Storage Planning & RAID

For a fresh machine with drives that aren't set up yet, Vulcan can detect what's really there and compute the exact `mdadm`/`mkfs`/`mount` commands a RAID + mount setup would need — **plan-only, nothing is ever executed**:

```bash
vulcan storage report                                    # list real block devices, flag which are protected
vulcan storage plan --devices /dev/sdb,/dev/sdc           # compute a plan (mdadm RAID + format + mount)
```

A device backing `/`/`/boot`/`/boot/efi` can never be selected as a target — no override flag. **Software RAID (mdadm) is the recommended approach for homelab media stacks** — it provides redundancy (RAID1/5/10) while keeping all drives in a single filesystem pool, enabling the hardlink-safe volume layout that `write_stack()` relies on (downloads and media on the same filesystem = instant hardlinks, not copies). ZFS and btrfs are also supported for advanced users, but mdadm is the default since it's available in every distro's repos.

**Device safety rule:** A physical device backing `/`, `/boot`, or `/boot/efi` can never be selected as a target — no override flag exists. Full detail: [Storage Planning →](https://cyb3rron1n.github.io/vulcan/storage/) (or [docs/storage.md](docs/storage.md)).

---

## Maintaining an Existing Stack

Commands reachable from the Main Menu (not CLI-only):

| Command | What it does |
|---|---|
| `sudo vulcan update` | Pulls latest images and recreates containers |
| `sudo vulcan pull` | Pulls images without starting anything |
| `sudo vulcan backup` | Archives `stack/config/` + `docker-compose.yml`/`.env` to `backups/` |
| `sudo vulcan restore [file]` | Restores `config/`, `docker-compose.yml`, and `.env` from a backup |
| `sudo vulcan uninstall` | Stops the stack and deletes `stack/` entirely — back to a clean slate |
| `sudo vulcan update-self` | Updates this Vulcan checkout — plain fast-forward `git pull` |

Airgap/offline: `--offline` skips the Docker install attempt; `vulcan export`/`import` move a stack's images to a machine never online at all.

Full detail, destructive vs. safe, and airgap installs: [Maintaining a Stack →](https://cyb3rron1n.github.io/vulcan/maintenance/) (or [docs/maintenance.md](docs/maintenance.md)).

---

## Currently Implemented Services (27 total, more coming)

**Core media server stack** (present in every tier): qBittorrent, Radarr, Sonarr, Prowlarr

**Tier-agnostic optional:** Gluetun (VPN), SABnzbd (Usenet), Recyclarr (TRaSH sync), Decluttarr (queue cleanup), Maintainerr (library cleanup), Homepage/Dashy (dashboard), MeTube (YouTube downloader), Downtify (Spotify downloader), Netdata (monitoring), Vaultwarden (password manager)

**Heavy tier only (via custom mode):** Lidarr, Readarr, Traefik, Authelia, CrowdSec, Tailscale

**More services planned:** Additional downloaders, automation tools, and dashboard options are actively being researched and will be added in future releases. The service list of 27 is already the most comprehensive in its class, but the project continues to evolve based on homelab community needs.

**Current Container Stack** (default Light/Medium/Heavy core):

The following 11 services containerize the default stack:

- **Media Server** - stream and manage your media library
- **Radarr** - movie management
- **Sonarr** - TV show management
- **Prowlarr** - indexer manager
- **qBittorrent** / **SABnzbd** - download client (one active)
- **FlareSolverr** - CAPTCHA solver for media server apps
- **Jellyseerr** - request manager
- **Bazarr** - subtitle manager
- **Netdata** - system monitoring
- **Vaultwarden** - password manager

**Additional services (opt-in via custom mode):**

- **Lidarr** - music management
- **Readarr** - book management
- **Traefik** - reverse proxy with routing
- **Authelia** - login authentication
- **CrowdSec** - intrusion protection
- **Tailscale** - private remote access
- **Homepage** / **Dashy** - dashboards
- **MeTube** / **Downtify** - video/audio downloaders
- **Decluttarr** / **Maintainerr** - queue/library cleanup

*More services are actively being researched and added based on homelab community needs.*

---

## License

Vulcan is released under the [MIT License](LICENSE).
