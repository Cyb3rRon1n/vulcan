# Vulcan install restructure — design

**Status:** draft for review
**Date:** 2026-08-31
**Depends on:** PR #3 (`fix/restore-working-main`), PR #4 (`fix/integrate-new-services`)

## Problem

Vulcan's install works — the engine is solid and a full stack came up live —
but the first five minutes on a genuinely fresh machine are rough, and the
cause is structural, not a set of isolated bugs:

1. **Privilege model is scattered.** `./install` is a thin bash bootstrap
   that punts almost everything to Python. Python then needs root for Docker
   install, `systemctl`, and `usermod`, so it sprinkles `sudo` onto
   individual commands via `run_privileged()` — password prompts appear at
   odd moments, e.g. right after a whiptail screen clears.

2. **Generation is gated behind Docker being fully ready.** `run_install()`
   runs `_ensure_docker_ready()` and hard-exits (`Docker isn't ready — can't
   continue.`) *before* it generates anything. Writing `docker-compose.yml`
   + `.env` needs no Docker at all. A user who just wants to see what Vulcan
   would build can't, if Docker isn't perfect. This contradicts the
   project's own "observe, then act" principle.

3. **"Configure" is a day-2 afterthought.** Services that need credentials
   (VPN, domain, tunnel tokens, Authelia) are configured either by scattered
   inline prompts during the wizard *or* by a separate `Configure Services`
   menu item positioned *after* "start the stack". The natural order —
   build, then fill in credentials, then start — isn't the flow.

4. **The wizard's prompt sequence is untested and rots.** 27 `test_cli`
   tests drive the prompt loop with positional `input="\n\n\ny\n"` strings;
   every added question silently shifts what each `\n` answers.

## Goals

- `./install` owns 100% of privileged system setup ("Phase 0") in one
  bounded pass, escalating to root at most once.
- Everything after Phase 0 runs as the invoking user. `sudo ./install`
  never leaves root-owned files in the checkout (PR #3 started this; this
  spec completes the model).
- `vulcan build` (generate, never start) succeeds whenever the chosen
  config is valid — Docker being down is a warning, not a stop.
- First-run flow is an explicit linear sequence:
  **Preflight → Detect → Recommend → Shape → Confirm → Build → Configure →
  Start → Report.**
- The 27 interactive `test_cli` tests are rewritten to match on prompt
  *text*, not position, so they stop rotting.

## Non-goals

- No change to the engine (`detect.py`, `generate.py`, `tiers.py`,
  `storage.py`) beyond what the reordering strictly requires.
- No change to the two-front-ends-over-one-engine architecture, the
  first-run-wizard / later-menu split, or the `sg docker` group workaround.
- Phase 6 (Configure) writes `stack/.env` and stops. No live validation of
  credentials (no DNS-resolves check, no "does the VPN connect" probe) —
  Phase 7 (Start) already surfaces those failures clearly.
- No `curl | bash` remote installer in this PR (tracked separately).

## Current state (what exists to reuse)

| Piece | Where | Role today |
|---|---|---|
| `ensure_system_deps()` | `installer/deps.py` | installs python3 / whiptail / mdadm, per-distro plan, dry-run mode |
| `install_plan_for()` / `install_docker()` / `start_docker_service()` / `add_user_to_docker_group()` / `ensure_compose_v2()` | `installer/docker_setup.py` | Docker bootstrap, all with real functional re-checks |
| `_ensure_docker_ready()` | `installer/cli.py` | drives the above inside `run_install`, with `run_privileged()` sudo |
| `_ensure_system_deps()` | `installer/cli.py` | calls `ensure_system_deps()` early in `run_install` |
| `check_ports_available()` / `check_network_conflicts()` | `installer/preflight.py` | Phase 7 pre-start conflict checks |
| `configure_services_flow()` | `installer/menu.sh` | the credential walkthrough (day-2 menu item) |
| inline VPN/domain/Authelia prompts | `installer/cli.py` `_gather_generation_config()` | credential collection during the wizard |

The logic is all here and tested. This spec **reorders and re-homes it**;
it does not build a new bootstrap engine.

## Design

### 1. `./install` — the bootstrap owns Phase 0

New flow:

```
./install [flags]
  1. ensure python3 present         (bash, distro-aware — unchanged)
  2. create/repair .venv as the     (unchanged; runs as $SUDO_USER when
     invoking user, pip install      under sudo — PR #3)
  3. run Phase 0:  .venv/bin/python -m installer preflight --fix
       - if it reports it needs root and we are not root:
           echo the heads-up block, then  exec sudo "$0" "$@"
       - (a second pass after re-exec finds python3 + .venv already there
          and goes straight to preflight, now as root)
  4. exec .venv/bin/python -m installer "$@"   as the invoking user
```

The heads-up block, printed immediately before `exec sudo`:

```
Vulcan needs root once to install:
  - system packages (git, whiptail, mdadm, ...)
  - Docker Engine + docker compose
Escalating now (Ctrl-C to abort)...
```

