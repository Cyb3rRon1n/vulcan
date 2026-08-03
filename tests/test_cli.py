from pathlib import Path
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

        # media path, tier, customize, gluetun confirm, sabnzbd confirm,
        # recyclarr confirm, PUID, PGID, timezone all hit enter to accept
        # their (previous-state-derived) defaults; the generate confirm has
        # no default so needs an explicit "y", then decline the final start
        # confirm with "n".
        result = runner.invoke(app, ["--plain"], input="\n\n\n\n\n\n\n\n\ny\nn\n")

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
            input="\n\n\nn\n"
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
            input="\n\n\nn\n"
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
            input="\n\n\ny\ny\n"
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
            input="\n\n\ny\n"
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
            input="y\n\n\n\ny\n"
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


def test_docker_bootstrap_offline_skips_install_attempt(tmp_path):

    media_path = str(tmp_path / "media")

    not_ready = make_system_info(
        docker_installed=False, docker_running=False, docker_compose_v2=False
    )

    with patch(
        "installer.cli.detect_system", return_value=not_ready
    ), patch(
        "installer.cli.install_plan_for"
    ) as mock_plan, patch(
        "installer.cli.install_docker"
    ) as mock_install:

        result = runner.invoke(
            app,
            [
                "--tier", "light", "--media-path", media_path,
                "--non-interactive", "--yes", "--offline"
            ]
        )

    assert result.exit_code == 1
    assert "No internet access" in result.output
    mock_plan.assert_not_called()
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
            input="\n\nn\n\n\ny\nn\n"
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
            input="y\n\n\n\ny\n"
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
            input="y\n\n\n\ny\n"
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
            input="\n\n\n\ny\nn\n"
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
            input="nonsense\nlight\n\n\n\ny\nn\n"
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


def test_non_interactive_light_with_explicit_sabnzbd_flag(tmp_path):

    media_path = str(tmp_path / "media")

    with patch(
        "installer.cli.detect_system", return_value=make_system_info()
    ), patch(
        "installer.cli.detect_disk",
        return_value={"disk_free_gb": 900.0, "disk_path_checked": media_path}
    ), patch(
        "installer.cli.write_stack",
        return_value={**READY_WRITE_RESULT, "warnings": ["configure your Usenet provider"]}
    ) as mock_write_stack:

        result = runner.invoke(
            app,
            [
                "--tier", "light", "--media-path", media_path,
                "--non-interactive", "--yes", "--sabnzbd"
            ]
        )

    assert result.exit_code == 0, result.output

    config = mock_write_stack.call_args[0][0]
    assert config.enabled_optional == {"sabnzbd"}
    assert "configure your Usenet provider" in result.output


def test_non_interactive_light_with_explicit_recyclarr_flag(tmp_path):

    media_path = str(tmp_path / "media")

    with patch(
        "installer.cli.detect_system", return_value=make_system_info()
    ), patch(
        "installer.cli.detect_disk",
        return_value={"disk_free_gb": 900.0, "disk_path_checked": media_path}
    ), patch(
        "installer.cli.write_stack",
        return_value={**READY_WRITE_RESULT, "warnings": ["scaffold its own config"]}
    ) as mock_write_stack:

        result = runner.invoke(
            app,
            [
                "--tier", "light", "--media-path", media_path,
                "--non-interactive", "--yes", "--recyclarr"
            ]
        )

    assert result.exit_code == 0, result.output

    config = mock_write_stack.call_args[0][0]
    assert config.enabled_optional == {"recyclarr"}
    assert "scaffold its own config" in result.output


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
            input=f"{prompted_path}\n\n\n\ny\nn\n"
        )

    assert result.exit_code == 0, result.output

    config = mock_write_stack.call_args[0][0]
    assert config.media_path == prompted_path


