from unittest.mock import MagicMock, mock_open, patch

from installer.detect import (
    SystemInfo,
    describe_media_redundancy,
    detect_cpu,
    detect_disk,
    detect_docker,
    detect_gpu,
    detect_host_ip,
    detect_media_redundancy,
    detect_memory,
    detect_os,
    detect_render_group_gid,
    detect_system,
)


FAKE_MDSTAT_RAID1 = (
    "Personalities : [raid1] \n"
    "md0 : active raid1 sdb1[1] sda1[0]\n"
    "      976630464 blocks super 1.2 [2/2] [UU]\n"
    "\n"
    "unused devices: <none>\n"
)

FAKE_MDSTAT_RAID0 = (
    "Personalities : [raid0] \n"
    "md0 : active raid0 sdb1[1] sda1[0]\n"
    "      1953260928 blocks super 1.2 512k chunks\n"
    "\n"
    "unused devices: <none>\n"
)

FAKE_ZPOOL_STATUS_MIRROR = (
    "  pool: tank\n"
    " state: ONLINE\n"
    "config:\n"
    "\n"
    "\tNAME        STATE     READ WRITE CKSUM\n"
    "\ttank        ONLINE       0     0     0\n"
    "\t  mirror-0  ONLINE       0     0     0\n"
    "\t    sda     ONLINE       0     0     0\n"
    "\t    sdb     ONLINE       0     0     0\n"
)

FAKE_ZPOOL_STATUS_SINGLE = (
    "  pool: tank\n"
    " state: ONLINE\n"
    "config:\n"
    "\n"
    "\tNAME        STATE     READ WRITE CKSUM\n"
    "\ttank        ONLINE       0     0     0\n"
    "\t  sda       ONLINE       0     0     0\n"
)


FAKE_CPUINFO = (
    "processor\t: 0\n"
    "vendor_id\t: GenuineIntel\n"
    "model name\t: Intel(R) Core(TM) i7-9700K CPU @ 3.60GHz\n"
    "cpu MHz\t\t: 3600.000\n"
)

# Real ARM64 /proc/cpuinfo shape - no "model name" line at all (the x86
# convention), just per-core implementer/architecture/part/revision
# fields. 0x41/0xd08 are the genuine, documented ARM Ltd. MIDR_EL1 values
# for a Cortex-A72 (e.g. a real Raspberry Pi 4's own cpuinfo).
FAKE_CPUINFO_ARM = (
    "processor\t: 0\n"
    "BogoMIPS\t: 108.00\n"
    "Features\t: fp asimd evtstrm aes pmull sha1 sha2 crc32 cpuid\n"
    "CPU implementer\t: 0x41\n"
    "CPU architecture: 8\n"
    "CPU variant\t: 0x0\n"
    "CPU part\t: 0xd08\n"
    "CPU revision\t: 3\n"
)

# Same shape, but a part ID this project's own small lookup table doesn't
# recognize - exercises the "known vendor, unrecognized core" fallback
# tier rather than the fully-decoded one.
FAKE_CPUINFO_ARM_UNKNOWN_PART = (
    "processor\t: 0\n"
    "CPU implementer\t: 0x41\n"
    "CPU architecture: 8\n"
    "CPU part\t: 0xfff\n"
)


def _multi_file_open(files: dict[str, str | None]):
    """A builtins.open stand-in that returns different fake content per
    path - a plain mock_open() can't do this (it returns the same content
    regardless of which file is opened), but detect_cpu()'s ARM fallback
    path now genuinely opens two different real files in sequence
    (/proc/cpuinfo, then /proc/device-tree/model). A path mapped to None
    raises OSError, the same "not present" shape a real missing file
    produces; a path not in the dict at all is a real test bug, so it
    raises too rather than silently returning something."""

    def _open(path, *args, **kwargs):

        if path not in files:
            raise AssertionError(f"unexpected open() call for {path!r}")

        content = files[path]
        if content is None:
            raise OSError(f"no such file: {path}")

        return mock_open(read_data=content)(path, *args, **kwargs)

    return _open

