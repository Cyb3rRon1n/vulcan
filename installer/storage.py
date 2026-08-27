"""
Storage detection and provisioning *planning* - a direct owner request
to go beyond detect_media_redundancy()'s read-only reporting, for a
fresh machine that needs its drives actually set up before Vulcan has
anything to point at. Deliberately still doesn't execute anything in
this module - list_block_devices()/identify_protected_devices()/
plan_storage_layout()/describe_storage_plan() are all read-only or
pure; real execution (an actual mdadm/mkfs/mount run) is a separate,
later, more heavily-gated piece of work, not built here. This is the
one real reversal so far of this project's own "Vulcan never creates
or modifies storage itself" principle (see README.md/CLAUDE.md), and
even that reversal only covers *planning* what would run, not running
it - confirmed directly with the owner before writing any of this.
"""

import json
import os
import shlex
import subprocess

from installer.shell import run_privileged

# zram (compressed RAM-backed swap) and loop devices both report as a
# real lsblk "disk" but aren't real storage a media stack could ever
# live on - confirmed live against this project's own dev machine,
# which has a real zram0 swap device that would otherwise show up
# as a selectable target.
_EXCLUDED_NAME_PREFIXES = ("zram", "loop")

# mdadm's own real, documented constraints per RAID level - not
# invented here. RAID0 deliberately excluded from what Vulcan proposes
# by default (no redundancy at all, defeats the point of a "help me
# set up storage safely" feature), though nothing stops a user from
# requesting it explicitly via filesystem/level overrides later.
_MDADM_MIN_DEVICES = {
    "0": 2,
    "1": 2,
    "5": 3,
    "6": 4,
    "10": 4,
}


def list_block_devices() -> list[dict]:
    """
    Real, structured lsblk -J output - JSON, not text-column parsing,
    specifically so partition-to-parent-disk relationships (NVMe's
    "p1" suffix vs SATA/virtio's bare "1") never need hand-rolled
    string logic; lsblk's own "pkname" field already resolves it.
    Returns real disks only (excludes zram/loop) - each with its
    child partitions' mountpoints/filesystems attached, so "does this
    disk have data anywhere on it" is answerable without a second call.
    """

    try:

        result = subprocess.run(
            ["lsblk", "-J", "-o", "NAME,PATH,SIZE,TYPE,FSTYPE,MOUNTPOINT,MODEL,PKNAME"],
            capture_output=True,
            text=True,
            timeout=5
        )

    except (subprocess.SubprocessError, OSError):
        return []

    if result.returncode != 0:
        return []

    try:
        parsed = json.loads(result.stdout)
    except json.JSONDecodeError:
        return []

    devices = []

    for device in parsed.get("blockdevices", []):

        if device.get("type") != "disk":
            continue

        if device.get("name", "").startswith(_EXCLUDED_NAME_PREFIXES):
            continue

        devices.append(device)

    return devices


def identify_protected_devices() -> set[str]:
    """
    The hard safety rule, not just a UI warning - resolves which real
    physical disk(s) back /, /boot, and /boot/efi and returns their
    device paths. plan_storage_layout() refuses to include any device
    in this set even if explicitly requested; there is no override.

    Walks findmnt's own real source device (the same [/subvol]-suffix
    handling detect_media_redundancy() already established for btrfs
    subvolumes - confirmed live: this machine's real root reports
    "/dev/nvme0n1p3[/root]") back to its parent disk via
    list_block_devices()'s own pkname-linked tree, rather than
    re-deriving NVMe-vs-SATA partition-suffix logic a second time.
    """

    devices = list_block_devices()
    protected: set[str] = set()

    partition_to_disk: dict[str, str] = {}

    for disk in devices:
        for child in disk.get("children", []) or []:
            partition_to_disk[child["path"]] = disk["path"]

    for mountpoint in ("/", "/boot", "/boot/efi"):

        try:

            result = subprocess.run(
                ["findmnt", "-no", "SOURCE", "-T", mountpoint],
                capture_output=True,
                text=True,
                timeout=5
            )

        except (subprocess.SubprocessError, OSError):
            continue

        if result.returncode != 0 or not result.stdout.strip():
            continue

        source = result.stdout.strip().split("[", 1)[0]

        if source in partition_to_disk:
            protected.add(partition_to_disk[source])
        else:
            # The mountpoint's own source *is* a whole disk (no
            # partition table at all) - a real, if unusual, case.
            protected.add(source)

    return protected