def test_media_path_shows_storage_description_and_warning(tmp_path):

    media_path = str(tmp_path / "media")

    with patch(
        "installer.cli.detect_system", return_value=make_system_info()
    ), patch(
        "installer.cli.detect_disk",
        return_value={"disk_free_gb": 900.0, "disk_path_checked": media_path}
    ), patch(
        "installer.cli.detect_media_redundancy",
        return_value={
            "device": "/dev/sda1", "filesystem": "ext4", "redundant": False,
            "redundancy_type": None, "device_count": 1
        }
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
    assert "Media storage: /dev/sda1 (ext4, single device - no redundancy)" in result.output
    assert "No drive-level redundancy" in result.output


def test_media_path_redundant_storage_shows_no_warning(tmp_path):

    media_path = str(tmp_path / "media")

    with patch(
        "installer.cli.detect_system", return_value=make_system_info()
    ), patch(
        "installer.cli.detect_disk",
        return_value={"disk_free_gb": 900.0, "disk_path_checked": media_path}
    ), patch(
        "installer.cli.detect_media_redundancy",
        return_value={
            "device": "/dev/md0", "filesystem": "ext4", "redundant": True,
            "redundancy_type": "raid1", "device_count": 2
        }
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
    assert "Media storage: /dev/md0 (ext4, raid1, 2 devices)" in result.output
    assert "No drive-level redundancy" not in result.output


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
            input="\n\n\nn\n"
        )

    assert result.exit_code == 0
    assert "Aborted" in result.output
    mock_write_stack.assert_not_called()


def test_update_no_stack_found_exits_1(tmp_path):

    with patch("installer.cli.STACK_DIR", tmp_path / "stack"):

        result = runner.invoke(app, ["update"])

    assert result.exit_code == 1
    assert "No stack found" in result.output


def test_update_non_interactive_without_yes_exits_1(tmp_path):

    stack_dir = tmp_path / "stack"
    stack_dir.mkdir()
    (stack_dir / "docker-compose.yml").write_text("services: {}\n")

    with patch("installer.cli.STACK_DIR", stack_dir):

        result = runner.invoke(app, ["update", "--non-interactive"])

    assert result.exit_code == 1
    assert "--yes is required" in result.output


def test_update_confirm_declined_aborts(tmp_path):

    stack_dir = tmp_path / "stack"
    stack_dir.mkdir()
    (stack_dir / "docker-compose.yml").write_text("services: {}\n")

    with patch("installer.cli.STACK_DIR", stack_dir), patch(
        "installer.cli.update_stack"
    ) as mock_update:

        result = runner.invoke(app, ["update"], input="n\n")

    assert result.exit_code == 0
    assert "Aborted" in result.output
    mock_update.assert_not_called()


def test_update_confirm_accepted_calls_update_stack(tmp_path):

    stack_dir = tmp_path / "stack"
    stack_dir.mkdir()
    (stack_dir / "docker-compose.yml").write_text("services: {}\n")

    with patch("installer.cli.STACK_DIR", stack_dir), patch(
        "installer.cli.update_stack", return_value={"success": True, "error": None}
    ) as mock_update:

        result = runner.invoke(app, ["update"], input="y\n")

    assert result.exit_code == 0, result.output
    assert "Stack updated" in result.output

    args = mock_update.call_args[0]
    assert args[0] == str(stack_dir / "docker-compose.yml")
    assert args[1] == str(stack_dir / ".env")


def test_update_non_interactive_yes_skips_confirm_and_reports_failure(tmp_path):

    stack_dir = tmp_path / "stack"
    stack_dir.mkdir()
    (stack_dir / "docker-compose.yml").write_text("services: {}\n")

    with patch("installer.cli.STACK_DIR", stack_dir), patch(
        "installer.cli.update_stack",
        return_value={"success": False, "error": "Failed to pull images - check `docker compose logs`."}
    ):

        result = runner.invoke(app, ["update", "--non-interactive", "--yes"])

    assert result.exit_code == 1
    assert "Failed to pull images" in result.output


def test_pull_no_stack_found_exits_1(tmp_path):

    with patch("installer.cli.STACK_DIR", tmp_path / "stack"):

        result = runner.invoke(app, ["pull"])

    assert result.exit_code == 1
    assert "No stack found" in result.output


def test_pull_success_prints_command_reminder(tmp_path):

    stack_dir = tmp_path / "stack"
    stack_dir.mkdir()
    (stack_dir / "docker-compose.yml").write_text("services: {}\n")

    with patch("installer.cli.STACK_DIR", stack_dir), patch(
        "installer.cli.pull_stack", return_value={"success": True, "error": None}
    ) as mock_pull:

        result = runner.invoke(app, ["pull"])

    assert result.exit_code == 0, result.output
    assert "Images pulled" in result.output
    assert "docker compose" in result.output
    assert "--env-file" in result.output

    args = mock_pull.call_args[0]
    assert args[0] == str(stack_dir / "docker-compose.yml")
    assert args[1] == str(stack_dir / ".env")


def test_pull_failure_exits_1(tmp_path):

    stack_dir = tmp_path / "stack"
    stack_dir.mkdir()
    (stack_dir / "docker-compose.yml").write_text("services: {}\n")

    with patch("installer.cli.STACK_DIR", stack_dir), patch(
        "installer.cli.pull_stack",
        return_value={"success": False, "error": "Failed to pull images - check `docker compose logs`."}
    ):

        result = runner.invoke(app, ["pull"])

    assert result.exit_code == 1
    assert "Failed to pull images" in result.output


def test_pull_never_prompts_for_confirmation(tmp_path):

    stack_dir = tmp_path / "stack"
    stack_dir.mkdir()
    (stack_dir / "docker-compose.yml").write_text("services: {}\n")

    with patch("installer.cli.STACK_DIR", stack_dir), patch(
        "installer.cli.pull_stack", return_value={"success": True, "error": None}
    ):

        result = runner.invoke(app, ["pull"], input="")

    assert result.exit_code == 0, result.output


def test_backup_success_prints_path_and_warnings():

    result_dict = {
        "success": True,
        "error": None,
        "backup_path": "/scratch/backups/vulcan-backup-20260101T000000Z.tar.gz",
        "warnings": ["This backup includes stack/.env, which may contain real credentials"]
    }

    with patch("installer.cli.backup_stack", return_value=result_dict):

        result = runner.invoke(app, ["backup"])

    assert result.exit_code == 0, result.output
    assert "vulcan-backup-20260101T000000Z.tar.gz" in result.output
    assert "may contain real credentials" in result.output


def test_backup_failure_exits_1():

    with patch(
        "installer.cli.backup_stack",
        return_value={
            "success": False, "error": "No stack found to back up.",
            "backup_path": None, "warnings": []
        }
    ):

        result = runner.invoke(app, ["backup"])

    assert result.exit_code == 1
    assert "No stack found to back up" in result.output


def test_backup_never_prompts_for_confirmation():

    result_dict = {
        "success": True, "error": None,
        "backup_path": "/scratch/backups/x.tar.gz", "warnings": []
    }

    with patch("installer.cli.backup_stack", return_value=result_dict):

        result = runner.invoke(app, ["backup"], input="")

    assert result.exit_code == 0, result.output


def test_export_success_prints_path():

    with patch(
        "installer.cli.export_images",
        return_value={"success": True, "error": None, "export_path": "/scratch/exports/x.tar"}
    ):

        result = runner.invoke(app, ["export"])

    assert result.exit_code == 0, result.output
    assert "/scratch/exports/x.tar" in result.output


def test_export_failure_exits_1():

    with patch(
        "installer.cli.export_images",
        return_value={"success": False, "error": "No stack found to export.", "export_path": None}
    ):

        result = runner.invoke(app, ["export"])

    assert result.exit_code == 1
    assert "No stack found to export" in result.output


def test_export_passes_explicit_output_path(tmp_path):

    output = str(tmp_path / "custom.tar")

    with patch(
        "installer.cli.export_images",
        return_value={"success": True, "error": None, "export_path": output}
    ) as mock_export:

        result = runner.invoke(app, ["export", "--output", output])

    assert result.exit_code == 0, result.output

    kwargs = mock_export.call_args[1]
    assert kwargs["output_path"] == Path(output)


def test_export_never_prompts_for_confirmation():

    with patch(
        "installer.cli.export_images",
        return_value={"success": True, "error": None, "export_path": "/scratch/exports/x.tar"}
    ):

        result = runner.invoke(app, ["export"], input="")

    assert result.exit_code == 0, result.output


def test_import_no_archive_found_exits_1():

    with patch("installer.cli.latest_export", return_value=None):

        result = runner.invoke(app, ["import"])

    assert result.exit_code == 1
    assert "No image archives found" in result.output


def test_import_defaults_to_latest_export(tmp_path):

    latest = tmp_path / "exports" / "vulcan-images-20260101T000000Z.tar"

    with patch("installer.cli.latest_export", return_value=latest), patch(
        "installer.cli.import_images", return_value={"success": True, "error": None}
    ) as mock_import:

        result = runner.invoke(app, ["import"])

    assert result.exit_code == 0, result.output
    mock_import.assert_called_once_with(str(latest))


def test_import_explicit_file_argument(tmp_path):

    tar_file = str(tmp_path / "custom.tar")

    with patch(
        "installer.cli.import_images", return_value={"success": True, "error": None}
    ) as mock_import:

        result = runner.invoke(app, ["import", tar_file])

    assert result.exit_code == 0, result.output
    mock_import.assert_called_once_with(tar_file)


def test_import_failure_exits_1(tmp_path):

    latest = tmp_path / "exports" / "vulcan-images-20260101T000000Z.tar"

    with patch("installer.cli.latest_export", return_value=latest), patch(
        "installer.cli.import_images",
        return_value={"success": False, "error": "Failed to load images from the archive."}
    ):

        result = runner.invoke(app, ["import"])

    assert result.exit_code == 1
    assert "Failed to load images" in result.output


def test_import_never_prompts_for_confirmation(tmp_path):

    latest = tmp_path / "exports" / "vulcan-images-20260101T000000Z.tar"

    with patch("installer.cli.latest_export", return_value=latest), patch(
        "installer.cli.import_images", return_value={"success": True, "error": None}
    ):

        result = runner.invoke(app, ["import"], input="")

    assert result.exit_code == 0, result.output


def test_restore_no_backup_found_exits_1():

    with patch("installer.cli.latest_backup", return_value=None):

        result = runner.invoke(app, ["restore"])

    assert result.exit_code == 1
    assert "No backup archives found" in result.output


def test_restore_explicit_path_not_found_exits_1(tmp_path):

    result = runner.invoke(app, ["restore", str(tmp_path / "nope.tar.gz")])

    assert result.exit_code == 1
    assert "Backup file not found" in result.output


def test_restore_non_interactive_without_yes_exits_1(tmp_path):

    backup_path = tmp_path / "vulcan-backup-20260101T000000Z.tar.gz"
    backup_path.write_text("fake")

    result = runner.invoke(app, ["restore", str(backup_path), "--non-interactive"])

    assert result.exit_code == 1
    assert "--yes is required" in result.output


def test_restore_confirm_declined_aborts(tmp_path):

    backup_path = tmp_path / "vulcan-backup-20260101T000000Z.tar.gz"
    backup_path.write_text("fake")

    with patch("installer.cli.STACK_DIR", tmp_path / "stack"), patch(
        "installer.cli.restore_stack"
    ) as mock_restore:

        result = runner.invoke(app, ["restore", str(backup_path)], input="n\n")

    assert result.exit_code == 0
    assert "Aborted" in result.output
    mock_restore.assert_not_called()


def test_restore_confirm_accepted_calls_restore_stack(tmp_path):

    backup_path = tmp_path / "vulcan-backup-20260101T000000Z.tar.gz"
    backup_path.write_text("fake")
    stack_dir = tmp_path / "stack"

    with patch("installer.cli.STACK_DIR", stack_dir), patch(
        "installer.cli.restore_stack", return_value={"success": True, "error": None}
    ) as mock_restore:

        result = runner.invoke(app, ["restore", str(backup_path)], input="y\nn\n")

    assert result.exit_code == 0, result.output
    assert "Stack restored" in result.output

    args = mock_restore.call_args[0]
    assert args[0] == backup_path
    assert args[1] == str(stack_dir / "docker-compose.yml")
    assert args[2] == str(stack_dir / ".env")


def test_restore_non_interactive_yes_reports_failure(tmp_path):

    backup_path = tmp_path / "vulcan-backup-20260101T000000Z.tar.gz"
    backup_path.write_text("fake")

    with patch("installer.cli.STACK_DIR", tmp_path / "stack"), patch(
        "installer.cli.restore_stack",
        return_value={"success": False, "error": "'fake.tar.gz' isn't a valid backup archive"}
    ):

        result = runner.invoke(
            app, ["restore", str(backup_path), "--non-interactive", "--yes"]
        )

    assert result.exit_code == 1
    assert "isn't a valid backup archive" in result.output


def test_restore_uses_explicit_backup_file_instead_of_latest(tmp_path):

    backup_path = tmp_path / "vulcan-backup-20260101T000000Z.tar.gz"
    backup_path.write_text("fake")

    with patch("installer.cli.STACK_DIR", tmp_path / "stack"), patch(
        "installer.cli.latest_backup"
    ) as mock_latest, patch(
        "installer.cli.restore_stack", return_value={"success": True, "error": None}
    ):

        result = runner.invoke(
            app, ["restore", str(backup_path), "--non-interactive", "--yes"]
        )

    assert result.exit_code == 0, result.output
    mock_latest.assert_not_called()


def test_restore_defaults_to_latest_backup_when_no_path_given(tmp_path):

    backup_path = tmp_path / "vulcan-backup-20260101T000000Z.tar.gz"
    backup_path.write_text("fake")

    with patch("installer.cli.STACK_DIR", tmp_path / "stack"), patch(
        "installer.cli.latest_backup", return_value=backup_path
    ), patch(
        "installer.cli.restore_stack", return_value={"success": True, "error": None}
    ) as mock_restore:

        result = runner.invoke(app, ["restore", "--non-interactive", "--yes"])

    assert result.exit_code == 0, result.output
    assert mock_restore.call_args[0][0] == backup_path


def test_restore_start_flag_starts_stack(tmp_path):

    backup_path = tmp_path / "vulcan-backup-20260101T000000Z.tar.gz"
    backup_path.write_text("fake")
    stack_dir = tmp_path / "stack"

    up_proc = MagicMock(returncode=0)

    with patch("installer.cli.STACK_DIR", stack_dir), patch(
        "installer.cli.restore_stack", return_value={"success": True, "error": None}
    ), patch(
        "installer.cli.run_docker_command", return_value=up_proc
    ) as mock_run_docker:

        result = runner.invoke(
            app, ["restore", str(backup_path), "--non-interactive", "--yes", "--start"]
        )

    assert result.exit_code == 0, result.output
    assert "Stack is up" in result.output
    mock_run_docker.assert_called_once()

    command = mock_run_docker.call_args[0][0]
    assert command[:2] == ["docker", "compose"]
    assert "up" in command and "-d" in command


def test_restore_start_failure_exits_1(tmp_path):

    backup_path = tmp_path / "vulcan-backup-20260101T000000Z.tar.gz"
    backup_path.write_text("fake")
    stack_dir = tmp_path / "stack"

    up_proc = MagicMock(returncode=1)

    with patch("installer.cli.STACK_DIR", stack_dir), patch(
        "installer.cli.restore_stack", return_value={"success": True, "error": None}
    ), patch(
        "installer.cli.run_docker_command", return_value=up_proc
    ):

        result = runner.invoke(
            app, ["restore", str(backup_path), "--non-interactive", "--yes", "--start"]
        )

    assert result.exit_code == 1
    assert "Failed to start the stack" in result.output


def test_services_unknown_key_rejected_before_detection():

    with patch("installer.cli.detect_system") as mock_detect:

        result = runner.invoke(
            app,
            [
                "--services", "jellyfin,notreal",
                "--non-interactive", "--yes", "--tier", "light", "--media-path", "/tmp/x"
            ]
        )

    assert result.exit_code == 1
    assert "Unknown service(s)" in result.output
    assert "notreal" in result.output
    mock_detect.assert_not_called()


def test_services_non_interactive_sets_custom_services(tmp_path):

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
                "--tier", "light", "--media-path", media_path,
                "--services", "jellyfin,homepage,watchtower",
                "--non-interactive", "--yes"
            ]
        )

    assert result.exit_code == 0, result.output

    config = mock_write_stack.call_args[0][0]
    assert config.custom_services == {"jellyfin", "homepage", "watchtower"}
    assert config.tier.name == "light"


