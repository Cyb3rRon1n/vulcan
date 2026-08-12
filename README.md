# Vulcan

<p align="center">
  <a href="https://github.com/Cyb3rRon1n/vulcan/actions/workflows/ci.yml"><img src="https://github.com/Cyb3rRon1n/vulcan/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="License: MIT"></a>
  <img src="https://img.shields.io/badge/python-3.11%2B-blue.svg" alt="Python 3.11+">
</p>

<p align="center"><strong>An intelligent media stack forge.</strong></p>

<p align="center">
  📖 <a href="https://cyb3rron1n.github.io/vulcan/">Full Documentation Site</a> · <a href="docs/getting-started/index.md">Getting Started</a> · <a href="ROADMAP.md">Roadmap</a>
</p>

Vulcan inspects your Linux host's real hardware, recommends a sized tier (Light / Medium / Heavy), and generates a ready-to-run Jellyfin + `*arr` Docker Compose media stack — scoped to what your machine can actually handle, not a one-size-fits-all stack that either starves a small machine or wastes a big one. Tier decisions are deterministic, fixed rules over detected CPU/RAM/disk/GPU — no LLM in the decision path.

**What** — A hardware-aware installer that detects your machine, recommends a sized Jellyfin + `*arr` media stack, and generates it as a ready-to-run Docker Compose project, plus the full lifecycle after that (update, backup, restore, uninstall).

**Who it's for** — Homelab and self-hosted folks who want a media server + download automation stack without hand-tuning resource limits or manually wiring a dozen services together.

**When** — Actively developed; changes ship continuously, not on a fixed release cadence. See [ROADMAP.md](ROADMAP.md) for what's genuinely finished versus still open.

**Where it runs** — Any Linux host with Docker (Ubuntu, Debian, Raspbian, Fedora, and Arch all get an automatic Docker install) and Python 3.11+.

**Why** — Fixed-size, copy-pasted media-stack guides either starve a small machine or waste a big one, and hand-wiring a dozen services together (VPN routing, reverse proxy, auth, dashboards) is real, repetitive, error-prone work. Vulcan replaces both with deterministic, hardware-aware generation — verified against real infrastructure (real Docker, real containers, real hardware where available) as it was built, not just exercised in isolation. Real ARM64 hardware is the one open verification gap.

---

## Contents

