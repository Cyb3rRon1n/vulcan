import json
from unittest.mock import MagicMock, patch

from installer.storage import (
    describe_storage_plan,
    identify_protected_devices,
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
