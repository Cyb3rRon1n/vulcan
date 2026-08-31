"""
System resource detection: CPU cores/model, RAM, free disk on candidate
paths, whether the media path has any drive-level redundancy (mdadm/
btrfs/ZFS), GPU vendor presence, Docker status, architecture, OS. Pure
and read-only - nothing here installs or mutates anything, and that
includes storage: detect_media_redundancy() only ever reports what's
already there, never creates or modifies a RAID/partition layout.
Every function catches its own failure modes and returns None/False/a
partial result rather than raising, since a missing tool (no
nvidia-smi, no docker) just means "not present," not an error.
"""

import grp
import os
import platform
import shutil
import socket
import subprocess
from dataclasses import dataclass
from pathlib import Path

import psutil

from installer.shell import run_ok, run_result
from installer.storage import list_blank_unprotected_devices


@dataclass
class SystemInfo:

    cpu_cores_physical: int | None
    cpu_cores_logical: int | None
    cpu_model: str | None

    ram_total_gb: float
    ram_available_gb: float

    disk_free_gb: float
    disk_path_checked: str

    gpu_vendor: str | None

    docker_installed: bool
    docker_running: bool
    docker_compose_v2: bool

    architecture: str
    os_id: str | None
    os_pretty_name: str | None
    os_is_atomic: bool

    # Daemon is up but this user can't reach the socket (not in the
    # docker group). Distinct from docker_running=False (daemon down):
    # the fix is a group add, not a service start. Defaults True so a
    # SystemInfo built without it behaves exactly as before.
    docker_accessible: bool = True


def detect_cpu() -> dict:

    cpu_model = None
    cpu_implementer = None
    cpu_part = None

    try:

        with open("/proc/cpuinfo") as f:

            for line in f:

                if line.startswith("model name"):

                    cpu_model = line.split(":", 1)[1].strip()
                    break

                elif line.startswith("CPU implementer"):
                    cpu_implementer = line.split(":", 1)[1].strip()

                elif line.startswith("CPU part"):
                    cpu_part = line.split(":", 1)[1].strip()

        # ARM64 /proc/cpuinfo has no "model name" line at all - the x86
        # convention this function originally only knew about. It does
        # carry CPU implementer/part hex codes (e.g. "0x41"/"0xd08" for
        # a Cortex-A72), which aren't a friendly name but are real and
        # better than reporting "unknown" on every ARM host.
        if cpu_model is None and cpu_implementer and cpu_part:
            cpu_model = f"ARM CPU (implementer {cpu_implementer}, part {cpu_part})"

    except OSError:
        cpu_model = None

    return {
        "cpu_cores_physical": psutil.cpu_count(logical=False),
        "cpu_cores_logical": psutil.cpu_count(logical=True),
        "cpu_model": cpu_model
    }


def detect_memory() -> dict:

    memory = psutil.virtual_memory()

    return {
        "ram_total_gb": round(memory.total / (1024 ** 3), 2),
        "ram_available_gb": round(memory.available / (1024 ** 3), 2)
    }


def detect_disk(path: str) -> dict:

    try:
        free_bytes = shutil.disk_usage(path).free

    except OSError:

        return {
            "disk_free_gb": 0.0,
            "disk_path_checked": path
        }

    return {
        "disk_free_gb": round(free_bytes / (1024 ** 3), 2),
        "disk_path_checked": path
    }


def _parse_block_size_gb(size: str) -> float | None:
    """lsblk human SIZE string -> GiB ('3.7T' -> 3788.8), or None on junk."""

    units = {
        "K": 1 / 1048576, "M": 1 / 1024, "G": 1.0,
        "T": 1024.0, "P": 1048576.0, "B": 1 / 1073741824,
    }

    try:
        number = float(size[:-1])
        unit = size[-1].upper()
    except (ValueError, IndexError):
        return None

    mult = units.get(unit)
    return round(number * mult, 2) if mult is not None else None


def provisionable_disk_gb() -> float:
    """Total GiB of genuinely spare (blank, unprotected) real disks - what a
    fresh machine can provision for media storage. Invisible to
    shutil.disk_usage('/',...), which only sees mounted filesystems; this is
    why a fresh box with blank drives used to recommend a lower tier."""

    total = 0.0

    for device in list_blank_unprotected_devices():
        size = _parse_block_size_gb(device.get("size", ""))
        if size is not None:
            total += size

    return total


