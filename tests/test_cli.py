from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from installer.cli import app
from installer.detect import SystemInfo


runner = CliRunner()


def make_system_info(**overrides) -> SystemInfo:

    base = dict(
        cpu_cores_physical=6,
        cpu_cores_logical=12,
        cpu_model="Test CPU",
        ram_total_gb=32.0,
        ram_available_gb=16.0,
        disk_free_gb=900.0,
        disk_path_checked="/",
        gpu_vendor=None,
        docker_installed=True,
        docker_running=True,
        docker_compose_v2=True,
        architecture="x86_64",
        os_id="fedora",
        os_pretty_name="Fedora Linux 44"
    )

    base.update(overrides)

    return SystemInfo(**base)


READY_WRITE_RESULT = {
    "success": True,
    "compose_path": "/scratch/stack/docker-compose.yml",
    "env_path": "/scratch/stack/.env",
    "warnings": []
}

PREVIOUS_STATE = {
    "tier": "medium",
    "media_path": "/mnt/previous-media",
    "puid": 2000,
    "pgid": 2000,
    "timezone": "Europe/London",
    "enabled_optional": ["gluetun"],
    "gpu_vendor": None,
    "generated_at": "2026-07-01T12:00:00+00:00"
}


def test_non_interactive_requires_yes():

    result = runner.invoke(
        app, ["--non-interactive", "--tier", "light", "--media-path", "/tmp/x"]
    )

    assert result.exit_code == 1
    assert "--yes is required" in result.output


def test_non_interactive_requires_tier_and_media_path_without_previous_state():

    with patch("installer.cli.load_previous_state", return_value=None):

        result = runner.invoke(app, ["--non-interactive", "--yes"])

    assert result.exit_code == 1
    assert "--tier and --media-path are required" in result.output


def test_default_interactive_mode_launches_tui():

    with patch("installer.tui.run_tui") as mock_run_tui, patch(
        "installer.cli.run_install"
    ) as mock_run_install:

        result = runner.invoke(app, [])

    assert result.exit_code == 0, result.output
    mock_run_tui.assert_called_once()
    mock_run_install.assert_not_called()


def test_plain_flag_launches_run_install_instead_of_tui():

    with patch("installer.tui.run_tui") as mock_run_tui, patch(
        "installer.cli.run_install"
    ) as mock_run_install:

        result = runner.invoke(app, ["--plain"])

    assert result.exit_code == 0, result.output
    mock_run_tui.assert_not_called()
    mock_run_install.assert_called_once()


def test_non_interactive_mode_never_launches_tui_with_or_without_plain(tmp_path):

    media_path = str(tmp_path / "media")

    with patch("installer.tui.run_tui") as mock_run_tui, patch(
        "installer.cli.detect_system", return_value=make_system_info()
    ), patch(
        "installer.cli.detect_disk",
        return_value={"disk_free_gb": 900.0, "disk_path_checked": media_path}
    ), patch(
        "installer.cli.write_stack", return_value=READY_WRITE_RESULT
    ):

        result = runner.invoke(
            app,
            [
                "--tier", "light", "--media-path", media_path,
                "--non-interactive", "--yes"
            ]
        )

    assert result.exit_code == 0, result.output
    mock_run_tui.assert_not_called()


def test_non_interactive_rerun_uses_previous_state_when_flags_omitted(tmp_path):

    previous_state = {**PREVIOUS_STATE, "media_path": str(tmp_path / "previous-media")}

    with patch(
        "installer.cli.load_previous_state", return_value=previous_state
    ), patch(
        "installer.cli.detect_system", return_value=make_system_info()
    ), patch(
        "installer.cli.detect_disk",
        return_value={"disk_free_gb": 900.0, "disk_path_checked": previous_state["media_path"]}
    ), patch(
        "installer.cli.write_stack", return_value=READY_WRITE_RESULT
    ) as mock_write_stack:

        result = runner.invoke(app, ["--non-interactive", "--yes"])

    assert result.exit_code == 0, result.output

    config = mock_write_stack.call_args[0][0]
    assert config.tier.name == "medium"
    assert config.media_path == previous_state["media_path"]
    assert config.puid == 2000
    assert config.pgid == 2000
    assert config.timezone == "Europe/London"
    assert config.enabled_optional == {"gluetun"}


