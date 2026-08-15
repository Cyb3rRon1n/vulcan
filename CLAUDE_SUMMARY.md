## Objective
- **Fix the real Guided Setup failure** `Failed to write the stack: [Errno 13] Permission denied: '/mnt/media/downloads'` — the provisioned media volume `/mnt/media` is root-owned, so the unprivileged user's `write_stack()` cannot create media subdirectories.
- **(Background, already shipped)** the Rich live progress panel for every menu operation — committed as `eb94ad8` and pushed to `github.com:Cyb3rRon1n/vulcan` main (`07fda94..eb94ad8`).

## Important Details
- **Debugging follows the systematic-debugging skill** (Phase 1 root-cause investigation complete, Phase 2-3 fix implemented): root cause confirmed before any fix was proposed.
- **Root cause**: `apply_storage_layout()` (installer/storage.py:576) provisions the volume (mdadm → mkfs → mount → fstab append) with **no chown anywhere**. A fresh ext4 root is `root:root` mode 755, so the invoking user (PUID/PGID 1000) gets EACCES when `write_stack()` (generate.py:884) tries `(media_path / "downloads").mkdir(parents=True, exist_ok=True)` plus sibling dirs at 885–890.
- **The failed machine already has `/mnt/media` mounted** from an earlier apply, so `apply_storage_layout` hits the `already_provisioned=True` early-return noop path (`storage.py:688-696`). A fresh-apply-only fix would not help — the fix must cover **both** the fresh apply path and the already-provisioned path, else this user can't recover without manual chown.
- **Planned fix direction**: add a `chown <uid>:<gid> <mount_point>` command after `mount` in both the plan's commands (so `vulcan storage plan` shows it) and in the `already_provisioned` early-return branch (so re-running `vulcan storage apply` repairs the existing mount). Owner = `SUDO_UID`/`SUDO_GID` env vars when set (whole CLI under sudo), else `os.geteuid()`/`os.getegid()`. Non-recursive chown on the mount root is sufficient — `write_stack` creates the subdirs itself as the invoking user, and containers run as that same PUID/PGID.
- **`_provision_owner()`** helper (storage.py:309-324) resolves the media-owner uid:gid: prefers `SUDO_UID`/`SUDO_GID` when set, else `os.geteuid()`/`os.getegid()`. Returns `"0:0"` when genuinely root-running (chown skipped as harmless no-op).
- **`plan_storage_layout()`** (storage.py:437): after `["mount", target_device, mount_point]`, appends `["chown", owner, mount_point]` (skipped when owner resolves to `"0:0"`). This keeps the plan's "commands list is the real argv that would run unchanged" invariant, and makes `vulcan storage plan` show the ownership fix.
- **`apply_storage_layout()`** (storage.py:688-711): the `already_provisioned` branch (`current_source == target_device`) now runs the chown repair via `run_privileged` before returning `already_provisioned=True`. If chown fails, returns `already_provisioned=False` with an error. If it succeeds, includes the chown in `ran` and keeps `already_provisioned=True`.
- **`_apply_plan()` test helper** (tests/test_storage.py:489) also appends `["chown", "1000:1000", mount]` so apply-sequence tests remain deterministic.
- **Existing tests updated** (44 storage tests, all pass; 603 total suite; ruff clean; 23 bats green) to account for the new chown command in exact-sequence assertions.
- **Environment**: workdir `/home/sentinel/Projects/github/my-repos/vulcan`; pytest/ruff via `.venv/bin/`; bats at `/home/sentinel/.npm-global/bin/bats`; commit at end of verified slice; **confirm before git push** (user explicitly confirmed).

## Work State
### Completed
- Entire Rich live panel slice: **committed `eb94ad8`** ("feat: Rich live progress panel for every menu operation", 9 files, +761/−43) and **pushed** to `github.com:Cyb3rRon1n/vulcan` main (`07fda94..eb94ad8`).
- `installer/panel.py` (new): `RunPanel`/`_NoOpPanel`/`progress_panel`; `Live(refresh_per_second=8, transient=False)`; `_LOG_LINES = 12`; stream sink set/cleared on enter/exit; `__exit__` finishes Failed on raised body.
- `installer/shell.py`: module-level stream sink + `run_streaming()` (merges stderr via `STDOUT`, `text=True`, `bufsize=1`, stdin inherited for sudo; strips only trailing newline; returns 127 on OSError); `run_privileged()` sink-aware with unchanged `{"success","error"}` shapes.
- `installer/docker_setup.py`: `run_docker_command()` sink-aware → synthetic `subprocess.CompletedProcess(command, returncode)`.
- `installer/cli.py`: all 8 commands wrapped — `update` (["Pull images","Recreate containers"], `on_phase=panel.advance`, `finish(result["success"])`), `pull`, `backup`, `update_self`, `storage_apply`, `restore` (start-confirm stays AFTER restore; up runs inside panel when `start is True`, else after panel for interactive), `uninstall`, `run_install` (phases = ["Detect system","Docker ready","Configure stack","Generate stack"] + "Start stack" when `start is not False`; `panel.finish(True)` at end). `_generate_and_maybe_start` gained optional `on_phase` param.
- `installer/menu.sh`: `confirm_and_run` now runs `VULCAN_PROGRESS=1 "$@"` (per-command only, not exported into the menu loop).
- Tests: **603 pytest** (+19 new: 13 in new tests/test_panel.py incl. `test_exit_with_raised_body_shows_failed`; 6 in tests/test_shell.py), ruff clean, **23 bats green**. Real-pty verification confirmed panel rendering, live streaming of subprocess lines, and final bold-green "Done." frame.
- Debugging Phase 1 (root cause) for the current permission bug: complete.

### Active
- Fix for the permission-denied bug: **implemented and verified** (all 603 pytest passing, ruff clean, 23 bats green). Fix adds `_provision_owner()` helper, chown to plan commands in `plan_storage_layout()`, and chown repair in the already-provisioned early-return branch of `apply_storage_layout()`.

### Blocked
- (none) — the fix handles both fresh apply and already-provisioned re-run; verified across full test suite.

## Next Move
- The verified slice is complete: all 603 pytest, ruff `check .`, and 23 bats tests pass. Commit the verified slice and ask before push.

## Relevant Files
- `installer/storage.py`: `_provision_owner()` (new, ~line 309), `plan_storage_layout()` chown addition (~line 437), `apply_storage_layout()` already_provisioned chown repair (~line 688)
- `tests/test_storage.py`: test updates for chown in plan commands and apply sequence (tests 141–605)
- `installer/panel.py`, `installer/shell.py`, `installer/cli.py`, `installer/menu.sh`: shipped panel slice (reference only, already completed)
- `tests/test_storage.py` 44 tests and `tests/test_menu.bats` 23 tests: updated to account for new chown command in assertions