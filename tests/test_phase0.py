from unittest.mock import patch

from installer import phase0


DOCKER_READY = {
    "docker_installed": True, "docker_running": True,
    "docker_accessible": True, "docker_compose_v2": True,
}
DOCKER_ABSENT = {
    "docker_installed": False, "docker_running": False,
    "docker_accessible": False, "docker_compose_v2": False,
}


def test_report_only_when_everything_present():
    with patch("installer.phase0.ensure_system_deps", return_value={
        "success": True, "packages": [], "installed": [], "missing_after": [], "needs_reboot": False,
    }), patch("installer.phase0.detect_docker", return_value=DOCKER_READY):

        report = phase0.ensure_system_ready(fix=False)

    assert report["ready"] is True
    assert report["missing"] == []
    assert report["did"] == []


def test_fix_installs_docker_then_starts_then_adds_group_in_order():
    calls = []

    with patch("installer.phase0.ensure_system_deps", return_value={
        "success": True, "packages": [], "installed": [], "missing_after": [], "needs_reboot": False,
    }), patch("installer.phase0.detect_docker", side_effect=[DOCKER_ABSENT, DOCKER_READY]), \
        patch("installer.phase0.os.geteuid", return_value=0), \
        patch("installer.phase0.install_plan_for", return_value={"method": "get.docker.com", "description": "x", "needs_reboot": False}), \
        patch("installer.phase0.install_docker", side_effect=lambda *a: calls.append("install") or {"success": True, "needs_reboot": False, "error": None}), \
        patch("installer.phase0.start_docker_service", side_effect=lambda *a: calls.append("start")), \
        patch("installer.phase0.ensure_compose_v2", side_effect=lambda *a: calls.append("compose")), \
        patch("installer.phase0.add_user_to_docker_group", side_effect=lambda u: calls.append("group") or {"success": True, "error": None}), \
        patch("installer.phase0.check_docker_ready", return_value={"docker_running": True, "docker_compose_v2": True}):

        report = phase0.ensure_system_ready(fix=True, user="sentinel")

    assert calls == ["install", "start", "compose", "group"]
    assert report["ready"] is True
    assert report["group_added"] is True


def test_fix_needs_root_when_not_root_and_docker_missing():
    with patch("installer.phase0.ensure_system_deps", return_value={
        "success": True, "packages": [], "installed": [], "missing_after": [], "needs_reboot": False,
    }), patch("installer.phase0.detect_docker", return_value=DOCKER_ABSENT), \
        patch("installer.phase0.os.geteuid", return_value=1000):

        report = phase0.ensure_system_ready(fix=True, user="sentinel")

    assert report["needs_root"] is True
    assert report["ready"] is False
    assert report["did"] == []


def test_fix_short_circuits_on_rpm_ostree_reboot():
    with patch("installer.phase0.ensure_system_deps", return_value={
        "success": True, "packages": [], "installed": [], "missing_after": [], "needs_reboot": False,
    }), patch("installer.phase0.detect_docker", return_value=DOCKER_ABSENT), \
        patch("installer.phase0.os.geteuid", return_value=0), \
        patch("installer.phase0.install_plan_for", return_value={"method": "rpm-ostree", "description": "x", "needs_reboot": True}), \
        patch("installer.phase0.install_docker", return_value={"success": True, "needs_reboot": True, "error": None}):

        report = phase0.ensure_system_ready(fix=True, user="sentinel")

    assert report["needs_reboot"] is True
    assert report["ready"] is False
