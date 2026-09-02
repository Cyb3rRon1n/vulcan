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
from installer.detect import detect_docker, detect_os
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

    # --- system packages ---------------------------------------------------
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

    # Unknown distro family: deps_plan["packages"] is empty (nothing to
    # install) but missing tools land in missing_after even in the dry
    # run. Surface them so the run stops here instead of dying later on
    # `whiptail: command not found`.
    report["missing"].extend(deps_plan["missing_after"])

    # --- Docker ----------------------------------------------------------
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

    return detect_os().get("os_id")


def _os_args() -> tuple:

    info = detect_os()

    return info.get("os_id"), info.get("os_is_atomic", False)


def install_plan_for_os():

    return install_plan_for(*_os_args())


def _finalize(report: dict, state: dict | None = None) -> dict:

    if state is not None:
        report["ready"] = not report["missing"] and _docker_fully_ready(state)

    return report
