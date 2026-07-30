"""
Post-install operations on an already-generated stack: pulling fresh
images and recreating containers (update_stack), and archiving config
for safekeeping (backup_stack). Both reuse the same real Docker/file
primitives generation already does - run_docker_command() for the
subprocess calls, the same STACK_DIR every other command reads from -
no new machinery, just a second thing to do with a stack that already
exists.
"""

import tarfile
from datetime import datetime
from datetime import timezone as dt_timezone
from pathlib import Path

from installer.docker_setup import run_docker_command
from installer.generate import STACK_DIR


def update_stack(compose_path: str, env_path: str) -> dict:

    pull = run_docker_command(
        ["docker", "compose", "-f", compose_path, "--env-file", env_path, "pull"]
    )

    if pull.returncode != 0:
        return {"success": False, "error": "Failed to pull images - check `docker compose logs`."}

    up = run_docker_command(
        ["docker", "compose", "-f", compose_path, "--env-file", env_path, "up", "-d"]
    )

    if up.returncode != 0:
        return {"success": False, "error": "Failed to recreate containers - check `docker compose logs`."}

    return {"success": True, "error": None}


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

    with tarfile.open(backup_path, "w:gz") as tar:

        tar.add(stack_dir / "config", arcname="config")
        tar.add(compose_path, arcname="docker-compose.yml")
        tar.add(stack_dir / ".env", arcname=".env")

    return {
        "success": True,
        "error": None,
        "backup_path": str(backup_path),
        "warnings": [
            "This backup includes stack/.env, which may contain real credentials "
            "(e.g. Gluetun VPN keys) - store the archive securely."
        ]
    }
