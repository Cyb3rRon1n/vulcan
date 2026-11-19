"""
Travel tier: the pieces that live on the box itself, outside the Docker
stack - Avahi so the box answers as <hostname>.local on any network, plus
the checks `vulcan doctor` runs. Plan builders are pure; apply_steps() is
the only thing that executes, always through run_privileged.
"""

import ipaddress
import os
import re
import shutil
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


ATOMIC_HINT = (
    "on an atomic/immutable host run: sudo rpm-ostree install avahi nss-mdns, reboot, "
    "then: sudo systemctl enable --now avahi-daemon"
)


def hosts_with_hostname(text: str, hostname: str) -> str:
    """/etc/hosts content with the 127.0.1.1 line pointing at hostname (added
    if missing). Every other line is left untouched; re-running is a no-op."""

    lines = text.splitlines()
    new = f"127.0.1.1 {hostname}"

    found = False

    for i, line in enumerate(lines):

        if line.split("#")[0].split()[:1] == ["127.0.1.1"]:
            lines[i] = new
            found = True

    if not found:
        lines.append(new)

    return "\n".join(lines) + "\n"


def _read_hosts() -> str | None:
    """None when /etc/hosts can't be read - never guess its content."""

    try:
        with open("/etc/hosts") as handle:
            return handle.read()
    except OSError:
        return None


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
    read_hosts=_read_hosts,
    which=shutil.which,
) -> list[dict]:
    """Every host-side travel step, in order. Re-run safe: each step is
    idempotent. services/kiosk/write/exists/user_exists/groups are used by
    the timer and kiosk steps."""

    if not valid_hostname(hostname):
        return [_row(f"avahi ({hostname}.local)", {"ok": False, "error": f"'{hostname}' is not a valid hostname (letters, digits, dashes; max 63)"})]

    atomic = os_info.get("os_is_atomic", False)
    steps = avahi_steps(os_info.get("os_id"), atomic, hostname)

    if steps is None:
        avahi = {"ok": False, "error": f"install avahi (avahi-daemon) by hand, then: sudo systemctl enable --now avahi-daemon. If this host is atomic/immutable: {ATOMIC_HINT}"}
    else:
        avahi = apply_steps(steps, run)

        if not avahi["ok"] and atomic:
            avahi["error"] += f" - {ATOMIC_HINT}"

    rows = [_row(f"avahi ({hostname}.local)", avahi)]

    if avahi["ok"]:

        # hostnamectl leaves /etc/hosts on the old name; sudo then warns/stalls.
        current = read_hosts()
        wanted = hosts_with_hostname(current, hostname) if current is not None else None

        if current is None:
            rows.append(_row("/etc/hosts hostname", {
                "ok": False,
                "error": f"could not read /etc/hosts - left unchanged; add `127.0.1.1 {hostname}` by hand",
            }))
        elif wanted == current:
            rows.append(_row("/etc/hosts (already current)", {"ok": True, "skipped": True}))
        else:
            result = write("/etc/hosts", wanted, run)

            # SELinux hosts (Fedora): keep the file's label right; skip if absent.
            if result["success"] and which("restorecon"):
                label = run(["restorecon", "/etc/hosts"])

                if not label["success"]:
                    result = {"success": False, "error": f"written; restorecon failed: {label['error']}"}

            rows.append(_hosts_row(result))

    return rows


def _hosts_row(result: dict) -> dict:

    return _row("/etc/hosts hostname", {"ok": result["success"], "error": result["error"]})


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
                   "sudo dnf install nss-mdns, Arch: sudo pacman -S avahi nss-mdns, atomic/immutable hosts: "
                   "sudo rpm-ostree install avahi nss-mdns then reboot - and check the name with: hostnamectl",
        },
    ]
