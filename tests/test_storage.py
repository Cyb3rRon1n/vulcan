import json
from unittest.mock import MagicMock, patch

from installer.storage import (
    apply_storage_layout,
    describe_storage_plan,
    identify_protected_devices,
    list_blank_unprotected_devices,
    list_block_devices,
    plan_storage_layout,
)

FAKE_LSBLK_OUTPUT = {
    "blockdevices": [
        {
            "name": "zram0", "path": "/dev/zram0", "size": "8G", "type": "disk",
            "fstype": "swap", "mountpoint": "[SWAP]", "model": None, "pkname": None
        },
        {
            "name": "sda", "path": "/dev/sda", "size": "500G", "type": "disk",
            "fstype": None, "mountpoint": None, "model": "Samsung SSD", "pkname": None,
            "children": [
                {
                    "name": "sda1", "path": "/dev/sda1", "size": "500G", "type": "part",
                    "fstype": "ext4", "mountpoint": "/", "model": None, "pkname": "sda"
                }
            ]
        },
        {
            "name": "sdb", "path": "/dev/sdb", "size": "4T", "type": "disk",
            "fstype": None, "mountpoint": None, "model": "WD Red", "pkname": None
        },
        {
            "name": "sdc", "path": "/dev/sdc", "size": "4T", "type": "disk",
            "fstype": None, "mountpoint": None, "model": "WD Red", "pkname": None
        }
    ]
}


def _mock_lsblk(returncode: int = 0, stdout: str | None = None) -> MagicMock:

    return MagicMock(returncode=returncode, stdout=stdout or json.dumps(FAKE_LSBLK_OUTPUT))


def _mock_findmnt_root() -> MagicMock:

    return MagicMock(returncode=0, stdout="/dev/sda1\n")


def _mock_findmnt_missing() -> MagicMock:

    return MagicMock(returncode=1, stdout="")


def test_list_block_devices_excludes_zram_and_returns_real_disks():

    with patch("installer.storage.subprocess.run", return_value=_mock_lsblk()):
        devices = list_block_devices()

    assert [d["path"] for d in devices] == ["/dev/sda", "/dev/sdb", "/dev/sdc"]


def test_list_block_devices_lsblk_failure_returns_empty():

    with patch("installer.storage.subprocess.run", return_value=_mock_lsblk(returncode=1)):
        devices = list_block_devices()

    assert devices == []


def test_list_block_devices_invalid_json_returns_empty():

    with patch("installer.storage.subprocess.run", return_value=_mock_lsblk(stdout="not json")):
        devices = list_block_devices()

    assert devices == []


def test_list_block_devices_subprocess_raises_returns_empty():

    with patch("installer.storage.subprocess.run", side_effect=OSError("lsblk not found")):
        devices = list_block_devices()

    assert devices == []


def _dispatch(args, **kwargs):

    if args[0] == "lsblk":
        return _mock_lsblk()

    if args[0] == "findmnt":

        target = args[-1]

        if target == "/":
            return _mock_findmnt_root()

        return _mock_findmnt_missing()

    raise AssertionError(f"unexpected call: {args}")


def test_identify_protected_devices_resolves_root_to_parent_disk():

    with patch("installer.storage.subprocess.run", side_effect=_dispatch):
        protected = identify_protected_devices()

    assert protected == {"/dev/sda"}


def test_identify_protected_devices_no_mountpoints_found_returns_empty():

    def dispatch(args, **kwargs):

        if args[0] == "lsblk":
            return _mock_lsblk()

        return _mock_findmnt_missing()

    with patch("installer.storage.subprocess.run", side_effect=dispatch):
        protected = identify_protected_devices()

    assert protected == set()


def test_plan_storage_layout_refuses_protected_device():

    with patch("installer.storage.subprocess.run", side_effect=_dispatch):
        plan = plan_storage_layout(["/dev/sda"], "/mnt/media")

    assert plan["error"] is not None
    assert "protected" in plan["error"]
    assert plan["commands"] == []


def test_plan_storage_layout_single_device_no_raid():

    with patch("installer.storage.subprocess.run", side_effect=_dispatch):
        plan = plan_storage_layout(["/dev/sdb"], "/mnt/media")

    assert plan["error"] is None
    assert plan["commands"] == [
        ["mkfs.ext4", "/dev/sdb"],
        ["mkdir", "-p", "/mnt/media"],
        ["mount", "/dev/sdb", "/mnt/media"],
        ["sh", "-c", "echo '/dev/sdb /mnt/media ext4 defaults 0 2' >> /etc/fstab"],
    ]


