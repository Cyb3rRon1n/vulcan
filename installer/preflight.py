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

import socket
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


def check_ports_available(compose_path: str) -> dict:

    parsed = yaml.safe_load(Path(compose_path).read_text()) or {}
    ports = set()

    for service in parsed.get("services", {}).values():

        for entry in service.get("ports", []):

            host_port = str(entry).split(":")[-2]
            ports.add(int(host_port))

    conflicts = sorted(port for port in ports if _port_in_use(port))

    return {"available": not conflicts, "conflicts": conflicts}
