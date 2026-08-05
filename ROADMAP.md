# Roadmap

All three originally-planned phases are complete; everything below shipped afterward. See [CLAUDE.md](CLAUDE.md) for the real architecture, decisions, and verification detail behind each item — this file is the scannable checklist version.

## Shipped

- [x] **Phase 1** — detection engine + CLI, Light/Medium/Heavy tiers from real detected hardware
- [x] **Phase 2** — Heavy tier, re-run safety, full guided TUI
- [x] **Phase 3** — update/backup lifecycle commands
- [x] **Custom mode** — free-pick any of the 17 known services regardless of tier, both via CLI `--services` and the TUI's "Customize Services" button
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
- [x] **aarch64/ARM static readiness audit** — every referenced Docker image confirmed to publish a real `linux/arm64` manifest, both install paths (get.docker.com script, Arch's pacman) confirmed architecture-agnostic, `psutil` confirmed to ship `manylinux_aarch64` wheels. Explicitly *not* counted as equivalent to a real hardware run — see Next.
- [x] **Traefik's own dashboard, routed securely through Traefik itself** — closes the one real gap found by actually checking whether Homepage covered every enabled service (12 of 18 did; the other 6 correctly have no web UI to link to except Traefik, which just never had its dashboard turned on). Enabled the documented-safe way (`api@internal` + routing labels, never `--api.insecure=true`), protected by `authelia@docker` when Authelia's enabled, with a `write_stack()` warning when it isn't. Found and fixed a real, separate pre-existing bug along the way: a Gluetun + qBittorrent + Traefik + domain combination was generating a dead-link Homepage tile (`https://qbittorrent.<domain>`, no matching router) instead of the working host-port fallback - confirmed empirically before fixing, not assumed.
- [x] **Homepage tile descriptions, and a real, significant Homepage bug fixed along the way** — every tile now shows a real one-line description (gethomepage.dev's own `description:` field), not just an icon and a name. Found while verifying it against a real running Homepage container: the current image outright refuses every request without a real `HOMEPAGE_ALLOWED_HOSTS` value (a relatively recent Homepage/Next.js security requirement) - meaning Homepage was completely unreachable on a fresh install before this fix, not a cosmetic gap. Fixed by computing the real allowed-hosts list (`localhost:3000`, the detected LAN IP, and the routed Traefik hostname when active) and threading it into the compose template. Verified end-to-end against a real container: came up and answered `200` instead of refusing the request, and every tile's real description round-tripped through the running app's own `/api/services` endpoint.

## Next

- [ ] **A real end-to-end run on actual ARM64 hardware.** The static audit above is done and clean, but nothing in this project's history has actually installed and run on real ARM hardware — everything real-verified so far has been on one x86_64 Fedora machine. The single biggest remaining gap.
- [ ] **`detect_cpu()`'s `cpu_model` parsing is x86-only.** It looks for a `"model name"` line in `/proc/cpuinfo`; real ARM64 Linux typically exposes `CPU implementer`/`CPU part` instead, so `cpu_model` will likely read as unknown on real ARM hardware. Not a crash (already handled as "not present"), but a known display gap to fix once real ARM hardware is available to verify against.
- [ ] **`detect_gpu()` has no ARM SBC-style detection** (e.g. a Raspberry Pi's VideoCore/V4L2 stack) — falls back cleanly to software-only Jellyfin transcoding today, but hardware transcoding on real ARM SBCs was never in scope.
- [ ] **Watch for a real stable Readarr release.** Currently pinned to `0.4.19-nightly` (over a year stale as of this writing) because it's the only tag LinuxServer publishes that actually works — re-pin once a real `:latest`-equivalent exists.
- [ ] **A shared constant for the Traefik/Homepage web-facing service set.** Both currently maintain their own independent per-service condition list; flagged as a real follow-up when Homepage pre-seeding shipped, never folded in since neither slice needed it enough to justify an unrelated template refactor.
- [ ] **Remove `presets/`.** Empty, unreferenced directory left over from the original scaffold at the repo root — not wired to anything.

## Deliberately out of scope

Recorded so these don't get relitigated as gaps later — each was considered and rejected for a real, documented reason.

- **Let's Encrypt / ACME automation.** HTTP-01 needs a port-forwarded public domain; DNS-01 needs picking one specific DNS provider's API out of dozens of legitimate choices — the same "don't hardcode one external assumption" reasoning already applied to Recyclarr's config and Gluetun/SABnzbd's credentials. Traefik's own auto-generated self-signed certificate is used instead.
- **Traefik routing for qBittorrent when Gluetun is enabled.** Not a bug — a real Docker networking limitation: a container using `network_mode: "service:gluetun"` has no network identity of its own for Traefik's Docker provider to discover. Explained via a `write_stack()` warning instead of silently generating labels that would never route.
- **A daemon or scheduled mode.** Every command is on-demand (`./install`, `vulcan update`/`pull`/`backup`/etc.), matching the project's "observe, then act" design principle — Heavy tier's Watchtower already covers continuous background updates for anyone who wants that specific behavior.