def list_blank_unprotected_devices() -> list[dict]:
    """
    The real disks that are genuinely spare: not backing / or /boot,
    with no filesystem of their own and no partition table at all -
    i.e. safe candidates for a storage plan without any erasure. This
    is what the install flow uses to decide whether offering media
    storage setup even makes sense (a fresh machine with four empty
    drives vs. one that's already fully provisioned). Read-only.
    """

    protected = identify_protected_devices()
    candidates = []

    for disk in list_block_devices():

        if disk["path"] in protected:
            continue

        if disk.get("fstype"):
            continue

        if disk.get("children"):
            continue

        candidates.append(disk)

    return candidates


def list_unprotected_devices() -> list[dict]:
    """
    All disks NOT backing / or /boot - includes drives with existing
    filesystems/partitions that the user may choose to wipe and repurpose.
    Used for the interactive storage setup where the user explicitly
    selects drives to provision as media storage. Read-only.
    """

    protected = identify_protected_devices()
    candidates = []

    for disk in list_block_devices():

        if disk["path"] in protected:
            continue

        candidates.append(disk)

    return candidates


def _mdadm_level_for_device_count(count: int) -> str:
    """
    Simple, honest default, not an attempt to guess the "best" level:
    2 devices -> RAID1 (mirroring, the only real option mdadm supports
    at exactly 2 devices for redundancy); 3+ devices -> RAID5 (one-
    drive fault tolerance, the common default for that range) - not
    RAID6/10, which need a real, separate choice this function doesn't
    try to guess on the caller's behalf. Pass raid_level explicitly to
    plan_storage_layout() to override.
    """

    return "1" if count == 2 else "5"


def _raid_usable_drive_equivalents(level: str, count: int) -> int:
    """
    How many drives' worth of usable capacity a RAID level leaves you
    with on `count` devices - the honest math behind the picker's
    "X of N drives" descriptors, not a guessed percentage. RAID1
    mirrors two drives into one usable; RAID5 spends one drive on
    parity; RAID6 spends two; RAID10 mirrors pairs so half the drives
    are usable.
    """

    if level == "0":
        return count

    if level == "1":
        return 1

    if level == "5":
        return max(count - 1, 0)

    if level == "6":
        return max(count - 2, 0)

    if level == "10":
        return count // 2

    return count


def _raid_level_options(count: int) -> list[dict]:
    """
    The real RAID choices worth offering for `count` devices, each with
    honest tradeoff descriptors - the picker's source of truth. Single
    device: no RAID makes sense, so nothing to choose. 2+ devices:
    RAID0 (striping, full capacity, no redundancy) is always offered
    as an explicit opt-in. Two devices additionally offer RAID1
    (mirror, the recommended redundancy pick). 3+ devices: RAID5 is
    the recommended default, RAID6 and RAID10 (even counts only) are
    the honest alternatives - deliberately not guessing which is
    "best", since that genuinely depends on the user's priorities
    (capacity vs. fault tolerance vs. rebuild speed).
    """

    options = []

    if count < 2:
        return options

    # RAID0 (striping) is always a valid choice on 2+ devices - full
    # capacity, no redundancy. It's opt-in, never the default: the whole
    # point of provisioning media storage here is data that survives a
    # drive failure, so redundant levels stay the recommended picks.
    options.append({
        "level": "0",
        "usable": _raid_usable_drive_equivalents("0", count),
        "total": count,
        "recommended": False,
    })

    if count == 2:
        return [*options, {
            "level": "1",
            "usable": 1,
            "total": count,
            "recommended": True,
        }]

    candidates = [
        ("5", count >= _MDADM_MIN_DEVICES["5"]),
        ("6", count >= _MDADM_MIN_DEVICES["6"]),
        ("10", count >= _MDADM_MIN_DEVICES["10"] and count % 2 == 0),
    ]

    for level, available in candidates:

        if not available:
            continue

        options.append({
            "level": level,
            "usable": _raid_usable_drive_equivalents(level, count),
            "total": count,
            "recommended": level == "5",
        })

    return options


