# Vulcan Install Restructure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move all privileged system setup into `./install` as one bounded "Phase 0" pass, let stack generation succeed without Docker, and make credential configuration an explicit step between build and start.

**Architecture:** `./install` (bash) gets Python + a user-owned venv, runs `vulcan preflight --fix` (auto-`exec sudo` once if not root), then `exec vulcan` as the invoking user. A new `installer/phase0.py` orchestrates deps + Docker install/start/group (logic moved verbatim from `installer/cli.py::_ensure_docker_ready`). `run_install()` splits generation (`_build`, always runs) from launch (`_start`, needs Docker). A new `installer/configure.py` collects service credentials after build, before start, called by both front-ends.

**Tech Stack:** Python 3.11+, Typer, Rich, Jinja2, PyYAML, pytest, bash, whiptail, bats.

**Spec:** `docs/superpowers/specs/2026-08-31-install-restructure-design.md`

## Global Constraints

- Python floor: **3.11+** (`pyproject.toml`, `install` `REQUIRED_VERSION="3.11"`).
- Lint: `ruff check .` must stay clean (Pyflakes `F` rules only). Run before every commit.
- Engine purity: `installer/detect.py`, `installer/generate.py`, `installer/tiers.py`, `installer/storage.py` are pure — no prompting, no `sudo`, no silent `except`. Do not add any.
- The two front-ends (`installer/cli.py`, `installer/menu.sh`) must stay behaviourally equal — neither owns business logic the other lacks.
- Privileged commands go through `installer/shell.py::run_privileged()` (prefixes `sudo` only when not already root). Never call `sudo` directly in Python.
- `menu.sh` shells out to `vulcan ... --non-interactive --yes`; it never re-implements engine logic.
- Code style: heavy vertical spacing, one blank line between logical blocks (match surrounding code; see `CLAUDE.md`).
- Commit message trailer on every commit: `Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>`.
- Branch: work on `spec/install-restructure` (already carries PR #3 + #4). Do not branch off `main`.
- Full test command: `.venv/bin/python -m pytest -q`. Bats: `bats tests/test_install.bats tests/test_menu.bats`.
- Baseline at plan start: **27 failing** pytest tests, all in `tests/test_cli.py` (interactive prompt-sequence rot — Task 10 fixes them). Every other task must keep the non-`test_cli` suite green and must not increase the `test_cli` failure count.

---

## File Structure

| File | Create/Modify | Responsibility |
|---|---|---|
| `installer/deps.py` | Modify | add `git` to the system-package tool list |
| `installer/phase0.py` | **Create** | orchestrate Phase 0: deps + Docker install/start/group, one report dict. Distinct from `installer/preflight.py` (that one is port/network conflict checks, run just before `compose up`). |
| `installer/cli.py` | Modify | new `preflight` + `build` + `configure` commands; `_ensure_docker_ready` → `_assert_docker_ready`; `_generate_and_maybe_start` → `_build` + `_start`; drop the inline VPN prompts + the `_ensure_system_deps` call from `run_install` |
| `installer/configure.py` | **Create** | `configure_pending()` — per-service credential prompts → write `stack/.env`; shared by both front-ends |
| `install` | Modify | run `vulcan preflight --fix` as Phase 0; auto-`exec sudo "$0" "$@"` once when it reports it needs root |
| `installer/menu.sh` | Modify | reorder the first-run wizard to Detect→Recommend→Shape→Confirm→Build→Configure→Start→Report; drop the Docker msgbox; fix the Review-dialog line widths |
| `tests/test_deps.py` | Modify | `git` in the plan |
| `tests/test_phase0.py` | **Create** | `ensure_system_ready` report shape, `--fix` call order, not-root path, `needs_reboot` short-circuit |
| `tests/test_configure.py` | **Create** | per-service credential prompt + `.env` write |
| `tests/test_cli.py` | Modify | `preflight`/`build`/`configure` command tests; `_assert_docker_ready`; Build-without-Docker; rewrite the 27 prompt-sequence tests |
| `tests/test_install.bats` | Modify | Phase-0 call + auto-sudo re-exec |
| `tests/test_menu.bats` | Modify | wizard reorder assertions |
| `docs/getting-started/index.md`, `docs/walkthrough.md` | Modify | new flow, prerequisites, AdGuard `:53` note |

---

## Task 1: Add `git` to system-dependency install

**Files:**
- Modify: `installer/deps.py`
- Test: `tests/test_deps.py`

**Interfaces:**
- Produces: `ensure_system_deps()` unchanged signature; its plan now also covers `git` when absent.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_deps.py`:

```python
def test_git_is_in_the_debian_install_plan_when_missing(monkeypatch):
    from installer import deps

    monkeypatch.setattr(deps, "detect_os", lambda: {"os_id": "ubuntu", "os_is_atomic": False})
    monkeypatch.setattr(deps, "_tool_present", lambda tool: tool != "git")

    plan = deps.ensure_system_deps(dry_run=True)

    assert "git" in plan["packages"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_deps.py::test_git_is_in_the_debian_install_plan_when_missing -v`
Expected: FAIL — `"git"` not in `plan["packages"]` (KeyError on `_TOOL_PACKAGES["git"]` is also acceptable; either means the feature is missing).

- [ ] **Step 3: Add `git` to the tool tables**

In `installer/deps.py`, add a `git` entry to `_TOOL_PACKAGES`:

```python
_TOOL_PACKAGES = {
    "python3": {"debian": ["python3", "python3-venv"], "fedora": ["python3"], "arch": ["python"]},
    "whiptail": {"debian": ["whiptail"], "fedora": ["newt"], "arch": ["libnewt"]},
    "mdadm": {"debian": ["mdadm"], "fedora": ["mdadm"], "arch": ["mdadm"]},
    "git": {"debian": ["git"], "fedora": ["git"], "arch": ["git"]},
}
```

And add `"git"` to the iteration tuple in `ensure_system_deps()`:

```python
    for tool in ("python3", "whiptail", "mdadm", "git"):
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_deps.py -v`
Expected: PASS (all, including existing).

- [ ] **Step 5: Lint + commit**

```bash
.venv/bin/ruff check .
git add installer/deps.py tests/test_deps.py
git commit -m "feat: install git as a system dependency (needed for the initial clone on a fresh host)

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 2: `installer/phase0.py` — the Phase 0 orchestrator

**Files:**
- Create: `installer/phase0.py`
- Create: `tests/test_phase0.py`

**Interfaces:**
- Consumes: `installer.deps.ensure_system_deps`, `installer.detect.detect_docker`/`detect_os`, `installer.docker_setup.{install_plan_for, install_docker, start_docker_service, add_user_to_docker_group, ensure_compose_v2, check_docker_ready}`, `installer.shell` (no direct use, but `run_privileged` is what the docker_setup functions call).
- Produces:
  ```python
  def ensure_system_ready(fix: bool, user: str | None = None) -> dict
  # returns:
  # {
  #   "ready": bool,          # deps present AND docker installed+running+accessible+compose_v2
  #   "needs_root": bool,     # a --fix step needs root and we are not root (nothing was done)
  #   "needs_reboot": bool,   # docker was layered via rpm-ostree; reboot then re-run
  #   "missing": list[str],   # tool/step names still not satisfied
  #   "did": list[str],       # human-readable steps performed (empty when fix=False)
  #   "group_added": bool,    # this run added `user` to the docker group
  # }
  ```

- [ ] **Step 1: Write the failing tests**

Create `tests/test_phase0.py`:

```python
from unittest.mock import patch

from installer import phase0


DOCKER_READY = {
    "docker_installed": True, "docker_running": True,
    "docker_accessible": True, "docker_compose_v2": True,
}
DOCKER_ABSENT = {
    "docker_installed": False, "docker_running": False,
    "docker_accessible": False, "docker_compose_v2": False,
}


def test_report_only_when_everything_present():
    with patch("installer.phase0.ensure_system_deps", return_value={
        "success": True, "packages": [], "installed": [], "missing_after": [], "needs_reboot": False,
    }), patch("installer.phase0.detect_docker", return_value=DOCKER_READY):

        report = phase0.ensure_system_ready(fix=False)

    assert report["ready"] is True
    assert report["missing"] == []
    assert report["did"] == []


def test_fix_installs_docker_then_starts_then_adds_group_in_order():
    calls = []

    with patch("installer.phase0.ensure_system_deps", return_value={
        "success": True, "packages": [], "installed": [], "missing_after": [], "needs_reboot": False,
    }), patch("installer.phase0.detect_docker", side_effect=[DOCKER_ABSENT, DOCKER_READY]), \
        patch("installer.phase0.install_plan_for", return_value={"method": "get.docker.com", "description": "x", "needs_reboot": False}), \
        patch("installer.phase0.install_docker", side_effect=lambda *a: calls.append("install") or {"success": True, "needs_reboot": False, "error": None}), \
        patch("installer.phase0.start_docker_service", side_effect=lambda *a: calls.append("start")), \
        patch("installer.phase0.ensure_compose_v2", side_effect=lambda *a: calls.append("compose")), \
        patch("installer.phase0.add_user_to_docker_group", side_effect=lambda u: calls.append("group") or {"success": True, "error": None}), \
        patch("installer.phase0.check_docker_ready", return_value={"docker_running": True, "docker_compose_v2": True}):

        report = phase0.ensure_system_ready(fix=True, user="sentinel")

    assert calls == ["install", "start", "compose", "group"]
    assert report["ready"] is True
    assert report["group_added"] is True


def test_fix_needs_root_when_not_root_and_docker_missing():
    with patch("installer.phase0.ensure_system_deps", return_value={
        "success": True, "packages": [], "installed": [], "missing_after": [], "needs_reboot": False,
    }), patch("installer.phase0.detect_docker", return_value=DOCKER_ABSENT), \
        patch("installer.phase0.os.geteuid", return_value=1000):

        report = phase0.ensure_system_ready(fix=True, user="sentinel")

    assert report["needs_root"] is True
    assert report["ready"] is False
    assert report["did"] == []


def test_fix_short_circuits_on_rpm_ostree_reboot():
    with patch("installer.phase0.ensure_system_deps", return_value={
        "success": True, "packages": [], "installed": [], "missing_after": [], "needs_reboot": False,
    }), patch("installer.phase0.detect_docker", return_value=DOCKER_ABSENT), \
        patch("installer.phase0.os.geteuid", return_value=0), \
        patch("installer.phase0.install_plan_for", return_value={"method": "rpm-ostree", "description": "x", "needs_reboot": True}), \
        patch("installer.phase0.install_docker", return_value={"success": True, "needs_reboot": True, "error": None}):

        report = phase0.ensure_system_ready(fix=True, user="sentinel")

    assert report["needs_reboot"] is True
    assert report["ready"] is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_phase0.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'installer.phase0'`.

- [ ] **Step 3: Create `installer/phase0.py`**

```python
"""
Phase 0 - everything a Vulcan first run needs in place before the
whiptail menu or `run_install` starts: system packages (git, whiptail,
mdadm; python3 is handled by the bash `install` bootstrap before any
Python exists) and a working Docker (installed, daemon up, this user in
the docker group, compose v2). This is the one privileged pass - the
bash `install` script re-execs itself under sudo when a step here
reports `needs_root`.

Distinct from installer/preflight.py, which checks host-port and Docker-
network conflicts against an already-written compose file, right before
`docker compose up -d`. Phase 0 is 'can this machine run a stack at all';
preflight is 'will this specific stack's ports bind'.

The Docker install/start/group logic here was moved verbatim out of
installer/cli.py::_ensure_docker_ready - same functions, same real
functional re-checks (add_user_to_docker_group's merge-entry trick,
check_docker_ready's sg-docker workaround), just relocated so it runs
once, up front, as root, instead of mid-wizard with scattered sudo.
"""

import getpass
import os

from installer.deps import ensure_system_deps
from installer.detect import detect_docker
from installer.docker_setup import (
    add_user_to_docker_group,
    check_docker_ready,
    ensure_compose_v2,
    install_docker,
    install_plan_for,
    start_docker_service,
)


def _docker_fully_ready(state: dict) -> bool:

    return (
        state["docker_installed"]
        and state["docker_running"]
        and state.get("docker_accessible", True)
        and state["docker_compose_v2"]
    )


def ensure_system_ready(fix: bool, user: str | None = None) -> dict:
    """See module docstring. `fix=False` only reports. `fix=True` installs
    what's missing; if a step needs root and we are not root, nothing is
    done and `needs_root` is True."""

    user = user or os.environ.get("SUDO_USER") or getpass.getuser()

    report = {
        "ready": False,
        "needs_root": False,
        "needs_reboot": False,
        "missing": [],
        "did": [],
        "group_added": False,
    }

    is_root = os.geteuid() == 0

    # --- system packages -------------------------------------------------
    deps_plan = ensure_system_deps(dry_run=True)

    if deps_plan["packages"]:

        if not fix:
            report["missing"].extend(deps_plan["packages"])
        elif not is_root:
            report["needs_root"] = True
        else:
            result = ensure_system_deps()
            report["did"].extend(f"installed {tool}" for tool in result["installed"])
            report["missing"].extend(result["missing_after"])

    # --- Docker --------------------------------------------------------
    state = detect_docker()

    if not _docker_fully_ready(state):

        if not fix:
            report["missing"].append("docker")
            return _finalize(report)

        if not is_root and not state["docker_installed"]:
            report["needs_root"] = True
            return _finalize(report)

        group_added = _fix_docker(state, user, is_root, report)

        if report["needs_root"] or report["needs_reboot"]:
            return _finalize(report)

        state = detect_docker()

        if group_added:
            readiness = check_docker_ready(use_group_workaround=True)
            state["docker_running"] = readiness["docker_running"]
            state["docker_compose_v2"] = readiness["docker_compose_v2"]
            state["docker_accessible"] = readiness["docker_running"]
            report["group_added"] = True

    return _finalize(report, state)


def _fix_docker(state: dict, user: str, is_root: bool, report: dict) -> bool:
    """Returns True if this user was just added to the docker group."""

    if not state["docker_installed"]:

        plan = install_plan_for_os()

        if plan is None:
            report["missing"].append("docker (no automatic install for this OS)")
            return False

        result = install_docker(*_os_args())

        if not result["success"]:
            report["missing"].append(f"docker ({result['error']})")
            return False

        report["did"].append("installed Docker")

        if result["needs_reboot"]:
            report["needs_reboot"] = True
            return False

        start_docker_service()
        report["did"].append("started the Docker service")

        ensure_compose_v2(_os_id())
        report["did"].append("ensured docker compose v2")

        group_result = add_user_to_docker_group(user)

        if not group_result["success"]:
            report["missing"].append(f"docker group ({group_result['error']})")
            return False

        report["did"].append(f"added {user} to the docker group")
        return True

    if state["docker_running"] and not state.get("docker_accessible", True):

        if not is_root:
            report["needs_root"] = True
            return False

        group_result = add_user_to_docker_group(user)

        if not group_result["success"]:
            report["missing"].append(f"docker group ({group_result['error']})")
            return False

        report["did"].append(f"added {user} to the docker group")
        return True

    if not state["docker_running"]:

        if not is_root:
            report["needs_root"] = True
            return False

        start_docker_service()
        report["did"].append("started the Docker service")

        group_result = add_user_to_docker_group(user)

        if not group_result["success"]:
            report["missing"].append(f"docker group ({group_result['error']})")
            return False

        report["did"].append(f"added {user} to the docker group")
        return True

    if not state["docker_compose_v2"]:

        if not is_root:
            report["needs_root"] = True
            return False

        ensure_compose_v2(_os_id())
        report["did"].append("installed docker compose v2")

    return False


def _os_id() -> str | None:
    from installer.detect import detect_os
    return detect_os().get("os_id")


def _os_args() -> tuple:
    from installer.detect import detect_os
    info = detect_os()
    return info.get("os_id"), info.get("os_is_atomic", False)


def install_plan_for_os():
    return install_plan_for(*_os_args())


def _finalize(report: dict, state: dict | None = None) -> dict:

    if state is not None:
        report["ready"] = not report["missing"] and _docker_fully_ready(state)

    return report
```

> Note: the test file patches `installer.phase0.install_plan_for` and
> `installer.phase0.os.geteuid` etc. directly — keep those names imported
> at module scope exactly as written above so the patches bind.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_phase0.py -v`
Expected: PASS (4 tests). Fix mismatches between the test's patch targets and the module's imports until green.

- [ ] **Step 5: Lint + commit**

```bash
.venv/bin/ruff check .
git add installer/phase0.py tests/test_phase0.py
git commit -m "feat: installer/phase0.py - one privileged pass for deps + Docker

Moves the Docker install/start/group chain out of cli.py's mid-wizard
_ensure_docker_ready into a standalone Phase 0 orchestrator that reports
whether it needs root, so the bash bootstrap can re-exec under sudo once.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 3: `vulcan preflight` command

**Files:**
- Modify: `installer/cli.py` (add command + imports)
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `installer.phase0.ensure_system_ready` (Task 2).
- Produces: `vulcan preflight [--fix]` — exit 0 when `report["ready"]`, exit 1 otherwise; exit 1 with a `sudo ./install` hint when `report["needs_root"]`; exit 0 (no error) but a reboot message when `report["needs_reboot"]`. Prints one line per `report["did"]` and per `report["missing"]`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_cli.py`:

```python
def test_preflight_reports_ready_and_exits_zero():
    with patch("installer.cli.ensure_system_ready", return_value={
        "ready": True, "needs_root": False, "needs_reboot": False,
        "missing": [], "did": [], "group_added": False,
    }):
        result = runner.invoke(app, ["preflight"])

    assert result.exit_code == 0
    assert "ready" in result.output.lower()


def test_preflight_fix_needs_root_hints_sudo_and_exits_one():
    with patch("installer.cli.ensure_system_ready", return_value={
        "ready": False, "needs_root": True, "needs_reboot": False,
        "missing": ["docker"], "did": [], "group_added": False,
    }):
        result = runner.invoke(app, ["preflight", "--fix"])

    assert result.exit_code == 1
    assert "sudo ./install" in result.output


def test_preflight_fix_reboot_prints_message_exits_zero():
    with patch("installer.cli.ensure_system_ready", return_value={
        "ready": False, "needs_root": False, "needs_reboot": True,
        "missing": [], "did": ["installed Docker"], "group_added": False,
    }):
        result = runner.invoke(app, ["preflight", "--fix"])

    assert result.exit_code == 0
    assert "reboot" in result.output.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_cli.py -k preflight -v`
Expected: FAIL — no `preflight` command (Typer usage error / exit 2).

- [ ] **Step 3: Implement the command**

In `installer/cli.py`, add near the other `from installer.*` imports:

```python
from installer.phase0 import ensure_system_ready
```

Add the command (place it next to the other `@app.command()` definitions, e.g. after `detect_shell`):

```python
@app.command()
def preflight(
    fix: bool = typer.Option(False, "--fix", help="Install what's missing (needs root for Docker/packages).")
):
    """Phase 0: check (or with --fix, install) the system packages and
    Docker setup a first run needs. Idempotent - safe to re-run."""

    report = ensure_system_ready(fix=fix)

    for step in report["did"]:
        console.print(f"[green]✓[/green] {step}")

    if report["needs_reboot"]:
        console.print(
            "\n[yellow]Docker was layered via rpm-ostree (atomic OS). Reboot, "
            "then run ./install again - it will pick up from here.[/yellow]\n"
            "  sudo systemctl reboot"
        )
        raise typer.Exit(code=0)

    if report["needs_root"]:
        console.print(
            "\n[red]Phase 0 needs root to install Docker / system packages.[/red]\n"
            "  sudo ./install"
        )
        raise typer.Exit(code=1)

    if report["ready"]:
        console.print("[green]System is ready.[/green]")
        raise typer.Exit(code=0)

    console.print("\n[red]Still missing:[/red] " + ", ".join(report["missing"]))
    console.print("Run  ./install  (or  sudo vulcan preflight --fix ) to install these.")
    raise typer.Exit(code=1)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_cli.py -k preflight -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Lint + commit**

```bash
.venv/bin/ruff check .
git add installer/cli.py tests/test_cli.py
git commit -m "feat: vulcan preflight [--fix] - Phase 0 as a command

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 4: `run_install` — drop the install logic, assert Docker

**Files:**
- Modify: `installer/cli.py` (`run_install`, `_ensure_docker_ready`)
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `_assert_docker_ready(info) -> SystemInfo` — re-detects; if Docker is not fully ready, prints the run-`./install` message and `raise typer.Exit(code=1)`; otherwise returns the refreshed `info`. `run_install` no longer calls `_ensure_system_deps` or the old `_ensure_docker_ready`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_cli.py`:

```python
def test_run_install_asserts_docker_and_exits_when_not_ready(tmp_path):
    """After the Phase-0 move, run_install does not install Docker - it
    asserts and points at ./install."""

    media_path = str(tmp_path / "media")
    down = make_system_info(docker_running=False, docker_compose_v2=False)

    with patch("installer.cli.detect_system", return_value=down), patch(
        "installer.cli.detect_disk",
        return_value={"disk_free_gb": 900.0, "disk_path_checked": media_path}
    ), patch(
        "installer.cli.detect_docker",
        return_value={"docker_installed": True, "docker_running": False,
                      "docker_accessible": False, "docker_compose_v2": False}
    ), patch("installer.cli.install_docker") as mock_install, patch(
        "installer.cli.start_docker_service"
    ) as mock_start:

        result = runner.invoke(app, [
            "--tier", "light", "--media-path", media_path,
            "--non-interactive", "--yes", "--no-vpn", "--start"
        ])

    assert result.exit_code == 1
    assert "./install" in result.output
    mock_install.assert_not_called()
    mock_start.assert_not_called()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_cli.py::test_run_install_asserts_docker_and_exits_when_not_ready -v`
Expected: FAIL — the old `_ensure_docker_ready` still calls `install_docker`/`start_docker_service`.

- [ ] **Step 3: Replace `_ensure_docker_ready` with `_assert_docker_ready`**

In `installer/cli.py`, delete the body of `_ensure_docker_ready` and replace with:

```python
def _assert_docker_ready(info: SystemInfo) -> SystemInfo:
    """Phase 0 (`./install` / `vulcan preflight --fix`) is responsible for
    getting Docker ready. By the time run_install runs it either is, or we
    stop here and point the user back at ./install."""

    state = detect_docker()
    info.docker_installed = state["docker_installed"]
    info.docker_running = state["docker_running"]
    info.docker_accessible = state.get("docker_accessible", True)
    info.docker_compose_v2 = state["docker_compose_v2"]

    if not (info.docker_installed and info.docker_running
            and info.docker_accessible and info.docker_compose_v2):
        console.print(
            "[red]Docker isn't ready.[/red] Run  ./install  again "
            "(or  vulcan preflight --fix ) to install/start it and add your "
            "user to the docker group, then retry."
        )
        raise typer.Exit(code=1)

    return info
```

In `run_install`, change the Phase 2 block. Find:

```python
        info, group_just_added = _ensure_docker_ready(info, non_interactive, yes, offline, panel)

        if not (info.docker_installed and info.docker_running and info.docker_compose_v2):
            panel.finish(False)
            console.print("[red]Docker isn't ready - can't continue.[/red]")
            raise typer.Exit(code=1)
```

Replace with:

```python
        group_just_added = False   # Phase 0 owns the group add now; kept for
                                   # _start's use_group_workaround signature.
```

(Do **not** call `_assert_docker_ready` here — it moves to `_start`, Task 6.)

Also in `run_install`, **remove** the line:

```python
    _ensure_system_deps(non_interactive=non_interactive)
```

Leave `_ensure_system_deps` and the old `deps` command path alone (the standalone `vulcan deps` command, if any, still works); only the `run_install` call is removed.

Update the `phases` list in `run_install` — remove `"Docker ready"`:

```python
    phases = ["Detect system", "Storage setup", "Configure stack", "Generate stack"]
```

and delete the now-orphaned `panel.advance()` that followed the old docker block.

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/test_cli.py -q`
Expected: the new test PASSES. Several **old** docker-install tests will now fail (`test_docker_installed_but_not_running_starts_service`, `test_docker_bootstrap_installs_when_not_ready_in_order`, `test_docker_running_but_missing_compose_v2`, `test_ensure_docker_ready_adds_group_when_daemon_up_but_inaccessible`, `test_docker_daemon_up_but_user_not_in_group_...`). **Delete** those tests — their behaviour moved to `tests/test_phase0.py` (Task 2). Confirm each deleted test's scenario is covered there; if a gap, add it to `test_phase0.py`.

Run: `.venv/bin/python -m pytest -q` — the non-`test_cli` suite must be green; `test_cli` failures must not exceed the 27 baseline minus whatever you deleted.

- [ ] **Step 5: Lint + commit**

```bash
.venv/bin/ruff check .
git add installer/cli.py tests/test_cli.py
git commit -m "refactor: run_install asserts Docker is ready, doesn't install it

Phase 0 (./install / vulcan preflight --fix) owns deps + Docker now.
_ensure_docker_ready -> _assert_docker_ready (re-detect + clear error).
Removed the _ensure_system_deps call and the 'Docker ready' wizard phase.
Docker-install tests moved to tests/test_phase0.py.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 5: `./install` — run Phase 0, auto-escalate once

**Files:**
- Modify: `install`
- Test: `tests/test_install.bats`

**Interfaces:**
- Consumes: `vulcan preflight --fix` exit codes (Task 3): `0` = ready (or reboot-needed message already printed), `1` = not ready. The `needs_root` case prints `sudo ./install` on stderr/stdout **and** exits 1.
- Produces: `./install` calls `preflight --fix`; if it exits 1 **and** we are not already root, print the heads-up block and `exec sudo "$0" "$@"`; if it exits 1 **and** we are root, exit 1 (Phase 0 genuinely failed).

- [ ] **Step 1: Write the failing test**

Add to `tests/test_install.bats`:

```bash
@test "install runs preflight --fix and re-execs under sudo when it needs root" {

    # healthy venv so the bootstrap goes straight to preflight
    cat > "$INSTALL_DIR/.venv/bin/python" <<'EOF'
#!/usr/bin/env bash
if [ "$1" = "-c" ]; then exit 0; fi          # import check passes
# `-m installer preflight --fix` -> pretend it needs root
if [ "$2" = "installer" ] && [ "$3" = "preflight" ]; then
    echo "Phase 0 needs root"
    echo "  sudo ./install"
    exit 1
fi
# any later `-m installer ...` (the real app) -> succeed
exit 0
EOF
    chmod +x "$INSTALL_DIR/.venv/bin/python"

    cat > "$INSTALL_DIR/bin/python3" <<'EOF'
#!/usr/bin/env bash
if [ "$1" = "-c" ]; then printf '3.11\n'; fi
exit 0
EOF
    cat > "$INSTALL_DIR/bin/id" <<'EOF'
#!/usr/bin/env bash
[ "$1" = "-u" ] && { echo 1000; exit 0; }
exec /usr/bin/id "$@"
EOF
    cat > "$INSTALL_DIR/bin/sudo" <<'EOF'
#!/usr/bin/env bash
printf 'sudo %s\n' "$*" >> "$RUNLOG"
exit 0
EOF
    chmod +x "$INSTALL_DIR/bin/python3" "$INSTALL_DIR/bin/id" "$INSTALL_DIR/bin/sudo"

    RUNLOG="$INSTALL_DIR/run.log"
    run env PATH="$INSTALL_DIR/bin:$PATH" RUNLOG="$RUNLOG" bash "$INSTALL_DIR/install" --plain version

    [ "$status" -eq 0 ]
    [[ "$output" == *"Vulcan needs root once"* ]]
    [[ "$(cat "$RUNLOG")" == *"sudo "*"install"*"--plain version"* ]]
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bats tests/test_install.bats -f "re-execs under sudo"`
Expected: FAIL — `install` never runs `preflight` and never re-execs.

- [ ] **Step 3: Implement in `install`**

In `install`, after the venv-setup block and before the final `exec`, insert:

```bash
# --- Phase 0: system packages + Docker (one privileged pass) ---------
if ! "${RUN_AS[@]}" "$VENV_DIR/bin/python" -m installer preflight --fix; then
    if [ "$(id -u)" -ne 0 ]; then
        echo
        echo "Vulcan needs root once to install:"
        echo "  - system packages (git, whiptail, mdadm, ...)"
        echo "  - Docker Engine + docker compose"
        echo "Escalating now (Ctrl-C to abort)..."
        echo
        exec sudo "$0" "$@"
    fi
    echo "Phase 0 failed - see the errors above." >&2
    exit 1
fi
```

Note: `preflight --fix` prints its own reboot message and exits `0` in the
rpm-ostree case, so that path falls through to the final `exec` (which then
runs the menu, which will show a clean "Docker not ready, reboot" via
`_assert_docker_ready`). That is acceptable — the user has been told to
reboot.

- [ ] **Step 4: Run tests to verify they pass**

Run: `bats tests/test_install.bats`
Expected: PASS (all — the existing 3 + the new one). The existing "runs as $SUDO_USER" and "broken venv" tests must still pass; if the new `preflight` call breaks them, stub `-m installer preflight` to `exit 0` in those tests' fake `python`.

- [ ] **Step 5: Commit**

```bash
git add install tests/test_install.bats
git commit -m "feat: ./install runs Phase 0 (vulcan preflight --fix), auto-escalates once

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 6: Build ≠ Start — split `_generate_and_maybe_start`

**Files:**
- Modify: `installer/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `_assert_docker_ready` (Task 4).
- Produces:
  - `_build(config, non_interactive, yes, panel, on_phase=None) -> dict` — the review print + confirm + `write_stack` + warnings. Returns the `write_stack` result dict. **Never touches Docker.**
  - `_start(config, build_result, group_just_added, panel, on_phase=None) -> None` — `_assert_docker_ready` first, then port/network resolution + `compose up -d` + `verify_stack_running` + summary. Raises `typer.Exit` on failure.
  - `run_install` calls `_build`, then (Task 8) `configure`, then `_start` only when start was requested.
  - New command: `vulcan build` (generate, never start).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_cli.py`:

```python
def test_build_succeeds_with_docker_down(tmp_path):
    media_path = str(tmp_path / "media")
    down = make_system_info(docker_running=False, docker_compose_v2=False)

    with patch("installer.cli.detect_system", return_value=down), patch(
        "installer.cli.detect_disk",
        return_value={"disk_free_gb": 900.0, "disk_path_checked": media_path}
    ), patch("installer.cli.write_stack", return_value=READY_WRITE_RESULT) as mock_write, patch(
        "installer.cli.run_docker_command"
    ) as mock_docker:

        result = runner.invoke(app, [
            "--tier", "light", "--media-path", media_path,
            "--non-interactive", "--yes", "--no-vpn", "--no-start"
        ])

    assert result.exit_code == 0, result.output
    mock_write.assert_called_once()
    mock_docker.assert_not_called()


def test_build_command_generates_without_starting(tmp_path):
    media_path = str(tmp_path / "media")

    with patch("installer.cli.detect_system", return_value=make_system_info()), patch(
        "installer.cli.detect_disk",
        return_value={"disk_free_gb": 900.0, "disk_path_checked": media_path}
    ), patch("installer.cli.write_stack", return_value=READY_WRITE_RESULT) as mock_write, patch(
        "installer.cli.run_docker_command"
    ) as mock_docker:

        result = runner.invoke(app, [
            "build", "--tier", "medium", "--media-path", media_path,
            "--non-interactive", "--yes", "--no-vpn"
        ])

    assert result.exit_code == 0, result.output
    mock_write.assert_called_once()
    mock_docker.assert_not_called()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_cli.py -k "build_succeeds_with_docker_down or build_command_generates" -v`
Expected: FAIL — `test_build_succeeds_with_docker_down` currently exits 1 (`_assert_docker_ready` runs before generation); `build` command doesn't exist.

- [ ] **Step 3: Split the function**

In `installer/cli.py`, rename `_generate_and_maybe_start` to `_build` and cut it at the `if do_start:` line. `_build` keeps everything up to and including the `write_stack` + warnings loop, and **returns `result`**. Change its signature to drop `start` and `group_just_added`:

```python
def _build(
    config: GenerationConfig,
    non_interactive: bool,
    yes: bool,
    on_phase=None,
    panel: RunPanel | _NoOpPanel | None = None,
) -> dict:
    # ... existing review prints, confirm, write_stack, warnings loop ...
    return result
```

Move the `if do_start:` block and everything after into a new `_start`:

```python
def _start(
    config: GenerationConfig,
    build_result: dict,
    group_just_added: bool,
    on_phase=None,
    panel: RunPanel | _NoOpPanel | None = None,
) -> None:

    panel = panel if panel is not None else _NoOpPanel(console)

    _assert_docker_ready(detect_system())

    result = _resolve_port_conflicts(config, build_result)

    net_check = check_network_conflicts(result["compose_path"])

    if not net_check["ok"]:
        console.print("[red]Network configuration errors (Docker would reject these):[/red]")
        console.print(format_network_conflicts(net_check))
        raise typer.Exit(code=1)

    proc = run_docker_command(
        ["docker", "compose", "-f", result["compose_path"],
         "--env-file", result["env_path"], "up", "-d"],
        use_group_workaround=group_just_added,
    )

    # ... rest of the existing post-`up -d` verification + summary block ...
```

In `run_install`, replace the `_generate_and_maybe_start(...)` call with:

```python
        build_result = _build(
            config, non_interactive, yes,
            on_phase=panel.advance, panel=panel,
        )
        panel.advance()

        # Task 8 inserts the configure step here.

        if start is not False:
            _start(config, build_result, group_just_added,
                   on_phase=panel.advance, panel=panel)

        panel.finish(True)
```

Move the "start now?" prompt (currently `if start is None: do_start = ... typer.confirm("Start the stack now?"...)`) out of `_build` and into `run_install`, just before the `if start is not False:` check:

```python
        if start is None and not non_interactive:
            start = typer.confirm("Start the stack now?", default=True)
```

Add the `build` command:

```python
@app.command()
def build(
    tier: str | None = typer.Option(None),
    media_path: str | None = typer.Option(None),
    non_interactive: bool = typer.Option(False),
    yes: bool = typer.Option(False),
    # ... mirror the run_install service flags you need, or accept **only**
    #     --tier/--media-path/--non-interactive/--yes and reuse run_install
    #     internals ...
):
    """Generate stack/docker-compose.yml + .env from your choices. Never
    starts anything - run `vulcan start` when Docker is ready."""

    run_install(
        tier=tier, media_path=media_path,
        non_interactive=non_interactive, yes=yes,
        start=False,
        # ... pass None/defaults for the rest, matching run_install's signature ...
    )
```

> Simplest correct approach: `build` is a thin wrapper that calls
> `run_install(..., start=False)` with the same option surface. If mirroring
> every flag is noisy, have `build` accept the core four and let the menu
> keep using `vulcan --non-interactive --yes --no-start` (already works).
> Pick whichever keeps the diff smaller; document the choice in the commit.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_cli.py -k "build or start or full_non_interactive or non_interactive_with_start" -v`
Expected: the two new tests PASS. `test_non_interactive_with_start_calls_run_docker_command` and `test_start_*` must still pass (they exercise `_start`). Update any test that patched `_generate_and_maybe_start` to patch `_build`/`_start`.

Run: `.venv/bin/python -m pytest -q` — non-`test_cli` green; `test_cli` failures ≤ baseline.

- [ ] **Step 5: Lint + commit**

```bash
.venv/bin/ruff check .
git add installer/cli.py tests/test_cli.py
git commit -m "refactor: split _generate_and_maybe_start into _build (always) + _start (needs Docker)

Generation now succeeds with Docker down (warns); only start asserts it.
New 'vulcan build' command.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 7: `installer/configure.py` — `configure_pending()`

**Files:**
- Create: `installer/configure.py`
- Create: `tests/test_configure.py`

**Interfaces:**
- Consumes: `installer.generate` for the `.env` path (`STACK_DIR / ".env"`), `installer.generate.enabled_service_keys(config)` to know what's enabled.
- Produces:
  ```python
  def pending_credentials(config) -> list[dict]
  # [{"service": "gluetun", "keys": ["VPN_SERVICE_PROVIDER", ...], "hint": "..."}]
  # - only services that are enabled AND whose keys are not all already set in stack/.env

  def configure_pending(config, non_interactive: bool, answers: dict | None = None) -> dict
  # answers: {"VPN_SERVICE_PROVIDER": "...", ...} for non-interactive / tests
  # returns {"written": ["VPN_SERVICE_PROVIDER", ...], "still_blank": ["TUNNEL_TOKEN", ...]}
  # writes the given keys into stack/.env (append or replace-in-place)
  ```

- [ ] **Step 1: Write the failing tests**

Create `tests/test_configure.py`:

```python
from installer.configure import pending_credentials, configure_pending
from installer.tiers import TIERS
from installer.generate import GenerationConfig


def _cfg(**kw):
    base = dict(tier=TIERS["heavy"], media_path="/tmp/m", puid=1000, pgid=1000,
               timezone="UTC", enabled_optional=set())
    base.update(kw)
    return GenerationConfig(**base)


def test_pending_lists_gluetun_when_vpn_enabled_and_env_empty(tmp_path, monkeypatch):
    monkeypatch.setattr("installer.configure.STACK_DIR", tmp_path)
    (tmp_path / ".env").write_text("PUID=1000\n")

    pending = pending_credentials(_cfg(enabled_optional={"gluetun"}))

    assert any(p["service"] == "gluetun" for p in pending)


def test_pending_skips_gluetun_when_creds_already_in_env(tmp_path, monkeypatch):
    monkeypatch.setattr("installer.configure.STACK_DIR", tmp_path)
    (tmp_path / ".env").write_text(
        "VPN_SERVICE_PROVIDER=mullvad\nVPN_TYPE=wireguard\nWIREGUARD_PRIVATE_KEY=abc\n"
    )

    pending = pending_credentials(_cfg(enabled_optional={"gluetun"}))

    assert not any(p["service"] == "gluetun" for p in pending)


def test_configure_pending_writes_answers_to_env(tmp_path, monkeypatch):
    monkeypatch.setattr("installer.configure.STACK_DIR", tmp_path)
    (tmp_path / ".env").write_text("PUID=1000\nVPN_SERVICE_PROVIDER=changeme\n")

    result = configure_pending(
        _cfg(enabled_optional={"gluetun"}),
        non_interactive=True,
        answers={"VPN_SERVICE_PROVIDER": "protonvpn", "VPN_TYPE": "wireguard",
                 "WIREGUARD_PRIVATE_KEY": "k", "WIREGUARD_ADDRESSES": "10.0.0.2/32"},
    )

    env = (tmp_path / ".env").read_text()
    assert "VPN_SERVICE_PROVIDER=protonvpn" in env
    assert "VPN_SERVICE_PROVIDER=changeme" not in env
    assert "VPN_TYPE=wireguard" in env
    assert "VPN_SERVICE_PROVIDER" in result["written"]


def test_configure_pending_reports_still_blank(tmp_path, monkeypatch):
    monkeypatch.setattr("installer.configure.STACK_DIR", tmp_path)
    (tmp_path / ".env").write_text("PUID=1000\n")

    result = configure_pending(
        _cfg(custom_services={"traefik", "cloudflared"}, enabled_optional=set()),
        non_interactive=True,
        answers={},
    )

    assert "CLOUDFLARE_TUNNEL_TOKEN" in result["still_blank"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_configure.py -v`
Expected: FAIL — `ModuleNotFoundError: installer.configure`.

- [ ] **Step 3: Create `installer/configure.py`**

```python
"""
Phase 6 - Configure. After a stack is built (stack/docker-compose.yml +
.env written) and before it's started, walk the user through the
credentials the enabled services need but don't have yet: VPN provider
+ key (gluetun), base domain (traefik), tunnel token (cloudflared),
auth key (tailscale), admin passwords (pihole/adguardhome).

Writes stack/.env and stops. No validation - Phase 7 (start) surfaces a
bad VPN key or an unresolved domain clearly enough, and a DNS/uptime
check here would just be wrong offline.

Both front ends call configure_pending() at the same point: cli.py's
run_install between _build and _start, and menu.sh's first-run wizard as
step 6 (it stays a day-2 menu item too).
"""

import typer

from installer.generate import STACK_DIR, enabled_service_keys


console = None  # set by cli.py when it imports; falls back to typer.echo


# service -> (env keys it needs, one-line hint shown before prompting)
_CREDENTIALS: dict[str, tuple[list[str], str]] = {
    "gluetun": (
        ["VPN_SERVICE_PROVIDER", "VPN_TYPE", "WIREGUARD_PRIVATE_KEY", "WIREGUARD_ADDRESSES"],
        "Your VPN provider's WireGuard details. Providers: "
        "https://github.com/qdm12/gluetun-wiki/tree/main/setup/providers",
    ),
    "traefik": (["DOMAIN"], "Base domain with DNS A records pointing at this host (blank to skip)."),
    "cloudflared": (["CLOUDFLARE_TUNNEL_TOKEN"], "Tunnel token from Cloudflare Zero Trust (starts 'ey...')."),
    "tailscale": (["TAILSCALE_AUTHKEY"], "Reusable auth key from the Tailscale admin console."),
    "pihole": (["PIHOLE_PASSWORD"], "Admin password for the Pi-hole web UI."),
    "adguardhome": (["ADGUARDHOME_PASSWORD"], "Admin password for the AdGuard Home web UI."),
}

# treated as "not really set" - the generate.py placeholder values
_PLACEHOLDERS = {"", "changeme", "changeme-please"}


def _read_env() -> dict[str, str]:
    path = STACK_DIR / ".env"
    if not path.exists():
        return {}
    values = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            values[k.strip()] = v.strip()
    return values


def _write_env(updates: dict[str, str]) -> None:
    path = STACK_DIR / ".env"
    lines = path.read_text().splitlines() if path.exists() else []
    seen = set()
    out = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in updates:
                out.append(f"{key}={updates[key]}")
                seen.add(key)
                continue
        out.append(line)
    for key, value in updates.items():
        if key not in seen:
            out.append(f"{key}={value}")
    path.write_text("\n".join(out) + "\n")


def _is_set(env: dict[str, str], key: str) -> bool:
    return env.get(key, "") not in _PLACEHOLDERS


def pending_credentials(config) -> list[dict]:
    enabled = enabled_service_keys(config)
    env = _read_env()
    pending = []
    for service, (keys, hint) in _CREDENTIALS.items():
        if service not in enabled:
            continue
        missing = [k for k in keys if not _is_set(env, k)]
        if missing:
            pending.append({"service": service, "keys": keys, "missing": missing, "hint": hint})
    return pending


def configure_pending(config, non_interactive: bool, answers: dict | None = None) -> dict:
    answers = answers or {}
    pending = pending_credentials(config)

    updates: dict[str, str] = {}
    still_blank: list[str] = []

    for item in pending:
        for key in item["missing"]:
            if key in answers and answers[key] != "":
                updates[key] = answers[key]
            elif not non_interactive:
                typer.echo(f"\n{item['service']}: {item['hint']}")
                value = typer.prompt(key, default="", show_default=False)
                if value:
                    updates[key] = value
                else:
                    still_blank.append(key)
            else:
                still_blank.append(key)

    if updates:
        _write_env(updates)

    return {"written": sorted(updates), "still_blank": still_blank}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_configure.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Lint + commit**

```bash
.venv/bin/ruff check .
git add installer/configure.py tests/test_configure.py
git commit -m "feat: installer/configure.py - Phase 6 credential walkthrough

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 8: Wire `configure` into `run_install` + `vulcan configure` command; drop the inline VPN prompts

**Files:**
- Modify: `installer/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `configure_pending` (Task 7), `_build`/`_start` (Task 6).
- Produces: `run_install` calls `configure_pending(config, non_interactive, answers=...)` between `_build` and `_start`. The `answers` dict is assembled from the existing env-var reads + flags (`VPN_SERVICE_PROVIDER` etc.). `_gather_generation_config` no longer prompts for VPN credentials. New `vulcan configure` command operates on the already-built stack.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_cli.py`:

```python
def test_run_install_calls_configure_between_build_and_start(tmp_path):
    media_path = str(tmp_path / "media")
    calls = []

    with patch("installer.cli.detect_system", return_value=make_system_info()), patch(
        "installer.cli.detect_disk",
        return_value={"disk_free_gb": 900.0, "disk_path_checked": media_path}
    ), patch("installer.cli._build", side_effect=lambda *a, **k: calls.append("build") or READY_WRITE_RESULT), \
        patch("installer.cli.configure_pending", side_effect=lambda *a, **k: calls.append("configure") or {"written": [], "still_blank": []}), \
        patch("installer.cli._start", side_effect=lambda *a, **k: calls.append("start")):

        result = runner.invoke(app, [
            "--tier", "medium", "--media-path", media_path,
            "--non-interactive", "--yes", "--no-vpn", "--start"
        ])

    assert result.exit_code == 0, result.output
    assert calls == ["build", "configure", "start"]


def test_gather_config_does_not_prompt_for_wireguard_key(tmp_path):
    """VPN credential prompts moved to Phase 6 - service selection must not
    ask for a key anymore."""
    media_path = str(tmp_path / "media")

    with patch("installer.cli.detect_system", return_value=make_system_info()), patch(
        "installer.cli.detect_disk",
        return_value={"disk_free_gb": 900.0, "disk_path_checked": media_path}
    ), patch("installer.cli._build", return_value=READY_WRITE_RESULT), patch(
        "installer.cli.configure_pending", return_value={"written": [], "still_blank": []}
    ), patch("installer.cli._start"):

        result = runner.invoke(app, [
            "--plain", "--media-path", media_path,
            "--puid", "1000", "--pgid", "1000", "--timezone", "UTC", "--no-start"
        ], input="\ny\n" + "\n" * 20)

    assert "WireGuard Private Key" not in result.output
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_cli.py -k "configure_between_build_and_start or does_not_prompt_for_wireguard" -v`
Expected: FAIL — no `configure_pending` import/call; the inline WireGuard prompt still fires.

- [ ] **Step 3: Implement**

In `installer/cli.py`:

```python
from installer.configure import configure_pending
```

In `run_install`, between `_build` and the `if start is not False:` block:

```python
        vpn_answers = {
            "VPN_SERVICE_PROVIDER": os.environ.get("VPN_SERVICE_PROVIDER", ""),
            "VPN_TYPE": os.environ.get("VPN_TYPE", ""),
            "WIREGUARD_PRIVATE_KEY": os.environ.get("WIREGUARD_PRIVATE_KEY", ""),
            "WIREGUARD_ADDRESSES": os.environ.get("WIREGUARD_ADDRESSES", ""),
            "OPENVPN_USER": os.environ.get("OPENVPN_USER", ""),
            "OPENVPN_PASSWORD": os.environ.get("OPENVPN_PASSWORD", ""),
            "DOMAIN": config.domain or "",
        }

        configure_pending(config, non_interactive, answers={k: v for k, v in vpn_answers.items() if v})
        panel.advance()
```

Add `"Configure services"` to the `phases` list in `run_install` (before `"Generate stack"` — actually after; place it so `panel.advance()` counts line up: `["Detect system", "Storage setup", "Configure stack", "Generate stack", "Configure services"]`).

In `_gather_generation_config`, **delete** the interactive VPN-credential block (the `if vpn is None and not non_interactive and (not vpn_service_provider or not vpn_type):` branch and its prompts). Keep the six `os.environ.get(...)` reads at the top (Task from PR #3) — `GenerationConfig` still carries them for `write_stack` to seed `.env` placeholders, and Phase 6 overwrites the placeholders.

Add the `configure` command:

```python
@app.command()
def configure():
    """Fill in credentials for services in the already-built stack
    (VPN, domain, tunnel token, ...). Run after `vulcan build`."""

    previous = load_previous_state(STACK_DIR)
    if previous is None:
        console.print("[red]No stack found. Run `vulcan build` first.[/red]")
        raise typer.Exit(code=1)

    config = _config_from_previous_state(previous)
    result = configure_pending(config, non_interactive=False)

    if result["written"]:
        console.print(f"[green]Wrote:[/green] {', '.join(result['written'])}")
    if result["still_blank"]:
        console.print(f"[yellow]Still blank:[/yellow] {', '.join(result['still_blank'])}")
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/test_cli.py -q`
Expected: the two new tests PASS. `test_non_interactive_medium_with_explicit_vpn_flag` and the PR#3 `test_non_interactive_vpn_off_generates_stack_without_crashing` must still pass. Some interactive tests shift by the removed prompts — that's expected; they get rewritten in Task 10.

Run: `.venv/bin/python -m pytest -q` — non-`test_cli` green.

- [ ] **Step 5: Lint + commit**

```bash
.venv/bin/ruff check .
git add installer/cli.py tests/test_cli.py
git commit -m "feat: Phase 6 configure runs between build and start; drop inline VPN prompts

New 'vulcan configure' command. run_install: build -> configure -> start.
_gather_generation_config no longer asks for a WireGuard key mid-service-pick.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 9: `menu.sh` — reorder the first-run wizard, fix the Review dialog

**Files:**
- Modify: `installer/menu.sh`
- Test: `tests/test_menu.bats`

**Interfaces:**
- Consumes: `vulcan build`, `vulcan configure`, `vulcan start` (Tasks 6, 8).
- Produces: `guided_setup` runs Welcome → (storage) → media/tier/services/PUID → Review → `vulcan build` → `vulcan configure` → (start?) → `vulcan start` → Setup Complete. No Docker msgbox. Review dialog lines bounded to width.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_menu.bats` (adapt to the file's existing `whiptail` mock style):

```bash
@test "guided_setup calls vulcan build then configure then start, no docker msgbox" {
    # whiptail mock answers every dialog with a benign default; record vulcan calls
    export VULCAN_CALLS="$BATS_TMPDIR/vcalls-$$"; : > "$VULCAN_CALLS"
    fake_vulcan() { printf '%s\n' "$*" >> "$VULCAN_CALLS"; }
    export -f fake_vulcan
    VULCAN_BIN=fake_vulcan

    whiptail() {
        case "$*" in
            *"--yesno"*"Docker"*) echo "DOCKER MSGBOX SHOWN" >&2; return 0 ;;
            *"--yesno"*) return 0 ;;
            *"--inputbox"*|*"--passwordbox"*) echo "" ;;
            *"--radiolist"*) echo "medium" ;;
            *"--checklist"*) echo "" ;;
            *"--menu"*) echo "done" ;;
        esac
        return 0
    }
    export -f whiptail

    source "$BATS_TEST_DIRNAME/../installer/menu.sh"
    run guided_setup

    grep -q "build" "$VULCAN_CALLS"
    grep -q "configure" "$VULCAN_CALLS"
    ! grep -q "DOCKER MSGBOX SHOWN" <<< "$output"
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bats tests/test_menu.bats -f "no docker msgbox"`
Expected: FAIL — the Docker msgbox block still runs; `configure` is never called from `guided_setup`.

- [ ] **Step 3: Edit `installer/menu.sh`**

In `guided_setup` (and `guided_setup_no_start` if kept):

1. **Delete** the Docker-readiness msgbox block:
   ```bash
   if [ "$DOCKER_INSTALLED" != "true" ] || [ "$DOCKER_RUNNING" != "true" ] || ...; then
       whiptail ... --msgbox "Docker isn't fully ready yet ..."
   fi
   ```
   (both copies — in `guided_setup` and `guided_setup_no_start`).

2. After the `confirm_and_run "Guided Setup" ... "$VULCAN_BIN" --non-interactive --yes --tier ... "$START_FLAG"` block, split it: build first, then configure, then start. Replace with:

   ```bash
   SKIP_RETURN_PROMPT=true confirm_and_run "Build Stack" \
       "Generate stack/docker-compose.yml + .env at $MEDIA_PATH (PUID=$PUID PGID=$PGID TZ=$TIMEZONE)." \
       "$VULCAN_BIN" build --non-interactive --yes \
           --tier "$TIER" --media-path "$MEDIA_PATH" \
           --puid "$PUID" --pgid "$PGID" --timezone "$TIMEZONE" \
           "${SERVICES_FLAG[@]}" "${TOGGLE_FLAGS[@]}" "${DOMAIN_FLAGS[@]}"
   local rc=$?
   [ "$rc" -ne 0 ] && return "$rc"

   # Phase 6: credentials
   if [ -n "$("$VULCAN_BIN" configure --help >/dev/null 2>&1; echo x)" ]; then :; fi
   "$VULCAN_BIN" configure || true

   if [ "$START_FLAG" = "--start" ]; then
       confirm_and_run "Start Stack" \
           "Start stack/docker-compose.yml, reassigning any port already in use." \
           "$VULCAN_BIN" start
   fi
   ```

   (Keep the existing "Setup Complete" screen block that follows.)

3. **Review dialog fix.** Where `$summary` is built for the "Review Settings" `whiptail --yesno`, bound each line and drop `--scrolltext` unless tall:

   ```bash
   local width=$(( DLG_COLS - 6 ))
   _rvline() { printf '%s\n' "$(printf '%-.*s' "$width" "$1")"; }

   local summary=""
   summary+="$(_rvline "Tier:        $TIER")"$'\n'
   summary+="$(_rvline "Media Path:  $MEDIA_PATH")"$'\n'
   summary+="$(_rvline "PUID/PGID:   $PUID / $PGID")"$'\n'
   summary+="$(_rvline "Timezone:    $TIMEZONE")"$'\n'
   summary+="$(_rvline "Services:    $services_summary")"$'\n'
   summary+="$(_rvline "Auto-start:  $([ "$START_FLAG" = "--start" ] && echo yes || echo no)")"

   if ! whiptail --backtitle "$BACKTITLE" --title "Review Settings" \
       --yesno "$summary" "$DLG_ROWS" "$DLG_COLS"; then
       return 0
   fi
   ```

   (No `--scrolltext`. If `$services_summary` is genuinely long, the
   `_rvline` truncation keeps the buttons reachable — the full list is in
   `vulcan install-summary` on the Setup Complete screen.)

4. Add `"configure"` to the `menu_configure` sub-menu so it stays a day-2 item:
   ```bash
   "credentials" "Configure Credentials → VPN, domain, tunnel token, passwords" \
   ```
   with `credentials) "$VULCAN_BIN" configure; read -rp "Press Enter..." _ ;;`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `bats tests/test_menu.bats`
Expected: the new test PASSES. Existing bats tests that assert the old single-call flow need updating to the build/configure/start split — update them, do not delete.

- [ ] **Step 5: Commit**

```bash
git add installer/menu.sh tests/test_menu.bats
git commit -m "feat: menu wizard is Detect->...->Build->Configure->Start; drop Docker msgbox; fix Review dialog width

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 10: Rewrite the 27 interactive `test_cli` tests

