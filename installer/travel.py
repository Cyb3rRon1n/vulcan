"""
Travel tier: the pieces that live on the box itself, outside the Docker
stack - Avahi so the box answers as <hostname>.local on any network, plus
the checks `vulcan doctor` runs. Plan builders are pure; apply_steps() is
the only thing that executes, always through run_privileged.
"""

import fcntl
import getpass
import grp
import ipaddress
import json
import os
import pwd
import re
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

from installer.deps import _INSTALL_CMD, _family_for
from installer.shell import run_privileged
from installer.userdata import Jellyfin

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
KIOSK_UNIT = "vulcan-kiosk"
KIOSK_USER = "vulcan-kiosk"
KIOSK_HOME = "/var/lib/vulcan-kiosk"
KIOSK_JELLYFIN_USER = "kiosk"
# cec-utils: `cec-client -l` shows whether a CEC adapter is there at all.
KIOSK_PACKAGES = ["kodi", "cec-utils"]
# dialout: USB-CEC adapters (most x86 HDMI ports have no CEC of their own).
KIOSK_GROUPS = ("video", "render", "input", "audio", "dialout")
JELLYFIN_KODI_ZIPS = (
    "https://kodi.jellyfin.org/repository.jellyfin.kodi.zip",
    "https://kodi.jellyfin.org/py3/plugin.video.jellyfin/plugin.video.jellyfin-2.2.0%2Bpy3.zip",
)


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


def _avahi_installed() -> bool:

    return bool(shutil.which("avahi-daemon") or os.path.exists("/usr/sbin/avahi-daemon"))


def avahi_steps(
    os_id: str | None, os_is_atomic: bool, hostname: str, installed: bool = False
) -> list[list[str]] | None:
    """Install + enable Avahi and set the system hostname it publishes.
    None when Vulcan doesn't know this distro's package names. When Avahi is
    already installed the package step is skipped, so an offline re-run works."""

    tail = [["hostnamectl", "set-hostname", hostname], ["systemctl", "enable", "--now", "avahi-daemon"]]

    # Atomic desktops (Bazzite, Silverblue) ship Avahi in the base image.
    if os_is_atomic or installed:
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


def timer_units(name: str, description: str, command: list[str], on_calendar: str, user: str, workdir: str) -> dict[str, str]:

    service = (
        f"[Unit]\nDescription={description}\nAfter=network-online.target docker.service\n"
        "Wants=network-online.target\n\n"
        f"[Service]\nType=oneshot\nUser={user}\nWorkingDirectory={workdir}\nExecStart={shlex.join(command)}\n"
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
    command: list[str],
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


def kiosk_unit() -> str:
    """Kodi full-screen on tty1 at boot. Conflicts= stops the login prompt
    there; remove_kiosk() starts it again."""

    return (
        "[Unit]\nDescription=Vulcan kiosk (Kodi full-screen on the TV)\n"
        "After=network-online.target docker.service systemd-user-sessions.service\n"
        "Wants=network-online.target\nConflicts=getty@tty1.service\n\n"
        f"[Service]\nUser={KIOSK_USER}\nEnvironment=HOME={KIOSK_HOME}\nPAMName=login\nTTYPath=/dev/tty1\n"
        "StandardInput=tty\nStandardOutput=journal\nExecStart=/usr/bin/kodi-standalone\n"
        "Restart=on-failure\nRestartSec=5\n\n"
        "[Install]\nWantedBy=multi-user.target\n"
    )


def kiosk_refusal(os_info: dict) -> str | None:

    if os_info.get("os_is_atomic"):
        return ("Kodi kiosk isn't supported on atomic/immutable systems (Bazzite, Silverblue, ...) - "
                "the stack still works; play from the TV's Jellyfin app instead")

    if _family_for(os_info.get("os_id")) != "debian":
        return "Kodi kiosk needs Debian or Ubuntu in this release - the stack still works"

    if os_info.get("architecture") not in ("x86_64", "amd64"):
        return "Kodi kiosk is x86-64 only in this release (Pi 5 is experimental) - the stack still works"

    return None


def kiosk_install_steps(user_exists: bool, groups: list[str]) -> list[list[str]]:

    member = ["usermod", "-aG", ",".join(groups), KIOSK_USER] if user_exists else [
        "useradd", "--system", "--create-home", "--home-dir", KIOSK_HOME,
        "--shell", "/usr/sbin/nologin", "--groups", ",".join(groups), KIOSK_USER,
    ]

    return [["apt-get", "install", "-y", *KIOSK_PACKAGES], member]


def _user_exists(name: str) -> bool:

    try:
        pwd.getpwnam(name)
    except KeyError:
        return False

    return True


def _existing_groups(names) -> list[str]:

    found = []

    for name in names:
        try:
            grp.getgrnam(name)
            found.append(name)
        except KeyError:
            pass

    return found


def install_kiosk(run, write, user_exists: bool, groups: list[str]) -> dict:

    result = apply_steps(kiosk_install_steps(user_exists, groups), run)

    if not result["ok"]:
        return result

    unit_path = f"{SYSTEMD_DIR}/{KIOSK_UNIT}.service"
    written = write(unit_path, kiosk_unit(), run)

    if not written["success"]:
        return {"ok": False, "error": f"couldn't write {unit_path}: {written['error']}"}

    # enable only: --now would grab tty1 (Conflicts=getty) in the middle of the install.
    return apply_steps([["systemctl", "daemon-reload"], ["systemctl", "enable", f"{KIOSK_UNIT}.service"]], run)


def remove_kiosk(run, exists) -> dict:
    """--no-kiosk: the unit goes, tty1 gets its login prompt back. Kodi and the
    kiosk user stay installed."""

    unit_path = f"{SYSTEMD_DIR}/{KIOSK_UNIT}.service"

    if not exists(unit_path):
        return {"ok": True, "error": None, "skipped": True}

    return apply_steps([
        ["systemctl", "disable", "--now", f"{KIOSK_UNIT}.service"],
        ["rm", "-f", unit_path],
        ["systemctl", "daemon-reload"],
        ["systemctl", "start", "getty@tty1.service"],
    ], run)


def kodi_credentials(login: dict, port: int) -> str:
    """The Jellyfin add-on's own saved-login file (addon_data/.../data.json)."""

    return json.dumps({"Servers": [{
        "Id": login["server_id"],
        "Name": login["server_name"],
        "address": f"http://localhost:{port}",
        "AccessToken": login["token"],
        "UserId": login["user_id"],
        "DateLastAccessed": "1970-01-01T00:00:00Z",
    }]}, indent=4, sort_keys=True)


def kiosk_jellyfin_login(url: str, api_key: str, password: str, opener=urllib.request.urlopen) -> dict:
    """Create the "kiosk" Jellyfin user if missing, then sign in as it."""

    jf = Jellyfin(url, api_key)
    info = jf("/System/Info/Public")

    if not any(user["Name"] == KIOSK_JELLYFIN_USER for user in jf("/Users")):
        jf("/Users/New", "POST", {"Name": KIOSK_JELLYFIN_USER, "Password": password})

    request = urllib.request.Request(
        url.rstrip("/") + "/Users/AuthenticateByName", method="POST",
        data=json.dumps({"Username": KIOSK_JELLYFIN_USER, "Pw": password}).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": 'MediaBrowser Client="Vulcan kiosk", Device="vulcan-kiosk", DeviceId="vulcan-kiosk", Version="1"',
        },
    )
    auth = json.loads(opener(request, timeout=30).read())

    return {"server_id": auth["ServerId"], "server_name": info["ServerName"],
            "user_id": auth["User"]["Id"], "token": auth["AccessToken"]}


