"""
Checks run once, right before the very first `docker compose up -d`
for a generated stack - distinct from docker_setup.py (is Docker
itself ready) and post_install.py (operations on an already-running-
or-runnable stack). check_ports_available() reads the already-written
compose file back and confirms every host port it publishes is
actually free, so a real conflict (something else already bound to
that port) gets reported clearly before Docker's own opaque failure,
not after.
"""

import re
import socket
import subprocess
from pathlib import Path

import yaml


def _port_in_use(port: int) -> bool:

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:

        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        try:
            s.bind(("0.0.0.0", port))
            return False
        except OSError:
            return True


def identify_port_owner(port: int, own_project_name: str | None = None) -> str | None:
    """
    Best-effort diagnosis of what's actually holding a conflicting
    port, so a refusal names a real cause instead of just a number -
    the exact gap that turned the original cAdvisor-vs-qBittorrent
    incident into a confusing debugging session instead of an obvious
    one. Docker-only: this project's one hard dependency is already
    Docker itself, so this needs no new tool (no lsof/ss requirement) -
    if the port isn't held by a Docker container, this honestly
    returns None rather than guessing further.

    docker ps's own `--filter publish=<port>` looked like the right
    tool for this but isn't - confirmed for real, not assumed: it
    matched a container on a completely unrelated host port during
    testing, and a container's real container-side port needs
    `expose=` instead. Parsing the real `{{.Ports}}` field directly
    (confirmed against a real bound container) is what's actually
    reliable.
    """

    result = subprocess.run(
        [
            "docker", "ps", "--format",
            '{{.Names}}\t{{.Image}}\t{{.Ports}}\t{{.Label "com.docker.compose.project"}}'
        ],
        capture_output=True,
        text=True
    )

    if result.returncode != 0:
        return None

    port_pattern = re.compile(rf":{port}->")

    for line in result.stdout.splitlines():

        parts = line.split("\t")

        if len(parts) != 4:
            continue

        name, image, ports_field, compose_project = parts

        if not port_pattern.search(ports_field):
            continue

        if own_project_name and compose_project == own_project_name:
            return (
                f"your own orphaned containers from a previous stack (project "
                f"\"{compose_project}\") - try `vulcan uninstall` to clean them up, "
                "then regenerate"
            )

        return f"container \"{name}\" (image {image})"

    return None


def check_ports_available(compose_path: str) -> dict:

    compose_path = Path(compose_path)
    parsed = yaml.safe_load(compose_path.read_text()) or {}
    ports = set()

    for service in parsed.get("services", {}).values():

        for entry in service.get("ports", []):

            host_port = str(entry).split(":")[-2]
            ports.add(int(host_port))

    conflicts = sorted(port for port in ports if _port_in_use(port))
    owners = {
        port: identify_port_owner(port, own_project_name=compose_path.parent.name)
        for port in conflicts
    }

    return {"available": not conflicts, "conflicts": conflicts, "owners": owners}


def format_port_conflicts(port_check: dict) -> str:
    """
    Single source of truth for the conflict message text, shared by
    both front ends (CLI/TUI) rather than each building its own -
    keeps the two genuinely identical instead of drifting apart.
    """

    lines = []

    for port in port_check["conflicts"]:

        owner = port_check["owners"].get(port)

        if owner:
            lines.append(f"  {port}: {owner}")
        else:
            lines.append(f"  {port}: not identified as a Docker container - check for a native service")

    return "\n".join(lines)