def describe_raid_option(option: dict) -> str:
    """
    The one shared renderer for a RAID picker option - the honest
    tradeoffs as plain text, used identically by the CLI prompt and the
    whiptail menu so neither drifts from the other. "X of N drives"
    capacity, not a percentage, so the math stays true regardless of
    actual drive size.
    """

    level = option["level"]
    usable = option["usable"]
    total = option["total"]

    tradeoffs = {
        "0": f"all {total} drives combined, full capacity - no redundancy, one drive failure loses everything",
        "1": "mirrors 2 drives into 1 - slow, but the only redundancy option at 2 drives",
        "5": f"~{usable} of {total} drives usable, survives 1 drive failure - read-friendly, slower writes",
        "6": f"~{usable} of {total} drives usable, survives 2 drive failures - slowest writes",
        "10": f"~{usable} of {total} drives usable, survives 1 drive failure - fastest reads/writes and fastest rebuilds",
    }

    label = f"RAID{level}"

    if option.get("recommended"):
        label = f"{label} (recommended)"

    return f"{label} - {tradeoffs.get(level, '')}"


def device_tree_text(device_path: str) -> str | None:
    """
    Real lsblk output for the newly-provisioned device - the post-apply
    "here's what you actually have now" view the CLI/offer/menu print
    after a successful run. For a RAID array this shows the md device
    with its member drives beneath it; for a single device, the one
    formatted disk. Read-only; None when lsblk can't see the device.
    """

    try:

        result = subprocess.run(
            ["lsblk", "-o", "NAME,SIZE,TYPE,FSTYPE,MOUNTPOINT", device_path],
            capture_output=True,
            text=True,
            timeout=5
        )

    except (subprocess.SubprocessError, OSError):
        return None

    if result.returncode != 0 or not result.stdout.strip():
        return None

    return result.stdout


def _provision_owner() -> str:
    """The uid:gid the provisioned media volume should be owned by - the
    invoking user (SUDO_UID/SUDO_GID when the CLI is run under sudo,
    else the process's own euid/egid). A fresh mkfs root is root:root
    mode 755, which would otherwise make write_stack()'s media/
    directory scaffolding fail with EACCES for the unprivileged user
    that actually runs the stack - the real bug this chown exists to
    fix."""

    uid = int(os.environ.get("SUDO_UID") or os.geteuid())
    gid = int(os.environ.get("SUDO_GID") or os.getegid())
    return f"{uid}:{gid}"