**Files:**
- Modify: `tests/test_cli.py`

**Interfaces:**
- Consumes: the post-restructure `_gather_generation_config`, `_build`, `configure_pending`, `_start`.
- Produces: a `respond_to_prompts(mapping)` helper + rewritten tests that assert on returned config / mocked calls, not on `input="\n..."` position.

- [ ] **Step 1: Write the helper + convert one test (RED via the helper being absent)**

Add to `tests/test_cli.py`:

```python
def respond_to_prompts(mapping: dict[str, str]):
    """Return a click input callback that answers each prompt by matching a
    substring of the prompt text against `mapping` keys. Unmatched prompts
    get an empty line (accept default)."""
    import click

    real_prompt = click.termui.visible_prompt_func

    def fake(text: str = "") -> str:
        for needle, answer in mapping.items():
            if needle.lower() in text.lower():
                return answer
        return ""

    return fake
```

Convert `test_sabnzbd_question_shown_and_accepted_at_light_tier` (representative):

```python
def test_sabnzbd_question_shown_and_accepted_at_light_tier(tmp_path, monkeypatch):
    media_path = str(tmp_path / "media")
    monkeypatch.setattr("click.termui.visible_prompt_func",
                        respond_to_prompts({"SABnzbd": "y", "tier": "light"}))

    with patch("installer.cli.detect_system", return_value=make_system_info()), patch(
        "installer.cli.detect_disk",
        return_value={"disk_free_gb": 900.0, "disk_path_checked": media_path}
    ), patch("installer.cli._build", return_value=READY_WRITE_RESULT) as mock_build, patch(
        "installer.cli.configure_pending", return_value={"written": [], "still_blank": []}
    ), patch("installer.cli._start"):

        result = runner.invoke(app, [
            "--plain", "--media-path", media_path,
            "--puid", "1000", "--pgid", "1000", "--timezone", "UTC", "--no-start"
        ])

    assert result.exit_code == 0, result.output
    config = mock_build.call_args[0][0]
    assert "sabnzbd" in config.enabled_optional
```