def test_interactive_rerun_prompts_default_to_previous_values(tmp_path):

    previous_state = {**PREVIOUS_STATE, "media_path": str(tmp_path / "previous-media")}

    with patch(
        "installer.cli.load_previous_state", return_value=previous_state
    ), patch(
        "installer.cli.detect_system", return_value=make_system_info()
    ), patch(
        "installer.cli.detect_disk",
        return_value={"disk_free_gb": 900.0, "disk_path_checked": previous_state["media_path"]}
    ), patch(
        "installer.cli.write_stack", return_value=READY_WRITE_RESULT
    ) as mock_write_stack:

        # media path, tier, gluetun confirm, PUID, PGID, timezone all hit
        # enter to accept their (previous-state-derived) defaults; the
        # generate confirm has no default so needs an explicit "y", then
        # decline the final start confirm with "n".
        result = runner.invoke(app, ["--plain"], input="\n\n\n\n\n\ny\nn\n")

    assert result.exit_code == 0, result.output
    assert "Found an existing" in result.output

    config = mock_write_stack.call_args[0][0]
    assert config.tier.name == "medium"
    assert config.media_path == previous_state["media_path"]
    assert config.puid == 2000
    assert config.pgid == 2000
    assert config.timezone == "Europe/London"
    assert config.enabled_optional == {"gluetun"}


def test_overwrite_confirmation_wording_when_stack_exists(tmp_path):

    stack_dir = tmp_path / "stack"
    stack_dir.mkdir()
    (stack_dir / "docker-compose.yml").write_text("services: {}\n")

    with patch(
        "installer.cli.STACK_DIR", stack_dir
    ), patch(
        "installer.cli.load_previous_state", return_value=None
    ), patch(
        "installer.cli.detect_system", return_value=make_system_info()
    ), patch(
        "installer.cli.detect_disk",
        return_value={"disk_free_gb": 900.0, "disk_path_checked": "/tmp/x"}
    ), patch(
        "installer.cli.write_stack"
    ) as mock_write_stack:

        result = runner.invoke(
            app,
            [
                "--plain", "--tier", "light", "--media-path", str(tmp_path / "media"),
                "--puid", "1000", "--pgid", "1000", "--timezone", "UTC"
            ],
            input="n\n"
        )

    assert result.exit_code == 0
    assert "This will overwrite the existing stack/docker-compose.yml" in result.output
    mock_write_stack.assert_not_called()


def test_generate_confirmation_wording_when_no_stack_exists(tmp_path):

    stack_dir = tmp_path / "stack"

    with patch(
        "installer.cli.STACK_DIR", stack_dir
    ), patch(
        "installer.cli.load_previous_state", return_value=None
    ), patch(
        "installer.cli.detect_system", return_value=make_system_info()
    ), patch(
        "installer.cli.detect_disk",
        return_value={"disk_free_gb": 900.0, "disk_path_checked": "/tmp/x"}
    ), patch(
        "installer.cli.write_stack"
    ) as mock_write_stack:

        result = runner.invoke(
            app,
            [
                "--plain", "--tier", "light", "--media-path", str(tmp_path / "media"),
                "--puid", "1000", "--pgid", "1000", "--timezone", "UTC"
            ],
            input="n\n"
        )

    assert result.exit_code == 0
    assert "Generate the stack with these settings?" in result.output
    assert "overwrite" not in result.output
    mock_write_stack.assert_not_called()


def test_tier_heavy_accepted_non_interactive(tmp_path):

    media_path = str(tmp_path / "media")

    with patch(
        "installer.cli.detect_system", return_value=make_system_info()
    ), patch(
        "installer.cli.detect_disk",
        return_value={"disk_free_gb": 900.0, "disk_path_checked": media_path}
    ), patch(
        "installer.cli.write_stack", return_value=READY_WRITE_RESULT
    ) as mock_write_stack:

        result = runner.invoke(
            app,
            ["--tier", "heavy", "--non-interactive", "--yes", "--media-path", media_path]
        )

    assert result.exit_code == 0, result.output

    config = mock_write_stack.call_args[0][0]
    assert config.tier.name == "heavy"


def test_tier_invalid_value_rejected():

    result = runner.invoke(app, ["--plain", "--tier", "extreme"])

    assert result.exit_code == 1
    assert "must be 'light', 'medium', or 'heavy'" in result.output