def test_non_interactive_rerun_reuses_previous_custom_services(tmp_path):

    previous_state = {
        "tier": "light", "media_path": str(tmp_path / "previous-media"),
        "puid": 1000, "pgid": 1000, "timezone": "UTC",
        "enabled_optional": [], "gpu_vendor": None,
        "custom_services": ["jellyfin", "homepage"],
        "generated_at": "2026-01-01T00:00:00+00:00"
    }

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
    assert config.custom_services == {"jellyfin", "homepage"}


def test_interactive_customize_accepted_with_edited_service_list(tmp_path):

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
                "--plain", "--tier", "light", "--media-path", media_path,
                "--puid", "1000", "--pgid", "1000", "--timezone", "UTC", "--no-start"
            ],
            input="y\njellyfin,homepage,watchtower\ny\n"
        )

    assert result.exit_code == 0, result.output

    config = mock_write_stack.call_args[0][0]
    assert config.custom_services == {"jellyfin", "homepage", "watchtower"}


def test_interactive_customize_reprompts_on_unknown_service_key(tmp_path):

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
                "--plain", "--tier", "light", "--media-path", media_path,
                "--puid", "1000", "--pgid", "1000", "--timezone", "UTC", "--no-start"
            ],
            input="y\njellyfin,notreal\njellyfin,homepage\ny\n"
        )

    assert result.exit_code == 0, result.output
    assert "Unknown service(s): notreal" in result.output

    config = mock_write_stack.call_args[0][0]
    assert config.custom_services == {"jellyfin", "homepage"}


