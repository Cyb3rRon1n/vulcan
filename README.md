# Vulcan

**An intelligent media stack forge.**

Vulcan inspects your system's resources and automatically builds a tailored Jellyfin + *arr homelab — sized as Light, Medium, or Heavy to match what your machine can actually handle. Point it at a Linux box, answer a handful of questions, and get back a working `docker-compose.yml` and `.env` scoped to your real hardware, not a one-size-fits-all stack that either starves a small machine or wastes a big one.

Tier decisions are deterministic — fixed rules based on detected CPU/RAM/disk/GPU, no LLM involved.

---

## Status

Phase 1 is complete and usable: real hardware detection, deterministic tier scoring, Docker/Compose bootstrap, stack generation, and a guided (or scripted) `./install` flow are all implemented, tested, and verified against real infrastructure. All three tiers — Light, Medium, and Heavy, including GPU-aware hardware transcoding when a GPU is detected — are now fully buildable. The guided flow is plain interactive CLI prompts today, not yet the Security Onion-style TUI; re-running the installer against an existing stack to upgrade tiers isn't built yet either — both are in progress as part of Phase 2.

---

## Quick Start

```bash
git clone https://github.com/<you>/vulcan.git
cd vulcan
./install
```

`./install` bootstraps a local virtual environment on first run, then walks you through a guided flow: detects your system, gets Docker ready if it isn't already, recommends a tier, asks only the questions that matter (media path, optional VPN, PUID/PGID/timezone), and generates a ready-to-run stack — with the option to start it immediately.

Non-interactive / scripted use is also supported:

```bash
./install --tier medium --media-path /mnt/media --non-interactive --yes --start
```

`--non-interactive` requires both `--yes` and an explicit `--tier`/`--media-path` — nothing is inferred silently in scripted mode. `--start` is likewise opt-in on every path: generating a stack never launches it without being asked (interactively) or told to (`--start`).

---

## Tiers

| Tier | Target Hardware | Core Services | Extras |
|---|---|---|---|
| Light | ≥ 2 cores, ≥ 4 GB RAM, ≥ 100 GB free | Jellyfin, Radarr, Sonarr, Prowlarr, qBittorrent | None by default |
| Medium | ≥ 4 cores, ≥ 8 GB RAM, ≥ 500 GB free | Light + Jellyseerr, Bazarr, FlareSolverr | Optional Gluetun (VPN) |
| Heavy | ≥ 6–8 cores, ≥ 16 GB RAM, ≥ 1 TB free | Medium + Lidarr (optional), reverse proxy, Homarr/Homepage, Uptime Kuma, Watchtower | Hardware transcoding if a GPU is detected |

All tiers share the same directory layout and volume naming, so re-running the installer later to move up a tier shouldn't lose data.

---

## Design Principles

- **Deterministic, not AI-driven.** Tier recommendations come from fixed rules over detected hardware — no LLM in the decision path.
- **Observe, then act.** The installer shows you what it detected and what it's about to generate before doing anything; nothing is silently overwritten.
- **Re-run safe.** Running the installer again against an existing stack should offer to upgrade/reconfigure, not clobber it.
- **Secrets stay out of git.** Generated `.env` files are never committed; `.gitignore` excludes the whole `stack/` output directory.

---

## License

Vulcan is released under the [MIT License](LICENSE).