def test_non_interactive_heavy_with_gpu_detected_auto_enables(tmp_path):

    media_path = str(tmp_path / "media")

    with patch(
        "installer.cli.detect_system", return_value=make_system_info(gpu_vendor="amd")
    ), patch(
        "installer.cli.detect_disk",
        return_value={"disk_free_gb": 2000.0, "disk_path_checked": media_path}
    ), patch(
        "installer.cli.write_stack", return_value=READY_WRITE_RESULT
    ) as mock_write_stack:

        result = runner.invoke(
            app,
            ["--tier", "heavy", "--media-path", media_path, "--non-interactive", "--yes"]
        )

    assert result.exit_code == 0, result.output

    config = mock_write_stack.call_args[0][0]
    assert config.gpu_vendor == "amd"


def test_non_interactive_heavy_with_no_gpu_flag_disables_it(tmp_path):

    media_path = str(tmp_path / "media")

    with patch(
        "installer.cli.detect_system", return_value=make_system_info(gpu_vendor="amd")
    ), patch(
        "installer.cli.detect_disk",
        return_value={"disk_free_gb": 2000.0, "disk_path_checked": media_path}
    ), patch(
        "installer.cli.write_stack", return_value=READY_WRITE_RESULT
    ) as mock_write_stack:

        result = runner.invoke(
            app,
            [
                "--tier", "heavy", "--media-path", media_path,
                "--non-interactive", "--yes", "--no-gpu"
            ]
        )

    assert result.exit_code == 0, result.output

    config = mock_write_stack.call_args[0][0]
    assert config.gpu_vendor is None


def test_interactive_heavy_gpu_confirm_prompt_accepted(tmp_path):

    media_path = str(tmp_path / "media")

    with patch(
        "installer.cli.detect_system", return_value=make_system_info(gpu_vendor="nvidia")
    ), patch(
        "installer.cli.detect_disk",
        return_value={"disk_free_gb": 2000.0, "disk_path_checked": media_path}
    ), patch(
        "installer.cli.write_stack", return_value=READY_WRITE_RESULT
    ) as mock_write_stack:

        result = runner.invoke(
            app,
            [
                "--plain", "--tier", "heavy", "--media-path", media_path,
                "--puid", "1000", "--pgid", "1000", "--timezone", "UTC", "--no-start"
            ],
            input="y\ny\n"
        )

    assert result.exit_code == 0, result.output
    assert "Enable hardware transcoding" in result.output

    config = mock_write_stack.call_args[0][0]
    assert config.gpu_vendor == "nvidia"


def test_explicit_gpu_flag_skips_confirm_prompt(tmp_path):

    media_path = str(tmp_path / "media")

    with patch(
        "installer.cli.detect_system", return_value=make_system_info(gpu_vendor="amd")
    ), patch(
        "installer.cli.detect_disk",
        return_value={"disk_free_gb": 2000.0, "disk_path_checked": media_path}
    ), patch(
        "installer.cli.write_stack", return_value=READY_WRITE_RESULT
    ) as mock_write_stack:

        result = runner.invoke(
            app,
            [
                "--plain", "--tier", "heavy", "--media-path", media_path,
                "--puid", "1000", "--pgid", "1000", "--timezone", "UTC",
                "--no-start", "--gpu"
            ],
            input="y\n"
        )

    assert result.exit_code == 0, result.output
    assert "Enable hardware transcoding" not in result.output

    config = mock_write_stack.call_args[0][0]
    assert config.gpu_vendor == "amd"


def test_full_non_interactive_run_generates_stack_without_starting(tmp_path):

    media_path = str(tmp_path / "media")

    with patch(
        "installer.cli.detect_system", return_value=make_system_info()
    ), patch(
        "installer.cli.detect_disk",
        return_value={"disk_free_gb": 900.0, "disk_path_checked": media_path}
    ), patch(
        "installer.cli.write_stack", return_value=READY_WRITE_RESULT
    ) as mock_write_stack, patch(
        "installer.cli.run_docker_command"
    ) as mock_run_docker:

        result = runner.invoke(
            app,
            [
                "--tier", "light",
                "--media-path", media_path,
                "--non-interactive",
                "--yes"
            ]
        )

    assert result.exit_code == 0, result.output
    mock_write_stack.assert_called_once()

    config = mock_write_stack.call_args[0][0]
    assert config.tier.name == "light"
    assert config.media_path == media_path

    mock_run_docker.assert_not_called()