def test_plan_storage_layout_two_devices_defaults_to_raid1():

    with patch("installer.storage.subprocess.run", side_effect=_dispatch):
        plan = plan_storage_layout(["/dev/sdb", "/dev/sdc"], "/mnt/media")

    assert plan["error"] is None
    assert plan["commands"][0] == [
        "mdadm", "--create", "/dev/md0", "--level=1", "--raid-devices=2", "/dev/sdb", "/dev/sdc"
    ]
    assert plan["commands"][1] == ["mkfs.ext4", "/dev/md0"]
    assert plan["commands"][3] == ["mount", "/dev/md0", "/mnt/media"]


def test_plan_storage_layout_explicit_raid_level_honored():

    with patch("installer.storage.subprocess.run", side_effect=_dispatch):
        plan = plan_storage_layout(
            ["/dev/sdb", "/dev/sdc"], "/mnt/media", raid_level="1"
        )

    assert plan["commands"][0][3] == "--level=1"


def test_plan_storage_layout_raid_level_below_minimum_devices_errors():

    with patch("installer.storage.subprocess.run", side_effect=_dispatch):
        plan = plan_storage_layout(["/dev/sdb", "/dev/sdc"], "/mnt/media", raid_level="5")

    assert plan["error"] is not None
    assert "at least 3 devices" in plan["error"]


def test_plan_storage_layout_flags_device_with_existing_data():

    with patch("installer.storage.subprocess.run", side_effect=_dispatch):
        plan = plan_storage_layout(["/dev/sda"], "/mnt/media")

    # /dev/sda is protected, so this hits the protected-device refusal
    # first - a separate test below covers the "has data but isn't
    # protected" case using a device with a real fstype of its own.
    assert plan["error"] is not None


def test_plan_storage_layout_flags_unprotected_device_with_existing_filesystem():

    fake_output = {
        "blockdevices": [
            {
                "name": "sdd", "path": "/dev/sdd", "size": "2T", "type": "disk",
                "fstype": "ext4", "mountpoint": None, "model": None, "pkname": None
            }
        ]
    }

    def dispatch(args, **kwargs):

        if args[0] == "lsblk":
            return _mock_lsblk(stdout=json.dumps(fake_output))

        return _mock_findmnt_missing()

    with patch("installer.storage.subprocess.run", side_effect=dispatch):
        plan = plan_storage_layout(["/dev/sdd"], "/mnt/media")

    assert plan["error"] is None
    assert plan["already_has_data"]["/dev/sdd"] is True
    assert any("already has a filesystem" in w for w in plan["warnings"])


def test_plan_storage_layout_unknown_device_warns_but_still_plans():

    with patch("installer.storage.subprocess.run", side_effect=_dispatch):
        plan = plan_storage_layout(["/dev/sdz"], "/mnt/media")

    assert plan["error"] is None
    assert plan["already_has_data"]["/dev/sdz"] is None
    assert any("was not found by lsblk" in w for w in plan["warnings"])


def test_describe_storage_plan_reports_error_without_commands():

    plan = {"error": "Refusing to plan against protected device(s) /dev/sda.", "commands": []}

    output = describe_storage_plan(plan)

    assert "Can't plan this layout" in output
    assert "protected" in output


def test_describe_storage_plan_lists_devices_commands_and_headroom_note():

    with patch("installer.storage.subprocess.run", side_effect=_dispatch):

        plan = plan_storage_layout(["/dev/sdb", "/dev/sdc"], "/mnt/media")
        output = describe_storage_plan(plan)

    assert "/dev/sdb" in output
    assert "4T" in output
    assert "WD Red" in output
    assert "mdadm --create" in output
    assert "nothing has been executed" in output
    assert "10-15%" in output


def _probe_dispatch(
    mount_source: str | None = None,
    lsblk_found: bool = True,
    target_fstype: str | None = None,
) -> MagicMock:

    def dispatch(args, **kwargs):

        if args[0] == "findmnt":

            if mount_source is None:
                return MagicMock(returncode=1, stdout="")

            return MagicMock(returncode=0, stdout=f"{mount_source}\n")

        if args[0] == "lsblk":

            if not lsblk_found:
                return MagicMock(returncode=2, stdout="")

            return MagicMock(returncode=0, stdout=f"{target_fstype or ''}\n")

        raise AssertionError(f"unexpected probe: {args}")

    return dispatch


class _PrivilegedRecorder:
    """Records privileged commands; fails on demand for one argv prefix."""

    def __init__(self, fail_prefix: str | None = None):
        self.calls: list[list[str]] = []
        self.fail_prefix = fail_prefix

    def __call__(self, command: list[str]) -> dict:

        self.calls.append(command)

        if self.fail_prefix is not None and command[0] == self.fail_prefix:
            return {"success": False, "error": "exit code 1"}

        return {"success": True, "error": None}


