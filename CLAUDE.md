# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Setup
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Run the CLI
./install                      # bootstraps .venv on first run, then execs into the TUI by default
vulcan --plain                 # plain Typer prompts instead of the TUI (installed console script)
python -m installer --plain    # equivalent, for running from source without reinstalling

# Lint (pyflakes-only - see "No formatter is configured" below for why)
ruff check .

# Tests (pytest, config lives in [tool.pytest.ini_options] in pyproject.toml — no separate ini file)
python -m pytest tests/
python -m pytest tests/test_generate.py -v
python -m pytest tests/test_tui.py::test_review_screen_shows_correct_summary
```

No formatter is configured, and deliberately so — this codebase has a real, documented style (heavy vertical spacing) that a default Black/ruff-format pass would fight; new code matches the file it's editing by hand.

## Architecture

**Two interfaces, one engine.** `installer/detect.py`, `installer/docker_setup.py`, `installer/tiers.py`, `installer/services.py`, `installer/generate.py`, and `installer/post_install.py` are the engine: pure or near-pure functions that never prompt, confirm, or catch their own mistakes silently — they return plain result dicts and let the caller decide what to do. `installer/cli.py` (Typer, Rich console output, plain prompts) and `installer/menu.sh` (bash + whiptail) are two independent front ends over that same engine — neither owns any business logic the other doesn't also have access to. When adding a capability, it belongs in the engine layer; a front end's job is only to gather input and call it.

**Entry points.** `./install` (bash) bootstraps `.venv` on first run and always `exec`s into `python -m installer "$@"` — no logic beyond that bootstrap, mirrored by `scripts/update.sh`/`scripts/backup.sh`/`scripts/restore.sh`. `installer/__main__.py` and the `vulcan` console script both point at `installer.cli:app`. `installer/cli.py`'s `main()` is a `@app.callback(invoke_without_command=True)` — required because both `./install` (zero args) and `./install --tier medium --non-interactive --yes` need to work with no subcommand name, while `vulcan version`/`vulcan update`/`vulcan backup`/`vulcan restore` still need to work as real subcommands.

**Detection (`detect.py`).** `detect_system(disk_path="/")` assembles `SystemInfo` from `detect_cpu()`/`detect_memory()`/`detect_disk()`/`detect_gpu()`/`detect_docker()`/`detect_os()` — all read-only, all catching their own failure modes and returning `None`/`False`/a zero value rather than raising, since "not present" isn't an error.

**Docker bootstrap (`docker_setup.py` + `shell.py`).** `install_plan_for(os_id, os_is_atomic)` maps a distro to an install method — `get.docker.com` (ubuntu/debian/raspbian/fedora) or `pacman` (arch), `rpm-ostree` for atomic hosts (checked *before* `os_id`), `None` for anything else (manual-install instructions). `run_privileged()` prefixes `sudo` only when not already root. **The group-membership gotcha**: a process's group list doesn't refresh mid-run after `usermod -aG docker <user>` — `run_docker_command(..., use_group_workaround=True)` routes through `sg docker -c "<cmd>"` (reads group membership fresh, no relogin needed) for exactly the run that just added the group, falling back to `sudo` if `sg` isn't present. Both `cli.py` and the TUI track a `group_just_added` flag through the whole session for this reason. `check_docker_ready(use_group_workaround)` applies the same `sg` fix to the readiness *re-check* right after `add_user_to_docker_group()`.

**Atomic/immutable-OS support.** `detect.py`'s `detect_os_is_atomic()` checks `/run/ostree-booted` before falling back to `shutil.which("rpm-ostree")`. `install_plan_for` checks it *before* `os_id` — Bazzite/Kinoite report `os_id="fedora"` (`ID_LIKE=fedora`), which would otherwise wrongly route through the plain `get.docker.com` script against a read-only base image. The atomic path adds Docker's real repo file then runs `rpm-ostree install docker-ce docker-ce-cli containerd.io docker-compose-plugin docker-buildx-plugin` — layered, not live, so a successful install reports `needs_reboot: True` and both front ends stop cleanly with real reboot instructions.

**Two real bugs, found and fixed live by Anvil against a real Bazzite host, ported here unchanged:**
1. **`usermod -aG docker <user>` reports real success and silently writes nothing** when the docker group was created by `systemd-sysusers` for a layered package and its canonical record lives only in `/usr/lib/group` (the `altfiles` NSS source, never present in `/etc/group` at all). **The real fix**: a local `/etc/group` entry with the same name+gid merges cleanly with the vendor entry (`nsswitch.conf`'s `group: files [SUCCESS=merge] altfiles ...`), after which `gpasswd` manages membership on it normally. `add_user_to_docker_group()` now tries plain `usermod` first and only falls back to the merge-entry trick when a real functional check (`_user_in_docker_group()`, `id -nG <user>`) shows the plain path didn't actually work.
2. **A plain `detect_docker()` re-check right after fixing group membership in the same process still fails**, since that process's own supplementary group list was fixed at login time and doesn't re-read `/etc/group`. `check_docker_ready(use_group_workaround=True)` closes this.

Also: `_ensure_docker_ready()` and `DockerReadyScreen` now check the result and report a clear error rather than silently proceeding into a readiness check that would just fail unexplained.

## Tiers

- **Light** — ≥ 2 cores, ≥ 4 GB RAM, ≥ 100 GB free
- **Medium** — ≥ 4 cores, ≥ 8 GB RAM, ≥ 500 GB free  
- **Heavy** — ≥ 6–8 cores, ≥ 16 GB RAM, ≥ 1 TB free

Every tier also offers the same tier-agnostic optional extras: Gluetun (VPN, on by default), SABnzbd (Usenet), Recyclarr (TRaSH sync), Decluttarr (queue cleanup), Maintainerr (library cleanup), Homepage/Dashy (dashboard), MeTube/Downtify (downloaders), Netdata (monitoring), Vaultwarden (password manager). Heavy adds GPU transcoding (when a GPU is detected), plus Lidarr, Readarr, Traefik, Authelia, CrowdSec, and Tailscale via custom mode.

All tiers share the same directory layout and volume naming, so re-running later to move up a tier shouldn't lose data.

### Custom mode

Pick exactly which services to include, from all known services regardless of tier, pre-checked based on what your hardware qualifies for. Resource limits still scale using whichever tier is chosen. `--domain` only ever takes effect when an explicit `--services` list containing `"traefik"` is passed.

## Design Principles

- **Deterministic, not AI-driven.** Tier recommendations from fixed rules over detected hardware — no LLM in the decision path.
- **Observe, then act.** The installer shows you what it detected and what it's about to generate before doing anything; nothing is silently overwritten.
- **Re-run safe.** Running again against an existing stack should offer to upgrade/reconfigure, not clobber it.
- **Secrets stay out of git.** Generated `.env` files are never committed; `.gitignore` excludes the whole `stack/` output directory.

## Code style

Heavy vertical spacing, matching the style established from the very first commit: each function argument on its own line in a multi-arg call, a blank line after `def ...():` before the body, blank lines between most statements. Very few docstrings (module-level explaining *why*, not function-level explaining *what*). New code should match whatever file it's editing.

## Project status

Pushed — `github.com/Cyb3rRon1n/vulcan` (private). The repo stayed local-only through its entire build, then was pushed for the first time once confirmed. Commit history was rewritten once, immediately before that first push (while there was still no remote — the only genuinely zero-risk moment to do it), to strip a `Co-Authored-By: Claude` trailer that had been added to 11 commits — the user asked not to have Claude appear as a contributor, confirmed to apply workspace-wide, not just here. New commits never get that trailer, in this repo or any other in this workspace. Commit freely at the end of a completed, verified slice, matching this workspace's general convention — `git push` has been explicitly requested per-instance each time so far (never given a standing "push whenever" approval the way `atlas` has), so continue confirming before pushing unless/until told otherwise.

All three originally-planned phases (engine + CLI, Heavy tier + re-run safety + full TUI, update/backup) are complete, plus a "custom mode" service picker (free pick across all 27 services, both in the plain-CLI flow via `--services` and in the TUI via `TierConfigScreen`'s "Customize Services" button), SABnzbd (purely-additive, tier-agnostic Usenet downloader alongside qBittorrent), Recyclarr (purely-additive, tier-agnostic TRaSH Guides config sync tool for Radarr/Sonarr), `vulcan restore` (the reverse of `vulcan backup`), real Traefik routing (domain-driven `traefik.*` labels + Traefik's own auto-generated self-signed HTTPS, verified against real containers), TUI back navigation (every screen but `WelcomeScreen` can `pop_screen()` back to a genuinely preserved previous screen), Homepage dashboard pre-seeding (real service tiles, not a blank dashboard), Readarr (a `*arr` app for books/ebooks, placed identically to Lidarr, pinned to the only real working image tag LinuxServer currently publishes), pre-pull mode (`vulcan pull`), airgap mode (`--offline`, `vulcan export`/`vulcan import`), read-only media-path redundancy detection, safe SQLite snapshotting in `vulcan backup` (via sqlite3's own online-backup API, so a live `*arr`/Jellyfin database is never archived mid-write), an Uptime Kuma setup reference (warning + real service URLs, scoped down from full pre-seeding once its Socket.IO-only API made that a materially bigger ask), a pre-flight port-availability check before the first `docker compose up -d` (root-caused to a genuine port collision with an unrelated container on the dev machine), a post-start summary listing every enabled service's real reachable URL added afterward, Homepage promoted from Heavy-only/non-optional to a real tier-agnostic opt-in question at every tier (default-enabled on a fresh install, with a backward-compatible default so an existing Heavy-tier deployment's next regenerate doesn't silently drop it), `vulcan uninstall` (stops the running stack and deletes `stack/` entirely, leaving the media library and, unless `--purge-artifacts` is passed, `backups/`/`exports/` untouched) rounding out the lifecycle commands for repeatable fresh-install testing, and an auth layer (Authelia behind Traefik's `forwardAuth` middleware, `default_policy: one_factor`, no LDAP/Postgres/Redis) closing the last open item from the original pain-points survey — verified end-to-end against real containers, including a real authenticated login round-trip through a real protected service, plus a follow-up fix so `vulcan uninstall` also tears down containers orphaned by `stack/` being deleted some other way (reported for real by the user, reproduced, and fixed), and a fix to `detect_gpu()` so it runs a real functional query per vendor instead of just checking tool presence (found while building the sibling Anvil project — this exact machine had been reporting a false "amd" for this project's entire history). Since then: keyboard-accessible TUI guidance (`DescendantFocus`-based tooltips reaching keyboard-only users, not just mouse-hover), a checklist-format `ROADMAP.md` (now the actively-maintained source of truth for shipped/open/out-of-scope, not this paragraph), Traefik's own dashboard routed securely through Traefik itself (closing the one real gap in Homepage's service coverage, plus a real pre-existing qBittorrent+Gluetun+Traefik dead-link bug found and fixed along the way), Homepage tile descriptions plus a real fix to a Homepage host-validation bug that made it completely unreachable on a fresh install, and Tailscale (a 19th real service) + Cloudflare DNS-01 support (a Traefik TLS modifier, not a 20th service), plus a second real pre-existing custom-mode/Gluetun bug found and fixed along the way — see the Architecture section above for all of these. See `ROADMAP.md` for anything past this point going forward. The only known, real, not-yet-addressed gap as of this writing: aarch64/ARM support has had a static readiness audit (every referenced Docker image confirmed to publish a real `linux/arm64` manifest, both install paths confirmed architecture-agnostic, two real known gaps in CPU/GPU detection documented rather than hidden) but has never actually been run end-to-end on real ARM hardware — everything real-verified in this project's history has been on this one real x86_64 Fedora machine, and a manifest/dependency check is deliberately not being counted as equivalent to that.