FAKE_OS_RELEASE = (
    'NAME="Fedora Linux"\n'
    'VERSION="44 (Workstation Edition)"\n'
    "ID=fedora\n"
    'PRETTY_NAME="Fedora Linux 44 (Workstation Edition)"\n'
)


def test_detect_cpu_reads_model_name_from_proc_cpuinfo():

    with patch(
        "installer.detect.psutil.cpu_count", side_effect=[8, 16]
    ), patch("builtins.open", mock_open(read_data=FAKE_CPUINFO)):

        result = detect_cpu()

    assert result == {
        "cpu_cores_physical": 8,
        "cpu_cores_logical": 16,
        "cpu_model": "Intel(R) Core(TM) i7-9700K CPU @ 3.60GHz"
    }


def test_detect_cpu_handles_missing_proc_cpuinfo():

    with patch(
        "installer.detect.psutil.cpu_count", side_effect=[4, 8]
    ), patch("builtins.open", side_effect=OSError("no such file")):

        result = detect_cpu()

    assert result == {
        "cpu_cores_physical": 4,
        "cpu_cores_logical": 8,
        "cpu_model": None
    }


def test_detect_cpu_falls_back_to_device_tree_model_on_arm():

    # The device tree's own real board-model string wins over decoding
    # implementer/part IDs whenever it's actually available - a genuine
    # board name ("Raspberry Pi 4 Model B Rev 1.4") is a better answer
    # than a decoded chip name ("ARM Cortex-A72") even though both are
    # technically correct here.
    files = {
        "/proc/cpuinfo": FAKE_CPUINFO_ARM,
        "/proc/device-tree/model": "Raspberry Pi 4 Model B Rev 1.4\x00",
    }

    with patch(
        "installer.detect.psutil.cpu_count", side_effect=[4, 4]
    ), patch("builtins.open", side_effect=_multi_file_open(files)):

        result = detect_cpu()

    assert result["cpu_model"] == "Raspberry Pi 4 Model B Rev 1.4"


def test_detect_cpu_falls_back_to_implementer_part_decode_without_device_tree():

    # No device tree at all (some ACPI-based ARM servers) - falls back to
    # decoding the real implementer/part IDs /proc/cpuinfo does carry.
    files = {
        "/proc/cpuinfo": FAKE_CPUINFO_ARM,
        "/proc/device-tree/model": None,
    }

    with patch(
        "installer.detect.psutil.cpu_count", side_effect=[4, 4]
    ), patch("builtins.open", side_effect=_multi_file_open(files)):

        result = detect_cpu()

    assert result["cpu_model"] == "ARM Cortex-A72"


def test_detect_cpu_decode_falls_back_to_vendor_only_for_unrecognized_part():

    files = {
        "/proc/cpuinfo": FAKE_CPUINFO_ARM_UNKNOWN_PART,
        "/proc/device-tree/model": None,
    }

    with patch(
        "installer.detect.psutil.cpu_count", side_effect=[4, 4]
    ), patch("builtins.open", side_effect=_multi_file_open(files)):

        result = detect_cpu()

    assert result["cpu_model"] == "ARM (part 0xfff)"


def test_detect_memory_converts_bytes_to_gb():

    fake_memory = MagicMock()
    fake_memory.total = 16 * 1024 ** 3
    fake_memory.available = 8 * 1024 ** 3

    with patch(
        "installer.detect.psutil.virtual_memory", return_value=fake_memory
    ):

        result = detect_memory()

    assert result == {"ram_total_gb": 16.0, "ram_available_gb": 8.0}


