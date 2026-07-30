from unittest.mock import MagicMock, patch

from installer.docker_setup import (
    add_user_to_docker_group,
    ensure_compose_v2,
    install_docker,
    install_plan_for,
    run_docker_command,
    start_docker_service,
)


def test_install_plan_for_docker_script_distros():

    for os_id in ("ubuntu", "debian", "raspbian", "fedora"):

        plan = install_plan_for(os_id)

        assert plan["method"] == "get.docker.com"


def test_install_plan_for_arch():

    plan = install_plan_for("arch")

    assert plan["method"] == "pacman"


def test_install_plan_for_unsupported_distro():

    assert install_plan_for("gentoo") is None
    assert install_plan_for(None) is None


def test_install_docker_runs_get_docker_script_for_ubuntu():

    with patch(
        "installer.docker_setup.run_privileged",
        return_value={"success": True, "error": None}
    ) as mock_run:

        result = install_docker("ubuntu")

    assert result == {"success": True, "error": None, "method": "get.docker.com"}
    mock_run.assert_called_once_with(
        ["sh", "-c", "curl -fsSL https://get.docker.com | sh"]
    )


def test_install_docker_runs_pacman_for_arch():

    with patch(
        "installer.docker_setup.run_privileged",
        return_value={"success": True, "error": None}
    ) as mock_run:

        result = install_docker("arch")

    assert result == {"success": True, "error": None, "method": "pacman"}
    mock_run.assert_called_once_with(
        ["pacman", "-Sy", "--noconfirm", "docker"]
    )


def test_install_docker_returns_clean_failure_for_unsupported_distro():

    result = install_docker("gentoo")

    assert result == {
        "success": False,
        "error": "No known install method for 'gentoo'",
        "method": None
    }


def test_ensure_compose_v2_short_circuits_when_already_working():

    with patch("installer.docker_setup.run_ok", return_value=True), patch(
        "installer.docker_setup.run_privileged"
    ) as mock_run_privileged:

        result = ensure_compose_v2("fedora")

    assert result == {"success": True, "error": None}
    mock_run_privileged.assert_not_called()


def test_ensure_compose_v2_arch_fallback_succeeds():

    with patch(
        "installer.docker_setup.run_ok", side_effect=[False, True]
    ), patch(
        "installer.docker_setup.run_privileged",
        return_value={"success": True, "error": None}
    ) as mock_run_privileged:

        result = ensure_compose_v2("arch")

    assert result == {"success": True, "error": None}
    mock_run_privileged.assert_called_once_with(
        ["pacman", "-S", "--noconfirm", "docker-compose"]
    )


def test_ensure_compose_v2_still_fails_after_arch_fallback():

    with patch(
        "installer.docker_setup.run_ok", side_effect=[False, False]
    ), patch(
        "installer.docker_setup.run_privileged",
        return_value={"success": True, "error": None}
    ):

        result = ensure_compose_v2("arch")

    assert result == {
        "success": False,
        "error": "docker compose v2 not available after install"
    }


def test_ensure_compose_v2_non_arch_fails_without_fallback_attempt():

    with patch("installer.docker_setup.run_ok", return_value=False), patch(
        "installer.docker_setup.run_privileged"
    ) as mock_run_privileged:

        result = ensure_compose_v2("fedora")

    assert result == {
        "success": False,
        "error": "docker compose v2 not available after install"
    }
    mock_run_privileged.assert_not_called()


def test_add_user_to_docker_group_calls_usermod():

    with patch(
        "installer.docker_setup.run_privileged",
        return_value={"success": True, "error": None}
    ) as mock_run:

        result = add_user_to_docker_group("sentinel")

    assert result == {"success": True, "error": None}
    mock_run.assert_called_once_with(["usermod", "-aG", "docker", "sentinel"])


def test_start_docker_service_calls_systemctl():

    with patch(
        "installer.docker_setup.run_privileged",
        return_value={"success": True, "error": None}
    ) as mock_run:

        result = start_docker_service()

    assert result == {"success": True, "error": None}
    mock_run.assert_called_once_with(
        ["systemctl", "enable", "--now", "docker"]
    )


def test_run_docker_command_plain_when_no_workaround_needed():

    with patch(
        "installer.docker_setup.subprocess.run",
        return_value=MagicMock(returncode=0)
    ) as mock_run:

        run_docker_command(["docker", "ps"])

    mock_run.assert_called_once_with(["docker", "ps"])


def test_run_docker_command_uses_sg_when_workaround_needed_and_available():

    with patch(
        "installer.docker_setup.shutil.which", return_value="/usr/bin/sg"
    ), patch(
        "installer.docker_setup.subprocess.run",
        return_value=MagicMock(returncode=0)
    ) as mock_run:

        run_docker_command(
            ["docker", "compose", "-f", "my compose.yml", "up", "-d"],
            use_group_workaround=True
        )

    mock_run.assert_called_once_with(
        [
            "sg", "docker", "-c",
            "docker compose -f 'my compose.yml' up -d"
        ]
    )


def test_run_docker_command_falls_back_to_sudo_when_sg_missing():

    with patch(
        "installer.docker_setup.shutil.which", return_value=None
    ), patch(
        "installer.docker_setup.subprocess.run",
        return_value=MagicMock(returncode=0)
    ) as mock_run:

        run_docker_command(["docker", "ps"], use_group_workaround=True)

    mock_run.assert_called_once_with(["sudo", "docker", "ps"])