def _apply_plan(
    devices: tuple[str, ...] = ("/dev/sdb",),
    mount: str = "/mnt/media",
    filesystem: str = "ext4",
    already_has_data: dict | None = None,
) -> dict:

    target = "/dev/md0" if len(devices) > 1 else devices[0]
    fstab_line = f"{target} {mount} {filesystem} defaults 0 2"

    commands: list[list[str]] = []

    if len(devices) > 1:
        commands.append(
            ["mdadm", "--create", target, "--level=1",
             f"--raid-devices={len(devices)}", *devices]
        )

    commands.append([f"mkfs.{filesystem}", target])
    commands.append(["mkdir", "-p", mount])
    commands.append(["mount", target, mount])
    commands.append(["sh", "-c", f"echo '{fstab_line}' >> /etc/fstab"])

    return {
        "target_devices": list(devices),
        "commands": commands,
        "warnings": [],
        "already_has_data": already_has_data or {d: False for d in devices},
        "error": None,
        "mount_point": mount,
        "target_device": target,
        "fstab_line": fstab_line,
    }


def test_apply_storage_layout_refuses_plan_with_error():

    plan = _apply_plan()
    plan["error"] = "Refusing to plan against protected device(s) /dev/sda."

    result = apply_storage_layout(plan)

    assert result["success"] is False
    assert "protected" in result["error"]


def test_apply_storage_layout_refuses_device_with_data_without_confirm_wipe():

    plan = _apply_plan(already_has_data={"/dev/sdb": True})

    result = apply_storage_layout(plan)

    assert result["success"] is False
    assert "already has a filesystem" in result["error"]


def test_apply_storage_layout_refuses_unknown_device():

    plan = _apply_plan(already_has_data={"/dev/sdz": None})

    result = apply_storage_layout(plan)

    assert result["success"] is False
    assert "wasn't found by lsblk" in result["error"]


def test_apply_storage_layout_confirm_wipe_overrides_existing_data_gate():

    plan = _apply_plan(already_has_data={"/dev/sdb": True})
    recorder = _PrivilegedRecorder()

    with patch("installer.storage.subprocess.run", side_effect=_probe_dispatch()), \
         patch("installer.storage._fstab_has_line", return_value=False), \
         patch("installer.storage.run_privileged", side_effect=recorder):

        result = apply_storage_layout(plan, confirm_wipe=True)

    assert result["success"] is True
    assert ["mkfs.ext4", "/dev/sdb"] in recorder.calls


def test_apply_storage_layout_single_device_runs_full_command_sequence():

    recorder = _PrivilegedRecorder()

    with patch("installer.storage.subprocess.run", side_effect=_probe_dispatch()), \
         patch("installer.storage._fstab_has_line", return_value=False), \
         patch("installer.storage.run_privileged", side_effect=recorder):

        result = apply_storage_layout(_apply_plan())

    assert result["success"] is True
    assert result["already_provisioned"] is False
    assert recorder.calls == [
        ["mkfs.ext4", "/dev/sdb"],
        ["mkdir", "-p", "/mnt/media"],
        ["mount", "/dev/sdb", "/mnt/media"],
        ["sh", "-c", "echo '/dev/sdb /mnt/media ext4 defaults 0 2' >> /etc/fstab"],
    ]


def test_apply_storage_layout_multi_device_prepends_mdadm_create():

    recorder = _PrivilegedRecorder()

    with patch("installer.storage.subprocess.run", side_effect=_probe_dispatch()), \
         patch("installer.storage._md_devices", return_value=set()), \
         patch("installer.storage._fstab_has_line", return_value=False), \
         patch("installer.storage.run_privileged", side_effect=recorder):

        result = apply_storage_layout(_apply_plan(devices=("/dev/sdb", "/dev/sdc")))

    assert result["success"] is True
    assert recorder.calls[0] == [
        "mdadm", "--create", "/dev/md0", "--level=1", "--raid-devices=2",
        "/dev/sdb", "/dev/sdc"
    ]
    assert ["mkfs.ext4", "/dev/md0"] in recorder.calls


def test_apply_storage_layout_already_mounted_returns_noop():

    recorder = _PrivilegedRecorder()

    with patch("installer.storage.subprocess.run",
               side_effect=_probe_dispatch(mount_source="/dev/sdb")), \
         patch("installer.storage.run_privileged", side_effect=recorder):

        result = apply_storage_layout(_apply_plan())

    assert result["success"] is True
    assert result["already_provisioned"] is True
    assert recorder.calls == []


