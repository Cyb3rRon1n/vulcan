from unittest.mock import MagicMock, mock_open, patch

from installer.detect import (
    SystemInfo,
    detect_cpu,
    detect_disk,
    detect_docker,
    detect_gpu,
    detect_memory,
    detect_os,
    detect_system,
)


FAKE_CPUINFO = (
    "processor\t: 0\n"
    "vendor_id\t: GenuineIntel\n"
    "model name\t: Intel(R) Core(TM) i7-9700K CPU @ 3.60GHz\n"
    "cpu MHz\t\t: 3600.000\n"
)

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


def test_detect_gpu_detects_nvidia():

    with patch(
        "installer.detect.shutil.which",
        side_effect=lambda name: "/usr/bin/nvidia-smi" if name == "nvidia-smi" else None
    ):

        assert detect_gpu() == "nvidia"


def test_detect_gpu_detects_amd():

    with patch(
        "installer.detect.shutil.which",
        side_effect=lambda name: "/usr/bin/rocm-smi" if name == "rocm-smi" else None
    ):

        assert detect_gpu() == "amd"


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
        "installer.detect.subprocess.run",
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
        "installer.detect.subprocess.run",
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
