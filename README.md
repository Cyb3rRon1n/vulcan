# Vulcan

<p align="center">
  <a href="https://github.com/Cyb3rRon1n/vulcan/actions/workflows/ci.yml"><img src="https://github.com/Cyb3rRon1n/vulcan/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="License: MIT"></a>
  <img src="https://img.shields.io/badge/python-3.11%2B-blue.svg" alt="Python 3.11+">
</p>

<p align="center"><strong>An intelligent media stack forge.</strong></p>

<p align="center">
  📖 <a href="https://cyb3rron1n.github.io/vulcan/">Documentation</a> · <a href="docs/getting-started/index.md">Getting Started</a> · <a href="ROADMAP.md">Roadmap</a>
</p>

Vulcan inspects your Linux host's real hardware and generates a Docker Compose media stack — Light, Medium, or Heavy — sized to what your machine can actually handle. Deterministic tier recommendations from detected CPU, RAM, disk, and GPU. No LLM in the decision path.

---

## Quick Start

```bash
git clone https://github.com/Cyb3rRon1n/vulcan.git
cd vulcan
./install
```

`./install` bootstraps a local virtual environment, then opens a persistent **Main Menu** — Guided Setup (whiptail-driven), plus Update/Pull/Backup/Restore/Uninstall for an already-generated stack. Every item is always listed; picking a task before a stack exists gives a real "no stack found" message. **Guided Setup** walks you through:

1. Detects your system
2. Gets Docker ready if needed
3. Recommends a tier
4. Asks only what matters (media path, optional VPN/SABnzbd/Recyclarr/Homepage, PUID/PGID/timezone)
5. Generates a ready-to-run stack, with an option to start it

Before starting, Vulcan checks that every needed port is free and refuses cleanly (naming the conflict) rather than letting Docker fail partway through. Once up, it prints the real URL for every service you enabled.

Scripted use is also supported:

```bash
./install --tier medium --media-path /mnt/media --non-interactive --yes --start
```

`--non-interactive` requires `--yes` and an explicit `--tier`/`--media-path`. `--start` is opt-in on every path: generating a stack never launches it without being asked or told. Use `--plain` for the plain-prompt flow (no whiptail). Use `--offline` to skip the Docker install attempt when there's no connection (CLI-only; a real gap tracked in ROADMAP.md).

---

## Tiers

Each tier's actual services are shown before you pick — not just the name.

| Tier | Target | Core Services |
|------|--------|---------------|
| Light | ≥ 2 cores, ≥ 4 GB RAM, ≥ 100 GB | Jellyfin, Radarr, Sonarr, Prowlarr, qBittorrent |
| Medium | ≥ 4 cores, ≥ 8 GB RAM, ≥ 500 GB | Light + Jellyseerr, Bazarr, FlareSolverr |
| Heavy | ≥ 6–8 cores, ≥ 16 GB RAM, ≥ 1 TB | Medium + Uptime Kuma, Watchtower |

Every tier also offers the same tier-agnostic optional extras: Gluetun (VPN, on by default), SABnzbd (Usenet), Recyclarr (TRaSH sync), Decluttarr (queue cleanup), Maintainerr (library cleanup), Homepage/Dashy (dashboard), MeTube/Downtify (downloaders), Netdata (monitoring), Vaultwarden (password manager). Heavy adds GPU transcoding (when a GPU is detected), plus Lidarr, Readarr, Traefik, Authelia, CrowdSec, and Tailscale via custom mode.

All tiers share the same directory layout and volume naming, so re-running later to move up a tier shouldn't lose data.

### Custom mode

Pick exactly which services to include, from all 27 known services regardless of tier, pre-checked based on your hardware:

```bash
./install --plain --tier medium --services jellyfin,radarr,homepage,watchtower --non-interactive --yes --media-path /mnt/media
```

Resource limits scale using whichever tier you choose — picking Homepage alongside Medium doesn't pull in Heavy-tier limits. In `--plain`, answer "y" to "Customize which services are included?" after picking a tier. In the whiptail menu, answer "Yes" to "Customize the full service list?" right after picking a tier. This is also the only path that can reach Traefik/Authelia/CrowdSec/Tailscale/Decluttarr/Maintainerr/Lidarr/Readarr, since domain-based routing only activates when an explicit service list includes `traefik`.

---

## Optional Integrations

Beyond the core `*arr` stack, custom mode (`--services` list) unlocks: Traefik (domain-based `<service>.<domain>` routing, self-signed HTTPS by default), Cloudflare DNS (real Let's Encrypt certs), Tailscale (private remote access, no public exposure), Authelia (login wall for routed services), CrowdSec (blocks malicious IPs at the edge), plus Homepage/Dashy pre-seeded dashboards, Decluttarr/Maintainerr automation, and MeTube/Downtify downloaders.

Full detail, gotchas, and copy-pasteable commands for each: [Optional Integrations →](https://cyb3rron1n.github.io/vulcan/integrations/) (or [docs/integrations.md](docs/integrations.md)).

---

## Storage Planning

For a fresh machine with drives not yet set up, Vulcan can detect what's really there and compute the exact `mdadm`/`mkfs`/`mount` commands a RAID + mount setup would need — **plan-only, nothing is ever executed**:

```bash
vulcan storage report                                    # list real block devices, flag which are protected
vulcan storage plan --devices /dev/sdb,/dev/sdc           # compute a plan (mdadm RAID + format + mount)
```

A device backing `/`/`/boot`/`/boot/efi` can never be selected as a target — no override flag. Full detail: [Storage Planning →](https://cyb3rron1n.github.io/vulcan/storage/) (or [docs/storage.md](docs/storage.md)).

---

## Maintaining an Existing Stack

Commands reachable from the Main Menu (not CLI-only):

| Command | What it does |
|---|---|
| `vulcan update` | Pulls latest images and recreates containers |
| `vulcan pull` | Pulls images without starting anything |
| `vulcan backup` | Archives `stack/config/` + `docker-compose.yml`/`.env` to `backups/` |
| `vulcan restore [file]` | Restores `config/`, `docker-compose.yml`, and `.env` from a backup |
| `vulcan uninstall` | Stops the stack and deletes `stack/` entirely — back to a clean slate |
| `vulcan update-self` | Updates this Vulcan checkout — plain fast-forward `git pull` |

Airgap/offline: `--offline` skips the Docker install attempt; `vulcan export`/`import` move a stack's images to a machine never online at all.

Full detail, destructive vs. safe, and airgap installs: [Maintaining a Stack →](https://cyb3rron1n.github.io/vulcan/maintenance/) (or [docs/maintenance.md](docs/maintenance.md)).

---

## Design Principles

- **Deterministic, not AI-driven.** Tier recommendations from fixed rules over detected hardware.
- **Observe, then act.** The installer shows what it detected and what it's about to generate before doing anything; nothing is silently overwritten.
- **Re-run safe.** Running again against an existing stack should offer to upgrade/reconfigure, not clobber it.
- **Secrets stay out of git.** Generated `.env` files are never committed; `.gitignore` excludes the whole `stack/` output directory.

---

## Contributing

Contributions welcome — see [CONTRIBUTING.md](CONTRIBUTING.md) for philosophy, development setup, and coding standards. [CLAUDE.md](CLAUDE.md) covers the real architecture in depth, and [ROADMAP.md](ROADMAP.md) tracks what's shipped versus still open. Found a security issue? See [SECURITY.md](SECURITY.md) for how to report it responsibly.

---

## License

Vulcan is released under the [MIT License](LICENSE).