`RUN_AS` from PR #3 already handles dropping back to `$SUDO_USER` for the
venv build and the final `exec`.

### 2. `vulcan preflight [--fix]` — Phase 0 as a command

New Typer command. Idempotent. Safe to re-run.

**Without `--fix`:** report only — what's present, what's missing, what
`--fix` would do. Exit 0 if nothing missing, 1 otherwise.

**With `--fix`:** actually install. Order:

1. `ensure_system_deps()` — extended to include **`git`** (new;
   `_TOOL_PACKAGES["git"] = {"debian": ["git"], "fedora": ["git"], "arch":
   ["git"]}`). python3-venv stays covered by the existing `python3` entry.
2. Docker: run the existing `install_plan_for` → `install_docker` →
   `start_docker_service` → `ensure_compose_v2` chain (moved verbatim from
   `_ensure_docker_ready`).
3. `add_user_to_docker_group($SUDO_USER or current user)` — the merge-entry
   trick and `_user_in_docker_group()` functional check are unchanged.
4. Re-detect and print a final ready/not-ready line.

**Root requirement:** `preflight --fix` needs root for steps 1–3. If not
root: print the one command to run (`sudo ./install`, or `sudo vulcan
preflight --fix`) and exit 1 — `./install` catches this and does the
`exec sudo` itself (step 3 above).

**Atomic-OS reboot split:** if `install_docker` returns `needs_reboot`
(rpm-ostree), `preflight --fix` prints the reboot instruction and exits;
re-running `./install` after reboot picks up from "Docker installed,
start + group" — same behaviour as today, just relocated.

### 3. `run_install()` — Build ≠ Start

- `_ensure_docker_ready()` shrinks to an **assertion**: re-detect; if Docker
  is not `installed && running && accessible && compose_v2`, print
  `Docker isn't ready — run  ./install  (or  vulcan preflight --fix ) first.`
  and exit 1. No install/start/group logic remains in `cli.py`.
- `_ensure_system_deps()` call in `run_install` is **removed** (preflight
  owns it).