def test_non_interactive_with_start_calls_run_docker_command(tmp_path):

    media_path = str(tmp_path / "media")
    mock_proc = MagicMock(returncode=0)

    with patch(
        "installer.cli.detect_system", return_value=make_system_info()
    ), patch(
        "installer.cli.detect_disk",
        return_value={"disk_free_gb": 900.0, "disk_path_checked": media_path}
    ), patch(
        "installer.cli.write_stack", return_value=READY_WRITE_RESULT
    ), patch(
        "installer.cli.run_docker_command", return_value=mock_proc
    ) as mock_run_docker:

        result = runner.invoke(
            app,
            [
                "--tier", "light",
                "--media-path", media_path,
                "--non-interactive",
                "--yes",
                "--start"
            ]
        )

    assert result.exit_code == 0, result.output
    mock_run_docker.assert_called_once()

    args, kwargs = mock_run_docker.call_args
    command = args[0]

    assert command[:2] == ["docker", "compose"]
    assert "up" in command and "-d" in command
    assert kwargs["use_group_workaround"] is False


def test_docker_bootstrap_installs_when_not_ready_in_order(tmp_path):

    media_path = str(tmp_path / "media")

    not_ready = make_system_info(
        docker_installed=False, docker_running=False, docker_compose_v2=False,
        os_id="fedora"
    )

    parent = MagicMock()

    with patch(
        "installer.cli.detect_system", return_value=not_ready
    ), patch(
        "installer.cli.detect_docker",
        return_value={
            "docker_installed": True, "docker_running": True, "docker_compose_v2": True
        }
    ), patch(
        "installer.cli.install_docker"
    ) as mock_install, patch(
        "installer.cli.start_docker_service"
    ) as mock_start, patch(
        "installer.cli.add_user_to_docker_group"
    ) as mock_add_group, patch(
        "installer.cli.ensure_compose_v2"
    ) as mock_compose, patch(
        "installer.cli.detect_disk",
        return_value={"disk_free_gb": 900.0, "disk_path_checked": media_path}
    ), patch(
        "installer.cli.write_stack", return_value=READY_WRITE_RESULT
    ):

        parent.attach_mock(mock_install, "install_docker")
        parent.attach_mock(mock_start, "start_docker_service")
        parent.attach_mock(mock_add_group, "add_user_to_docker_group")
        parent.attach_mock(mock_compose, "ensure_compose_v2")

        result = runner.invoke(
            app,
            [
                "--plain",
                "--tier", "light",
                "--media-path", media_path,
                "--puid", "1000",
                "--pgid", "1000",
                "--timezone", "UTC",
                "--no-start"
            ],
            input="y\ny\n"
        )

    assert result.exit_code == 0, result.output

    mock_install.assert_called_once()
    mock_start.assert_called_once()
    mock_add_group.assert_called_once()
    mock_compose.assert_called_once()

    call_order = [call[0] for call in parent.mock_calls]
    assert call_order == [
        "install_docker", "start_docker_service", "add_user_to_docker_group", "ensure_compose_v2"
    ]


def test_docker_bootstrap_unsupported_distro_exits_cleanly(tmp_path):

    media_path = str(tmp_path / "media")

    not_ready = make_system_info(
        docker_installed=False, docker_running=False, docker_compose_v2=False,
        os_id="gentoo"
    )

    with patch(
        "installer.cli.detect_system", return_value=not_ready
    ), patch(
        "installer.cli.install_plan_for", return_value=None
    ), patch(
        "installer.cli.install_docker"
    ) as mock_install:

        result = runner.invoke(
            app,
            ["--tier", "light", "--media-path", media_path, "--non-interactive", "--yes"]
        )

    assert result.exit_code == 1
    assert "No known automatic install method" in result.output
    mock_install.assert_not_called()


def test_interactive_full_run_with_prompts(tmp_path):

    media_path = str(tmp_path / "media")

    info = make_system_info(
        disk_free_gb=600.0, ram_total_gb=16.0,
        cpu_cores_logical=6, cpu_cores_physical=6
    )

    with patch(
        "installer.cli.detect_system", return_value=info
    ), patch(
        "installer.cli.detect_disk",
        return_value={"disk_free_gb": 600.0, "disk_path_checked": media_path}
    ), patch(
        "installer.cli.write_stack", return_value=READY_WRITE_RESULT
    ) as mock_write_stack, patch(
        "installer.cli.run_docker_command"
    ) as mock_run_docker:

        result = runner.invoke(
            app,
            [
                "--plain", "--media-path", media_path,
                "--puid", "1000", "--pgid", "1000", "--timezone", "UTC"
            ],
            input="\nn\ny\nn\n"
        )

    assert result.exit_code == 0, result.output
    mock_write_stack.assert_called_once()

    config = mock_write_stack.call_args[0][0]
    assert config.tier.name == "medium"
    assert config.enabled_optional == set()

    mock_run_docker.assert_not_called()