def install_kodi_addon(login: dict | None, port: int, run=run_privileged, fetch=urllib.request.urlretrieve, exists=None) -> dict:
    """Place the Jellyfin repo + add-on in the kiosk user's Kodi, plus its saved
    login when we have one. Needs the internet (the zips), hence 'set it up at
    home first'. Once the add-on is in place nothing is downloaded, so a re-run
    on the road (offline) still refreshes the saved login."""

    kodi_dir = f"{KIOSK_HOME}/.kodi"
    marker = f"{kodi_dir}/addons/plugin.video.jellyfin"
    # The kiosk home isn't readable by us - ask through sudo unless told.
    installed = exists(marker) if exists else run(["test", "-d", marker])["success"]
    staging = Path(tempfile.mkdtemp(prefix="vulcan-kodi-"))

    try:

        addons = staging / "addons"
        addons.mkdir()

        for url in () if installed else JELLYFIN_KODI_ZIPS:

            zip_path = staging / url.rsplit("/", 1)[1]
            fetch(url, zip_path)

            with zipfile.ZipFile(zip_path) as archive:
                archive.extractall(addons)

            zip_path.unlink()

        if login:
            data = staging / "userdata" / "addon_data" / "plugin.video.jellyfin" / "data.json"
            data.parent.mkdir(parents=True)
            data.write_text(kodi_credentials(login, port))
            data.chmod(0o600)  # holds the access token

        return apply_steps([
            ["mkdir", "-p", kodi_dir],
            ["cp", "-a", f"{staging}/.", kodi_dir],
            ["chown", "-R", f"{KIOSK_USER}:{KIOSK_USER}", kodi_dir],
        ], run)

    except (OSError, zipfile.BadZipFile) as error:
        return {"ok": False, "error": f"couldn't fetch the Kodi Jellyfin add-on ({error}) - needs internet, run it at home"}

    finally:
        shutil.rmtree(staging, ignore_errors=True)


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
    avahi_installed=None,
) -> list[dict]:
    """Every host-side travel step, in order. Re-run safe: each step is
    idempotent. services/kiosk/write/exists/user_exists/groups are used by
    the timer and kiosk steps."""

    if not valid_hostname(hostname):
        return [_row(f"avahi ({hostname}.local)", {"ok": False, "error": f"'{hostname}' is not a valid hostname (letters, digits, dashes; max 63)"})]

    atomic = os_info.get("os_is_atomic", False)
    steps = avahi_steps(os_info.get("os_id"), atomic, hostname, (avahi_installed or _avahi_installed)())

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
            [sys.executable, "-m", "installer", "media", "register"], run=run, write=write,
        )))
    else:
        rows.append(_row("media-register timer (removed)", remove_timer(MEDIA_REGISTER_UNIT, run, exists)))

    # The sync timer needs Tailscale; without it (--no-home-sync) drop the timer.
    if "tailscale" not in services:
        rows.append(_row("sync timer (removed)", remove_timer(SYNC_UNIT, run, exists)))

    if kiosk:

        refusal = kiosk_refusal(os_info)

        if refusal:
            rows.append(_row("kiosk", {"ok": False, "error": refusal}))
        else:
            rows.append(_row("kiosk", install_kiosk(
                run, write,
                _user_exists(KIOSK_USER) if user_exists is None else user_exists,
                _existing_groups(KIOSK_GROUPS) if groups is None else groups,
            )))

    else:
        rows.append(_row("kiosk (removed)", remove_kiosk(run, exists)))

    return rows