- [ ] **Step 2: Run to verify the pattern works**

Run: `.venv/bin/python -m pytest tests/test_cli.py::test_sabnzbd_question_shown_and_accepted_at_light_tier -v`
Expected: PASS.

- [ ] **Step 3: Convert the remaining tests**

Work through the failing list (`pytest -q -rf tests/test_cli.py | grep FAILED`). For each:
- If it asserts a **config outcome** → patch `_build`, read `mock_build.call_args[0][0]`, drop the `input=` string, use `respond_to_prompts`.
- If it asserts **`vulcan start` behaviour** (`test_start_*`, `test_run_docker_command_failure_reported_cleanly`) → keep it going through `_start`, but feed answers via `respond_to_prompts` and stop asserting on prompt-order-sensitive output.
- If it asserts **wording of a specific prompt** → match that exact string via `in result.output`, feed a benign answer to everything else.

Commit in batches of ~5 conversions with a running count in the message.

- [ ] **Step 4: Full green**

Run: `.venv/bin/python -m pytest -q`
Expected: **0 failed**. If a converted test reveals a real behaviour bug (not just rot), fix the code, note it in the commit.

- [ ] **Step 5: Lint + final commit**

```bash
.venv/bin/ruff check .
git add tests/test_cli.py
git commit -m "test: rewrite the 27 interactive CLI tests to match prompts by text, not position

Suite green (was 27 failing since the service-list expansions).

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 11: Docs

**Files:**
- Modify: `docs/getting-started/index.md`, `docs/walkthrough.md`, `README.md`

- [ ] **Step 1: `getting-started/index.md`**

Under **Requirements**, state that `./install` installs `git`, `python3-venv`, `whiptail`, `mdadm`, and Docker itself on Ubuntu/Debian/Fedora/Arch, and that it will prompt once for `sudo` to do so. Under the quick start, note the new flow: `./install` → Phase 0 → wizard (`Detect → Recommend → Shape → Confirm → Build → Configure → Start`).

- [ ] **Step 2: `walkthrough.md`**

Add a short "What `./install` does" section describing the phases. Add an **AdGuard Home** note: its `:53` collides with `systemd-resolved` on Ubuntu — disable the stub listener (`sudo mkdir -p /etc/systemd/resolved.conf.d && echo -e '[Resolve]\nDNSStubListener=no' | sudo tee /etc/systemd/resolved.conf.d/adguard.conf && sudo systemctl restart systemd-resolved`) before starting the stack.

- [ ] **Step 3: `README.md`**

Update the Quick Start block and the "Sudo required" paragraph to describe the single Phase-0 escalation and the Build→Configure→Start order.

- [ ] **Step 4: Commit**

```bash
git add docs/ README.md
git commit -m "docs: Phase 0, the Build->Configure->Start flow, AdGuard :53 note

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 12: Live verification on the real host