- **Phase split.** `_generate_and_maybe_start()` becomes two steps:
  - `_build(config)` — always runs when `config` is valid. Writes
    `docker-compose.yml`, `.env`, `config/` dirs, `.vulcan-state.json`.
    Docker being down here produces a **warning line**, never an exit.
  - `_start(config, group_just_added)` — the Docker-requiring half:
    `check_ports_available` → `check_network_conflicts` → `compose up -d`
    → post-start health check. Runs only when `start` is true (from
    `--start` or the wizard's "start now?"), and only after asserting
    Docker ready.
- `vulcan build` — new command alias for "generate, never start" (today
  that's `--no-start` on the callback; keep `--no-start` working, add the
  named subcommand for discoverability).

### 4. Phase 6 — Configure, shared by both front-ends

New module `installer/configure.py` exposing
`configure_pending(config, non_interactive, answers) -> dict`:

- Given a built stack, determine which enabled services need credentials
  not yet in `.env`: gluetun (VPN provider + type + key/creds), traefik
  (`DOMAIN`), cloudflared (`TUNNEL_TOKEN`), tailscale (`TAILSCALE_AUTHKEY`),
  authelia (admin user — already hashed at build time, so this is
  informational), pihole/adguardhome (admin password).
- Interactive: prompt for each, in dependency order, write to `stack/.env`.
- Non-interactive: read from env vars / flags (the surface that already
  exists), write, and list anything still blank as a warning.
- **No validation.** Writes and returns.

Both front-ends call it at the same point:

- `cli.py` `run_install`: after `_build`, before `_start`. The inline VPN
  prompts currently in `_gather_generation_config` **move here** — the
  wizard stops asking for a WireGuard key mid-service-selection.
- `menu.sh`: `configure_services_flow` becomes a call into
  `vulcan configure` and is invoked as **step 6 of first-run**, not only as
  a day-2 menu item (it stays available day-2 too).

### 5. `menu.sh` first-run wizard — reordered

New sequence (each is a whiptail screen or a shell-out to `vulcan`):

| # | Screen | Backed by |
|---|---|---|
| — | *(Phase 0 already done by `./install` before menu.sh launched)* | |
| 1 | Welcome | whiptail |
| 2 | Detect — hardware summary | `vulcan detect` |
| 3 | Recommend — tier radiolist, pre-selected | `vulcan detect` fields |
| 4 | Shape — media path, tier, customize?, services, PUID/PGID/TZ | argv builder |
| 5 | Confirm — settings summary + yes/no | whiptail (fix the `--scrolltext` hang: bound each summary line to the box width so the buttons are always reachable) |
| 6 | Build | `vulcan build --non-interactive --yes …` |
| 7 | Configure — credential walkthrough | `vulcan configure` |
| 8 | Start now? → Start | `vulcan start` |
| 9 | Report — URLs + status + setup order | `vulcan urls` / `install-summary` |

Removed: the "Docker isn't fully ready" msgbox (Phase 0 handled it).

The **Review Settings hang** (observed under automation, unconfirmed at a
real TTY) is addressed regardless: the summary is built with real newlines
and each line padded/truncated to `DLG_COLS - 4`, and `--scrolltext` is
dropped unless the content genuinely overflows the dialog height.

### 6. The 27 `test_cli` tests

Rewrite against the post-restructure `_gather_generation_config`:

- Prefer calling `_gather_generation_config(...)` / the new
  `configure_pending(...)` **directly with explicit kwargs** and asserting
  on the returned `GenerationConfig`, rather than driving `runner.invoke`
  through the whole prompt loop.
- Where the full loop must be exercised, answer prompts by **matching the
  prompt text** (a small helper that feeds responses keyed on a substring
  of each `typer.prompt`/`confirm` message) instead of a positional `\n`
  string.
- Net: these tests stop breaking every time a question is added or moved.

## Data flow

```
./install ──► preflight --fix (root) ──► deps + docker + group
    │                                         │
    └─ drop to $SUDO_USER ────────────────────┘
              │
              ▼
        vulcan  (menu.sh or run_install)
              │
   detect ─► recommend ─► shape ─► confirm
              │
              ▼
         _build(config)                 ← no Docker needed; warns if down
              │
              ▼
      configure_pending(config)         ← writes stack/.env
              │
              ▼  (only if start requested)
     assert Docker ready ─► _start()    ← ports, network, compose up, health
              │
              ▼
          report (urls, status)
```

## Error handling

- **Phase 0 can't reach root:** `./install` prints the `sudo ./install`
  line and exits non-zero. Never proceeds half-configured.
- **Phase 0 partially fails** (e.g. Docker installs but the daemon won't
  start): `preflight --fix` reports each step's real result and exits
  non-zero; `./install` does not `exec vulcan`.
- **Docker down at Start:** `_start` asserts and exits with the
  run-preflight message. The built stack is left in place — the user can
  `vulcan start` later.
- **Build with Docker down:** succeeds, prints
  `Stack written to stack/ — Docker isn't ready yet, run  vulcan start
  when it is.`
- **A credential left blank in Configure:** written as-is (or left unset),
  listed in the Report as "needs configuration", Start still attempted —
  matching today's gluetun behaviour.

## Testing strategy

- **`preflight`:** unit tests mocking `ensure_system_deps` / the
  `docker_setup` functions — assert the report shape, the `--fix` call
  order, the not-root exit path, the `needs_reboot` short-circuit.
- **`./install`:** extend `tests/test_install.bats` — stub `id`,
  `runuser`, and a fake `vulcan` that prints a "needs root" sentinel;
  assert `./install` re-execs `sudo "$0"` exactly once and prints the
  heads-up block.
- **Build ≠ Start:** a `run_install` test with `detect_docker` mocked to
  "down" asserts `write_stack` **is** called and `compose up` is **not**,
  exit 0.
- **`configure_pending`:** unit tests per service (gluetun / traefik /
  cloudflared / tailscale / pihole) — given a built compose + partial
  `.env`, assert the right prompts and the resulting `.env`.
- **The 27:** rewritten as above; CI green.
- **Live, on the real host:** fresh-ish Ubuntu, `sudo ./install` end to
  end — Phase 0 installs Docker + adds the group, wizard builds a stack,
  Configure writes `.env`, Start brings it up, Report lists URLs.

## Rollout

Single PR, single branch off `fix/integrate-new-services` (so it carries
PR #3 + #4). Estimated ~6–10 commits:

1. add `git` to `deps.py` + tests
2. `vulcan preflight` command (move Docker logic out of `_ensure_docker_ready`) + tests
3. `./install` Phase-0 call + auto-sudo + bats
4. Build/Start split in `run_install` + `vulcan build` + tests
5. `configure_pending` + move inline VPN prompts + tests
6. `menu.sh` wizard reorder + Review-dialog fix + bats
7. rewrite the 27 `test_cli` tests
8. docs (`getting-started`, `walkthrough`, the AdGuard `:53` note)
9. live verification pass on the real host

`main` stays releasable at each commit only loosely — this is a restructure,
so the branch is long-lived and merged once, after the live pass.

## Risks / open

- **`preflight` as root running Python:** the venv is user-owned; root
  executing `$VENV/bin/python` is fine (it's just an interpreter), but any
  file it writes (there should be none in `--fix` — it only installs
  packages and calls `usermod`) must not land in the checkout. Audit that
  `preflight --fix` touches nothing under `SCRIPT_DIR`.
- **`runuser` availability:** util-linux, present on all target distros;
  PR #3 already depends on it. `sudo -u` is the fallback if a target lacks
  it (none known).
- **The Review-dialog hang** is still unconfirmed at a real TTY — the fix
  (bound line widths, conditional `--scrolltext`) is defensive and correct
  regardless, but someone should drive it at a keyboard once.
- **AdGuard `:53` vs `systemd-resolved`:** documentation only in this PR
  (disable `DNSStubListener`); a future change could detect the conflict in
  `preflight`.
