"""
Docker install/setup toolbox. Unlike detect.py, these functions
mutate the base system - package install, systemd service, group
membership - so they're deliberately just a toolbox: no confirmation
prompts, no "do everything" orchestrator. The CLI/TUI layer (Phase 1
slice 5) shows current state and confirms before calling into each
piece individually, the same split Atlas keeps between pure manager
functions and the CLI layer that gates on typer.confirm().

The atomic/immutable-OS path (rpm-ostree layering, plus
add_user_to_docker_group()'s systemd-sysusers fallback) is ported from
the sibling Anvil project, which built and live-verified all of it
against a real Bazzite GPU host (msi-laptop) - including two real bugs
(usermod silently no-op'ing, a stale group cache on the immediate
re-check) found only by actually running it, not from reasoning about
the code. See Anvil's own CLAUDE.md/ROADMAP.md "v0.9" entries for the
full live-verification account this port is based on.
"""

import shlex
import shutil
import subprocess

from installer.shell import get_stream_sink, run_ok, run_privileged, run_streaming


def prune_docker_artifacts() -> dict:
    """
    Run `docker system prune -a` to clean up all stopped containers,
    unused networks, dangling images, and build cache. This is a
    preventive measure run at the start of guided install to ensure
    no leftover Docker artifacts from previous sessions cause port
    conflicts or other issues. Does NOT remove named volumes (use
    `--volumes` with caution - that would delete user data).

    -f/--force is required, not optional: without it, `docker system
    prune -a` prints its own "Are you sure? [y/N]" and blocks on
    stdin - real, reproduced live: the CLI's `uninstall --prune-docker`
    already confirms with the user before calling this (typer.confirm
    ("Continue?")), so Docker's own confirmation is always redundant.
    Worse under the Rich Live progress panel specifically: run_privileged()
    routes through run_streaming() there, which reads output line-by-line -
    Docker's prompt has no trailing newline, so it never reaches the log
    pane at all. The result looked like a silent, permanent stall at
    "Prune Docker artifacts" (confirmed: still blocked 10+ seconds in,
    zero images actually reclaimed) rather than an unseen, unanswerable
    question.

    Returns a result dict consistent with this project's pattern:
    {"success": bool, "error": str | None}.
    """

    result = run_privileged(["docker", "system", "prune", "-af"])

    if result["success"]:
        return {"success": True, "error": None}
    else:
        return {
            "success": False,
            "error": "docker system prune -a failed: %s"
            % result.get("error", "unknown error")
        }


DOCKER_SCRIPT_DISTROS = {"ubuntu", "debian", "raspbian", "fedora"}

_DOCKER_CE_REPO_URL = "https://download.docker.com/linux/fedora/docker-ce.repo"
_RPM_OSTREE_DOCKER_PACKAGES = [
    "docker-ce",
    "docker-ce-cli",
    "containerd.io",
    "docker-compose-plugin",
    "docker-buildx-plugin"
]


def install_plan_for(os_id: str | None, os_is_atomic: bool = False) -> dict | None:
    """
    What running install would actually do, for display before
    confirming - not decision logic that belongs inside install
    itself. None means no known auto-install method for this distro,
    so the caller falls back to printing manual install instructions.

    Checked before the plain-distro table, not after: an atomic host's
    os_id is still "fedora" (Bazzite/Kinoite both report ID=bazzite,
    ID_LIKE=fedora - but even a real "fedora" os_id here would be wrong
    to route through DOCKER_SCRIPT_DISTROS's plain `dnf install`-style
    get.docker.com script, since the base image is read-only). Every
    plan dict carries needs_reboot so callers have one flag to check
    regardless of which method fired - True only for this branch.
    """

    if os_is_atomic:

        return {
            "method": "rpm-ostree",
            "description": (
                "adding Docker's official repo, then "
                f"`rpm-ostree install {' '.join(_RPM_OSTREE_DOCKER_PACKAGES)}` "
                "(layered, not live - needs a reboot to take effect)"
            ),
            "needs_reboot": True
        }

    if os_id in DOCKER_SCRIPT_DISTROS:

        return {
            "method": "get.docker.com",
            "description": "curl -fsSL https://get.docker.com | sudo sh",
            "needs_reboot": False
        }

    if os_id == "arch":

        return {
            "method": "pacman",
            "description": "sudo pacman -Sy --noconfirm docker",
            "needs_reboot": False
        }

    return None


def install_docker(os_id: str | None, os_is_atomic: bool = False) -> dict:

    plan = install_plan_for(os_id, os_is_atomic)

    if plan is None:

        return {
            "success": False,
            "error": f"No known install method for '{os_id}'",
            "method": None,
            "needs_reboot": False
        }

    if plan["method"] == "rpm-ostree":

        repo_result = run_privileged(
            ["sh", "-c", f"curl -fsSL -o /etc/yum.repos.d/docker-ce.repo {_DOCKER_CE_REPO_URL}"]
        )

        if not repo_result["success"]:

            return {
                "success": False,
                "error": f"failed to add Docker's repo: {repo_result['error']}",
                "method": "rpm-ostree",
                "needs_reboot": False
            }

        result = run_privileged(["rpm-ostree", "install", *_RPM_OSTREE_DOCKER_PACKAGES])

    elif plan["method"] == "get.docker.com":

        result = run_privileged(
            ["sh", "-c", "curl -fsSL https://get.docker.com | sh"]
        )

    else:

        result = run_privileged(
            ["pacman", "-Sy", "--noconfirm", "docker"]
        )

    result["method"] = plan["method"]
    result["needs_reboot"] = plan["needs_reboot"] and result["success"]

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


