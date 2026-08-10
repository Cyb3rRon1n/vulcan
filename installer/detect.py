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

check_drive_readiness() is the one function here that performs a real
(tiny, self-cleaning) write - a genuine writability probe, not just a
permission-bit read - since a mount can look writable (correct owner,
correct mode bits) and still reject every write (read-only remount
after a disk error, a full filesystem). Still read-only in effect: the
probe file is created and removed in the same call, nothing persists.
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


# Real, stable ARM Ltd. MIDR_EL1 implementer/part values (documented in
# ARM's own architecture reference manual, and the exact same table the
# Linux kernel itself and util-linux's lscpu carry) - the last-resort
# fallback below for a system with no /proc/device-tree/model at all
# (some ACPI-based ARM servers). Deliberately not exhaustive - just the
# implementers/cores a homelab box is actually likely to report.
_ARM_IMPLEMENTERS = {
    "0x41": "ARM",
    "0x42": "Broadcom",
    "0x43": "Cavium",
    "0x4e": "NVIDIA",
    "0x50": "APM",
    "0x51": "Qualcomm",
    "0x61": "Apple",
    "0xc0": "Ampere",
}

_ARM_CORTEX_PARTS = {
    "0xd03": "Cortex-A53",
    "0xd04": "Cortex-A35",
    "0xd05": "Cortex-A55",
    "0xd07": "Cortex-A57",
    "0xd08": "Cortex-A72",
    "0xd09": "Cortex-A73",
    "0xd0a": "Cortex-A75",
    "0xd0b": "Cortex-A76",
    "0xd0c": "Neoverse-N1",
    "0xd40": "Neoverse-V1",
    "0xd41": "Cortex-A78",
    "0xd44": "Cortex-X1",
    "0xd49": "Neoverse-N2",
}


def _read_device_tree_model() -> str | None:

    # /proc/device-tree/model is the real, standard way ARM Linux exposes
    # a human-readable board name (the DTB's own "model" property) -
    # present on virtually every ARM SBC (Raspberry Pi's own docs point at
    # this exact file), and a far more direct answer than decoding
    # implementer/part IDs into a chip name. The raw file is null-
    # terminated, so the trailing \x00 has to be stripped explicitly or
    # it survives into the returned string.
    try:

        with open("/proc/device-tree/model") as f:
            model = f.read().strip("\x00").strip()

        return model or None

    except OSError:
        return None


def _decode_arm_cpuinfo(implementer: str | None, part: str | None) -> str | None:

    # Last-resort fallback for an ARM system with no device tree at all -
    # decodes the real, stable implementer/part fields /proc/cpuinfo does
    # expose on every ARM64 kernel, even though there's no single human-
    # readable "model name" line the way x86 has. Degrades gracefully
    # through three tiers: a known core on a known vendor, a known vendor
    # with an unrecognized core, or neither - never silently drops the
    # raw IDs once we know they exist.
    if not implementer or not part:
        return None

    vendor = _ARM_IMPLEMENTERS.get(implementer.lower())
    core = _ARM_CORTEX_PARTS.get(part.lower()) if implementer.lower() == "0x41" else None

    if vendor and core:
        return f"{vendor} {core}"

    if vendor:
        return f"{vendor} (part {part})"

    return f"Unknown ARM CPU (implementer {implementer}, part {part})"


def detect_cpu() -> dict:

    cpu_model = None
    implementer = None
    part = None

    try:

        with open("/proc/cpuinfo") as f:

            for line in f:

                key, sep, value = line.partition(":")
                if not sep:
                    continue

                key = key.strip().lower()
                value = value.strip()

                if key == "model name" and cpu_model is None:
                    cpu_model = value
                elif key == "cpu implementer" and implementer is None:
                    implementer = value
                elif key == "cpu part" and part is None:
                    part = value

    except OSError:
        cpu_model = None

    if cpu_model is None:

        # x86's "model name" line simply doesn't exist on a real ARM64
        # kernel - fall back to the device tree's real board model, then
        # to decoding the real implementer/part IDs /proc/cpuinfo does
        # carry there instead. Neither fallback ever triggers on x86,
        # where "model name" is always present and this branch is never
        # reached.
        cpu_model = _read_device_tree_model() or _decode_arm_cpuinfo(implementer, part)

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


# Not a guess at how large the user's own media library will grow to -
# this project has no way to know that and it isn't Vulcan's call to
# make. It's a real, defensible floor for Vulcan's *own* footprint
# (container images across a full tier, plus config/database growth
# over time) - low_space flags "not even enough room to run the stack
# itself," not "not enough room for your movies."
_MIN_FREE_GB_FOR_STACK = 10.0


def check_drive_readiness(media_path: str) -> dict:
    """
    Real pre-install checks on the chosen media path, run once right
    after it's created - distinct from detect_media_redundancy() (is
    the drive protected against failure) and preflight.py's port
    checks (run later, right before the first `docker compose up`).
    Three real, independent signals, each catching a different class
    of "install proceeds, then fails or disappoints later":

    - writable: an actual write-then-delete probe, not a permission-
      bit read - the same gap detect_gpu() closed for tool presence
      vs. a working driver applies here too: correct ownership/mode
      bits don't guarantee a write succeeds (read-only remount after
      a disk error, a genuinely full filesystem).
    - low_space: free space against the real _MIN_FREE_GB_FOR_STACK
      floor above, not a guess at media-library size.
    - same_device_as_root: a plain os.stat().st_dev comparison against
      "/" (no new subprocess dependency, unlike detect_media_
      redundancy()'s findmnt use, which is solving a different
      problem) - flags the well-known homelab pitfall of a growing
      media library sharing the OS's own filesystem, advisory only,
      never a hard block.
    """

    result = {
        "path": media_path,
        "writable": False,
        "write_error": None,
        "free_gb": detect_disk(media_path)["disk_free_gb"],
        "low_space": True,
        "same_device_as_root": None,
    }

    result["low_space"] = result["free_gb"] < _MIN_FREE_GB_FOR_STACK

    probe = Path(media_path) / f".vulcan-write-test-{os.getpid()}"

    try:

        probe.write_text("vulcan")
        probe.unlink()
        result["writable"] = True

    except OSError as error:
        result["write_error"] = str(error)

    try:
        result["same_device_as_root"] = os.stat(media_path).st_dev == os.stat("/").st_dev
    except OSError:
        pass

    return result


def describe_drive_readiness(result: dict) -> list[str]:
    """
    Plain, unmarked-up status lines (✓/!/✗ prefixes only, no Rich
    markup) so both the CLI (which colors them via the prefix) and the
    TUI (which prints them as-is, matching how warnings are already
    rendered in ReviewScreen) can share one formatter - the same
    single-source-of-truth reasoning WEB_FACING_SERVICES already
    established, applied here to avoid a second, driftable copy of
    this wording.
    """

    lines = []

    if result["writable"]:
        lines.append(f"✓ {result['path']} is writable")
    else:
        lines.append(f"✗ {result['path']} is not writable: {result['write_error']}")

    if result["low_space"]:

        lines.append(
            f"! Only {result['free_gb']:.1f}GB free - Vulcan's own containers and "
            f"configs want at least {_MIN_FREE_GB_FOR_STACK:.0f}GB, separate from "
            "whatever space your actual media library needs"
        )

    else:
        lines.append(f"✓ {result['free_gb']:.1f}GB free")

    if result["same_device_as_root"] is True:

        lines.append(
            "! Media path is on the same filesystem as your OS drive - a growing "
            "library can starve the system of space. A separate mount is safer."
        )

    return lines


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