def test_non_interactive_custom_services_with_traefik_and_domain_flag(tmp_path):

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
                "--tier", "heavy", "--media-path", media_path,
                "--services", "jellyfin,radarr,traefik",
                "--domain", "media.example.com",
                "--non-interactive", "--yes"
            ]
        )

    assert result.exit_code == 0, result.output

    config = mock_write_stack.call_args[0][0]
    assert config.domain == "media.example.com"


def test_domain_flag_ignored_when_traefik_not_in_custom_selection(tmp_path):

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
                "--tier", "light", "--media-path", media_path,
                "--services", "jellyfin,homepage",
                "--domain", "media.example.com",
                "--non-interactive", "--yes"
            ]
        )

    assert result.exit_code == 0, result.output

    config = mock_write_stack.call_args[0][0]
    assert config.domain is None


def test_non_interactive_rerun_reuses_previous_domain(tmp_path):

    previous_state = {
        "tier": "heavy", "media_path": str(tmp_path / "previous-media"),
        "puid": 1000, "pgid": 1000, "timezone": "UTC",
        "enabled_optional": [], "gpu_vendor": None,
        "custom_services": ["jellyfin", "traefik"],
        "domain": "media.example.com",
        "generated_at": "2026-01-01T00:00:00+00:00"
    }

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
    assert config.domain == "media.example.com"