def test_detect_disk_returns_free_space_in_gb():

    fake_usage = MagicMock()
    fake_usage.free = 100 * 1024 ** 3

    with patch(
        "installer.detect.shutil.disk_usage", return_value=fake_usage
    ):

        result = detect_disk("/mnt/media")

    assert result == {"disk_free_gb": 100.0, "disk_path_checked": "/mnt/media"}


def test_detect_disk_handles_missing_path():

    with patch(
        "installer.detect.shutil.disk_usage",
        side_effect=OSError("no such path")
    ):

        result = detect_disk("/does/not/exist")

    assert result == {
        "disk_free_gb": 0.0,
        "disk_path_checked": "/does/not/exist"
    }


def _mock_findmnt(source: str, fstype: str, mountpoint: str = "/mnt/media") -> MagicMock:

    return MagicMock(returncode=0, stdout=f"{source} {fstype} {mountpoint}\n")


def test_detect_media_redundancy_unresolvable_path_returns_all_none():

    with patch(
        "installer.detect.subprocess.run", return_value=MagicMock(returncode=1, stdout="")
    ):

        result = detect_media_redundancy("/no/such/path")

    assert result == {
        "device": None, "filesystem": None, "redundant": None,
        "redundancy_type": None, "device_count": None
    }


def test_detect_media_redundancy_findmnt_raises_returns_all_none():

    with patch(
        "installer.detect.subprocess.run", side_effect=OSError("findmnt not found")
    ):

        result = detect_media_redundancy("/mnt/media")

    assert result["device"] is None
    assert result["redundant"] is None


def test_detect_media_redundancy_mdadm_raid1_is_redundant():

    with patch(
        "installer.detect.subprocess.run", return_value=_mock_findmnt("/dev/md0", "ext4")
    ), patch(
        "builtins.open", mock_open(read_data=FAKE_MDSTAT_RAID1)
    ):

        result = detect_media_redundancy("/mnt/media")

    assert result["device"] == "/dev/md0"
    assert result["filesystem"] == "ext4"
    assert result["redundant"] is True
    assert result["redundancy_type"] == "raid1"
    assert result["device_count"] == 2


def test_detect_media_redundancy_mdadm_raid0_is_not_redundant():

    with patch(
        "installer.detect.subprocess.run", return_value=_mock_findmnt("/dev/md0", "ext4")
    ), patch(
        "builtins.open", mock_open(read_data=FAKE_MDSTAT_RAID0)
    ):

        result = detect_media_redundancy("/mnt/media")

    assert result["redundant"] is False
    assert result["redundancy_type"] == "raid0"


def test_detect_media_redundancy_btrfs_single_device_is_not_redundant():

    # media_path is a subdirectory under the real mountpoint, not the
    # mountpoint itself - `btrfs filesystem show` rejects an arbitrary
    # subpath (confirmed against a real filesystem), so this also
    # guards against passing media_path to it instead of TARGET.
    findmnt_result = _mock_findmnt("/dev/nvme0n1p3[/home]", "btrfs", mountpoint="/home")
    show_result = MagicMock(
        returncode=0,
        stdout="Label: 'fedora'  uuid: xxx\n\tTotal devices 1 FS bytes used 62.66GiB\n"
    )

    with patch(
        "installer.detect.subprocess.run", side_effect=[findmnt_result, show_result]
    ) as mock_run, patch(
        "installer.detect.shutil.which", return_value="/usr/bin/btrfs"
    ):

        result = detect_media_redundancy("/home/sentinel/media")

    assert result["device"] == "/dev/nvme0n1p3"
    assert result["filesystem"] == "btrfs"
    assert result["redundant"] is False
    assert result["device_count"] == 1

    show_call_args = mock_run.call_args_list[1][0][0]
    assert show_call_args == ["btrfs", "filesystem", "show", "/home"]