**Not a code task — a manual gate. Do not mark the branch done without it.**

- [ ] **Step 1:** On the test host (192.168.10.157), `sudo chown -R sentinel:sentinel ~/vulcan`, `git fetch`, check out this branch, `rm -rf .venv stack`.
- [ ] **Step 2:** Run `sudo ./install`. Expect: the heads-up block, one sudo prompt, Phase 0 installs nothing new (Docker already present) but confirms the group, then the wizard opens.
- [ ] **Step 3:** Walk the wizard: pick `medium`, a media path under `/mnt/media`, homepage on, VPN on. At **Confirm**, verify the Review dialog responds to Enter/Tab at the real keyboard.
- [ ] **Step 4:** After **Build**, verify `stack/docker-compose.yml` exists and no containers are running.
- [ ] **Step 5:** At **Configure**, enter dummy VPN creds; verify they land in `stack/.env` (replacing `changeme`).
- [ ] **Step 6:** Let it **Start**. Verify the post-start summary lists reachable URLs; `curl` two of them.
- [ ] **Step 7:** `vulcan uninstall --non-interactive --yes`; `sudo rm -rf /mnt/media/<test path>`.
- [ ] **Step 8:** Second run: `./install` with Docker already fine and the user already in the group — expect **no sudo prompt** (Phase 0 finds everything ready) straight into the menu.
- [ ] **Step 9:** Record the result in the PR description. Open the PR against `main`.