_STORAGE_MOUNT_DEFAULT = "/mnt/media"


def detect_storage_mount() -> str | None:
    """
    The provisioned media-storage mount point (default /mnt/media) when
    it's actually mounted, else None. This is what `vulcan storage
    apply` mounts by default; reporting it lets the menu's Guided Setup
    default the Media Library path to the provisioned RAID array instead
    of $HOME/media on a machine that just provisioned one.
    """

    if os.path.ismount(_STORAGE_MOUNT_DEFAULT):
        return _STORAGE_MOUNT_DEFAULT

    return None


def detect_media_disk_path(previous_media_path: str | None = None) -> str:
    """
    The real filesystem to measure disk free against for the tier
    recommendation, when one is already known: the previous install's
    media path if it still exists, else a provisioned storage mount
    (default /mnt/media) if one is actually mounted, else "/". This is
    what fixes the menu's Guided Setup reporting the boot disk's free
    space instead of the RAID array's - the CLI flow already re-detects
    against the real chosen path, the menu's one-shot `vulcan detect`
    call had no way to before.
    """

    for candidate in (previous_media_path, detect_storage_mount()):

        if candidate and os.path.isdir(candidate):
            return candidate

    return "/"


_REDUNDANT_MDADM_LEVELS = {"raid1", "raid4", "raid5", "raid6", "raid10"}


def detect_media_redundancy(media_path: str) -> dict:
    """
    Read-only: what's actually backing media_path, and whether it has
    any drive-level redundancy (mdadm/btrfs/ZFS) - never suggests or
    performs any storage action itself. `installer/storage.py`'s
    `plan_storage_layout()` (a later, deliberate reversal of this
    project's earlier "never touches storage" stance) *can* compute
    what provisioning a fresh drive would look like, but still never
    executes anything - real execution stays out of scope, see
    ROADMAP.md. Every field stays None when it can't be determined
    (missing tool, unresolvable path) - same "not present isn't an
    error" convention as every other detector here.

    The ZFS branch is implemented from documented `zpool status`
    output, not verified against a real pool - no zfs/zpool tooling
    exists in this project's own dev/test environment. Treat it the
    same way NVIDIA GPU passthrough is treated elsewhere: shipped,
    clearly not hardware-verified yet.
    """

    result = {
        "device": None,
        "filesystem": None,
        "redundant": None,
        "redundancy_type": None,
        "device_count": None,
    }

    try:

        findmnt = subprocess.run(
            ["findmnt", "-no", "SOURCE,FSTYPE,TARGET", "-T", media_path],
            capture_output=True,
            text=True,
            timeout=5
        )

    except (subprocess.SubprocessError, OSError):
        return result

    if findmnt.returncode != 0 or not findmnt.stdout.strip():
        return result

    parts = findmnt.stdout.strip().split(None, 2)

    if len(parts) != 3:
        return result

    source, filesystem, mountpoint = parts
    device = source.split("[", 1)[0]

    result["device"] = device
    result["filesystem"] = filesystem

    if device.startswith("/dev/md"):

        md_name = device.removeprefix("/dev/")

        try:
            with open("/proc/mdstat") as f:
                mdstat = f.read()
        except OSError:
            mdstat = ""

        for line in mdstat.splitlines():

            if not line.startswith(f"{md_name} :"):
                continue

            tokens = line.split()
            level = next((t for t in tokens if t in _REDUNDANT_MDADM_LEVELS or t in ("raid0", "linear")), None)
            members = [t for t in tokens if "[" in t and t.endswith("]")]

            result["redundancy_type"] = level
            result["redundant"] = level in _REDUNDANT_MDADM_LEVELS
            result["device_count"] = len(members) or None
            break

    elif filesystem == "btrfs":

        # A missing btrfs binary means "can't determine," not "not
        # redundant" - result stays all-None past this point rather
        # than falling through to the plain-device branch below.
        if shutil.which("btrfs"):

            try:

                # `btrfs filesystem show` needs the real mountpoint -
                # it rejects an arbitrary path underneath it (unlike
                # findmnt -T, which resolves any path fine), confirmed
                # by hitting the real "not a valid btrfs filesystem"
                # error against a real subdirectory before switching
                # from media_path to findmnt's own resolved TARGET.
                show = subprocess.run(
                    ["btrfs", "filesystem", "show", mountpoint],
                    capture_output=True,
                    text=True,
                    timeout=5
                )

            except (subprocess.SubprocessError, OSError):
                show = None

            if show is not None and show.returncode == 0:

                for line in show.stdout.splitlines():

                    if "Total devices" not in line:
                        continue

                    try:
                        count = int(line.split("Total devices", 1)[1].split()[0])
                    except (IndexError, ValueError):
                        break

                    result["device_count"] = count
                    result["redundant"] = count > 1
                    result["redundancy_type"] = "btrfs-multi-device" if count > 1 else None
                    break

    elif filesystem == "zfs":

        # Same reasoning as the btrfs branch: no zpool binary means
        # "can't determine," not "not redundant."
        if shutil.which("zpool"):

            pool = device.split("/", 1)[0]

            try:

                status = subprocess.run(
                    ["zpool", "status", pool],
                    capture_output=True,
                    text=True,
                    timeout=5
                )

            except (subprocess.SubprocessError, OSError):
                status = None

            if status is not None and status.returncode == 0:

                output = status.stdout.lower()
                redundancy_type = next(
                    (kind for kind in ("mirror", "raidz1", "raidz2", "raidz3", "raidz") if kind in output),
                    None
                )

                result["redundant"] = redundancy_type is not None
                result["redundancy_type"] = f"zfs-{redundancy_type}" if redundancy_type else None

    else:

        result["redundant"] = False
        result["device_count"] = 1

    return result