def test_apply_storage_layout_refuses_mount_point_held_by_other_device():

    recorder = _PrivilegedRecorder()

    with patch("installer.storage.subprocess.run",
               side_effect=_probe_dispatch(mount_source="/dev/sdd")), \
         patch("installer.storage.run_privileged", side_effect=recorder):

        result = apply_storage_layout(_apply_plan())

    assert result["success"] is False
    assert "already mounted from /dev/sdd" in result["error"]
    assert recorder.calls == []


def test_apply_storage_layout_skips_mdadm_create_when_array_exists():

    recorder = _PrivilegedRecorder()

    with patch("installer.storage.subprocess.run", side_effect=_probe_dispatch()), \
         patch("installer.storage._md_devices", return_value={"md0"}), \
         patch("installer.storage._fstab_has_line", return_value=False), \
         patch("installer.storage.run_privileged", side_effect=recorder):

        result = apply_storage_layout(_apply_plan(devices=("/dev/sdb", "/dev/sdc")))

    assert result["success"] is True
    assert not any(call[0] == "mdadm" for call in recorder.calls)
    assert any("already exists" in s for s in result["skipped"])


def test_apply_storage_layout_skips_mkfs_when_target_has_filesystem():

    recorder = _PrivilegedRecorder()

    with patch("installer.storage.subprocess.run",
               side_effect=_probe_dispatch(target_fstype="ext4")), \
         patch("installer.storage._fstab_has_line", return_value=False), \
         patch("installer.storage.run_privileged", side_effect=recorder):

        result = apply_storage_layout(_apply_plan())

    assert result["success"] is True
    assert not any(call[0].startswith("mkfs.") for call in recorder.calls)
    assert any("already has a filesystem" in s for s in result["skipped"])


def test_apply_storage_layout_skips_fstab_append_when_line_present():

    recorder = _PrivilegedRecorder()

    with patch("installer.storage.subprocess.run", side_effect=_probe_dispatch()), \
         patch("installer.storage._fstab_has_line", return_value=True), \
         patch("installer.storage.run_privileged", side_effect=recorder):

        result = apply_storage_layout(_apply_plan())

    assert result["success"] is True
    assert not any(call[0] == "sh" for call in recorder.calls)
    assert any("already" in s for s in result["skipped"])


def test_apply_storage_layout_stops_at_first_failed_command():

    recorder = _PrivilegedRecorder(fail_prefix="mount")

    with patch("installer.storage.subprocess.run", side_effect=_probe_dispatch()), \
         patch("installer.storage._fstab_has_line", return_value=False), \
         patch("installer.storage.run_privileged", side_effect=recorder):

        result = apply_storage_layout(_apply_plan())

    assert result["success"] is False
    assert "mount" in result["error"]
    assert not any(call[0] == "sh" for call in recorder.calls)


def test_list_blank_unprotected_devices_only_returns_clean_spare_disks():

    with patch("installer.storage.subprocess.run", side_effect=_dispatch):

        devices = list_blank_unprotected_devices()

    # sda is protected (backs /); sdb/sdc are blank spare disks.
    assert [d["path"] for d in devices] == ["/dev/sdb", "/dev/sdc"]


def test_list_blank_unprotected_devices_skips_formatted_or_partitioned_disks():

    fake_output = {
        "blockdevices": [
            {
                "name": "sdd", "path": "/dev/sdd", "size": "2T", "type": "disk",
                "fstype": "ext4", "mountpoint": None, "model": None, "pkname": None
            },
            {
                "name": "sde", "path": "/dev/sde", "size": "2T", "type": "disk",
                "fstype": None, "mountpoint": None, "model": None, "pkname": None,
                "children": [{
                    "name": "sde1", "path": "/dev/sde1", "size": "2T", "type": "part",
                    "fstype": "ext4", "mountpoint": None, "model": None, "pkname": "sde"
                }]
            },
            {
                "name": "sdf", "path": "/dev/sdf", "size": "2T", "type": "disk",
                "fstype": None, "mountpoint": None, "model": None, "pkname": None
            }
        ]
    }

    def dispatch(args, **kwargs):

        if args[0] == "lsblk":
            return _mock_lsblk(stdout=json.dumps(fake_output))

        return _mock_findmnt_missing()

    with patch("installer.storage.subprocess.run", side_effect=dispatch):

        devices = list_blank_unprotected_devices()

    assert [d["path"] for d in devices] == ["/dev/sdf"]


def test_list_blank_unprotected_devices_lsblk_failure_returns_empty():

    with patch("installer.storage.subprocess.run", return_value=_mock_lsblk(returncode=1)):

        devices = list_blank_unprotected_devices()

    assert devices == []
