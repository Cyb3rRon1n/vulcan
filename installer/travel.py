"""
Travel tier: the pieces that live on the box itself, outside the Docker
stack - Avahi so the box answers as <hostname>.local on any network, plus
the checks `vulcan doctor` runs. Plan builders are pure; apply_steps() is
the only thing that executes, always through run_privileged.
"""

import getpass
import ipaddress
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

from installer.deps import _INSTALL_CMD, _family_for
from installer.shell import run_privileged

_HOSTNAME = re.compile(r"[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?")

# libnss-mdns/nss-mdns let this box itself resolve *.local (what doctor checks).
AVAHI_PACKAGES = {
    "debian": ["avahi-daemon", "libnss-mdns"],
    "fedora": ["avahi", "nss-mdns"],
    "arch": ["avahi", "nss-mdns"],
}

SYSTEMD_DIR = "/etc/systemd/system"
MEDIA_REGISTER_UNIT = "vulcan-media-register"
SYNC_UNIT = "vulcan-travel-sync"
# Relative to the media path; the media assistant imports from here.
SYNC_INBOX = Path("downloads") / "from-home"
SYNC_LEDGER = Path("stack") / "travel-sync-ledger.txt"
SSH_COMMAND = "ssh -o BatchMode=yes -o ConnectTimeout=10"


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


def invoking_user() -> str:
    """The real user behind sudo - timers must run as them, not root."""

    return os.environ.get("SUDO_USER") or getpass.getuser()


def timer_units(name: str, description: str, command: str, on_calendar: str, user: str, workdir: str) -> dict[str, str]:

    service = (
        f"[Unit]\nDescription={description}\nAfter=network-online.target docker.service\n"
        "Wants=network-online.target\n\n"
        f"[Service]\nType=oneshot\nUser={user}\nWorkingDirectory={workdir}\nExecStart={command}\n"
    )
    timer = (
        f"[Unit]\nDescription={description} (timer)\n\n"
        f"[Timer]\nOnCalendar={on_calendar}\nPersistent=true\nRandomizedDelaySec=5m\n\n"
        "[Install]\nWantedBy=timers.target\n"
    )

    return {f"{SYSTEMD_DIR}/{name}.service": service, f"{SYSTEMD_DIR}/{name}.timer": timer}


def install_timer(
    name: str,
    description: str,
    command: str,
    on_calendar: str = "hourly",
    run=run_privileged,
    write=write_root_file,
    user: str | None = None,
    workdir: str | None = None,
) -> dict:

    units = timer_units(name, description, command, on_calendar, user or invoking_user(), workdir or os.getcwd())

    for path, content in units.items():

        written = write(path, content, run)

        if not written["success"]:
            return {"ok": False, "error": f"couldn't write {path}: {written['error']}"}

    return apply_steps([["systemctl", "daemon-reload"], ["systemctl", "enable", "--now", f"{name}.timer"]], run)


def remove_timer(name: str, run=run_privileged, exists=os.path.exists) -> dict:

    timer = f"{SYSTEMD_DIR}/{name}.timer"

    if not exists(timer):
        return {"ok": True, "error": None, "skipped": True}

    return apply_steps([
        ["systemctl", "disable", "--now", f"{name}.timer"],
        ["rm", "-f", timer, f"{SYSTEMD_DIR}/{name}.service"],
        ["systemctl", "daemon-reload"],
    ], run)


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

    # Hourly catch-up for imports queued while Sonarr/Radarr were offline -
    # only meaningful when the self-download group is in the stack.
    if services & {"sonarr", "radarr"}:
        rows.append(_row("media-register timer", install_timer(
            MEDIA_REGISTER_UNIT, "Vulcan: register imported media with Sonarr/Radarr",
            f"{sys.executable} -m installer media register", run=run, write=write,
        )))
    else:
        rows.append(_row("media-register timer (removed)", remove_timer(MEDIA_REGISTER_UNIT, run, exists)))

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