def travel_teardown(run=run_privileged, exists=os.path.exists) -> list[dict]:
    """Leaving the travel tier (uninstall, or a rebuild as a home tier): the
    kiosk unit and both timers go. Nothing installed means no privileged calls."""

    return [
        _row("kiosk (removed)", remove_kiosk(run, exists)),
        _row("media-register timer (removed)", remove_timer(MEDIA_REGISTER_UNIT, run, exists)),
        _row("sync timer (removed)", remove_timer(SYNC_UNIT, run, exists)),
    ]


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

    if "Connection refused" in stderr:
        return True, f"{home} is up but isn't accepting ssh - start its ssh server (or `sudo tailscale set --ssh` there)"

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


def home_host_problem(home: str, own_names, resolve=socket.getaddrinfo) -> str | None:
    """The travel box answers to its own hostname (default `vulcan`, same as a
    home box often is), so syncing "from" that would pull from itself."""

    host = home.rpartition("@")[2].strip("[]").lower()
    own = {name.lower() for name in own_names if name}
    own |= {f"{name}.local" for name in own}

    message = (f"'{home}' is this box itself - use the home box's own tailnet name, "
               "e.g. you@home-vulcan, or its full name like you@vulcan.<tailnet>.ts.net when both are "
               "called vulcan (see `tailscale status`)")

    if host in own:
        return message

    try:
        found = {ipaddress.ip_address(item[4][0]) for item in resolve(host, None)}
    except (OSError, ValueError):
        return None

    return message if any(address.is_loopback for address in found) else None


def sync_args_problem(home: str, remote_path: str, own_names=None, resolve=socket.getaddrinfo) -> str | None:
    """Why a sync (or an hourly timer for it) can't use these settings; None if fine."""

    if any(c.isspace() or ord(c) < 32 for c in home) or any(ord(c) < 32 for c in remote_path):
        return "the home box and library path can't contain spaces, newlines or control characters"

    if home.startswith("-"):
        return f"'{home}' isn't a valid home box (it looks like an option) - use [user@]host"

    if not remote_path.strip("/"):
        return "the home library path can't be / - set TRAVEL_SYNC_PATH (e.g. /mnt/media/media)"

    return home_host_problem(home, own_names, resolve) if own_names is not None else None


def sync_from_home(
    home: str,
    remote_path: str,
    media_path,
    max_bytes: int,
    min_free_bytes: int,
    ledger_path=SYNC_LEDGER,
    run=subprocess.run,
    free: int | None = None,
    own_names=None,
    resolve=socket.getaddrinfo,
) -> dict:
    """Pull files the box doesn't have yet into <media>/downloads/from-home.
    The ledger remembers what arrived, so a file imported (and moved out of
    the inbox) by the media assistant is never pulled twice."""

    inbox = Path(media_path) / SYNC_INBOX
    library = Path(media_path) / "media"
    ledger = Path(ledger_path)
    result = {"reachable": False, "files": [], "bytes": 0, "limited_by": None, "error": None, "inbox": str(inbox),
              "busy": False}

    result["error"] = sync_args_problem(home, remote_path, own_names, resolve)

    if result["error"]:
        return result

    ledger.parent.mkdir(parents=True, exist_ok=True)
    lock = open(ledger.with_suffix(".lock"), "w")

    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        lock.close()
        result["busy"] = True
        return result

    try:
        return _sync_locked(home, remote_path, inbox, library, ledger, max_bytes, min_free_bytes, run, free, result)
    finally:
        lock.close()  # closing drops the lock


def _sync_locked(home, remote_path, inbox, library, ledger, max_bytes, min_free_bytes, run, free, result) -> dict:

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
        with ledger.open("a") as out:
            out.write("".join(f"{name}\n" for _, name in arrived))

    result["files"] = [name for _, name in arrived]
    result["bytes"] = sum(size for size, _ in arrived)

    if copied.returncode != 0:
        result["error"] = f"rsync stopped (exit {copied.returncode}) - run again to resume"

    return result