def test_detect_media_redundancy_btrfs_multi_device_is_redundant():

    findmnt_result = _mock_findmnt("/dev/sda1", "btrfs", mountpoint="/mnt/media")
    show_result = MagicMock(
        returncode=0,
        stdout="Label: 'tank'  uuid: xxx\n\tTotal devices 2 FS bytes used 10.00GiB\n"
    )

    with patch(
        "installer.detect.subprocess.run", side_effect=[findmnt_result, show_result]
    ), patch(
        "installer.detect.shutil.which", return_value="/usr/bin/btrfs"
    ):

        result = detect_media_redundancy("/mnt/media")

    assert result["redundant"] is True
    assert result["device_count"] == 2
    assert result["redundancy_type"] == "btrfs-multi-device"


def test_detect_media_redundancy_btrfs_missing_tool_cannot_determine():

    with patch(
        "installer.detect.subprocess.run", return_value=_mock_findmnt("/dev/sda1", "btrfs")
    ), patch(
        "installer.detect.shutil.which", return_value=None
    ):

        result = detect_media_redundancy("/mnt/media")

    assert result["device"] == "/dev/sda1"
    assert result["redundant"] is None


def test_detect_media_redundancy_zfs_mirror_is_redundant():

    findmnt_result = _mock_findmnt("tank/media", "zfs")
    status_result = MagicMock(returncode=0, stdout=FAKE_ZPOOL_STATUS_MIRROR)

    with patch(
        "installer.detect.subprocess.run", side_effect=[findmnt_result, status_result]
    ), patch(
        "installer.detect.shutil.which", return_value="/usr/sbin/zpool"
    ):

        result = detect_media_redundancy("/mnt/media")

    assert result["device"] == "tank/media"
    assert result["filesystem"] == "zfs"
    assert result["redundant"] is True
    assert result["redundancy_type"] == "zfs-mirror"


def test_detect_media_redundancy_zfs_single_vdev_is_not_redundant():

    findmnt_result = _mock_findmnt("tank/media", "zfs")
    status_result = MagicMock(returncode=0, stdout=FAKE_ZPOOL_STATUS_SINGLE)

    with patch(
        "installer.detect.subprocess.run", side_effect=[findmnt_result, status_result]
    ), patch(
        "installer.detect.shutil.which", return_value="/usr/sbin/zpool"
    ):

        result = detect_media_redundancy("/mnt/media")

    assert result["redundant"] is False
    assert result["redundancy_type"] is None


def test_detect_media_redundancy_zfs_missing_tool_cannot_determine():

    with patch(
        "installer.detect.subprocess.run", return_value=_mock_findmnt("tank/media", "zfs")
    ), patch(
        "installer.detect.shutil.which", return_value=None
    ):

        result = detect_media_redundancy("/mnt/media")

    assert result["device"] == "tank/media"
    assert result["redundant"] is None


def test_detect_media_redundancy_plain_device_is_not_redundant():

    with patch(
        "installer.detect.subprocess.run", return_value=_mock_findmnt("/dev/sda1", "ext4")
    ):

        result = detect_media_redundancy("/mnt/media")

    assert result["device"] == "/dev/sda1"
    assert result["filesystem"] == "ext4"
    assert result["redundant"] is False
    assert result["device_count"] == 1
    assert result["redundancy_type"] is None


def test_describe_media_redundancy_returns_none_when_device_unknown():

    result = {
        "device": None, "filesystem": None, "redundant": None,
        "redundancy_type": None, "device_count": None
    }

    assert describe_media_redundancy(result) is None


def test_describe_media_redundancy_unknown_redundancy_wording():

    result = {
        "device": "/dev/sda1", "filesystem": "ext4", "redundant": None,
        "redundancy_type": None, "device_count": None
    }

    assert describe_media_redundancy(result) == (
        "/dev/sda1 (ext4) - redundancy could not be determined"
    )


def test_describe_media_redundancy_redundant_wording():

    result = {
        "device": "/dev/md0", "filesystem": "ext4", "redundant": True,
        "redundancy_type": "raid1", "device_count": 2
    }

    assert describe_media_redundancy(result) == "/dev/md0 (ext4, raid1, 2 devices)"