def plan_storage_layout(
    device_paths: list[str],
    mount_point: str,
    filesystem: str = "ext4",
    raid_level: str | None = None,
    confirm_wipe: bool = False
) -> dict:
    """
    Pure - computes the real command sequence that would provision
    device_paths as a single mounted volume at mount_point, never runs
    anything. One device -> format + mount directly. 2+ devices ->
    mdadm RAID first (level chosen by _mdadm_level_for_device_count()
    unless raid_level is given explicitly), then format + mount the
    resulting /dev/mdX. The returned "commands" list is the real argv
    a future execution step would run unchanged - not a simplified
    preview that would need regenerating later.
    """

    protected = identify_protected_devices()
    already_targeted_protected = sorted(set(device_paths) & protected)

    if already_targeted_protected:

        return {
            "target_devices": device_paths,
            "commands": [],
            "warnings": [],
            "already_has_data": {},
            "mount_point": mount_point,
            "target_device": None,
            "fstab_line": None,
            "error": (
                "Refusing to plan against protected device(s) "
                f"{', '.join(already_targeted_protected)} - currently backing / or /boot."
            ),
        }

    devices_by_path = {
        disk["path"]: disk for disk in list_block_devices()
    }

    already_has_data = {}
    warnings = []

    for path in device_paths:

        disk = devices_by_path.get(path)

        if disk is None:
            warnings.append(f"{path} was not found by lsblk - it may not exist on this machine.")
            already_has_data[path] = None
            continue

        has_fstype = bool(disk.get("fstype"))
        has_partitions = bool(disk.get("children"))
        already_has_data[path] = has_fstype or has_partitions

        if already_has_data[path]:
            warnings.append(
                f"{path} already has a filesystem or partition table - this plan would erase it."
            )

    commands: list[list[str]] = []
    target_device = device_paths[0] if len(device_paths) == 1 else "/dev/md0"

    if len(device_paths) > 1:

        level = raid_level or _mdadm_level_for_device_count(len(device_paths))
        valid_levels = [o["level"] for o in _raid_level_options(len(device_paths))]

        if raid_level is not None and raid_level not in valid_levels:

            return {
                "target_devices": device_paths,
                "commands": [],
                "warnings": warnings,
                "already_has_data": already_has_data,
                "mount_point": mount_point,
                "target_device": None,
                "fstab_line": None,
                "error": (
                    f"RAID{raid_level} isn't a valid choice for {len(device_paths)} "
                    f"devices. Valid: {', '.join(f'RAID{v}' for v in valid_levels)}"
                    f"{' (RAID10 needs an even number of devices)' if raid_level == '10' else ''}."
                ),
            }

        min_devices = _MDADM_MIN_DEVICES.get(level, 2)

        if len(device_paths) < min_devices:

            return {
                "target_devices": device_paths,
                "commands": [],
                "warnings": warnings,
                "already_has_data": already_has_data,
                "mount_point": mount_point,
                "target_device": None,
                "fstab_line": None,
                "error": (
                    f"RAID{level} needs at least {min_devices} devices, "
                    f"only {len(device_paths)} given."
                ),
            }

        if confirm_wipe:
            for path in device_paths:
                if already_has_data.get(path):
                    commands.append(["wipefs", "-a", path])

        commands.append(
            ["mdadm", "--create", "/dev/md0", f"--level={level}",
             f"--raid-devices={len(device_paths)}", *device_paths]
        )

    commands.append([f"mkfs.{filesystem}", target_device])
    commands.append(["mkdir", "-p", mount_point])
    commands.append(["mount", target_device, mount_point])

    owner = _provision_owner()
    if owner != "0:0":
        commands.append(["chown", owner, mount_point])

    fs_passno = "0" if filesystem in ("btrfs", "xfs") else "2"
    fstab_line = f"{target_device} {mount_point} {filesystem} defaults 0 {fs_passno}"
    commands.append(["sh", "-c", f"echo '{fstab_line}' >> /etc/fstab"])

    return {
        "target_devices": device_paths,
        "commands": commands,
        "warnings": warnings,
        "already_has_data": already_has_data,
        "mount_point": mount_point,
        "target_device": target_device,
        "fstab_line": fstab_line,
        "error": None,
    }


def describe_storage_plan(plan: dict, devices: list[dict] | None = None) -> str:
    """
    The one shared human-readable renderer for a plan - CLI calls this
    today; a future TUI would call the identical function rather than
    building a second copy, the same "single source of truth for
    display text" role format_port_conflicts() already plays for port
    conflicts.
    """

    if plan.get("error"):
        return f"Can't plan this layout: {plan['error']}"

    devices = devices if devices is not None else list_block_devices()
    devices_by_path = {disk["path"]: disk for disk in devices}

    lines = []

    for path in plan["target_devices"]:

        disk = devices_by_path.get(path)
        size = disk["size"] if disk else "unknown size"
        model = f" ({disk['model']})" if disk and disk.get("model") else ""

        note = " - ALREADY HAS DATA, WOULD BE ERASED" if plan["already_has_data"].get(path) else ""
        lines.append(f"  {path}  {size}{model}{note}")

    lines.append("")
    lines.append("Commands that WOULD run (nothing has been executed):")

    for i, command in enumerate(plan["commands"], start=1):
        lines.append(f"  {i}. {' '.join(command)}")

    for warning in plan["warnings"]:
        lines.append(f"! {warning}")

    lines.append("")
    lines.append(
        "Recommended: keep at least 10-15% of usable capacity free after this plan - "
        "transcoding caches, download-client temp files, and RAID/filesystem overhead "
        "all eat into headroom you'd otherwise count as free space."
    )

    return "\n".join(lines)