---

## Self-Review

**Spec coverage:**

| Spec section | Task |
|---|---|
| 1. `./install` owns Phase 0 | 5 |
| 2. `vulcan preflight [--fix]` | 2, 3 (+ `git` in 1) |
| 3. Build ≠ Start | 4, 6 |
| 4. Phase 6 Configure | 7, 8 |
| 5. `menu.sh` reorder + Review fix | 9 |
| 6. The 27 tests | 10 |
| Non-goal: no engine change | respected — no task touches `detect.py`/`generate.py`/`tiers.py`/`storage.py` logic |
| Error handling matrix | 3 (needs_root/reboot), 4 (assert), 6 (`_start` failures), 7 (still_blank) |
| Docs (AdGuard `:53`) | 11 |
| Live pass | 12 |

**Placeholder scan:** `build` command option surface in Task 6 Step 3 is left as "pick the smaller diff" — that is a real, bounded decision with both options spelled out, not a TODO. Everything else has concrete code.

**Type consistency:** `ensure_system_ready(fix, user)` → dict with keys `ready/needs_root/needs_reboot/missing/did/group_added` — used identically in Tasks 2, 3. `configure_pending(config, non_interactive, answers)` → `{written, still_blank}` — Tasks 7, 8, 10. `_build(config, non_interactive, yes, on_phase, panel) -> dict` and `_start(config, build_result, group_just_added, on_phase, panel)` — Tasks 6, 8, 10 consistent.
