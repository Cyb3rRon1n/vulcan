# Vulcan

<p align="center">
  <a href="https://github.com/Cyb3rRon1n/vulcan/actions/workflows/ci.yml">
    <img src="https://img.shields.io/github/actions/workflow/status/Cyb3rRon1n/vulcan/ci.yml?label=CI" alt="CI">
  </a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="License: MIT"></a>
  <img src="https://img.shields.io/badge/python-3.11%2B-blue.svg" alt="Python 3.11+">
</p>

<p align="center">
  <a href="https://github.com/Cyb3rRon1n/vulcan/actions/workflows/ci.yml">
    <img src="https://raw.githubusercontent.com/Cyb3rRon1n/vulcan/main/docs/images/banner.svg"
         alt="Vulcan - Deploy a self-hosted media homelab, sized to your hardware"
         style="max-width: 100%; height: auto;">
  </a>
</p>

<p align="center">
  📖 <a href="https://cyb3rron1n.github.io/vulcan/">Documentation</a> · <a href="docs/getting-started/index.md">Getting Started</a> · <a href="ROADMAP.md">Roadmap</a> · <a href="docs/walkthrough.md">Walkthrough</a> · <a href="https://cyb3rron1n.github.io/">Sibling Projects</a> · <a href="docs/images/favicon.svg">Favicon</a>
</p>

**Deploy a self-hosted media homelab, sized to your hardware.** Vulcan inspects your Linux host's real hardware and generates a Docker Compose media stack — Light, Medium, or Heavy — sized to what your machine can actually handle. Deterministic tier recommendations from detected CPU, RAM, disk, and GPU. No LLM in the decision path.

**Sudo required:** run `./install` as a non-root user with `sudo` available. Before anything else it runs one **Phase 0** pass — installs `git`, `python3-venv`, `whiptail`, `mdadm`, and Docker Engine + `docker compose` on Ubuntu/Debian/Fedora/Arch, adds you to the `docker` group — and escalates to root **once** (prints a heads-up block, then `sudo`) if it needs to. On other distros it prints what to install by hand. `vulcan preflight [--fix]` runs Phase 0 on its own.

---

## Quick Start

```bash
git clone https://github.com/Cyb3rRon1n/vulcan.git
cd vulcan
./install
```

`./install` runs Phase 0 (system packages + Docker, one `sudo` escalation — see above), bootstraps a local virtual environment, then opens a persistent **Main Menu** — Guided Setup (whiptail-driven), plus Update/Pull/Backup/Restore/Uninstall for an already-generated stack. Every item is always listed; picking a task before a stack exists gives a real "no stack found" message. **Guided Setup** runs an explicit sequence:

1. **Preflight** — re-check Phase 0
2. **Detect** hardware
3. **Recommend** a tier
4. **Shape** — pick the tier and services (media path, optional VPN/SABnzbd/Recyclarr/Homepage, PUID/PGID/timezone)
5. **Confirm** what's about to be generated
6. **Build** (`vulcan build`) — writes `stack/docker-compose.yml` + `.env` and starts nothing; works even with Docker down
7. **Configure** (`vulcan configure`) — prompts for the credentials the enabled services need (Gluetun VPN + WireGuard key, Cloudflare Tunnel `TUNNEL_TOKEN`, Tailscale `TS_AUTHKEY`, Pi-hole web password) and writes them into `stack/.env`
8. **Start** (`vulcan start`) — needs Docker; checks every needed port is free and refuses cleanly (naming the conflict), then `docker compose up -d`, then a container-stayed-up check
9. **Report** — the real URL for every service you enabled

Scripted use is also supported:

```bash
./install --tier medium --media-path /mnt/media --non-interactive --yes --start
```

`--non-interactive` requires `--yes` and an explicit `--tier`/`--media-path`. `--start` is opt-in on every path: generating a stack never launches it without being asked or told. Use `--plain` for the plain-prompt flow (no whiptail).

<p align="center">
  <img src="docs/images/screenshots/main-menu.svg" alt="Vulcan Main Menu example" style="max-width: 100%; width: 700px;"><br>
  <sub>The persistent Main Menu (representative mockup, real <code>whiptail</code> theme) — <a href="https://cyb3rron1n.github.io/vulcan/">more in the docs →</a></sub>
</p>

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

Pick exactly which services to include, from all 28 known services regardless of tier, pre-checked based on your hardware:

```bash
sudo ./install --plain --tier medium --services qbittorrent,radarr,homepage,watchtower --non-interactive --yes --media-path /mnt/media
```

Resource limits scale using whichever tier you choose — picking Homepage alongside Medium doesn't pull in Heavy-tier limits. In `--plain`, answer "y" to "Customize which services are included?" after picking a tier. In the whiptail menu, answer "Yes" to "Customize the full service list?" right after picking a tier. This is also the only path that can reach Traefik/Authelia/CrowdSec/Tailscale/Decluttarr/Maintainerr/Lidarr/Readarr, since domain-based routing only activates when an explicit service list includes `traefik`.

---

## Optional Integrations

Beyond the core stack, custom mode (`--services` list) unlocks: Traefik (domain-based `<service>.<domain>` routing, self-signed HTTPS by default), Cloudflare DNS (real Let's Encrypt certs) and Cloudflare Tunnel (no forwarded ports at all), Tailscale (private remote access, no public exposure), Authelia (login wall for routed services), CrowdSec (blocks malicious IPs at the edge), plus Homepage/Dashy pre-seeded dashboards, Decluttarr/Maintainerr automation, and MeTube/Downtify downloaders.

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

Airgap/offline: `vulcan export`/`import` move a stack's images to a machine never online at all.

Full detail, destructive vs. safe, and airgap installs: [Maintaining a Stack →](https://cyb3rron1n.github.io/vulcan/maintenance/) (or [docs/maintenance.md](docs/maintenance.md)).

---

## License

Vulcan is released under the [MIT License](LICENSE).