def _findmnt_source(mount_point: str) -> str | None:
    """
    The real device (or md array) currently backing mount_point, or None
    when nothing is mounted there / findmnt is unavailable. Strips a
    btrfs [/subvol] suffix the same way identify_protected_devices() and
    detect_media_redundancy() already do, so "/dev/md0[/media]" and
    "/dev/md0" compare equal.
    """

    try:

        result = subprocess.run(
            ["findmnt", "-no", "SOURCE", "-T", mount_point],
            capture_output=True,
            text=True,
            timeout=5
        )

    except (subprocess.SubprocessError, OSError):
        return None

    if result.returncode != 0 or not result.stdout.strip():
        return None

    return result.stdout.strip().split("[", 1)[0]


def _lsblk_fstype(device_path: str) -> str | None:
    """
    The filesystem on device_path ("" meaning none yet), or None when
    lsblk can't see the device at all. apply_storage_layout() uses this
    to tell "needs formatting" from "already formatted" without ever
    probing the device contents itself.
    """

    try:

        result = subprocess.run(
            ["lsblk", "-no", "FSTYPE", device_path],
            capture_output=True,
            text=True,
            timeout=5
        )

    except (subprocess.SubprocessError, OSError):
        return None

    if result.returncode != 0:
        return None

    return result.stdout.strip()


def _md_devices() -> set[str]:
    """
    The set of live md array names (e.g. {"md0"}) from /proc/mdstat.
    apply_storage_layout() checks this before ever running `mdadm
    --create`, so a re-run on a machine where the array already exists
    skips creation instead of trying to create it a second time.
    """

    try:

        with open("/proc/mdstat", encoding="utf-8") as handle:
            content = handle.read()

    except OSError:
        return set()

    devices: set[str] = set()

    for line in content.splitlines():
        if line.startswith("md"):
            devices.add(line.split(" ", 1)[0])

    return devices


def _fstab_has_line(fstab_line: str) -> bool:
    """
    Whether /etc/fstab already carries this exact line - read-only, so
    apply_storage_layout() can skip appending a duplicate on a re-run.
    """

    try:

        with open("/etc/fstab", encoding="utf-8") as handle:
            return fstab_line in handle.read()

    except OSError:
        return False