def test_docker_installed_but_not_running_starts_service(tmp_path):

    media_path = str(tmp_path / "media")

    not_running = make_system_info(docker_running=False, docker_compose_v2=False)

    with patch(
        "installer.cli.detect_system", return_value=not_running
    ), patch(
        "installer.cli.detect_docker",
        return_value={
            "docker_installed": True, "docker_running": True, "docker_compose_v2": True
        }
    ), patch(
        "installer.cli.start_docker_service"
    ) as mock_start, patch(
        "installer.cli.install_docker"
    ) as mock_install, patch(
        "installer.cli.detect_disk",
        return_value={"disk_free_gb": 900.0, "disk_path_checked": media_path}
    ), patch(
        "installer.cli.write_stack", return_value=READY_WRITE_RESULT
    ):

        result = runner.invoke(
            app,
            [
                "--plain", "--tier", "light", "--media-path", media_path,
                "--puid", "1000", "--pgid", "1000", "--timezone", "UTC", "--no-start"
            ],
            input="y\ny\n"
        )

    assert result.exit_code == 0, result.output
    mock_start.assert_called_once()
    mock_install.assert_not_called()


def test_docker_running_but_missing_compose_v2(tmp_path):

    media_path = str(tmp_path / "media")

    no_compose = make_system_info(docker_compose_v2=False)

    with patch(
        "installer.cli.detect_system", return_value=no_compose
    ), patch(
        "installer.cli.detect_docker",
        return_value={
            "docker_installed": True, "docker_running": True, "docker_compose_v2": True
        }
    ), patch(
        "installer.cli.ensure_compose_v2"
    ) as mock_compose, patch(
        "installer.cli.detect_disk",
        return_value={"disk_free_gb": 900.0, "disk_path_checked": media_path}
    ), patch(
        "installer.cli.write_stack", return_value=READY_WRITE_RESULT
    ):

        result = runner.invoke(
            app,
            [
                "--plain", "--tier", "light", "--media-path", media_path,
                "--puid", "1000", "--pgid", "1000", "--timezone", "UTC", "--no-start"
            ],
            input="y\ny\n"
        )

    assert result.exit_code == 0, result.output
    mock_compose.assert_called_once()


def test_heavy_recommendation_is_offered_as_the_default_choice(tmp_path):

    media_path = str(tmp_path / "media")

    heavy_capable = make_system_info(
        cpu_cores_logical=8, cpu_cores_physical=8, ram_total_gb=32.0, disk_free_gb=2000.0
    )

    with patch(
        "installer.cli.detect_system", return_value=heavy_capable
    ), patch(
        "installer.cli.detect_disk",
        return_value={"disk_free_gb": 2000.0, "disk_path_checked": media_path}
    ), patch(
        "installer.cli.write_stack", return_value=READY_WRITE_RESULT
    ) as mock_write_stack:

        result = runner.invoke(
            app,
            [
                "--plain", "--media-path", media_path,
                "--puid", "1000", "--pgid", "1000", "--timezone", "UTC"
            ],
            input="\ny\nn\n"
        )

    assert result.exit_code == 0, result.output

    config = mock_write_stack.call_args[0][0]
    assert config.tier.name == "heavy"


def test_invalid_tier_input_reprompts_until_valid(tmp_path):

    media_path = str(tmp_path / "media")

    with patch(
        "installer.cli.detect_system", return_value=make_system_info()
    ), patch(
        "installer.cli.detect_disk",
        return_value={"disk_free_gb": 900.0, "disk_path_checked": media_path}
    ), patch(
        "installer.cli.write_stack", return_value=READY_WRITE_RESULT
    ) as mock_write_stack:

        result = runner.invoke(
            app,
            [
                "--plain", "--media-path", media_path,
                "--puid", "1000", "--pgid", "1000", "--timezone", "UTC"
            ],
            input="nonsense\nlight\ny\nn\n"
        )

    assert result.exit_code == 0, result.output

    config = mock_write_stack.call_args[0][0]
    assert config.tier.name == "light"


