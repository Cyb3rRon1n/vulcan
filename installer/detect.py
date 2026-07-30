"""
System resource detection: CPU cores/model, RAM, free disk on candidate
paths, GPU vendor presence, Docker status, architecture, OS. Pure and
read-only - nothing here installs or mutates anything. Every function
catches its own failure modes and returns None/False/a partial result
rather than raising, since a missing tool (no nvidia-smi, no docker)
just means "not present," not an error.
"""

import platform
import shutil
import subprocess
from dataclasses import dataclass

import psutil


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


def _run_ok(command: list[str]) -> bool:

    try:

        result = subprocess.run(
            command,
            capture_output=True,
            timeout=10
        )

        return result.returncode == 0

    except (subprocess.SubprocessError, OSError):
        return False


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
        "docker_running": _run_ok(["docker", "info"]),
        "docker_compose_v2": _run_ok(["docker", "compose", "version"])
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
