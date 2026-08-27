"""
Install the system packages a Vulcan first run needs but a fresh OS may
not ship with: python3 (+ venv), whiptail (the TUI), and mdadm (software
RAID). The bash `install` bootstrap uses this same family mapping to get
python3 in place before any Python exists; ensure_system_deps() runs from
within the Python flow for everything else. Mirrors docker_setup.py's
shape - a per-distro install plan plus a run_privileged execution half,
same result-dict convention, same "not present isn't an error, but the
caller sees what's still missing" rule.
"""

import shutil

from installer.detect import detect_os
from installer.shell import run_privileged


def _family_for(os_id: str | None) -> str | None:

    if os_id in ("ubuntu", "debian", "raspbian", "linuxmint"):
        return "debian"

    if os_id in ("fedora", "rhel", "centos", "rocky", "almalinux"):
        return "fedora"

    if os_id == "arch":
        return "arch"

    return None


_INSTALL_CMD = {
    "debian": ["apt-get", "install", "-y"],
    "fedora": ["dnf", "install", "-y"],
    "arch": ["pacman", "-Sy", "--noconfirm"],
}

# tool -> {family -> [package, ...]}. whiptail's package is `newt` on
# Fedora and `libnewt` on Arch; python3 needs venv on Debian-family only.
_TOOL_PACKAGES = {
    "python3": {"debian": ["python3", "python3-venv"], "fedora": ["python3"], "arch": ["python"]},
    "whiptail": {"debian": ["whiptail"], "fedora": ["newt"], "arch": ["libnewt"]},
    "mdadm": {"debian": ["mdadm"], "fedora": ["mdadm"], "arch": ["mdadm"]},
}


def _tool_present(tool: str) -> bool:

    binary = "python3" if tool == "python3" else tool

    return shutil.which(binary) is not None


def ensure_system_deps(dry_run: bool = False) -> dict:
    """Install whatever of {python3, whiptail, mdadm} is missing and report
    what's still missing. dry_run only computes the plan (never runs) so the
    front ends can preview the install command before confirming."""

    result = {
        "success": True,
        "error": None,
        "already_present": [],
        "installed": [],
        "missing_after": [],
        "packages": [],
        "needs_reboot": False,
    }

    os_info = detect_os()
    family = _family_for(os_info.get("os_id"))
    os_is_atomic = os_info.get("os_is_atomic", False)

    to_install: list[str] = []

    for tool in ("python3", "whiptail", "mdadm"):

        if _tool_present(tool):
            result["already_present"].append(tool)
            continue

        if family is None:
            result["missing_after"].append(tool)
            continue

        to_install.extend(_TOOL_PACKAGES[tool][family])

    if not to_install:
        result["success"] = not result["missing_after"]
        return result
    result["packages"] = list(dict.fromkeys(to_install))

    if dry_run or family is None:
        return result

    if os_is_atomic and family == "fedora":

        ok = run_privileged(["rpm-ostree", "install", *result["packages"]])["success"]
        result["needs_reboot"] = ok

    else:

        ok = run_privileged([*_INSTALL_CMD[family], *result["packages"]])["success"]

    for tool in ("python3", "whiptail", "mdadm"):

        if _tool_present(tool):
            if tool not in result["already_present"]:
                result["installed"].append(tool)
        else:
            result["missing_after"].append(tool)

    result["success"] = not result["missing_after"]

    if result["missing_after"] and not ok:
        result["error"] = f"failed to install: {', '.join(result['packages'])}"

    return result