def apply_storage_layout(plan: dict, confirm_wipe: bool = False) -> dict:
    """
    Executes a plan from plan_storage_layout() - the real mdadm/mkfs/
    mount/fstab run the roadmap's "Real storage-provisioning execution
    doesn't exist yet" entry has always pointed at. Deliberately NOT a
    blind "run every command in plan['commands']" loop: each destructive
    step is re-checked against the machine's real current state first,
    so a re-run after a partial/failed first attempt resumes instead of
    destroying, and a re-run against an already-provisioned mount is a
    no-op. Returns the same plain result dict shape every other
    engine-layer function here uses.

    Safety gates, all engine-side (not just front-end warnings):
      - a plan that already carries an error is refused outright;
      - a target device that has a filesystem or partition table (or
        wasn't found by lsblk at all) is refused unless confirm_wipe is
        explicitly set - the typed-device-name confirmation in the CLI
        is what produces that flag, never an unguarded default;
      - a mount point already held by a *different* device is refused -
        apply_storage_layout() never unmounts something else to steal
        its mount point.

    Idempotency, checked against real state (not against whether the
    plan was generated fresh):
      - mount point already backed by the plan's own target device ->
        success with already_provisioned=True, zero commands run;
      - the md array already exists (in /proc/mdstat) -> mdadm --create
        is skipped, the rest proceeds;
      - the target already has a filesystem -> mkfs is skipped, the
        rest proceeds;
      - /etc/fstab already has the line -> the append is skipped.
    """

    if plan.get("error"):
        return {
            "success": False,
            "error": plan["error"],
            "already_provisioned": False,
            "ran": [],
            "skipped": [],
        }

    if not plan.get("commands"):
        return {
            "success": False,
            "error": "Nothing to execute for this plan.",
            "already_provisioned": False,
            "ran": [],
            "skipped": [],
        }

    already_has_data = plan.get("already_has_data", {})
    not_blank = [
        path for path, has_data in already_has_data.items()
        if has_data is True
    ]
    not_found = [
        path for path, has_data in already_has_data.items()
        if has_data is None
    ]

    if not_found and not confirm_wipe:

        return {
            "success": False,
            "error": (
                f"Can't apply: {', '.join(not_found)} wasn't found by lsblk. "
                "Double-check the device paths - nothing has been touched."
            ),
            "already_provisioned": False,
            "ran": [],
            "skipped": [],
        }

    if not_blank and not confirm_wipe:

        return {
            "success": False,
            "error": (
                f"Refusing to apply: {', '.join(not_blank)} already has a "
                "filesystem or partition table - this plan would erase it. "
                "Re-run with --confirm-wipe to deliberately destroy that data."
            ),
            "already_provisioned": False,
            "ran": [],
            "skipped": [],
        }

    target_device = plan["target_device"]
    mount_point = plan["mount_point"]

    current_source = _findmnt_source(mount_point)

    if current_source == target_device:

        chown = ["chown", _provision_owner(), mount_point]
        result = run_privileged(chown)

        if not result["success"]:
            return {
                "success": False,
                "error": f"Failed fixing ownership on {mount_point}: {result['error']}",
                "already_provisioned": False,
                "ran": [],
                "skipped": ["already mounted at target"],
            }

        return {
            "success": True,
            "error": None,
            "already_provisioned": True,
            "ran": [" ".join(chown)],
            "skipped": ["already mounted at target"],
        }

    if current_source is not None:

        return {
            "success": False,
            "error": (
                f"{mount_point} is already mounted from {current_source}, "
                f"not {target_device}. Refusing to unmount it - free it "
                "manually first."
            ),
            "already_provisioned": False,
            "ran": [],
            "skipped": [],
        }

    is_mdadm_plan = plan["commands"][0][0] == "mdadm"
    array_exists = is_mdadm_plan and target_device.split("/")[-1] in _md_devices()

    target_fstype = _lsblk_fstype(target_device)
    target_has_fs = bool(target_fstype)
    fstab_present = _fstab_has_line(plan.get("fstab_line") or "")

    commands_to_run: list[list[str]] = []
    skipped: list[str] = []

    for command in plan["commands"]:

        if command[0] == "mdadm" and array_exists:
            skipped.append(f"{target_device} already exists - skipping array creation")
            continue

        if command[0].startswith("mkfs.") and target_has_fs:
            skipped.append(f"{target_device} already has a filesystem - skipping format")
            continue

        if command[0] == "sh" and fstab_present:
            skipped.append("/etc/fstab already has this mount - skipping append")
            continue

        commands_to_run.append(command)

    ran: list[str] = []

    for command in commands_to_run:

        result = run_privileged(command)

        if not result["success"]:

            return {
                "success": False,
                "error": f"Failed running {' '.join(command)}: {result['error']}",
                "already_provisioned": False,
                "ran": ran,
                "skipped": skipped,
            }

        ran.append(" ".join(command))

    return {
        "success": True,
        "error": None,
        "already_provisioned": False,
        "ran": ran,
        "skipped": skipped,
    }


