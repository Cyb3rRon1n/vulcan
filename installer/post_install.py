"""
Post-install operations on an already-generated stack: pulling images
without starting anything (pull_stack), pulling fresh images and
recreating containers (update_stack, which just calls pull_stack for
its own pull step), archiving config for safekeeping (backup_stack -
which snapshots any live SQLite database it finds via sqlite3's own
online-backup API rather than archiving a possibly-mid-write file
directly), reversing that archive back onto disk (restore_stack),
bundling a stack's already-pulled images into a transferable tarball
for a machine that never touches the network (export_images/
import_images), and tearing a generated stack down entirely
(uninstall_stack - stops containers (falling back to a project-label
lookup via stack_containers_exist() if stack/ is already gone),
deletes stack/, never touches the media library). All of these reuse
the same real Docker/file
primitives generation already does - run_docker_command() for the
subprocess calls, the same STACK_DIR every other command reads from -
no new machinery, just more things to do with a stack that already
exists.
"""

import json
import shutil
import sqlite3
import subprocess
import tarfile
import tempfile
from datetime import datetime
from datetime import timezone as dt_timezone
from pathlib import Path

from installer.docker_setup import run_docker_command
from installer.generate import STACK_DIR


def _parse_compose_ps_json(stdout: str) -> list[dict]:
    """
    docker compose ps --format json's real shape isn't fully pinned
    across Compose versions (some emit a single JSON array, others -
    matching every other docker CLI --format json command - emit one
    object per line/NDJSON); this project has no live Docker in its own
    dev environment to confirm either way, so both are handled rather
    than guessed at from a single assumption.
    """

    stdout = stdout.strip()

    if not stdout:
        return []

    try:
        parsed = json.loads(stdout)
        if isinstance(parsed, list):
            return parsed
    except json.JSONDecodeError:
        pass

    return [json.loads(line) for line in stdout.splitlines() if line.strip()]


def verify_stack_running(compose_path: str) -> dict:
    """
    Real post-start verification, not just trusting `docker compose up
    -d`'s own exit code - up -d only waits for the initial container
    start, not for the process inside to actually stay up, so a
    container can be reported as started and then immediately
    crash-loop without up -d itself ever reporting a failure. Mirrors
    the same "verify what actually happened, don't just trust the
    command's exit code" principle Security Onion's own so-verify
    applies before declaring its install complete.
    """

    result = subprocess.run(
        ["docker", "compose", "-f", str(compose_path), "ps", "--format", "json"],
        capture_output=True,
        text=True
    )

    if result.returncode != 0:
        return {
            "all_running": False,
            "error": result.stderr.strip() or "docker compose ps failed",
            "not_running": []
        }

    not_running = [
        {
            "service": container.get("Service", "?"),
            "state": container.get("State", "?"),
            "status": container.get("Status", "")
        }
        for container in _parse_compose_ps_json(result.stdout)
        if container.get("State") != "running"
    ]

    return {"all_running": not not_running, "error": None, "not_running": not_running}


def pull_stack(compose_path: str, env_path: str) -> dict:

    pull = run_docker_command(
        ["docker", "compose", "-f", compose_path, "--env-file", env_path, "pull"]
    )

    if pull.returncode != 0:
        return {"success": False, "error": "Failed to pull images - check `docker compose logs`."}

    return {"success": True, "error": None}


def update_stack(compose_path: str, env_path: str, on_phase=None) -> dict:
    """
    Pull the latest images, then recreate containers - as two distinct
    steps so a pull failure reports distinctly from a recreate failure.
    on_phase, when given, is called with a phase label between the two
    steps (the CLI's progress panel advances its bar on real step
    completion; engine behavior is identical with or without it).
    """

    if on_phase is not None:
        on_phase("Pull images")

    pull_result = pull_stack(compose_path, env_path)

    if not pull_result["success"]:
        return pull_result

    if on_phase is not None:
        on_phase("Recreate containers")

    up = run_docker_command(
        ["docker", "compose", "-f", compose_path, "--env-file", env_path, "up", "-d"]
    )

    if up.returncode != 0:
        return {"success": False, "error": "Failed to recreate containers - check `docker compose logs`."}

    return {"success": True, "error": None}


