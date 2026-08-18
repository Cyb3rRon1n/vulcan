# Roadmap

All three originally-planned phases are complete; everything below shipped afterward. See [CLAUDE.md](CLAUDE.md) for the real architecture, decisions, and verification detail behind each item — this file is the scannable checklist version.

## Shipped

- [x] **Phase 1** — detection engine + CLI, Light/Medium/Heavy tiers from real detected hardware
- [x] **Phase 2** — Heavy tier, re-run safety, full guided TUI
- [x] **Phase 3** — update/backup lifecycle commands
- [x] **Custom mode** — free-pick any of the 27 known services regardless of tier, both via CLI `--services` and the TUI's "Customize Services" button
- [x] **SABnzbd** — Usenet downloader, tier-agnostic, purely additive alongside qBittorrent
- [x] **Recyclarr** — TRaSH Guides config sync for Radarr/Sonarr, tier-agnostic, purely additive
- [x] **`vulcan restore`** — reverse of `vulcan backup`
- [x] **Real Traefik routing** — domain-driven `<service>.<domain>` labels, Traefik's own auto-generated self-signed HTTPS, verified against real containers (real router discovery, real 404 on unmatched host, real 301 HTTP→HTTPS redirect)
- [x] **TUI back navigation** — every screen but `WelcomeScreen` can pop back to a genuinely preserved previous screen
- [x] **Homepage dashboard pre-seeding** — real service tiles (correct icon, correct link) instead of a blank dashboard on first boot; never overwrites a hand-edited `services.yaml` on a later regenerate
- [x] **Readarr** — books/ebooks `*arr` app, placed identically to Lidarr, pinned to the only real working image tag LinuxServer currently publishes (see Next — that tag is stale)
- [x] **Pre-pull mode** — `vulcan pull`
- [x] **Airgap mode** — `--offline`, `vulcan export`/`vulcan import`
- [x] **Read-only media-path redundancy detection** — reports whether the media path has real drive-level redundancy (mdadm/btrfs/ZFS); never creates or modifies storage itself
- [x] **Safe SQLite snapshotting in `vulcan backup`** — via sqlite3's own online-backup API, so a live `*arr`/Jellyfin database is never archived mid-write
- [x] **Uptime Kuma setup reference** — warning + real service URLs, scoped down from full pre-seeding once its Socket.IO-only API made that a materially bigger ask
- [x] **Pre-flight port-availability check** — refuses cleanly before the first `docker compose up -d` if a needed port is already taken, naming the conflict, instead of letting Docker fail partway through
- [x] **Post-start summary** — lists every enabled service's real reachable URL after a successful start
- [x] **Homepage promoted to tier-agnostic** — a real opt-in question at every tier, not Heavy-only; default-enabled with a backward-compatible default so an existing Heavy deployment's next regenerate doesn't silently drop it
- [x] **`vulcan uninstall`** — stops the running stack and deletes `stack/` entirely, rounding out the lifecycle commands; leaves the media library and (unless `--purge-artifacts`) `backups/`/`exports/` untouched
- [x] **Auth layer** — Authelia behind Traefik's `forwardAuth` middleware (`default_policy: one_factor`, no LDAP/Postgres/Redis), closing the last open item from the original pain-points survey; verified end-to-end including a real authenticated login round-trip through a real protected service
- [x] **`vulcan uninstall` orphaned-container cleanup** — also tears down containers left running when `stack/` was deleted some other way, not just via `vulcan uninstall` itself; found via a real user bug report, reproduced, fixed
- [x] **`detect_gpu()` real functional check** — fixed to run a real per-vendor query instead of just checking tool presence; this exact dev machine had been reporting a false `"amd"` for this project's entire history until this fix, found while building the sibling Anvil project
- [x] **Keyboard-accessible TUI guidance** — `DescendantFocus`-based tooltips reach keyboard-only users, not just mouse-hover; five previously-untooltipped fields also got real tooltip text along the way
- [x] **`vulcan uninstall --prune-docker`** — opt-in flag to also run `docker system prune -a` after stack teardown, in both the plain CLI and the whiptail menu (own confirmation prompt, defaults to No); clearly scoped as whole-Docker-host, not vulcan-only, since `docker system prune -a` isn't container-scoped

## Next

The following are genuine open items, not shipped:

- [ ] **aarch64/ARM end-to-end verification** — static readiness audit has been done (every referenced Docker image confirmed to publish a real `linux/arm64` manifest, both install paths confirmed architecture-agnostic, two real known gaps in CPU/GPU detection documented rather than hidden) but has never actually been run on real ARM hardware. Everything real-verified in this project's history has been on this one real x86_64 Fedora machine.
- [ ] **Real-infrastructure verification (real Docker containers, real compose files, live API calls)** — a mocked suite passing is considered necessary but not sufficient. Real-infrastructure verification is a project-wide value; this remains an open gap.
- [ ] **`whiptail` interactive testing** — no `Pilot`-equivalent automation harness exists, and the dev sandbox has no `whiptail`/shellcheck/`bats` installed nor passwordless `sudo`/general internet access to install them. Full interactive `whiptail` dialog rendering and navigation in an actual terminal is unverified.
- [ ] **Real GUIX/GuixSD support** — not currently in scope; only x86_64/Fedora, Ubuntu/Debian/Raspbian, and Arch are tested/verified.
- [ ] **Tailscale plugin download for Traefik** — the Traefik plugin catalog itself returned `error: 500` in this dev environment against two plugin versions and the official `plugindemo` example. Strong evidence this is a Traefik-plugin-catalog-side issue, not a CrowdSec or Vulcan-specific misconfiguration, but genuinely unconfirmed whether it's environment-specific or a live upstream problem.
- [ ] **`detect_cpu()` `cpu_model` display gap on ARM** — `cpu_model` parsing looks for a `"model name"` line in `/proc/cpuinfo`, the x86 convention. Real ARM64 Linux typically exposes `CPU implementer`/`CPU part` fields instead, so `cpu_model` will likely come back `None` ("unknown" in the CLI's own summary) on real ARM hardware. Not a crash, since the function already treats a missing field as "not present" by design, but a real display gap worth knowing about going in.

## How to read this file

- **Shipped** — complete, verified, merged. These items have real-infrastructure verification (real Docker containers, real compose files, live API calls where applicable) or are pure code/configuration changes with no Docker dependency.
- **Next** — genuine open items. These either lack real-infrastructure verification in this environment, or are explicitly acknowledged as unverified gaps.
- **Read the **Shipped** items against [CLAUDE.md](CLAUDE.md)** for the real architecture, decisions, and verification narrative behind each one — this file is just the checklist.
