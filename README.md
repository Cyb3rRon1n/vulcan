# Vulcan

**An intelligent media stack forge.**

Vulcan inspects your system's resources and automatically builds a tailored Jellyfin + *arr homelab — sized as Light, Medium, or Heavy to match what your machine can actually handle. Point it at a Linux box, answer a handful of questions, and get back a working `docker-compose.yml` and `.env` scoped to your real hardware, not a one-size-fits-all stack that either starves a small machine or wastes a big one.

Tier decisions are deterministic — fixed rules based on detected CPU/RAM/disk/GPU, no LLM involved.

---

## Status

Early scaffolding. Phase 1 (detection + scoring, a basic TUI, Light/Medium tiers, Compose/`.env` generation, CLI flags) is in progress — nothing here is usable yet.

---

## Quick Start (target experience)

```bash
git clone https://github.com/<you>/vulcan.git
cd vulcan
./install
```

`./install` bootstraps a local virtual environment on first run, then launches an interactive, Security Onion-style guided flow: detects your system, recommends a tier, asks only the questions that matter, and generates a ready-to-run stack.

Non-interactive / scripted use will also be supported:

```bash
./install --tier medium --media-path /mnt/media --non-interactive --yes
```

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