def test_describe_media_redundancy_not_redundant_wording():

    result = {
        "device": "/dev/sda1", "filesystem": "ext4", "redundant": False,
        "redundancy_type": None, "device_count": 1
    }

    assert describe_media_redundancy(result) == (
        "/dev/sda1 (ext4, single device - no redundancy)"
    )


def test_detect_gpu_detects_nvidia():

    with patch(
        "installer.detect.shutil.which",
        side_effect=lambda name: "/usr/bin/nvidia-smi" if name == "nvidia-smi" else None
    ), patch(
        "installer.detect.run_ok", return_value=True
    ):

        assert detect_gpu() == "nvidia"


def test_detect_gpu_nvidia_binary_present_but_query_fails_falls_through():
    """
    The exact class of false positive this function exists to avoid -
    a present-but-non-functional nvidia-smi (no driver, no card) must
    not be reported as NVIDIA.
    """

    with patch(
        "installer.detect.shutil.which",
        side_effect=lambda name: "/usr/bin/nvidia-smi" if name == "nvidia-smi" else None
    ), patch(
        "installer.detect.run_ok", return_value=False
    ):

        assert detect_gpu() is None


def test_detect_gpu_detects_amd():

    with patch(
        "installer.detect.shutil.which",
        side_effect=lambda name: "/usr/bin/rocm-smi" if name == "rocm-smi" else None
    ), patch(
        "installer.detect.subprocess.run",
        return_value=MagicMock(returncode=0, stdout="GPU[0]\t: Device ID: 0x1002", stderr="")
    ):

        assert detect_gpu() == "amd"


def test_detect_gpu_amd_binary_present_but_no_driver_falls_through():
    """
    A real, confirmed bug, not hypothetical: rocm-smi exits 0 even
    when it fails - "ERROR:root:Driver not initialized (amdgpu not
    found in modules)" was the actual real output captured from this
    project's own dev machine, which has rocm-smi installed with no
    AMD GPU at all. A plain exit-code check alone would have kept
    reporting "amd" on this exact machine forever - the return code
    doesn't signal failure here, only the output does.
    """

    with patch(
        "installer.detect.shutil.which",
        side_effect=lambda name: "/usr/bin/rocm-smi" if name == "rocm-smi" else None
    ), patch(
        "installer.detect.subprocess.run",
        return_value=MagicMock(
            returncode=0, stdout="", stderr="ERROR:root:Driver not initialized (amdgpu not found in modules)"
        )
    ):

        assert detect_gpu() is None


def test_detect_gpu_detects_intel_via_lspci():

    with patch(
        "installer.detect.shutil.which",
        side_effect=lambda name: "/usr/bin/lspci" if name == "lspci" else None
    ), patch(
        "installer.detect.subprocess.run",
        return_value=MagicMock(
            stdout="00:02.0 VGA compatible controller: Intel Corporation UHD Graphics"
        )
    ):

        assert detect_gpu() == "intel"


def test_detect_gpu_returns_none_when_nothing_found():

    with patch("installer.detect.shutil.which", return_value=None):

        assert detect_gpu() is None


def test_detect_render_group_gid_prefers_render():

    def getgrnam_side_effect(name):

        if name == "render":
            return MagicMock(gr_gid=105)

        raise KeyError(name)

    with patch("installer.detect.grp.getgrnam", side_effect=getgrnam_side_effect):

        assert detect_render_group_gid() == 105


def test_detect_render_group_gid_falls_back_to_video():

    def getgrnam_side_effect(name):

        if name == "render":
            raise KeyError(name)

        if name == "video":
            return MagicMock(gr_gid=39)

        raise KeyError(name)

    with patch("installer.detect.grp.getgrnam", side_effect=getgrnam_side_effect):

        assert detect_render_group_gid() == 39