def describe_media_redundancy(result: dict) -> str | None:

    if result["device"] is None:
        return None

    filesystem = result["filesystem"] or "unknown filesystem"

    if result["redundant"] is None:
        return f"{result['device']} ({filesystem}) - redundancy could not be determined"

    if result["redundant"]:

        kind = result["redundancy_type"] or "redundant"
        count = f", {result['device_count']} devices" if result["device_count"] else ""

        return f"{result['device']} ({filesystem}, {kind}{count})"

    return f"{result['device']} ({filesystem}, single device - no redundancy)"


def detect_gpu() -> str | None:
    """
    Real functional queries for NVIDIA/AMD, not just binary presence -
    a tool being installed doesn't mean a working driver/GPU is
    actually behind it. Found and confirmed on this project's own real
    dev machine, not hypothetical: rocm-smi is present here with no
    AMD GPU at all (no amdgpu kernel module loaded), and the previous
    presence-only check reported "amd" on this machine for this
    project's entire history - a genuine, live false positive.
    Backported from the same fix built and verified in the sibling
    Anvil project, which independently hit and root-caused this while
    researching its own GPU-VRAM detection.

    NVIDIA and AMD need different failure checks, confirmed by
    actually running both on this real machine: nvidia-smi follows the
    normal convention (non-zero exit when it can't reach a driver -
    the same signal NVIDIA's own driver-validator tooling relies on),
    but rocm-smi does not - `rocm-smi --showid` against this machine's
    real absent AMD driver prints "ERROR:root:Driver not initialized"
    and still exits 0, so its check has to look at the actual output,
    not just the return code. Intel has no equivalent "smi" tool, so
    its check stays the pre-existing lspci-output heuristic (already a
    real check of actual command output, not just presence).
    """

    if shutil.which("nvidia-smi") and run_ok(["nvidia-smi", "-L"]):
        return "nvidia"

    if shutil.which("rocm-smi"):

        try:

            result = subprocess.run(
                ["rocm-smi", "--showid"],
                capture_output=True,
                text=True,
                timeout=5
            )

            if result.returncode == 0 and "ERROR" not in result.stdout and "ERROR" not in result.stderr:
                return "amd"

        except (subprocess.SubprocessError, OSError):
            pass

    if shutil.which("lspci"):

        try:

            result = subprocess.run(
                ["lspci"],
                capture_output=True,
                text=True,
                timeout=5
            )

            output = result.stdout.lower()

            if "intel" in output and (
                "vga" in output or "3d controller" in output
            ):
                return "intel"

        except (subprocess.SubprocessError, OSError):
            pass

    return None