def home_status(home: str, run=subprocess.run) -> tuple[bool, str | None]:
    """(reachable, error). Home being away is (False, None); ssh getting an
    answer but refusing us (host key, key, user) is (True, a plain fix hint) -
    BatchMode makes all of those exit 255, same as no route."""

    try:
        probe = run([*SSH_COMMAND.split(), home, "true"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return False, None

    if probe.returncode == 0:
        return True, None

    stderr = probe.stderr or ""

    if "Host key verification failed" in stderr:
        return True, f"ssh doesn't trust {home} yet - run `ssh {home}` once and accept its host key"

    if "Permission denied" in stderr:
        return True, f"ssh to {home} was refused (key or user) - check TRAVEL_SYNC_FROM and that your ssh key is on the home box"

    return False, None


def list_command(home: str, remote_path: str, inbox: Path) -> list[str]:
    """Dry run: every file the inbox doesn't already have, as '<bytes> <path>' lines."""

    return ["rsync", "-a", "-s", "-8", "--dry-run", "--out-format=%l %n", "-e", SSH_COMMAND,
            f"{home}:{remote_path.rstrip('/')}/", f"{inbox}/"]


def transfer_command(home: str, remote_path: str, inbox: Path, files_from: str) -> list[str]:
    """--partial-dir keeps an interrupted file, so the next run resumes it."""

    return ["rsync", "-a", "-s", "--partial-dir=.vulcan-partial", "--info=progress2", f"--files-from={files_from}",
            "-e", SSH_COMMAND, f"{home}:{remote_path.rstrip('/')}/", f"{inbox}/"]


def parse_listing(output: str) -> list[tuple[int, str]]:

    files = []

    for line in output.splitlines():

        size, _, name = line.partition(" ")

        if size.isdigit() and name and not name.endswith("/"):
            files.append((int(size), name))

    return files


def select_files(
    files: list[tuple[int, str]], max_bytes: int, free_bytes: int, min_free_bytes: int
) -> tuple[list[tuple[int, str]], str | None]:
    """Files that fit both the per-run cap and the free-space floor, in listing
    order; a file too big for what's left is skipped, smaller ones still go."""

    budget = min(max_bytes, free_bytes - min_free_bytes)
    chosen, total, limited_by = [], 0, None

    for size, name in files:

        if total + size > budget:
            limited_by = "size cap" if max_bytes <= free_bytes - min_free_bytes else "free-space floor"
            continue

        chosen.append((size, name))
        total += size

    return chosen, limited_by


def sync_from_home(
    home: str,
    remote_path: str,
    media_path,
    max_bytes: int,
    min_free_bytes: int,
    ledger_path=SYNC_LEDGER,
    run=subprocess.run,
    free: int | None = None,
) -> dict:
    """Pull files the box doesn't have yet into <media>/downloads/from-home.
    The ledger remembers what arrived, so a file imported (and moved out of
    the inbox) by the media assistant is never pulled twice."""

    inbox = Path(media_path) / SYNC_INBOX
    library = Path(media_path) / "media"
    ledger = Path(ledger_path)
    result = {"reachable": False, "files": [], "bytes": 0, "limited_by": None, "error": None, "inbox": str(inbox)}

    if home.startswith("-"):
        result["error"] = f"'{home}' isn't a valid home box (it looks like an option) - use [user@]host"
        return result

    if not remote_path.strip("/"):
        result["error"] = "the home library path can't be / - set TRAVEL_SYNC_PATH (e.g. /mnt/media/media)"
        return result

    result["reachable"], result["error"] = home_status(home, run)

    if not result["reachable"] or result["error"]:
        return result

    inbox.mkdir(parents=True, exist_ok=True)
    listed = run(list_command(home, remote_path, inbox), capture_output=True, text=True)

    if listed.returncode != 0:
        result["error"] = f"couldn't list {home}:{remote_path} ({(listed.stderr or '').strip()[:200]})"
        return result

    done = set(ledger.read_text().splitlines()) if ledger.exists() else set()
    new = [(size, name) for size, name in parse_listing(listed.stdout)
           if name not in done and not (library / name).exists()]
    chosen, result["limited_by"] = select_files(
        new, max_bytes, shutil.disk_usage(inbox).free if free is None else free, min_free_bytes
    )

    if not chosen:
        return result

    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as handle:
        handle.write("".join(f"{name}\n" for _, name in chosen))

    try:
        copied = run(transfer_command(home, remote_path, inbox, handle.name))
    finally:
        os.unlink(handle.name)

    arrived = [(size, name) for size, name in chosen
               if (inbox / name).is_file() and (inbox / name).stat().st_size == size]

    if arrived:
        ledger.parent.mkdir(parents=True, exist_ok=True)
        with ledger.open("a") as out:
            out.write("".join(f"{name}\n" for _, name in arrived))

    result["files"] = [name for _, name in arrived]
    result["bytes"] = sum(size for size, _ in arrived)

    if copied.returncode != 0:
        result["error"] = f"rsync stopped (exit {copied.returncode}) - run again to resume"

    return result