def _mdadm_export_field(array_path: str) -> list[str]:
    """
    Real member device paths for a live md array, via mdadm's own
    --export mode (MD_DEVICE_devN_DEV=/dev/sdX lines) - the officially
    documented machine-parseable interface, not scraped from --detail's
    human table formatting which varies by mdadm version. Empty list
    when the array doesn't exist or mdadm can't be run.
    """

    try:

        result = subprocess.run(
            ["mdadm", "--detail", "--export", array_path],
            capture_output=True,
            text=True,
            timeout=5
        )

    except (subprocess.SubprocessError, OSError):
        return []

    if result.returncode != 0:
        return []

    members = []

    for line in result.stdout.splitlines():

        key, _, value = line.partition("=")

        if key.startswith("MD_DEVICE_") and key.endswith("_DEV"):
            members.append(value)

    return sorted(members)


def _fstab_line_for_mount_point(mount_point: str) -> str | None:
    """
    The real, currently-present /etc/fstab line for mount_point (its
    second whitespace-separated field), or None when there isn't one.
    plan_storage_teardown() uses the real line text rather than
    reconstructing it, so removal matches whatever's actually on disk -
    including a line a user hand-edited after Vulcan wrote it.
    """

    try:

        with open("/etc/fstab", encoding="utf-8") as handle:
            lines = handle.readlines()

    except OSError:
        return None

    for line in lines:

        stripped = line.strip()

        if not stripped or stripped.startswith("#"):
            continue

        fields = stripped.split()

        if len(fields) >= 2 and fields[1] == mount_point:
            return line.rstrip("\n")

    return None


def plan_storage_teardown(mount_point: str) -> dict:
    """
    Pure - computes the real command sequence that would reverse
    whatever plan_storage_layout()/apply_storage_layout() provisioned
    at mount_point: unmount, stop the RAID array and zero every
    member's superblock (if it's a RAID array), wipefs the array and
    each member, then remove the real /etc/fstab line - so
    list_blank_unprotected_devices() sees the member device(s) as blank
    again afterward. Never runs anything - apply_storage_teardown() is
    the execution half, same split as plan_storage_layout()/
    apply_storage_layout(). The one real reversal Vulcan's storage
    module already makes of "never touch storage itself" (see this
    module's own top docstring) already covers provisioning; this is
    the same reversal applied to un-provisioning, not a new precedent.
    """

    target_device = _findmnt_source(mount_point)

    if target_device is None:

        return {
            "mount_point": mount_point,
            "target_device": None,
            "member_devices": [],
            "is_raid": False,
            "commands": [],
            "fstab_line": None,
            "error": f"Nothing is mounted at {mount_point} - nothing to tear down.",
        }

    protected = identify_protected_devices()

    if target_device in protected:

        return {
            "mount_point": mount_point,
            "target_device": target_device,
            "member_devices": [],
            "is_raid": False,
            "commands": [],
            "fstab_line": None,
            "error": (
                f"Refusing to plan a teardown of {target_device} - "
                "it's backing / or /boot."
            ),
        }

    is_raid = target_device.split("/")[-1] in _md_devices()
    member_devices = _mdadm_export_field(target_device) if is_raid else []

    commands: list[list[str]] = [["umount", mount_point]]

    if is_raid:

        commands.append(["mdadm", "--stop", target_device])

        for member in member_devices:
            commands.append(["mdadm", "--zero-superblock", member])

    commands.append(["wipefs", "-a", target_device])

    for member in member_devices:
        commands.append(["wipefs", "-a", member])

    fstab_line = _fstab_line_for_mount_point(mount_point)

    if fstab_line:
        commands.append(
            ["sh", "-c",
             f"grep -vF {shlex.quote(fstab_line)} /etc/fstab > /etc/fstab.vulcan-tmp "
             "&& mv /etc/fstab.vulcan-tmp /etc/fstab"]
        )

    return {
        "mount_point": mount_point,
        "target_device": target_device,
        "member_devices": member_devices,
        "is_raid": is_raid,
        "commands": commands,
        "fstab_line": fstab_line,
        "error": None,
    }