def detect_render_group_gid() -> int | None:
    """
    The gid of the host's DRM render-node group - needed alongside
    /dev/dri passthrough for AMD/Intel hardware transcoding, since
    PUID/PGID alone doesn't grant a containerized process access to a
    device node owned by this group. "video" is the fallback name on
    distros/kernels that predate the dedicated "render" group.
    """

    for name in ("render", "video"):

        try:
            return grp.getgrnam(name).gr_gid
        except KeyError:
            continue

    return None


def detect_host_ip() -> str | None:
    """
    Best-effort LAN-facing address for links a dashboard viewed from
    another device needs - not a secret the way a VPN key is, so a real
    detected default beats a placeholder. A UDP "connect" sends no
    actual packets (UDP has no handshake); it only asks the kernel's
    routing table which local address it would use to reach that
    destination, which is exactly the address other devices on the
    same network can reach this host at.
    """

    try:

        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            return sock.getsockname()[0]

    except OSError:
        return None


def detect_docker() -> dict:

    installed = shutil.which("docker") is not None

    if not installed:

        return {
            "docker_installed": False,
            "docker_running": False,
            "docker_accessible": False,
            "docker_compose_v2": False
        }

    info_rc, info_err = run_result(["docker", "info"])

    running = info_rc == 0
    accessible = running

    # `docker info` failing with EACCES on the socket means the daemon
    # is up and this user just isn't in the docker group - "running but
    # not accessible", whose fix is a group add, not a service start.
    if not running and "permission denied" in info_err.lower():
        running = True
        accessible = False

    return {
        "docker_installed": True,
        "docker_running": running,
        "docker_accessible": accessible,
        "docker_compose_v2": run_ok(["docker", "compose", "version"])
    }


def detect_os_is_atomic() -> bool:
    """
    True on an rpm-ostree-based image (Fedora Silverblue/Kinoite,
    Bazzite, and other Universal Blue derivatives, CoreOS) - a real
    functional signal, not a name guess. Ported from the sibling Anvil
    project, which built and live-verified this against a real Bazzite
    GPU host (msi-laptop): /run/ostree-booted is written by ostree
    itself at boot only when the running root is an ostree deployment -
    confirmed present there, absent on this project's own normal-Fedora
    dev machine. Docker can't be `dnf install`ed on these systems the
    way install_plan_for's DOCKER_SCRIPT_DISTROS assume - the base
    image is read-only, packages are layered via `rpm-ostree install`
    instead, and that layering only takes effect after a reboot.
    shutil.which("rpm-ostree") is kept as a narrower fallback for the
    (unobserved) case where the marker file is missing but the tooling
    still is - never the primary signal, since a tool on PATH doesn't
    confirm the running root actually is one.
    """

    if Path("/run/ostree-booted").exists():
        return True

    return shutil.which("rpm-ostree") is not None


def detect_os() -> dict:

    os_id = None
    os_pretty_name = None

    try:

        with open("/etc/os-release") as f:

            values = {}

            for line in f:

                line = line.strip()

                if not line or "=" not in line:
                    continue

                key, _, value = line.partition("=")
                values[key] = value.strip('"')

            os_id = values.get("ID")
            os_pretty_name = values.get("PRETTY_NAME")

    except OSError:
        pass

    return {
        "architecture": platform.machine(),
        "os_id": os_id,
        "os_pretty_name": os_pretty_name,
        "os_is_atomic": detect_os_is_atomic()
    }


def detect_system(disk_path: str = "/") -> SystemInfo:
    """
    Assembles every detect_*() piece into one SystemInfo. disk_path
    defaults to "/" here purely to drive the first tier
    recommendation, before the user's real media path is known - the
    CLI/TUI flow calls detect_disk() again directly against the real
    chosen path once it has one, rather than trusting this default
    for anything but that initial guess. disk_free_gb reports the
    larger of free space on the disk_path mount and the raw spare
    disk capacity available to provision, so a fresh machine with
    blank (unmounted) drives isn't mis-sized by the boot partition.
    """

    disk_info = detect_disk(disk_path)
    disk_info["disk_free_gb"] = max(
        disk_info["disk_free_gb"],
        provisionable_disk_gb(),
    )

    return SystemInfo(
        **detect_cpu(),
        **detect_memory(),
        **disk_info,
        gpu_vendor=detect_gpu(),
        **detect_docker(),
        **detect_os()
    )
