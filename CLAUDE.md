# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Quick Reference

```bash
# Setup
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Run the CLI
./install                      # bootstraps .venv, then opens Main Menu (whiptail GUI)
vulcan --plain                 # plain Typer prompts instead of TUI
python -m installer --plain    # equivalent, for running from source

# Lint (pyflakes-only - real bugs, not style)
ruff check .

# Tests
python -m pytest tests/        # see README's Known Issues for 3 env-state tests to deselect
python -m pytest tests/test_generate.py -v
```

## Architecture Overview

**Two interfaces, one engine.** The engine layer (`installer/detect.py`, `installer/docker_setup.py`, `installer/tiers.py`, `installer/services.py`, `installer/generate.py`, `installer/post_install.py`) consists of pure functions returning plain result dicts — they never prompt, confirm, or silently catch errors. `installer/cli.py` (Typer + Rich console) and `installer/menu.sh` (bash + real whiptail) are two independent front ends over that same engine — neither owns business logic the other doesn't also have.

**Entry points.**
- `./install` (bash) bootstraps `.venv` on first run and always `exec`s into `python -m installer "$@"` — mirrored by `scripts/update.sh`/`scripts/backup.sh`/`scripts/restore.sh`.
- `installer/__main__.py` and the `vulcan` console script both point at `installer.cli:app`.
- `installer/cli.py`'s `main()` is a `@app.callback(invoke_without_command=True)` — needed because both `./install` (zero args) and `./install --tier medium --non-interactive --yes` must work with no subcommand name, while `vulcan version`/`vulcan update`/`vulcan backup`/`vulcan restore` are real subcommands alongside it.

**Detection.** `detect_system(disk_path="/")` assembles `SystemInfo` from `detect_cpu()`/`detect_memory()`/`detect_disk()`/`detect_gpu()`/`detect_docker()`/`detect_os()` — all read-only, all catching their own failure modes and returning `None`/`False`/a zero value rather than raising.

**Docker bootstrap.** `install_plan_for(os_id, os_is_atomic)` maps a distro to an install method: `get.docker.com` (ubuntu/debian/raspbian/fedora), `pacman` (arch), `rpm-ostree` for atomic hosts (checked *before* `os_id`), `None` for anything else (manual install). `run_privileged()` prefixes `sudo` only when not already root.

**The group-membership gotcha.** A process's group list doesn't refresh mid-run after `usermod -aG docker <user>` — `run_docker_command(..., use_group_workaround=True)` routes through `sg docker -c "<cmd>"` (reads group membership fresh, no relogin needed) for exactly the run that just added the group, falling back to `sudo` if `sg` isn't present. Both `cli.py` and the TUI track a `group_just_added` flag through the whole session for this reason.

**Atomic/immutable-OS support.** `detect.py`'s `detect_os_is_atomic()` checks `/run/ostree-booted` before falling back to `shutil.which("rpm-ostree")`. `install_plan_for` checks it *before* `os_id` — Bazzite/Kinoite report `os_id="fedora"` (`ID_LIKE=fedora`), which would otherwise wrongly route through the plain `get.docker.com` script against a read-only base image.

**Two real bugs, found and fixed live by Anvil against a real Bazzite host, ported here unchanged:**
1. **`usermod -aG docker <user>` reports real success and silently writes nothing** when the docker group was created by `systemd-sysusers` for a layered package and its canonical record lives only in `/usr/lib/group` (the `altfiles` NSS source, never present in `/etc/group` at all). **The real fix**: a local `/etc/group` entry with the same name+gid merges cleanly with the vendor entry (`nsswitch.conf`'s `group: files [SUCCESS=merge] altfiles ...`), after which `gpasswd` manages membership on it normally. `add_user_to_docker_group()` now tries plain `usermod` first and only falls back to the merge-entry trick when a real functional check (`_user_in_docker_group()`, `id -nG <user>`) shows the plain path didn't actually work.
2. **A plain `detect_docker()` re-check right after fixing group membership in the same process still fails**, since that process's own supplementary group list was fixed at login time and doesn't re-read `/etc/group`. `check_docker_ready(use_group_workaround=True)` closes this.

Also: `_ensure_docker_ready()` and the TUI `DockerReadyScreen` now check the result and report a clear error rather than silently proceeding into a readiness check that would just fail unexplained.

## Tiers

- **Light** — ≥ 2 cores, ≥ 4 GB RAM, ≥ 100 GB free
- **Medium** — ≥ 4 cores, ≥ 8 GB RAM, ≥ 500 GB free
- **Heavy** — ≥ 6–8 cores, ≥ 16 GB RAM, ≥ 1 TB free

Every tier also offers tier-agnostic optional extras: Gluetun (VPN, on by default), SABnzbd (Usenet), Recyclarr (TRaSH sync), Decluttarr (queue cleanup), Maintainerr (library cleanup), Homepage/Dashy (dashboard), MeTube/Downtify (downloaders), Netdata (monitoring), Vaultwarden (password manager). Heavy adds GPU transcoding (when a GPU is detected), plus Lidarr, Readarr, Traefik, Authelia, CrowdSec, and Tailscale via custom mode.

All tiers share the same directory layout and volume naming, so re-running later to move up a tier shouldn't lose data.

### Custom mode

Pick exactly which services to include, from all known services regardless of tier, pre-checked based on what your hardware qualifies for. Resource limits still scale using whichever tier is chosen. `--domain` only ever takes effect when an explicit `--services` list containing `"traefik"` is passed.

## Design Principles

- **Deterministic, not AI-driven.** Tier recommendations from fixed rules over detected hardware — no LLM in the decision path.
- **Observe, then act.** The installer shows you what it detected and what it's about to generate before doing anything; nothing is silently overwritten.
- **Re-run safe.** Running again against an existing stack should offer to upgrade/reconfigure, not clobber it.
- **Secrets stay out of git.** Generated `.env` files are never committed; `.gitignore` excludes the whole `stack/` output directory.

## Project Status

Public — `github.com/Cyb3rRon1n/vulcan`. All three originally-planned phases (engine + CLI, Heavy
tier + re-run safety + full TUI, update/backup) are complete, plus everything shipped since —
custom-mode service picker, SABnzbd, Recyclarr, `vulcan restore`, real Traefik routing, TUI back
navigation, Homepage/Dashy pre-seeding, Readarr, airgap mode, an auth layer (Authelia + Traefik
`forwardAuth`), and more. See [ROADMAP.md](ROADMAP.md) for the full shipped/open checklist — it's
the maintained source of truth for what's done and what's next, this file covers the architecture
and decisions behind it.
