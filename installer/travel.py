"""
Travel tier: the pieces that live on the box itself, outside the Docker
stack - Avahi so the box answers as <hostname>.local on any network, plus
the checks `vulcan doctor` runs. Plan builders are pure; apply_steps() is
the only thing that executes, always through run_privileged.
"""

import ipaddress
import os
import re
import socket
import subprocess
import tempfile

from installer.deps import _INSTALL_CMD, _family_for
from installer.shell import run_privileged

_HOSTNAME = re.compile(r"[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?")

# libnss-mdns/nss-mdns let this box itself resolve *.local (what doctor checks).
AVAHI_PACKAGES = {
    "debian": ["avahi-daemon", "libnss-mdns"],
    "fedora": ["avahi", "nss-mdns"],
    "arch": ["avahi", "nss-mdns"],
}


def valid_hostname(name: str) -> bool:
    """One DNS label (RFC 1123): what Avahi can publish as <name>.local."""

    return bool(_HOSTNAME.fullmatch(name))


def valid_ip(value: str) -> bool:

    try:
        ipaddress.ip_address(value)
    except ValueError:
        return False

    return True


def apply_steps(steps: list[list[str]], run=run_privileged) -> dict:
    """Run each argv in order; stop at the first failure and name it."""

    for argv in steps:

        result = run(argv)

        if not result["success"]:
            return {"ok": False, "error": f"{' '.join(argv)}: {result['error']}"}

    return {"ok": True, "error": None}


def write_root_file(path: str, content: str, run=run_privileged) -> dict:
    """Write a root-owned 0644 file (systemd units) via `install` through sudo."""

    with tempfile.NamedTemporaryFile("w", delete=False, suffix=".vulcan") as handle:
        handle.write(content)

    try:
        return run(["install", "-m", "0644", handle.name, path])
    finally:
        os.unlink(handle.name)


def avahi_steps(os_id: str | None, os_is_atomic: bool, hostname: str) -> list[list[str]] | None:
    """Install + enable Avahi and set the system hostname it publishes.
    None when Vulcan doesn't know this distro's package names."""

    tail = [["hostnamectl", "set-hostname", hostname], ["systemctl", "enable", "--now", "avahi-daemon"]]

    # Atomic desktops (Bazzite, Silverblue) ship Avahi in the base image.
    if os_is_atomic:
        return tail

    family = _family_for(os_id)

    if family is None:
        return None

    return [[*_INSTALL_CMD[family], *AVAHI_PACKAGES[family]], *tail]


def _row(step: str, result: dict) -> dict:

    return {"step": step, "ok": result["ok"], "error": result.get("error"), "skipped": result.get("skipped", False)}


def host_setup(
    services: set[str],
    hostname: str,
    kiosk: bool,
    os_info: dict,
    run=run_privileged,
    write=write_root_file,
    exists=os.path.exists,
    user_exists: bool | None = None,
    groups: list[str] | None = None,
) -> list[dict]:
    """Every host-side travel step, in order. Re-run safe: each step is
    idempotent. services/kiosk/write/exists/user_exists/groups are used by
    the timer and kiosk steps."""

    steps = avahi_steps(os_info.get("os_id"), os_info.get("os_is_atomic", False), hostname)

    if steps is None:
        avahi = {"ok": False, "error": "install avahi (avahi-daemon) by hand, then: sudo systemctl enable --now avahi-daemon"}
    else:
        avahi = apply_steps(steps, run)

    return [_row(f"avahi ({hostname}.local)", avahi)]


def doctor_checks(hostname: str, run_capture=subprocess.run, resolve=socket.getaddrinfo) -> list[dict]:

    try:
        active = run_capture(["systemctl", "is-active", "avahi-daemon"], capture_output=True, text=True).stdout.strip() == "active"
    except OSError:
        active = False

    try:
        resolve(f"{hostname}.local", None)
        resolves = True
    except OSError:
        resolves = False

    return [
        {
            "name": "Avahi (avahi-daemon) running",
            "ok": active,
            "fix": "sudo systemctl enable --now avahi-daemon   (or re-run: vulcan travel setup)",
        },
        {
            "name": f"{hostname}.local resolves",
            "ok": resolves,
            "fix": "install mDNS lookups - Debian/Ubuntu: sudo apt install libnss-mdns, Fedora: "
                   "sudo dnf install nss-mdns - and check the name with: hostnamectl",
        },
    ]