def _user_in_docker_group(username: str) -> bool:
    """
    A real functional check (id -nG), never trusted from a tool's own
    claimed exit code alone - the exact reason this function exists,
    see add_user_to_docker_group()'s docstring.
    """

    result = subprocess.run(["id", "-nG", username], capture_output=True, text=True)

    return result.returncode == 0 and "docker" in result.stdout.split()


def _docker_group_gid() -> str | None:

    result = subprocess.run(["getent", "group", "docker"], capture_output=True, text=True)

    if result.returncode != 0 or not result.stdout.strip():
        return None

    fields = result.stdout.strip().split(":")

    return fields[2] if len(fields) >= 3 else None


def add_user_to_docker_group(username: str) -> dict:
    """
    A real, confirmed-live bug in the obvious approach, not a
    hypothetical (found and fixed in the sibling Anvil project, ported
    here unchanged): on a host where the docker group was created by
    systemd-sysusers for a layered package (the atomic-OS install path
    above, e.g. Bazzite) rather than a plain package manager, its
    canonical record lives only in /usr/lib/group - part of the
    read-only base image, resolved via nsswitch.conf's "altfiles"
    source, never present in /etc/group at all. Confirmed directly
    against a real Bazzite host: `usermod -aG docker <user>` reported
    real success (exit 0) and silently wrote nothing - `getent group
    docker` and `id <user>` both showed no membership change
    afterward. `gpasswd -a` fails the same way, more honestly ("group
    'docker' does not exist in /etc/group") - both tools only ever
    look at the literal file, not the merged NSS view.

    The real, verified fix: a *local* /etc/group entry with the same
    name and gid merges cleanly with the vendor-owned altfiles entry
    (nsswitch.conf's own `group: files [SUCCESS=merge] altfiles ...`),
    after which gpasswd can manage membership on that local entry
    normally - confirmed live end to end (`id` showed real docker
    membership afterward, and a real `sg docker -c "docker info"`
    succeeded where it had failed before).

    Tries the plain, normal path first (works on every non-atomic
    host, unchanged from this project's own original behavior) and
    only falls back to the merge-entry trick if a real check shows the
    plain path didn't actually work - not gated behind os_is_atomic,
    since the underlying cause (a group usermod/gpasswd can't see via
    plain file enumeration) is what matters, not the OS family name.
    """

    plain_result = run_privileged(["usermod", "-aG", "docker", username])

    if plain_result["success"] and _user_in_docker_group(username):
        return plain_result

    gid = _docker_group_gid()

    if gid is None:

        return plain_result if not plain_result["success"] else {
            "success": False,
            "error": "usermod reported success but the docker group still has no real "
                     "members, and `getent group docker` found no group to fall back on"
        }

    ensure_entry_result = run_privileged(
        ["sh", "-c", f'grep -q "^docker:" /etc/group || echo "docker:x:{gid}:" >> /etc/group']
    )

    if not ensure_entry_result["success"]:
        return ensure_entry_result

    gpasswd_result = run_privileged(["gpasswd", "-a", username, "docker"])

    if gpasswd_result["success"] and _user_in_docker_group(username):
        return gpasswd_result

    return gpasswd_result if not gpasswd_result["success"] else {
        "success": False,
        "error": "user still isn't a real member of the docker group after the "
                 "local-entry fallback"
    }


def check_docker_ready(use_group_workaround: bool = False) -> dict:
    """
    docker_running/docker_compose_v2, optionally re-read through the
    same sg-based group-refresh workaround run_docker_command() uses.

    A real bug, found live (sibling Anvil project) against a real
    Bazzite host, not a hypothetical: a plain run_ok(["docker",
    "info"]) right after add_user_to_docker_group() in the same
    process still fails with a genuine "permission denied while trying
    to connect to the docker API" - usermod -aG updates /etc/group
    immediately, but this process's own supplementary group list was
    already fixed at its parent shell's login time and doesn't re-read
    it. `sg docker -c "..."` re-reads group membership fresh from the
    system (no relogin needed) and is what this project's own
    run_docker_command() already relies on for the same reason - this
    just applies the identical fix one step earlier, to the readiness
    re-check itself, not only the final `docker compose up`.
    """

    if use_group_workaround and shutil.which("sg"):

        running = subprocess.run(
            ["sg", "docker", "-c", "docker info"], capture_output=True
        ).returncode == 0

        compose_v2 = subprocess.run(
            ["sg", "docker", "-c", "docker compose version"], capture_output=True
        ).returncode == 0

    else:

        running = run_ok(["docker", "info"])
        compose_v2 = run_ok(["docker", "compose", "version"])

    return {"docker_running": running, "docker_compose_v2": compose_v2}


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
            command = ["sg", "docker", "-c", shlex.join(args)]

        else:
            command = ["sudo", *args]

    else:
        command = args

    sink = get_stream_sink()

    if sink is not None:

        returncode = run_streaming(command, sink)

        # Callers only ever read .returncode, so a synthetic
        # CompletedProcess carries everything they need from the
        # streaming path (which has no captured stdout/stderr anyway).
        return subprocess.CompletedProcess(command, returncode)

    return subprocess.run(command)