def test_detect_render_group_gid_returns_none_when_neither_exists():

    with patch("installer.detect.grp.getgrnam", side_effect=KeyError):

        assert detect_render_group_gid() is None


def test_detect_host_ip_returns_a_real_address():
    """
    Genuinely unmocked - this machine has a real route out, so this
    exercises the real socket call rather than assuming the technique
    works, matching this project's existing precedent of exercising
    real syscalls where safe (e.g. detect_render_group_gid()'s own
    real-grp.getgrnam tests elsewhere in this project's history).
    """

    result = detect_host_ip()

    assert result is not None
    assert result.count(".") == 3


def test_detect_host_ip_returns_none_on_failure():

    with patch("installer.detect.socket.socket", side_effect=OSError("network unreachable")):

        assert detect_host_ip() is None


def test_detect_docker_when_not_installed():

    with patch("installer.detect.shutil.which", return_value=None):

        result = detect_docker()

    assert result == {
        "docker_installed": False,
        "docker_running": False,
        "docker_compose_v2": False
    }


def test_detect_docker_when_installed_and_running():

    with patch(
        "installer.detect.shutil.which", return_value="/usr/bin/docker"
    ), patch(
        "installer.shell.subprocess.run",
        return_value=MagicMock(returncode=0)
    ):

        result = detect_docker()

    assert result == {
        "docker_installed": True,
        "docker_running": True,
        "docker_compose_v2": True
    }


def test_detect_docker_when_installed_but_daemon_not_running():

    with patch(
        "installer.detect.shutil.which", return_value="/usr/bin/docker"
    ), patch(
        "installer.shell.subprocess.run",
        return_value=MagicMock(returncode=1)
    ):

        result = detect_docker()

    assert result == {
        "docker_installed": True,
        "docker_running": False,
        "docker_compose_v2": False
    }


def test_detect_os_reads_os_release():

    with patch("builtins.open", mock_open(read_data=FAKE_OS_RELEASE)):

        result = detect_os()

    assert result["os_id"] == "fedora"
    assert result["os_pretty_name"] == "Fedora Linux 44 (Workstation Edition)"
    assert result["architecture"]


def test_detect_os_handles_missing_file():

    with patch("builtins.open", side_effect=OSError("no such file")):

        result = detect_os()

    assert result["os_id"] is None
    assert result["os_pretty_name"] is None
    assert result["architecture"]


def test_detect_system_assembles_everything():

    with patch(
        "installer.detect.detect_cpu",
        return_value={
            "cpu_cores_physical": 8, "cpu_cores_logical": 16,
            "cpu_model": "Fake CPU"
        }
    ), patch(
        "installer.detect.detect_memory",
        return_value={"ram_total_gb": 16.0, "ram_available_gb": 8.0}
    ), patch(
        "installer.detect.detect_disk",
        return_value={"disk_free_gb": 500.0, "disk_path_checked": "/"}
    ), patch(
        "installer.detect.detect_gpu", return_value="nvidia"
    ), patch(
        "installer.detect.detect_docker",
        return_value={
            "docker_installed": True, "docker_running": True,
            "docker_compose_v2": True
        }
    ), patch(
        "installer.detect.detect_os",
        return_value={
            "architecture": "x86_64", "os_id": "fedora",
            "os_pretty_name": "Fedora Linux 44"
        }
    ):

        result = detect_system()

    assert result == SystemInfo(
        cpu_cores_physical=8,
        cpu_cores_logical=16,
        cpu_model="Fake CPU",
        ram_total_gb=16.0,
        ram_available_gb=8.0,
        disk_free_gb=500.0,
        disk_path_checked="/",
        gpu_vendor="nvidia",
        docker_installed=True,
        docker_running=True,
        docker_compose_v2=True,
        architecture="x86_64",
        os_id="fedora",
        os_pretty_name="Fedora Linux 44"
    )
