# Getting Started

## Requirements

- Linux. On Ubuntu, Debian, Fedora, and Arch, `./install` runs a **Phase 0** pass first that installs anything missing — `git`, `python3-venv`, `whiptail`, `mdadm`, and Docker Engine + `docker compose` — adds your user to the `docker` group, and escalates to root **once** (it prints a heads-up block, then calls `sudo`) if it needs to. On other distros it prints the exact packages to install by hand and stops.
- Python 3.11+
- Docker — installed and started by Phase 0 on the supported distros if it isn't already there

## Quick Start

```bash
git clone https://github.com/Cyb3rRon1n/vulcan.git
cd vulcan
./install
```

`./install` runs Phase 0 (system packages + Docker, one `sudo` escalation — see Requirements), bootstraps a local virtual environment on first run, then opens on a persistent **Main Menu** — Guided Setup, plus Update/Pull/Backup/Restore/Uninstall for a stack you've already generated. Every item is always listed, DockSTARTer-style; picking a maintenance command before a stack exists gives you the same real "no stack found" message the CLI itself would. Picking **Guided Setup** runs an explicit sequence:

1. **Preflight** — re-checks Phase 0 (also available on its own as `vulcan preflight [--fix]`)
2. **Detect** your hardware
3. **Recommend** a tier
4. **Shape** — pick the tier and the services, answering only the questions that matter (media path, optional VPN/SABnzbd/Recyclarr/Homepage, PUID/PGID/timezone)
5. **Confirm** what's about to be generated
6. **Build** (`vulcan build`) — writes `stack/docker-compose.yml` + `.env` and stops; never starts anything, succeeds even if Docker is down
7. **Configure** (`vulcan configure`) — prompts for the credentials the enabled services need (Gluetun VPN provider + WireGuard key, Cloudflare Tunnel `TUNNEL_TOKEN`, Tailscale `TS_AUTHKEY`, Pi-hole web password) and writes them into `stack/.env`; it doesn't validate them
8. **Start** (`vulcan start`) — needs Docker; checks ports/network, runs `docker compose up -d`, then verifies the containers stayed up
9. **Report** — prints the real URL for every service you enabled

Before actually starting, Vulcan checks that every port your stack needs is genuinely free and refuses cleanly (naming the conflicting port) rather than letting Docker fail partway through. Once it's up, Vulcan prints the real URL for every service you enabled, so you're not left guessing ports.

## Non-interactive / scripted use

```bash
./install --tier medium --media-path /mnt/media --non-interactive --yes --start
```

`--non-interactive` requires both `--yes` and an explicit `--tier`/`--media-path` — nothing is inferred silently in scripted mode. `--start` is likewise opt-in on every path: generating a stack never launches it without being asked (interactively) or told to (`--start`).

Prefer the original plain-prompt flow over the guided `whiptail` menu (e.g. on a limited terminal, or `whiptail` isn't installed)? Add `--plain`.

### Dry run (generate without starting)

`--dry-run` generates the full stack to `stack/` and prints every URL, credential placeholder, and setup step — without starting Docker at all. Useful for:

- Verifying what the installer would create before it does anything
- Getting a setup walkthrough on paper to read through before starting services
- Testing a new `--services` combination without affecting a running stack

```bash
./install --dry-run --tier heavy --services traefik,authelia,cloudflared,jellyfin,seerr,radarr,sonarr --domain media.example.com --auth-username admin --auth-password 'yourpassword' --non-interactive --yes
```

`--dry-run` implies `--no-start --non-interactive --yes` — no confirmation prompts, no Docker operations. After generating, review `stack/docker-compose.yml` and `stack/.env`, then start manually when ready:

```bash
docker compose -f stack/docker-compose.yml --env-file stack/.env up -d
```

### Multi-user Authelia (RBAC)

Pass `--auth-users` to add additional Authelia users at install time — useful for giving family members their own Jellyfin/Seerr login while keeping Radarr, Sonarr, and management services admin-only:

```bash
./install --plain --tier heavy --services traefik,authelia,cloudflared,jellyfin,seerr,radarr,sonarr --domain media.example.com --auth-username admin --auth-password 'yourpassword' --auth-users 'friend:friendpass:media' --non-interactive --yes
```

Format: `username:password:group` — group is either `admin` (full access) or `media` (Jellyfin + Seerr only). See [Optional Integrations](../integrations.md#auth-authelia) for full details.

!!! note "`--offline` is currently CLI-only"
    `--offline` skips the automatic Docker install attempt when there's no connection. The guided menu doesn't yet ask about it — a real, open gap, tracked in the [Roadmap](../roadmap.md). Use `--plain --offline` or `--non-interactive --offline` on a machine with no internet access.

## Next

- Not sure which tier or services you need? See [Tiers & Custom Mode](../tiers.md).
- Want domain routing, real TLS, a login wall, or intrusion protection? See [Optional Integrations](../integrations.md).
- Setting up on a machine with fresh, unformatted drives? See [Storage Planning](../storage.md).
