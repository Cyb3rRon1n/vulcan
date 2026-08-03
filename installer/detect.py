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
import platform
import shutil
import socket
import subprocess
from dataclasses import dataclass

import psutil

from installer.shell import run_ok


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


def detect_cpu() -> dict:

    cpu_model = None

    try:

        with open("/proc/cpuinfo") as f:

            for line in f:

                if line.startswith("model name"):

                    cpu_model = line.split(":", 1)[1].strip()
                    break

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


_REDUNDANT_MDADM_LEVELS = {"raid1", "raid4", "raid5", "raid6", "raid10"}


def detect_media_redundancy(media_path: str) -> dict:
    """
    Read-only: what's actually backing media_path, and whether it has
    any drive-level redundancy (mdadm/btrfs/ZFS) - never suggests or
    performs any storage action. RAID/partitioning is a deliberate
    pre-Vulcan step this project doesn't manage. Every field stays
    None when it can't be determined (missing tool, unresolvable
    path) - same "not present isn't an error" convention as every
    other detector here.

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
    Presence + vendor only, not driver-version validation - Phase 1
    only needs Light/Medium, and hardware transcoding is Heavy-tier
    scope. Intel has no equivalent "smi" tool, so its check is a
    weaker presence heuristic (a render device with neither NVIDIA
    nor AMD tooling present) rather than a real vendor query.
    """

    if shutil.which("nvidia-smi"):
        return "nvidia"

    if shutil.which("rocm-smi"):
        return "amd"

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
            "docker_compose_v2": False
        }

    return {
        "docker_installed": True,
        "docker_running": run_ok(["docker", "info"]),
        "docker_compose_v2": run_ok(["docker", "compose", "version"])
    }


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
        "os_pretty_name": os_pretty_name
    }


def detect_system(disk_path: str = "/") -> SystemInfo:
    """
    Assembles every detect_*() piece into one SystemInfo. disk_path
    defaults to "/" here purely to drive the first tier
    recommendation, before the user's real media path is known - the
    CLI/TUI flow calls detect_disk() again directly against the real
    chosen path once it has one, rather than trusting this default
    for anything but that initial guess.
    """

    return SystemInfo(
        **detect_cpu(),
        **detect_memory(),
        **detect_disk(disk_path),
        gpu_vendor=detect_gpu(),
        **detect_docker(),
        **detect_os()
    )