def test_interactive_customize_with_traefik_prompts_for_domain(tmp_path):

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
                "--plain", "--tier", "heavy", "--media-path", media_path,
                "--puid", "1000", "--pgid", "1000", "--timezone", "UTC", "--no-start"
            ],
            input="y\njellyfin,radarr,traefik\nmedia.example.com\ny\n"
        )

    assert result.exit_code == 0, result.output
    assert "Base domain for Traefik routing" in result.output

    config = mock_write_stack.call_args[0][0]
    assert config.domain == "media.example.com"


def test_interactive_customize_with_traefik_domain_left_blank_skips_routing(tmp_path):

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
                "--plain", "--tier", "heavy", "--media-path", media_path,
                "--puid", "1000", "--pgid", "1000", "--timezone", "UTC", "--no-start"
            ],
            input="y\njellyfin,radarr,traefik\n\ny\n"
        )

    assert result.exit_code == 0, result.output

    config = mock_write_stack.call_args[0][0]
    assert config.domain is None


def test_gpu_question_shown_in_custom_mode_even_for_light_tier(tmp_path):

    media_path = str(tmp_path / "media")

    with patch(
        "installer.cli.detect_system", return_value=make_system_info(gpu_vendor="amd")
    ), patch(
        "installer.cli.detect_disk",
        return_value={"disk_free_gb": 900.0, "disk_path_checked": media_path}
    ), patch(
        "installer.cli.write_stack", return_value=READY_WRITE_RESULT
    ) as mock_write_stack:

        result = runner.invoke(
            app,
            [
                "--plain", "--tier", "light", "--media-path", media_path,
                "--puid", "1000", "--pgid", "1000", "--timezone", "UTC", "--no-start"
            ],
            input="y\njellyfin,radarr\ny\ny\n"
        )

    assert result.exit_code == 0, result.output
    assert "Enable hardware transcoding" in result.output

    config = mock_write_stack.call_args[0][0]
    assert config.gpu_vendor == "amd"