def test_non_interactive_medium_with_explicit_vpn_flag(tmp_path):

    media_path = str(tmp_path / "media")

    with patch(
        "installer.cli.detect_system", return_value=make_system_info()
    ), patch(
        "installer.cli.detect_disk",
        return_value={"disk_free_gb": 900.0, "disk_path_checked": media_path}
    ), patch(
        "installer.cli.write_stack",
        return_value={**READY_WRITE_RESULT, "warnings": ["fill in your VPN credentials"]}
    ) as mock_write_stack:

        result = runner.invoke(
            app,
            [
                "--tier", "medium", "--media-path", media_path,
                "--non-interactive", "--yes", "--vpn"
            ]
        )

    assert result.exit_code == 0, result.output

    config = mock_write_stack.call_args[0][0]
    assert config.enabled_optional == {"gluetun"}
    assert "fill in your VPN credentials" in result.output


def test_write_stack_oserror_reported_cleanly(tmp_path):

    media_path = str(tmp_path / "media")

    with patch(
        "installer.cli.detect_system", return_value=make_system_info()
    ), patch(
        "installer.cli.detect_disk",
        return_value={"disk_free_gb": 900.0, "disk_path_checked": media_path}
    ), patch(
        "installer.cli.write_stack", side_effect=OSError("permission denied")
    ):

        result = runner.invoke(
            app,
            ["--tier", "light", "--media-path", media_path, "--non-interactive", "--yes"]
        )

    assert result.exit_code == 1
    assert "Failed to write the stack" in result.output


def test_run_docker_command_failure_reported_cleanly(tmp_path):

    media_path = str(tmp_path / "media")
    mock_proc = MagicMock(returncode=1)

    with patch(
        "installer.cli.detect_system", return_value=make_system_info()
    ), patch(
        "installer.cli.detect_disk",
        return_value={"disk_free_gb": 900.0, "disk_path_checked": media_path}
    ), patch(
        "installer.cli.write_stack", return_value=READY_WRITE_RESULT
    ), patch(
        "installer.cli.run_docker_command", return_value=mock_proc
    ):

        result = runner.invoke(
            app,
            [
                "--tier", "light", "--media-path", media_path,
                "--non-interactive", "--yes", "--start"
            ]
        )

    assert result.exit_code == 1
    assert "Failed to start the stack" in result.output


def test_media_path_prompted_when_not_passed(tmp_path):

    prompted_path = str(tmp_path / "prompted-media")

    with patch(
        "installer.cli.detect_system", return_value=make_system_info()
    ), patch(
        "installer.cli.detect_disk",
        return_value={"disk_free_gb": 900.0, "disk_path_checked": prompted_path}
    ), patch(
        "installer.cli.write_stack", return_value=READY_WRITE_RESULT
    ) as mock_write_stack:

        result = runner.invoke(
            app,
            [
                "--plain", "--tier", "light",
                "--puid", "1000", "--pgid", "1000", "--timezone", "UTC"
            ],
            input=f"{prompted_path}\ny\nn\n"
        )

    assert result.exit_code == 0, result.output

    config = mock_write_stack.call_args[0][0]
    assert config.media_path == prompted_path


def test_media_path_creation_failure_reported_cleanly():

    with patch(
        "installer.cli.detect_system", return_value=make_system_info()
    ), patch(
        "installer.cli.Path.mkdir", side_effect=OSError("permission denied")
    ):

        result = runner.invoke(
            app,
            [
                "--tier", "light", "--media-path", "/root/no-access",
                "--non-interactive", "--yes"
            ]
        )

    assert result.exit_code == 1
    assert "Can't create media path" in result.output


def test_declining_generate_confirm_aborts(tmp_path):

    media_path = str(tmp_path / "media")

    with patch(
        "installer.cli.detect_system", return_value=make_system_info()
    ), patch(
        "installer.cli.detect_disk",
        return_value={"disk_free_gb": 900.0, "disk_path_checked": media_path}
    ), patch(
        "installer.cli.write_stack"
    ) as mock_write_stack:

        result = runner.invoke(
            app,
            [
                "--plain", "--tier", "light", "--media-path", media_path,
                "--puid", "1000", "--pgid", "1000", "--timezone", "UTC"
            ],
            input="n\n"
        )

    assert result.exit_code == 0
    assert "Aborted" in result.output
    mock_write_stack.assert_not_called()
