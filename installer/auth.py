"""
Authelia setup helpers: hashing a real admin password via Authelia's own
CLI (hash_authelia_password) and generating the random secrets Authelia
needs to run at all (generate_authelia_secrets) - genuinely random
values Vulcan can produce itself, unlike Gluetun's VPN credentials,
which Vulcan has no way to know and leaves as a placeholder instead.
"""

import secrets
import subprocess
from pathlib import Path


def hash_authelia_password(password: str) -> dict:
    """
    Real subprocess call, not a pure function - shells out to Authelia's
    own image to hash a password via its argon2 CLI, since that's the
    only supported way to produce a hash its file-backed auth accepts.
    A captured call (like export_images()'s exception to the normal
    non-capturing run_docker_command()) - the real hash string has to
    come back, not just an exit code.
    """

    proc = subprocess.run(
        [
            "docker", "run", "--rm", "authelia/authelia:latest",
            "authelia", "crypto", "hash", "generate", "argon2",
            "--password", password
        ],
        capture_output=True,
        text=True
    )

    if proc.returncode != 0:
        return {"success": False, "error": "Failed to hash password via authelia's own CLI.", "hash": None}

    # On a cold image cache, Docker's own pull output also prints a line
    # starting "Digest: sha256:..." before Authelia's real hash line -
    # confirmed by actually running this against a real, uncached image.
    # The real hash is "$"-delimited (argon2's own encoding), so match
    # "Digest: $" specifically, not just "Digest:".
    for line in proc.stdout.splitlines():

        if line.startswith("Digest: $"):
            return {"success": True, "error": None, "hash": line.removeprefix("Digest: ").strip()}

    return {"success": False, "error": "Could not find a password hash in authelia's output.", "hash": None}


def generate_authelia_secrets(secrets_dir: Path) -> None:
    """
    Writes JWT_SECRET/SESSION_SECRET/STORAGE_ENCRYPTION_KEY, each only
    if it doesn't already exist - same never-overwrite rule as
    Homepage's services.yaml, so a regenerate never invalidates real
    existing sessions/encrypted storage.
    """

    secrets_dir.mkdir(parents=True, exist_ok=True)

    for filename in ("JWT_SECRET", "SESSION_SECRET", "STORAGE_ENCRYPTION_KEY"):

        path = secrets_dir / filename

        if not path.exists():
            path.write_text(secrets.token_hex(32))