def export_images(
    compose_path: str,
    env_path: str,
    output_path: Path | None = None,
    export_dir: Path = Path("exports")
) -> dict:

    if not Path(compose_path).exists():
        return {"success": False, "error": "No stack found to export.", "export_path": None}

    # docker compose config --images needs its own captured subprocess call -
    # run_docker_command() deliberately never captures output, since every
    # other call site (pull/up/down) wants its real progress on the terminal.
    try:

        list_result = subprocess.run(
            ["docker", "compose", "-f", compose_path, "--env-file", env_path, "config", "--images"],
            capture_output=True,
            text=True
        )

    except OSError as error:
        return {"success": False, "error": str(error), "export_path": None}

    if list_result.returncode != 0:
        return {"success": False, "error": "Failed to resolve the stack's image list.", "export_path": None}

    images = [line.strip() for line in list_result.stdout.splitlines() if line.strip()]

    if not images:
        return {"success": False, "error": "No images found for this stack.", "export_path": None}

    if output_path is None:

        export_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(dt_timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        output_path = export_dir / f"vulcan-images-{timestamp}.tar"

    else:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    save = run_docker_command(["docker", "save", "-o", str(output_path), *images])

    if save.returncode != 0:
        return {"success": False, "error": "Failed to save images to a tarball.", "export_path": None}

    return {"success": True, "error": None, "export_path": str(output_path)}


def latest_export(export_dir: Path = Path("exports")) -> Path | None:

    if not export_dir.is_dir():
        return None

    archives = sorted(export_dir.glob("vulcan-images-*.tar"))

    return archives[-1] if archives else None


def import_images(tar_path: str) -> dict:

    tar_path = Path(tar_path)

    if not tar_path.exists():
        return {"success": False, "error": f"Image archive not found: {tar_path}"}

    load = run_docker_command(["docker", "load", "-i", str(tar_path)])

    if load.returncode != 0:
        return {"success": False, "error": "Failed to load images from the archive."}

    return {"success": True, "error": None}


def _is_sqlite_file(path: Path) -> bool:

    try:
        with open(path, "rb") as f:
            return f.read(16) == b"SQLite format 3\x00"
    except OSError:
        return False


def _snapshot_sqlite_database(live_path: Path, staged_path: Path) -> bool:
    """
    Writes a consistent point-in-time copy of a live SQLite database
    to staged_path via sqlite3's own online-backup API - safe to run
    against a database another process (e.g. Radarr) is actively
    writing to, confirmed against a real concurrent-write scenario
    before this was built. Opens the live file read-only so this
    process never takes a write lock or creates a stray -wal/-shm file
    of its own. Returns False (never raises) on any sqlite3.Error, so
    the caller can fall back to a plain copy rather than losing data.
    """

    try:

        src = sqlite3.connect(f"file:{live_path}?mode=ro", uri=True)
        dst = sqlite3.connect(staged_path)

        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()

        return True

    except sqlite3.Error:
        return False


def backup_stack(stack_dir: Path = STACK_DIR, backup_dir: Path = Path("backups")) -> dict:

    compose_path = stack_dir / "docker-compose.yml"

    if not compose_path.exists():

        return {
            "success": False,
            "error": "No stack found to back up.",
            "backup_path": None,
            "warnings": []
        }

    backup_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(dt_timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = backup_dir / f"vulcan-backup-{timestamp}.tar.gz"

    config_dir = stack_dir / "config"
    unsafe_snapshots = []

    with tempfile.TemporaryDirectory() as tmp:

        staged_config = Path(tmp) / "config"

        # SQLite files are skipped here, not copied - each one gets a
        # proper consistent snapshot written into place below instead
        # of a possibly-torn raw copy.
        shutil.copytree(
            config_dir,
            staged_config,
            ignore=lambda directory, names: {
                name for name in names
                if (Path(directory) / name).is_file() and _is_sqlite_file(Path(directory) / name)
            }
        )

        for live_path in config_dir.rglob("*"):

            if not live_path.is_file() or not _is_sqlite_file(live_path):
                continue

            staged_path = staged_config / live_path.relative_to(config_dir)

            if not _snapshot_sqlite_database(live_path, staged_path):

                shutil.copy2(live_path, staged_path)
                unsafe_snapshots.append(str(live_path.relative_to(config_dir)))

        with tarfile.open(backup_path, "w:gz") as tar:

            tar.add(staged_config, arcname="config")
            tar.add(compose_path, arcname="docker-compose.yml")
            tar.add(stack_dir / ".env", arcname=".env")

    warnings = [
        "This backup includes stack/.env, which may contain real credentials "
        "(e.g. Gluetun VPN keys) - store the archive securely."
    ]

    if unsafe_snapshots:

        warnings.append(
            "Could not safely snapshot while running, copied directly instead "
            f"(may be inconsistent if it was mid-write): {', '.join(unsafe_snapshots)}"
        )

    return {
        "success": True,
        "error": None,
        "backup_path": str(backup_path),
        "warnings": warnings
    }


def latest_backup(backup_dir: Path = Path("backups")) -> Path | None:

    if not backup_dir.is_dir():
        return None

    archives = sorted(backup_dir.glob("vulcan-backup-*.tar.gz"))

    return archives[-1] if archives else None


def restore_stack(
    backup_path: Path,
    compose_path: str,
    env_path: str,
    stack_dir: Path = STACK_DIR
) -> dict:

    backup_path = Path(backup_path)

    if not backup_path.exists():
        return {"success": False, "error": f"Backup file not found: {backup_path}"}

    if Path(compose_path).exists():

        down = run_docker_command(
            ["docker", "compose", "-f", compose_path, "--env-file", env_path, "down"]
        )

        if down.returncode != 0:
            return {"success": False, "error": "Failed to stop the running stack - check `docker compose logs`."}

    stack_dir.mkdir(parents=True, exist_ok=True)

    # tarfile.extractall() only ever adds/overwrites members present in the
    # archive - it never deletes files already on disk that aren't part of
    # it. Without clearing config/ first, a stray file added after the
    # backup was taken (or a service's config dir for something no longer
    # enabled) would silently survive a "restore" - confirmed by actually
    # hitting this with a real drifted file before adding the rmtree.
    config_dir = stack_dir / "config"

    if config_dir.exists():
        shutil.rmtree(config_dir)

    try:
        with tarfile.open(backup_path, "r:gz") as tar:
            tar.extractall(path=stack_dir, filter="data")
    except tarfile.TarError as error:
        return {"success": False, "error": f"'{backup_path.name}' isn't a valid backup archive: {error}"}

    return {"success": True, "error": None}


def remove_orphaned_containers(project_name: str) -> dict:
    """
    Narrower than uninstall_stack() on purpose: stops and removes just
    the containers still carrying this project's compose label, by
    label alone (`docker compose -p <project> down`, no -f needed - the
    exact mechanism stack_containers_exist()'s own docstring already
    established) - and never touches stack/ on disk. The port-conflict
    remediation flow calls this for the "your own orphaned containers"
    case, where stack/ is *not* stale - it's the freshly-generated
    stack the current run is actively trying to start, so
    uninstall_stack()'s own unconditional _remove_stack_dir() would
    delete the very compose file this run just wrote.
    """

    down = run_docker_command(["docker", "compose", "-p", project_name, "down"])

    if down.returncode != 0:
        return {"success": False, "error": "Failed to stop orphaned containers - check `docker compose logs`."}

    return {"success": True, "error": None}


def stack_containers_exist(project_name: str) -> bool:
    """
    True if any container (running or stopped) still carries Docker
    Compose's own com.docker.compose.project label for this project -
    confirmed the real label key by inspecting a real generated
    container, not assumed. Used to detect containers orphaned by
    stack/ being deleted through some means other than a real
    `vulcan uninstall` run (confirmed a real, recurring scenario, not
    hypothetical) - docker compose itself needs no compose file to act
    on these, only the project name.
    """

    try:

        result = subprocess.run(
            ["docker", "ps", "-a", "--filter", f"label=com.docker.compose.project={project_name}", "-q"],
            capture_output=True,
            text=True
        )

    except OSError:
        return False

    return bool(result.stdout.strip())


def uninstall_stack(
    compose_path: str,
    env_path: str,
    stack_dir: Path = STACK_DIR,
    backup_dir: Path = Path("backups"),
    export_dir: Path = Path("exports"),
    purge_artifacts: bool = False
) -> dict:

    if Path(compose_path).exists():

        down = run_docker_command(
            ["docker", "compose", "-f", compose_path, "--env-file", env_path, "down"]
        )

        if down.returncode != 0:
            return {"success": False, "error": "Failed to stop the running stack - check `docker compose logs`."}

    elif stack_containers_exist(stack_dir.name):

        down = run_docker_command(["docker", "compose", "-p", stack_dir.name, "down"])

        if down.returncode != 0:
            return {"success": False, "error": "Failed to stop orphaned containers - check `docker compose logs`."}

    if stack_dir.exists():
        _remove_stack_dir(stack_dir)

    if purge_artifacts:

        if backup_dir.exists():
            shutil.rmtree(backup_dir)

        if export_dir.exists():
            shutil.rmtree(export_dir)

    return {"success": True, "error": None}


def _remove_stack_dir(stack_dir: Path) -> None:
    """
    A plain shutil.rmtree() is enough for every service Vulcan generates
    except one: Authelia's official image runs as its own internal user
    (root, confirmed by inspecting real file ownership after running it),
    not PUID/PGID like every LinuxServer.io image here - files it creates
    at runtime (its SQLite db, notification log) can end up owned by a
    UID the host user can't delete directly. Confirmed by hitting a real
    PermissionError against a real running Authelia container, not
    assumed. Falls back to emptying the directory from inside a
    throwaway root container - the same real technique already used to
    clean up stray test state in this project's own history - then
    removing the now-empty tree normally.
    """

    try:
        shutil.rmtree(stack_dir)
    except PermissionError:

        run_docker_command(
            ["docker", "run", "--rm", "-v", f"{stack_dir.resolve()}:/target", "alpine", "sh", "-c", "rm -rf /target/*"]
        )

        shutil.rmtree(stack_dir, ignore_errors=True)
