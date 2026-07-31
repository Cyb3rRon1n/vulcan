# Vulcan

**An intelligent media stack forge.**

Vulcan inspects your system's resources and automatically builds a tailored Jellyfin + *arr homelab — sized as Light, Medium, or Heavy to match what your machine can actually handle. Point it at a Linux box, answer a handful of questions, and get back a working `docker-compose.yml` and `.env` scoped to your real hardware, not a one-size-fits-all stack that either starves a small machine or wastes a big one.

Tier decisions are deterministic — fixed rules based on detected CPU/RAM/disk/GPU, no LLM involved.

---

## Status

All three planned phases are complete. Real hardware detection, deterministic tier scoring, Docker/Compose bootstrap, stack generation, and re-run/upgrade safety are all implemented, tested, and verified against real infrastructure. All three tiers — Light, Medium, and Heavy, including GPU-aware hardware transcoding when a GPU is detected — are fully buildable. Re-running the installer against an existing stack is safe: it picks up your previous settings as defaults and never resets real credentials (like Gluetun VPN keys) back to placeholders. `./install` launches the full Security Onion-style guided TUI by default — detection, Docker readiness, media path, tier/configuration, and review/generate/start as five real screens in the primary flow, plus a sixth (custom service selection) on the branch off the tier screen; `--plain` falls back to the original interactive CLI prompts (useful over a limited terminal, or for scripting-adjacent debugging), and `--non-interactive` remains the fully scripted path either way. `vulcan update`/`vulcan backup`/`vulcan restore` round out ongoing maintenance of an already-generated stack.

---

## Quick Start

```bash
git clone https://github.com/<you>/vulcan.git
cd vulcan
./install
```

`./install` bootstraps a local virtual environment on first run, then walks you through a guided flow: detects your system, gets Docker ready if it isn't already, recommends a tier, asks only the questions that matter (media path, optional VPN/SABnzbd/Recyclarr, PUID/PGID/timezone), and generates a ready-to-run stack — with the option to start it immediately.

Non-interactive / scripted use is also supported:

```bash
./install --tier medium --media-path /mnt/media --non-interactive --yes --start
```

`--non-interactive` requires both `--yes` and an explicit `--tier`/`--media-path` — nothing is inferred silently in scripted mode. `--start` is likewise opt-in on every path: generating a stack never launches it without being asked (interactively) or told to (`--start`). Prefer the original plain-prompt flow over the TUI (e.g. on a limited terminal)? Add `--plain`.

---

## Tiers

| Tier | Target Hardware | Core Services | Extras |
|---|---|---|---|
| Light | ≥ 2 cores, ≥ 4 GB RAM, ≥ 100 GB free | Jellyfin, Radarr, Sonarr, Prowlarr, qBittorrent | Optional SABnzbd (Usenet), Recyclarr (TRaSH sync) |
| Medium | ≥ 4 cores, ≥ 8 GB RAM, ≥ 500 GB free | Light + Jellyseerr, Bazarr, FlareSolverr | Optional Gluetun (VPN) |
| Heavy | ≥ 6–8 cores, ≥ 16 GB RAM, ≥ 1 TB free | Medium + Homepage, Uptime Kuma, Watchtower | Hardware transcoding if a GPU is detected; Lidarr and Traefik (with domain-based routing) available via custom mode |

All tiers share the same directory layout and volume naming, so re-running the installer later to move up a tier shouldn't lose data.

**Custom mode** lets you pick exactly which services to include, from all 16 known services regardless of tier, pre-checked based on what your hardware qualifies for:

```bash
./install --plain --tier medium --services jellyfin,radarr,homepage,watchtower --non-interactive --yes --media-path /mnt/media
```

Resource limits still scale using whichever tier you choose (`--tier` here, or the detected recommendation if omitted) - picking Homepage or Watchtower alongside a Medium selection doesn't pull in Heavy-tier resource limits. In the interactive `--plain` flow, answer "y" to "Customize which services are included?" after picking a tier. In the default TUI, click "Customize Services" on the tier screen instead of "Continue" to get the same free-pick checklist.

**Domain-based routing.** If `traefik` is part of your custom selection, pass `--domain` to get real `<service>.<domain>` routing (e.g. `jellyfin.media.example.com`) for every included web-facing service, instead of Traefik's default do-nothing skeleton:

```bash
./install --plain --tier heavy --services jellyfin,radarr,sonarr,traefik --domain media.example.com --non-interactive --yes --media-path /mnt/media
```

HTTPS uses Traefik's own auto-generated self-signed certificate by default - real routing and encryption with zero external setup, at the cost of a browser trust warning on first visit. Vulcan doesn't create DNS records or configure Let's Encrypt/ACME for you; point each subdomain at this host yourself. qBittorrent isn't routed when Gluetun is also enabled, since it shares Gluetun's network namespace in a way Traefik can't discover.

---

## Maintaining an existing stack

```bash
vulcan update              # pull the latest images and recreate containers
vulcan backup              # archive stack/config/ + docker-compose.yml/.env to backups/
vulcan restore [file]      # restore config/, docker-compose.yml, and .env from a backup archive
```

`vulcan update` is the on-demand alternative to Heavy tier's Watchtower (which updates continuously on its own) - useful for every other tier, for a cron job, or to force an update right now instead of waiting for the next poll. It confirms before touching anything running (`--non-interactive --yes` for scripted use). `vulcan backup` needs no confirmation - it only ever adds a new timestamped archive under `backups/` (gitignored, like `stack/`) - but the archive includes `stack/.env`, which may hold real credentials, so store it securely. `vulcan restore` reverses a backup: it defaults to the most recent archive in `backups/` if you don't pass a specific file, stops the currently running stack first (if there is one) so extraction can't race with a container actively using its own config directory, then extracts over what's there now - genuinely destructive, so it confirms before touching anything, same as every other mutating command.

---

## Design Principles

- **Deterministic, not AI-driven.** Tier recommendations come from fixed rules over detected hardware — no LLM in the decision path.
- **Observe, then act.** The installer shows you what it detected and what it's about to generate before doing anything; nothing is silently overwritten.
- **Re-run safe.** Running the installer again against an existing stack should offer to upgrade/reconfigure, not clobber it.
- **Secrets stay out of git.** Generated `.env` files are never committed; `.gitignore` excludes the whole `stack/` output directory.

---

## Contributing

Contributions are welcome - see [CONTRIBUTING.md](CONTRIBUTING.md) for the project's philosophy, development setup, and coding standards. [CLAUDE.md](CLAUDE.md) covers the real architecture in depth.

---

## License

Vulcan is released under the [MIT License](LICENSE).