def test_gpu_question_not_shown_for_non_custom_light_tier_even_with_gpu_detected(tmp_path):

    media_path = str(tmp_path / "media")

    with patch(
        "installer.cli.detect_system", return_value=make_system_info(gpu_vendor="amd")
    ), patch(
        "installer.cli.detect_disk",
        return_value={"disk_free_gb": 900.0, "disk_path_checked": media_path}
    ), patch(
        "installer.cli.write_stack", return_value=READY_WRITE_RESULT
    ) as mock_write_stack:

        result = runner.invoke(
            app,
            [
                "--plain", "--tier", "light", "--media-path", media_path,
                "--puid", "1000", "--pgid", "1000", "--timezone", "UTC", "--no-start"
            ],
            input="\n\n\ny\n"
        )

    assert result.exit_code == 0, result.output
    assert "Enable hardware transcoding" not in result.output
    assert mock_write_stack.call_args[0][0].gpu_vendor is None


def test_sabnzbd_question_shown_and_accepted_at_light_tier(tmp_path):

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
                "--plain", "--tier", "light", "--media-path", media_path,
                "--puid", "1000", "--pgid", "1000", "--timezone", "UTC", "--no-start"
            ],
            input="\ny\n\ny\n"
        )

    assert result.exit_code == 0, result.output
    assert "Enable SABnzbd" in result.output

    config = mock_write_stack.call_args[0][0]
    assert config.enabled_optional == {"sabnzbd"}


def test_recyclarr_question_shown_and_accepted_at_light_tier(tmp_path):

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
                "--plain", "--tier", "light", "--media-path", media_path,
                "--puid", "1000", "--pgid", "1000", "--timezone", "UTC", "--no-start"
            ],
            input="\n\ny\ny\n"
        )

    assert result.exit_code == 0, result.output
    assert "Enable Recyclarr" in result.output

    config = mock_write_stack.call_args[0][0]
    assert config.enabled_optional == {"recyclarr"}
