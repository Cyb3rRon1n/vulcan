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
DOCKER_GROUP_ONLY = {
    "docker_installed": True, "docker_running": True,
    "docker_accessible": False, "docker_compose_v2": True,
}
DOCKER_STOPPED = {
    "docker_installed": True, "docker_running": False,
    "docker_accessible": False, "docker_compose_v2": True,
}
DOCKER_NO_COMPOSE = {
    "docker_installed": True, "docker_running": True,
    "docker_accessible": True, "docker_compose_v2": False,
}

_DEPS_OK = {
    "success": True, "packages": [], "installed": [], "missing_after": [], "needs_reboot": False,
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


def test_fix_unsupported_distro_reports_missing_and_does_not_install():
    with patch("installer.phase0.ensure_system_deps", return_value=_DEPS_OK), \
        patch("installer.phase0.detect_docker", return_value=DOCKER_ABSENT), \
        patch("installer.phase0.os.geteuid", return_value=0), \
        patch("installer.phase0.install_plan_for", return_value=None), \
        patch("installer.phase0.install_docker") as install_docker:

        report = phase0.ensure_system_ready(fix=True, user="sentinel")

    install_docker.assert_not_called()
    assert report["ready"] is False
    assert any("no automatic install" in m for m in report["missing"])


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


def test_fix_group_only_adds_user_when_root():
    with patch("installer.phase0.ensure_system_deps", return_value=_DEPS_OK), \
        patch("installer.phase0.detect_docker", return_value=dict(DOCKER_GROUP_ONLY)), \
        patch("installer.phase0.os.geteuid", return_value=0), \
        patch("installer.phase0.install_docker") as install_docker, \
        patch("installer.phase0.start_docker_service") as start_docker_service, \
        patch("installer.phase0.add_user_to_docker_group", return_value={"success": True, "error": None}) as add_group, \
        patch("installer.phase0.check_docker_ready", return_value={"docker_running": True, "docker_compose_v2": True}):

        report = phase0.ensure_system_ready(fix=True, user="sentinel")

    add_group.assert_called_once_with("sentinel")
    install_docker.assert_not_called()
    start_docker_service.assert_not_called()
    assert report["group_added"] is True


def test_fix_group_only_needs_root_when_not_root():
    with patch("installer.phase0.ensure_system_deps", return_value=_DEPS_OK), \
        patch("installer.phase0.detect_docker", return_value=dict(DOCKER_GROUP_ONLY)), \
        patch("installer.phase0.os.geteuid", return_value=1000), \
        patch("installer.phase0.add_user_to_docker_group") as add_group:

        report = phase0.ensure_system_ready(fix=True, user="sentinel")

    assert report["needs_root"] is True
    add_group.assert_not_called()
    assert report["did"] == []


def test_fix_starts_service_then_adds_group_when_stopped():
    calls = []

    with patch("installer.phase0.ensure_system_deps", return_value=_DEPS_OK), \
        patch("installer.phase0.detect_docker", return_value=dict(DOCKER_STOPPED)), \
        patch("installer.phase0.os.geteuid", return_value=0), \
        patch("installer.phase0.install_docker") as install_docker, \
        patch("installer.phase0.start_docker_service", side_effect=lambda *a: calls.append("start")), \
        patch("installer.phase0.add_user_to_docker_group", side_effect=lambda u: calls.append("group") or {"success": True, "error": None}), \
        patch("installer.phase0.check_docker_ready", return_value={"docker_running": True, "docker_compose_v2": True}):

        report = phase0.ensure_system_ready(fix=True, user="sentinel")

    assert calls == ["start", "group"]
    install_docker.assert_not_called()
    assert report["group_added"] is True


def test_fix_compose_v2_only_when_root():
    with patch("installer.phase0.ensure_system_deps", return_value=_DEPS_OK), \
        patch("installer.phase0.detect_docker", return_value=DOCKER_NO_COMPOSE), \
        patch("installer.phase0.os.geteuid", return_value=0), \
        patch("installer.phase0.ensure_compose_v2") as ensure_compose_v2, \
        patch("installer.phase0.add_user_to_docker_group") as add_group:

        report = phase0.ensure_system_ready(fix=True, user="sentinel")

    ensure_compose_v2.assert_called_once()
    add_group.assert_not_called()
    assert report["group_added"] is False


def test_fix_compose_v2_only_needs_root_when_not_root():
    with patch("installer.phase0.ensure_system_deps", return_value=_DEPS_OK), \
        patch("installer.phase0.detect_docker", return_value=DOCKER_NO_COMPOSE), \
        patch("installer.phase0.os.geteuid", return_value=1000), \
        patch("installer.phase0.ensure_compose_v2") as ensure_compose_v2:

        report = phase0.ensure_system_ready(fix=True, user="sentinel")

    assert report["needs_root"] is True
    ensure_compose_v2.assert_not_called()