- [Screenshots](#screenshots)
- [Features](#features)
- [Requirements](#requirements)
- [Quick Start](#quick-start)
- [Tiers](#tiers)
- [Optional Integrations](#optional-integrations)
- [Storage Planning](#storage-planning)
- [Maintaining an Existing Stack](#maintaining-an-existing-stack)
- [Design Principles](#design-principles)
- [Contributing](#contributing)
- [License](#license)

---

## Screenshots

`vulcan` (no flags) opens on a real `whiptail`-driven Main Menu - Guided Setup plus every lifecycle command (update/pull/backup/restore/uninstall a stack, update Vulcan itself).

<p align="center">
  <img src="docs/images/screenshots/main-menu.svg" alt="Vulcan Main Menu example" width="720"><br>
  <sub>The persistent Main Menu — real <code>whiptail</code>, matching <code>installer/menu.sh</code>'s real theme</sub>
</p>

<p align="center">
  <img src="docs/images/screenshots/tier-picker.svg" alt="Vulcan tier picker example" width="720"><br>
  <sub>Guided Setup's tier picker — real detected specs and a real recommendation, before you choose</sub>
</p>

> **Representative mockups, not literal captures.** Hand-built to match `installer/menu.sh`'s real theme and dialog text - a real interactive `whiptail` terminal run hasn't happened yet (see [ROADMAP.md](ROADMAP.md)). More screens and the full explanation are on the [docs site](https://cyb3rron1n.github.io/vulcan/); these will be swapped for real captures once that run happens.

---

## Features

**Core**

- **Hardware-aware sizing** — Light, Medium, or Heavy, picked from real detected CPU, RAM, disk, and GPU, with hardware transcoding wired in automatically when a GPU is found.
- **Guided whiptail menu or scriptable CLI** — a full guided setup by default (real bash + `whiptail`, DockSTARTer-style), a plain-prompt fallback (`--plain`), and a fully non-interactive path (`--non-interactive`) for automation.
- **Persistent Main Menu** — the guided menu opens on a real hub (Guided Setup plus every lifecycle command below), not straight into detection. Pick a maintenance task, finish it, and land back on the menu to pick another, rather than the app just exiting.
- **Custom mode** — free-pick any of Vulcan's 27 known services regardless of tier, pre-checked from what your hardware qualifies for.
- **Re-run safe** — regenerating an existing stack never resets a real credential (like a Gluetun VPN key) back to a placeholder.
- **Full lifecycle, not just first install** — `vulcan update`/`pull`/`backup`/`restore`/`uninstall` round out an already-generated stack.
- **Airgap-friendly** — `--offline` skips the automatic Docker install attempt when there's no connection, and `vulcan export`/`import` move a stack's images to a machine that never touches the network.
- **Storage-aware** — reports whether your media path actually has any drive-level redundancy (mdadm/btrfs/ZFS), and warns if a single drive failure would mean data loss.
- **Storage planning** — `vulcan storage report`/`plan` detect real block devices on the machine and compute the exact `mdadm`/`mkfs`/`mount` commands a RAID + mount setup would need — a real device backing `/`/`/boot` can never be selected as a target. Plan-only for now: nothing is executed, see [Storage Planning](#storage-planning) below.

**Networking & security**

- **Real domain-based routing** — optional Traefik integration with automatic HTTPS (self-signed by default, or real Let's Encrypt certificates if your domain's DNS is on Cloudflare), no manual reverse-proxy config.
- **Real login, not just routing** — optional Authelia integration puts a real username/password in front of every routed service, no external identity provider or database required.
- **Intrusion protection** — optional CrowdSec watches Traefik's own access log and blocks IPs its community blocklist flags as malicious, on every routed service (including the two that skip Authelia) — protects the door, not just the login page behind it.
- **Password manager** — optional Vaultwarden (a lightweight, Bitwarden-compatible server) for every credential this stack generates, with the official Bitwarden apps working against it unmodified.
- **Private remote access** — optional Tailscale integration puts every host-published port in your stack on your own tailnet, reachable from anywhere with no port-forwarding and no public exposure at all.

**Media automation**

- **Automated queue and library cleanup** — optional Decluttarr removes stalled or failed downloads from Radarr/Sonarr's queue and triggers a fresh search, and optional Maintainerr cleans up unwatched media on your media server's own rules — complementary, not overlapping.
- **Automated downloaders** — optional MeTube (video) and Downtify (Spotify-sourced audio, no Premium account needed) for on-demand grabs outside the `*arr` automation pipeline.

**Dashboards & monitoring**

- **Pre-seeded dashboard, two options** — optional Homepage or Dashy, available at every tier, both boot with real, grouped, described tiles for your actual stack instead of a blank page.
- **Real-time system monitoring** — optional Netdata for live CPU/RAM/disk/network/temperature and per-container awareness, matched to its own official recommended configuration.

---

## Requirements

- Linux (Ubuntu, Debian, Raspbian, Fedora, and Arch all have an automatic Docker install path; other distros need Docker installed manually first)
- Python 3.11+
- Docker — installed and started automatically on supported distros if it isn't already there

## Quick Start

```bash
git clone https://github.com/Cyb3rRon1n/vulcan.git
cd vulcan
./install
```

`./install` bootstraps a local virtual environment on first run, then opens on a persistent **Main Menu** — Guided Setup, plus Update/Pull/Backup/Restore/Uninstall for a stack you've already generated. Every item is always listed, DockSTARTer-style; picking a maintenance command before a stack exists gives you the same real "no stack found" message the CLI itself would. Picking **Guided Setup** walks you through:

1. Detects your system
2. Gets Docker ready if it isn't already
3. Recommends a tier
4. Asks only the questions that matter (media path, optional VPN/SABnzbd/Recyclarr/Homepage, PUID/PGID/timezone)
5. Generates a ready-to-run stack, with the option to start it immediately

Before actually starting, Vulcan checks that every port your stack needs is genuinely free and refuses cleanly (naming the conflicting port) rather than letting Docker fail partway through. Once it's up, Vulcan prints the real URL for every service you enabled, so you're not left guessing ports.

Non-interactive / scripted use is also supported:

```bash
./install --tier medium --media-path /mnt/media --non-interactive --yes --start
```

`--non-interactive` requires both `--yes` and an explicit `--tier`/`--media-path` — nothing is inferred silently in scripted mode. `--start` is likewise opt-in on every path: generating a stack never launches it without being asked (interactively) or told to (`--start`). Prefer the original plain-prompt flow over the guided whiptail menu (e.g. on a limited terminal, or `whiptail` isn't installed)? Add `--plain`.

`--offline` (skip the automatic Docker install attempt when there's no connection) is currently CLI-only — the guided menu doesn't yet ask about it, a real, open gap (see [ROADMAP.md](ROADMAP.md)). Use `--plain --offline` or `--non-interactive --offline` on a machine with no internet access.

---

## Tiers

Both the guided menu and the plain CLI show what each tier actually contains before you pick one — not just its name.

| Tier | Target Hardware | Core Services |
|---|---|---|
| Light | ≥ 2 cores, ≥ 4 GB RAM, ≥ 100 GB free | Jellyfin, Radarr, Sonarr, Prowlarr, qBittorrent |
| Medium | ≥ 4 cores, ≥ 8 GB RAM, ≥ 500 GB free | Light + Jellyseerr, Bazarr, FlareSolverr |
| Heavy | ≥ 6–8 cores, ≥ 16 GB RAM, ≥ 1 TB free | Medium + Uptime Kuma, Watchtower |

Every tier also offers the same tier-agnostic optional extras: Gluetun (VPN, on by default), SABnzbd (Usenet), Recyclarr (TRaSH sync), Decluttarr (queue cleanup), Maintainerr (library cleanup), Homepage or Dashy (dashboard), MeTube/Downtify (downloaders), Netdata (monitoring), and Vaultwarden (password manager). Heavy tier adds GPU transcoding when a GPU is detected, plus Lidarr, Readarr, Traefik, Authelia, CrowdSec, and Tailscale via custom mode.

All tiers share the same directory layout and volume naming, so re-running the installer later to move up a tier shouldn't lose data.

### Custom mode

Pick exactly which services to include, from all 27 known services regardless of tier, pre-checked based on what your hardware qualifies for:

```bash
./install --plain --tier medium --services jellyfin,radarr,homepage,watchtower --non-interactive --yes --media-path /mnt/media
```

Resource limits still scale using whichever tier you choose (`--tier` here, or the detected recommendation if omitted) — picking Homepage or Watchtower alongside a Medium selection doesn't pull in Heavy-tier resource limits. In the interactive `--plain` flow, answer "y" to "Customize which services are included?" after picking a tier. In the guided whiptail menu, answer "Yes" to "Customize the full service list?" right after picking a tier to get the same free-pick checklist — this is also the only path (menu or `--plain`) that can reach Traefik/Authelia/CrowdSec/Tailscale/Decluttarr/Maintainerr/Lidarr/Readarr, since domain-based routing only activates when an explicit service list includes `traefik`.

---

## Optional Integrations

Beyond the core `*arr` stack, custom mode (an explicit `--services` list) unlocks: **Traefik** (real domain-based `<service>.<domain>` routing, self-signed by default), **Cloudflare DNS** (real trusted Let's Encrypt certs instead), **Tailscale** (private remote access, zero public exposure), **Authelia** (a real login wall in front of every routed service), **CrowdSec** (blocks malicious IPs at the edge before they reach a login page), plus Homepage/Dashy pre-seeded dashboards, Decluttarr/Maintainerr automation, and MeTube/Downtify downloaders.

**Full detail, real gotchas, and copy-pasteable commands for each: [Optional Integrations on the docs site →](https://cyb3rron1n.github.io/vulcan/integrations/) (or [docs/integrations.md](docs/integrations.md) directly)**

---

## Storage Planning

For a fresh machine with drives that aren't set up yet, Vulcan can detect what's really there and compute the exact `mdadm`/`mkfs`/`mount` commands a RAID + mount setup would need — **plan-only, nothing is ever executed**:

```bash
vulcan storage report                                    # list real block devices, flag which are protected
vulcan storage plan --devices /dev/sdb,/dev/sdc           # compute a plan (mdadm RAID + format + mount)
```

A device backing `/`/`/boot`/`/boot/efi` can never be selected as a target — there's no override flag. **Full detail: [Storage Planning on the docs site →](https://cyb3rron1n.github.io/vulcan/storage/) (or [docs/storage.md](docs/storage.md))**

---

## Maintaining an Existing Stack

Every command below is also reachable from the guided menu's own **Main Menu** — not CLI-only.

| Command | What it does |
|---|---|
| `vulcan update` | Pulls the latest images and recreates containers |
| `vulcan pull` | Pulls images without starting anything |
| `vulcan backup` | Archives `stack/config/` + `docker-compose.yml`/`.env` to `backups/` |
| `vulcan restore [file]` | Restores `config/`, `docker-compose.yml`, and `.env` from a backup archive |
| `vulcan uninstall` | Stops the stack and deletes `stack/` entirely — back to a clean slate |
| `vulcan update-self` | Updates *this Vulcan checkout* (not a stack) — a plain fast-forward `git pull` |

Airgap/offline covered too: `--offline` skips the automatic Docker install attempt, and `vulcan export`/`import` move a stack's images to a machine that's never been online at all.

**Full detail on each command, what's destructive vs. safe, and airgap installs: [Maintaining a Stack on the docs site →](https://cyb3rron1n.github.io/vulcan/maintenance/) (or [docs/maintenance.md](docs/maintenance.md))**

---

## Design Principles

- **Deterministic, not AI-driven.** Tier recommendations come from fixed rules over detected hardware — no LLM in the decision path.
- **Observe, then act.** The installer shows you what it detected and what it's about to generate before doing anything; nothing is silently overwritten.
- **Re-run safe.** Running the installer again against an existing stack should offer to upgrade/reconfigure, not clobber it.
- **Secrets stay out of git.** Generated `.env` files are never committed; `.gitignore` excludes the whole `stack/` output directory.

---

## Contributing

Contributions are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md) for the project's philosophy, development setup, and coding standards. [CLAUDE.md](CLAUDE.md) covers the real architecture in depth, and [ROADMAP.md](ROADMAP.md) tracks what's shipped versus still open. Found a security issue? See [SECURITY.md](SECURITY.md) for how to report it responsibly.

---

## License

Vulcan is released under the [MIT License](LICENSE).