def describe_storage_teardown(plan: dict) -> str:
    """
    The one shared human-readable renderer for a teardown plan - same
    role describe_storage_plan() plays for a provisioning plan, so the
    CLI and whiptail menu never drift from each other on what a
    teardown is actually about to do.
    """

    if plan.get("error"):
        return f"Can't plan this teardown: {plan['error']}"

    lines = [f"Currently mounted: {plan['target_device']} at {plan['mount_point']}"]

    if plan["is_raid"]:
        lines.append(f"RAID array with {len(plan['member_devices'])} member(s):")
        lines.extend(f"  {member}" for member in plan["member_devices"])

    lines.append("")
    lines.append("Commands that WOULD run (nothing has been executed):")

    for i, command in enumerate(plan["commands"], start=1):
        lines.append(f"  {i}. {' '.join(command)}")

    lines.append("")
    lines.append(
        "This permanently destroys every filesystem/RAID signature on "
        f"{plan['target_device']}"
        + (" and its member devices" if plan["is_raid"] else "")
        + " - there is no undo."
    )

    return "\n".join(lines)


def apply_storage_teardown(plan: dict, confirm_wipe: bool = False) -> dict:
    """
    Executes a plan from plan_storage_teardown() - the real umount/
    mdadm/wipefs/fstab run that reverses whatever plan_storage_layout()/
    apply_storage_layout() provisioned. Mirrors apply_storage_layout()'s
    own safety/idempotency model, just in reverse.

    Safety gates, all engine-side (never just a front-end warning):
      - a plan that already carries an error is refused outright;
      - real execution only happens with confirm_wipe=True - the CLI's
        own typed-confirmation flow is what sets this, never a silent
        default, the identical gate apply_storage_layout() already uses
        for its own destructive path.

    Idempotency, checked against real state (not against whether the
    plan was generated fresh) so a re-run after a partial/failed first
    attempt resumes instead of erroring out:
      - mount_point already unmounted -> the umount step is skipped;
      - the md array is already stopped (not in /proc/mdstat) -> the
        mdadm --stop step is skipped - --zero-superblock and wipefs -a
        are both real no-ops against an already-wiped device, so they
        always run rather than needing their own skip check.
    """

    if plan.get("error"):
        return {
            "success": False,
            "error": plan["error"],
            "ran": [],
            "skipped": [],
        }

    if not plan.get("commands"):
        return {
            "success": False,
            "error": "Nothing to execute for this plan.",
            "ran": [],
            "skipped": [],
        }

    if not confirm_wipe:

        return {
            "success": False,
            "error": (
                "Refusing to tear down storage without explicit confirmation. "
                "Re-run with --confirm-wipe to deliberately erase "
                f"{plan['target_device']}"
                + (" and its member device(s)." if plan["is_raid"] else ".")
            ),
            "ran": [],
            "skipped": [],
        }

    mount_point = plan["mount_point"]
    target_device = plan["target_device"]

    already_unmounted = _findmnt_source(mount_point) is None
    array_already_stopped = target_device.split("/")[-1] not in _md_devices()

    commands_to_run: list[list[str]] = []
    skipped: list[str] = []

    for command in plan["commands"]:

        if command[0] == "umount" and already_unmounted:
            skipped.append(f"{mount_point} is already unmounted")
            continue

        if command[0] == "mdadm" and command[1] == "--stop" and array_already_stopped:
            skipped.append(f"{target_device} is already stopped")
            continue

        commands_to_run.append(command)

    ran: list[str] = []

    for command in commands_to_run:

        result = run_privileged(command)

        if not result["success"]:

            return {
                "success": False,
                "error": f"Failed running {' '.join(command)}: {result['error']}",
                "ran": ran,
                "skipped": skipped,
            }

        ran.append(" ".join(command))

    return {
        "success": True,
        "error": None,
        "ran": ran,
        "skipped": skipped,
    }
