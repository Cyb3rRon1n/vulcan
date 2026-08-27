import json
from unittest.mock import MagicMock, mock_open, patch

from installer.storage import (
    _raid_level_options,
    _raid_usable_drive_equivalents,
    apply_storage_layout,
    apply_storage_teardown,
    describe_raid_option,
    describe_storage_plan,
    describe_storage_teardown,
    device_tree_text,
    identify_protected_devices,
    list_blank_unprotected_devices,
    list_block_devices,
    plan_storage_layout,
    plan_storage_teardown,
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

    with patch("installer.storage._provision_owner", return_value="1000:1000"), \
         patch("installer.storage.subprocess.run", side_effect=_dispatch):
        plan = plan_storage_layout(["/dev/sdb"], "/mnt/media")

    assert plan["error"] is None
    assert plan["commands"] == [
        ["mkfs.ext4", "/dev/sdb"],
        ["mkdir", "-p", "/mnt/media"],
        ["mount", "/dev/sdb", "/mnt/media"],
        ["chown", "1000:1000", "/mnt/media"],
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
    assert "isn't a valid choice for 2 devices" in plan["error"]


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


def test_raid_level_options_single_device_has_no_raid_choice():

    assert _raid_level_options(1) == []


def test_raid_level_options_two_devices_offers_raid0_and_raid1():

    options = _raid_level_options(2)

    assert [o["level"] for o in options] == ["0", "1"]
    assert options[0]["recommended"] is False
    assert options[1]["recommended"] is True


def test_raid_level_options_three_devices_offers_raid0_and_raid5():

    options = _raid_level_options(3)

    assert [o["level"] for o in options] == ["0", "5"]
    assert options[0]["recommended"] is False
    assert options[1]["recommended"] is True


def test_raid_level_options_four_devices_offers_0_5_6_10_with_5_recommended():

    options = _raid_level_options(4)

    assert [o["level"] for o in options] == ["0", "5", "6", "10"]
    assert options[0]["recommended"] is False
    assert options[1]["recommended"] is True
    assert options[2]["recommended"] is False
    assert options[3]["recommended"] is False


def test_raid_level_options_five_devices_skips_raid10():

    options = _raid_level_options(5)

    assert [o["level"] for o in options] == ["0", "5", "6"]


def test_raid_level_options_six_devices_offers_raid10_again():

    options = _raid_level_options(6)

    assert [o["level"] for o in options] == ["0", "5", "6", "10"]


def test_raid_usable_capacity_raid0_is_full_capacity():

    assert _raid_usable_drive_equivalents("0", 4) == 4
    assert _raid_usable_drive_equivalents("0", 8) == 8


def test_raid_usable_capacity_four_drives_raid5_is_three():

    assert _raid_usable_drive_equivalents("5", 4) == 3
    assert _raid_usable_drive_equivalents("6", 4) == 2
    assert _raid_usable_drive_equivalents("10", 4) == 2


def test_raid_usable_capacity_three_drives_raid5_is_two():

    assert _raid_usable_drive_equivalents("5", 3) == 2


def test_describe_raid_option_renders_honest_tradeoffs():

    text = describe_raid_option({"level": "5", "usable": 3, "total": 4})

    assert "RAID5" in text
    assert "3 of 4" in text
    assert "survives 1 drive failure" in text


def test_plan_storage_layout_explicit_raid6_with_four_devices():

    fake_output = {
        "blockdevices": [
            {
                "name": "sdb", "path": "/dev/sdb", "size": "4T", "type": "disk",
                "fstype": None, "mountpoint": None, "model": None, "pkname": None
            },
            {
                "name": "sdc", "path": "/dev/sdc", "size": "4T", "type": "disk",
                "fstype": None, "mountpoint": None, "model": None, "pkname": None
            },
            {
                "name": "sdd", "path": "/dev/sdd", "size": "4T", "type": "disk",
                "fstype": None, "mountpoint": None, "model": None, "pkname": None
            },
            {
                "name": "sde", "path": "/dev/sde", "size": "4T", "type": "disk",
                "fstype": None, "mountpoint": None, "model": None, "pkname": None
            },
        ]
    }

    def dispatch(args, **kwargs):

        if args[0] == "lsblk":
            return _mock_lsblk(stdout=json.dumps(fake_output))

        if args[0] == "findmnt":
            return _mock_findmnt_missing()

        raise AssertionError(f"unexpected call: {args}")

    with patch("installer.storage.subprocess.run", side_effect=dispatch):
        plan = plan_storage_layout(
            ["/dev/sdb", "/dev/sdc", "/dev/sdd", "/dev/sde"],
            "/mnt/media",
            raid_level="6",
        )

    assert plan["error"] is None
    assert plan["commands"][0][3] == "--level=6"


def test_plan_storage_layout_rejects_raid10_with_odd_device_count():

    fake_output = {
        "blockdevices": [
            {
                "name": "sdb", "path": "/dev/sdb", "size": "4T", "type": "disk",
                "fstype": None, "mountpoint": None, "model": None, "pkname": None
            },
            {
                "name": "sdc", "path": "/dev/sdc", "size": "4T", "type": "disk",
                "fstype": None, "mountpoint": None, "model": None, "pkname": None
            },
            {
                "name": "sdd", "path": "/dev/sdd", "size": "4T", "type": "disk",
                "fstype": None, "mountpoint": None, "model": None, "pkname": None
            },
        ]
    }

    def dispatch(args, **kwargs):

        if args[0] == "lsblk":
            return _mock_lsblk(stdout=json.dumps(fake_output))

        if args[0] == "findmnt":
            return _mock_findmnt_missing()

        raise AssertionError(f"unexpected call: {args}")

    with patch("installer.storage.subprocess.run", side_effect=dispatch):
        plan = plan_storage_layout(
            ["/dev/sdb", "/dev/sdc", "/dev/sdd"],
            "/mnt/media",
            raid_level="10",
        )

    assert plan["error"] is not None
    assert "even number" in plan["error"]


def test_device_tree_text_runs_lsblk_on_target():

    with patch("installer.storage.subprocess.run", return_value=MagicMock(returncode=0, stdout="md0\ndevices...\n")):
        text = device_tree_text("/dev/md0")

    assert text == "md0\ndevices...\n"


def test_device_tree_text_failure_returns_none():

    with patch("installer.storage.subprocess.run", return_value=MagicMock(returncode=2, stdout="")):
        text = device_tree_text("/dev/md0")

    assert text is None


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
    commands.append(["chown", "1000:1000", mount])
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
        ["chown", "1000:1000", "/mnt/media"],
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
         patch("installer.storage.run_privileged", side_effect=recorder), \
         patch("installer.storage._provision_owner", return_value="1000:1000"):

        result = apply_storage_layout(_apply_plan())

    assert result["success"] is True
    assert result["already_provisioned"] is True
    assert recorder.calls == [["chown", "1000:1000", "/mnt/media"]]


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


# --- Storage teardown -------------------------------------------------

def test_mdadm_export_field_parses_md_device_lines():

    from installer.storage import _mdadm_export_field

    export_output = (
        "MD_LEVEL=raid1\n"
        "MD_DEVICES=2\n"
        "MD_DEVICE_dev0_DEV=/dev/sdb\n"
        "MD_DEVICE_dev0_ROLE=0\n"
        "MD_DEVICE_dev1_DEV=/dev/sdc\n"
        "MD_DEVICE_dev1_ROLE=1\n"
    )

    with patch(
        "installer.storage.subprocess.run",
        return_value=MagicMock(returncode=0, stdout=export_output)
    ):

        members = _mdadm_export_field("/dev/md0")

    assert members == ["/dev/sdb", "/dev/sdc"]


def test_mdadm_export_field_returns_empty_on_failure():

    from installer.storage import _mdadm_export_field

    with patch(
        "installer.storage.subprocess.run",
        return_value=MagicMock(returncode=1, stdout="")
    ):

        assert _mdadm_export_field("/dev/md0") == []


def test_fstab_line_for_mount_point_finds_real_line():

    from installer.storage import _fstab_line_for_mount_point

    fstab = (
        "# comment\n"
        "UUID=abc / ext4 defaults 0 1\n"
        "/dev/sdb /mnt/media ext4 defaults 0 2\n"
    )

    with patch("builtins.open", mock_open(read_data=fstab)):
        line = _fstab_line_for_mount_point("/mnt/media")

    assert line == "/dev/sdb /mnt/media ext4 defaults 0 2"


def test_fstab_line_for_mount_point_returns_none_when_absent():

    from installer.storage import _fstab_line_for_mount_point

    fstab = "UUID=abc / ext4 defaults 0 1\n"

    with patch("builtins.open", mock_open(read_data=fstab)):
        assert _fstab_line_for_mount_point("/mnt/media") is None


def test_plan_storage_teardown_nothing_mounted_returns_error():

    with patch("installer.storage._findmnt_source", return_value=None):

        plan = plan_storage_teardown("/mnt/media")

    assert plan["error"] is not None
    assert "Nothing is mounted" in plan["error"]
    assert plan["commands"] == []


def test_plan_storage_teardown_refuses_protected_device():

    with patch("installer.storage._findmnt_source", return_value="/dev/sda"), \
         patch("installer.storage.identify_protected_devices", return_value={"/dev/sda"}):

        plan = plan_storage_teardown("/")

    assert plan["error"] is not None
    assert "backing / or /boot" in plan["error"]
    assert plan["commands"] == []


def test_plan_storage_teardown_single_device_no_raid():

    with patch("installer.storage._findmnt_source", return_value="/dev/sdb"), \
         patch("installer.storage.identify_protected_devices", return_value=set()), \
         patch("installer.storage._md_devices", return_value=set()), \
         patch(
             "installer.storage._fstab_line_for_mount_point",
             return_value="/dev/sdb /mnt/media ext4 defaults 0 2"
         ):

        plan = plan_storage_teardown("/mnt/media")

    assert plan["error"] is None
    assert plan["is_raid"] is False
    assert plan["member_devices"] == []
    assert plan["commands"] == [
        ["umount", "/mnt/media"],
        ["wipefs", "-a", "/dev/sdb"],
        ["sh", "-c",
         "grep -vF '/dev/sdb /mnt/media ext4 defaults 0 2' /etc/fstab "
         "> /etc/fstab.vulcan-tmp && mv /etc/fstab.vulcan-tmp /etc/fstab"],
    ]


def test_plan_storage_teardown_raid_array_includes_members():

    with patch("installer.storage._findmnt_source", return_value="/dev/md0"), \
         patch("installer.storage.identify_protected_devices", return_value=set()), \
         patch("installer.storage._md_devices", return_value={"md0"}), \
         patch(
             "installer.storage._mdadm_export_field",
             return_value=["/dev/sdb", "/dev/sdc"]
         ), \
         patch("installer.storage._fstab_line_for_mount_point", return_value=None):

        plan = plan_storage_teardown("/mnt/media")

    assert plan["error"] is None
    assert plan["is_raid"] is True
    assert plan["member_devices"] == ["/dev/sdb", "/dev/sdc"]
    assert plan["commands"] == [
        ["umount", "/mnt/media"],
        ["mdadm", "--stop", "/dev/md0"],
        ["mdadm", "--zero-superblock", "/dev/sdb"],
        ["mdadm", "--zero-superblock", "/dev/sdc"],
        ["wipefs", "-a", "/dev/md0"],
        ["wipefs", "-a", "/dev/sdb"],
        ["wipefs", "-a", "/dev/sdc"],
    ]


def test_plan_storage_teardown_no_fstab_line_skips_removal_command():

    with patch("installer.storage._findmnt_source", return_value="/dev/sdb"), \
         patch("installer.storage.identify_protected_devices", return_value=set()), \
         patch("installer.storage._md_devices", return_value=set()), \
         patch("installer.storage._fstab_line_for_mount_point", return_value=None):

        plan = plan_storage_teardown("/mnt/media")

    assert plan["fstab_line"] is None
    assert not any(c[0] == "sh" for c in plan["commands"])


def test_describe_storage_teardown_reports_error_without_commands():

    plan = {"error": "Nothing is mounted at /mnt/media - nothing to tear down."}

    output = describe_storage_teardown(plan)

    assert "Can't plan this teardown" in output


def test_describe_storage_teardown_lists_members_commands_and_warning():

    plan = {
        "mount_point": "/mnt/media",
        "target_device": "/dev/md0",
        "member_devices": ["/dev/sdb", "/dev/sdc"],
        "is_raid": True,
        "commands": [["umount", "/mnt/media"], ["wipefs", "-a", "/dev/md0"]],
        "fstab_line": None,
        "error": None,
    }

    output = describe_storage_teardown(plan)

    assert "/dev/md0" in output
    assert "/dev/sdb" in output
    assert "/dev/sdc" in output
    assert "nothing has been executed" in output
    assert "no undo" in output


def _teardown_plan(
    target: str = "/dev/sdb",
    mount: str = "/mnt/media",
    members: list[str] | None = None,
    is_raid: bool = False,
    fstab_line: str | None = "/dev/sdb /mnt/media ext4 defaults 0 2",
) -> dict:

    members = members or []
    commands: list[list[str]] = [["umount", mount]]

    if is_raid:
        commands.append(["mdadm", "--stop", target])
        for member in members:
            commands.append(["mdadm", "--zero-superblock", member])

    commands.append(["wipefs", "-a", target])

    for member in members:
        commands.append(["wipefs", "-a", member])

    if fstab_line:
        commands.append(
            ["sh", "-c",
             f"grep -vF '{fstab_line}' /etc/fstab > /etc/fstab.vulcan-tmp "
             "&& mv /etc/fstab.vulcan-tmp /etc/fstab"]
        )

    return {
        "mount_point": mount,
        "target_device": target,
        "member_devices": members,
        "is_raid": is_raid,
        "commands": commands,
        "fstab_line": fstab_line,
        "error": None,
    }


def test_apply_storage_teardown_refuses_plan_with_error():

    result = apply_storage_teardown({"error": "nothing mounted"}, confirm_wipe=True)

    assert result["success"] is False
    assert result["error"] == "nothing mounted"


def test_apply_storage_teardown_refuses_without_confirm_wipe():

    recorder = _PrivilegedRecorder()

    with patch("installer.storage.run_privileged", side_effect=recorder):

        result = apply_storage_teardown(_teardown_plan())

    assert result["success"] is False
    assert "--confirm-wipe" in result["error"]
    assert recorder.calls == []


def test_apply_storage_teardown_single_device_runs_full_sequence():

    recorder = _PrivilegedRecorder()

    with patch("installer.storage._findmnt_source", return_value="/dev/sdb"), \
         patch("installer.storage._md_devices", return_value=set()), \
         patch("installer.storage.run_privileged", side_effect=recorder):

        result = apply_storage_teardown(_teardown_plan(), confirm_wipe=True)

    assert result["success"] is True
    assert recorder.calls == [
        ["umount", "/mnt/media"],
        ["wipefs", "-a", "/dev/sdb"],
        ["sh", "-c",
         "grep -vF '/dev/sdb /mnt/media ext4 defaults 0 2' /etc/fstab "
         "> /etc/fstab.vulcan-tmp && mv /etc/fstab.vulcan-tmp /etc/fstab"],
    ]


def test_apply_storage_teardown_raid_runs_full_sequence():

    recorder = _PrivilegedRecorder()

    plan = _teardown_plan(
        target="/dev/md0", members=["/dev/sdb", "/dev/sdc"],
        is_raid=True, fstab_line=None
    )

    with patch("installer.storage._findmnt_source", return_value="/dev/md0"), \
         patch("installer.storage._md_devices", return_value={"md0"}), \
         patch("installer.storage.run_privileged", side_effect=recorder):

        result = apply_storage_teardown(plan, confirm_wipe=True)

    assert result["success"] is True
    assert recorder.calls == [
        ["umount", "/mnt/media"],
        ["mdadm", "--stop", "/dev/md0"],
        ["mdadm", "--zero-superblock", "/dev/sdb"],
        ["mdadm", "--zero-superblock", "/dev/sdc"],
        ["wipefs", "-a", "/dev/md0"],
        ["wipefs", "-a", "/dev/sdb"],
        ["wipefs", "-a", "/dev/sdc"],
    ]


def test_apply_storage_teardown_skips_umount_when_already_unmounted():

    recorder = _PrivilegedRecorder()

    with patch("installer.storage._findmnt_source", return_value=None), \
         patch("installer.storage._md_devices", return_value=set()), \
         patch("installer.storage.run_privileged", side_effect=recorder):

        result = apply_storage_teardown(_teardown_plan(), confirm_wipe=True)

    assert result["success"] is True
    assert not any(call[0] == "umount" for call in recorder.calls)
    assert any("already unmounted" in s for s in result["skipped"])


def test_apply_storage_teardown_skips_mdadm_stop_when_already_stopped():

    recorder = _PrivilegedRecorder()

    plan = _teardown_plan(
        target="/dev/md0", members=["/dev/sdb"], is_raid=True, fstab_line=None
    )

    with patch("installer.storage._findmnt_source", return_value="/dev/md0"), \
         patch("installer.storage._md_devices", return_value=set()), \
         patch("installer.storage.run_privileged", side_effect=recorder):

        result = apply_storage_teardown(plan, confirm_wipe=True)

    assert result["success"] is True
    assert not any(call[:2] == ["mdadm", "--stop"] for call in recorder.calls)
    assert any("already stopped" in s for s in result["skipped"])
    # --zero-superblock still runs even though --stop was skipped.
    assert ["mdadm", "--zero-superblock", "/dev/sdb"] in recorder.calls


def test_apply_storage_teardown_stops_at_first_failed_command():

    recorder = _PrivilegedRecorder(fail_prefix="wipefs")

    with patch("installer.storage._findmnt_source", return_value="/dev/sdb"), \
         patch("installer.storage._md_devices", return_value=set()), \
         patch("installer.storage.run_privileged", side_effect=recorder):

        result = apply_storage_teardown(_teardown_plan(), confirm_wipe=True)

    assert result["success"] is False
    assert "wipefs" in result["error"]
    assert not any(call[0] == "sh" for call in recorder.calls)
