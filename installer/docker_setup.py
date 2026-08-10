"""
Docker install/setup toolbox. Unlike detect.py, these functions
mutate the base system - package install, systemd service, group
membership - so they're deliberately just a toolbox: no confirmation
prompts, no "do everything" orchestrator. The CLI/TUI layer (Phase 1
slice 5) shows current state and confirms before calling into each
piece individually, the same split Atlas keeps between pure manager
functions and the CLI layer that gates on typer.confirm().
"""

import shlex
import shutil
import subprocess

from installer.shell import run_ok, run_privileged

DOCKER_SCRIPT_DISTROS = {"ubuntu", "debian", "raspbian", "fedora"}


def install_plan_for(os_id: str | None) -> dict | None:
    """
    What running install would actually do, for display before
    confirming - not decision logic that belongs inside install
    itself. None means no known auto-install method for this distro,
    so the caller falls back to printing manual install instructions.
    """

    if os_id in DOCKER_SCRIPT_DISTROS:

        return {
            "method": "get.docker.com",
            "description": "curl -fsSL https://get.docker.com | sudo sh"
        }

    if os_id == "arch":

        return {
            "method": "pacman",
            "description": "sudo pacman -Sy --noconfirm docker"
        }

    return None


def install_docker(os_id: str) -> dict:

    plan = install_plan_for(os_id)

    if plan is None:

        return {
            "success": False,
            "error": f"No known install method for '{os_id}'",
            "method": None
        }

    if plan["method"] == "get.docker.com":

        result = run_privileged(
            ["sh", "-c", "curl -fsSL https://get.docker.com | sh"]
        )

    else:

        result = run_privileged(
            ["pacman", "-Sy", "--noconfirm", "docker"]
        )

    result["method"] = plan["method"]

    return result


def ensure_compose_v2(os_id: str) -> dict:
    """
    Verifies `docker compose version` actually works post-install.
    get.docker.com bundles the compose plugin, so this is expected to
    already pass for those four distros - but Arch's official docker
    package hasn't consistently bundled it, so this is a real check
    with a real fallback, not defensive paranoia for its own sake.
    """

    if run_ok(["docker", "compose", "version"]):

        return {
            "success": True,
            "error": None
        }

    if os_id == "arch":

        fallback = run_privileged(
            ["pacman", "-S", "--noconfirm", "docker-compose"]
        )

        if fallback["success"] and run_ok(["docker", "compose", "version"]):

            return {
                "success": True,
                "error": None
            }

    return {
        "success": False,
        "error": "docker compose v2 not available after install"
    }


def add_user_to_docker_group(username: str) -> dict:

    return run_privileged(["usermod", "-aG", "docker", username])


def start_docker_service() -> dict:

    return run_privileged(["systemctl", "enable", "--now", "docker"])


def run_docker_command(args: list[str], use_group_workaround: bool = False):
    """
    Runs a normal (non-privileged) docker/docker compose command -
    what the rest of Vulcan calls once Docker is actually ready.
    use_group_workaround=True (only needed right after this same run
    just added the docker group) routes through `sg docker -c "..."`,
    which reads group membership fresh from the system rather than
    the calling process's stale cached group list - no sudo, no
    relogin needed. Falls back to sudo if sg itself isn't present.
    """

    if use_group_workaround:

        if shutil.which("sg"):
            return subprocess.run(["sg", "docker", "-c", shlex.join(args)])

        return subprocess.run(["sudo", *args])

    return subprocess.run(args)
