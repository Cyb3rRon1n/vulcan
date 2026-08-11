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
        os_pretty_name="Fedora Linux 44",
        os_is_atomic=False
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
        # recyclarr confirm, homepage confirm, metube confirm, downtify
        # confirm, netdata confirm, vaultwarden confirm, dashy confirm,
        # PUID, PGID, timezone all hit enter to accept their
        # (previous-state-derived) defaults; the generate confirm has no
        # default so needs an explicit "y", then decline the final start
        # confirm with "n".
        result = runner.invoke(app, ["--plain"], input="\n\n\n\n\n\n\n\n\n\n\n\n\n\n\ny\nn\n")

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
            input="\n\n\n\n\n\n\n\n\n\nn\n"
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
            input="\n\n\n\n\n\n\n\n\n\nn\n"
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
            input="\n\n\n\n\n\n\n\n\n\ny\ny\n"
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
            input="\n\n\n\n\n\n\n\n\n\ny\n"
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
        "installer.cli.check_ports_available",
        return_value={"available": True, "conflicts": []}
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


def test_start_success_prints_service_url_summary(tmp_path):

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
        "installer.cli.check_ports_available",
        return_value={"available": True, "conflicts": []}
    ), patch(
        "installer.cli.detect_host_ip", return_value="192.168.1.50"
    ), patch(
        "installer.cli.run_docker_command", return_value=mock_proc
    ):

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
    assert "Stack is up" in result.output
    assert "Jellyfin: http://192.168.1.50:8096" in result.output
    assert "Radarr: http://192.168.1.50:7878" in result.output


def test_start_aborts_cleanly_on_port_conflict(tmp_path):

    media_path = str(tmp_path / "media")

    with patch(
        "installer.cli.detect_system", return_value=make_system_info()
    ), patch(
        "installer.cli.detect_disk",
        return_value={"disk_free_gb": 900.0, "disk_path_checked": media_path}
    ), patch(
        "installer.cli.write_stack", return_value=READY_WRITE_RESULT
    ), patch(
        "installer.cli.check_ports_available",
        return_value={"available": False, "conflicts": [8080], "owners": {8080: None}}
    ), patch(
        "installer.cli.run_docker_command"
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

    assert result.exit_code == 1
    assert "8080" in result.output
    mock_run_docker.assert_not_called()


def test_start_aborts_with_identified_port_owner_in_output(tmp_path):

    media_path = str(tmp_path / "media")

    with patch(
        "installer.cli.detect_system", return_value=make_system_info()
    ), patch(
        "installer.cli.detect_disk",
        return_value={"disk_free_gb": 900.0, "disk_path_checked": media_path}
    ), patch(
        "installer.cli.write_stack", return_value=READY_WRITE_RESULT
    ), patch(
        "installer.cli.check_ports_available",
        return_value={
            "available": False,
            "conflicts": [8080],
            "owners": {8080: 'container "homepage-old" (image ghcr.io/gethomepage/homepage:latest)'}
        }
    ), patch(
        "installer.cli.run_docker_command"
    ):

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

    assert result.exit_code == 1
    assert "homepage-old" in result.output


def test_interactive_start_remaps_conflicting_port_and_retries(tmp_path):
    """
    The real port-conflict-override flow: a remappable conflict no
    longer just refuses - typing a new port regenerates the stack
    (write_stack called a second time with the override set) and
    re-checks for real before starting.
    """

    media_path = str(tmp_path / "media")
    mock_proc = MagicMock(returncode=0)

    conflict_then_clear = [
        {
            "available": False,
            "conflicts": [8096],
            "owners": {8096: None},
            "port_services": {8096: "jellyfin"},
            "own_orphan": {8096: False},
        },
        {"available": True, "conflicts": [], "owners": {}, "port_services": {}, "own_orphan": {}},
    ]

    with patch(
        "installer.cli.detect_system", return_value=make_system_info()
    ), patch(
        "installer.cli.detect_disk",
        return_value={"disk_free_gb": 900.0, "disk_path_checked": media_path}
    ), patch(
        "installer.cli.write_stack", return_value=READY_WRITE_RESULT
    ) as mock_write_stack, patch(
        "installer.cli.check_ports_available", side_effect=conflict_then_clear
    ), patch(
        "installer.cli.run_docker_command", return_value=mock_proc
    ):

        result = runner.invoke(
            app,
            [
                "--plain", "--tier", "light",
                "--media-path", media_path,
                "--puid", "1000", "--pgid", "1000", "--timezone", "UTC"
            ],
            input="\n\n\n\n\n\n\n\n\n\ny\ny\n9096\n"
        )

    assert result.exit_code == 0, result.output
    assert "Stack is up" in result.output

    assert mock_write_stack.call_count == 2
    regenerated_config = mock_write_stack.call_args_list[1][0][0]
    assert regenerated_config.port_overrides == {"jellyfin": 9096}


def test_interactive_start_own_orphan_conflict_cleans_up_and_retries(tmp_path):
    """
    The other real case the diagnosis distinguishes: your own orphaned
    containers from a previous stack get cleaned up automatically
    (confirmed) rather than remapped - remove_orphaned_containers(),
    not uninstall_stack(), since stack/ here is the fresh compose file
    this run just wrote, not a stale one.
    """

    media_path = str(tmp_path / "media")
    mock_proc = MagicMock(returncode=0)

    conflict_then_clear = [
        {
            "available": False,
            "conflicts": [8080],
            "owners": {8080: 'your own orphaned containers from a previous stack (project "stack")'},
            "port_services": {8080: "qbittorrent"},
            "own_orphan": {8080: True},
        },
        {"available": True, "conflicts": [], "owners": {}, "port_services": {}, "own_orphan": {}},
    ]

    with patch(
        "installer.cli.detect_system", return_value=make_system_info()
    ), patch(
        "installer.cli.detect_disk",
        return_value={"disk_free_gb": 900.0, "disk_path_checked": media_path}
    ), patch(
        "installer.cli.write_stack", return_value=READY_WRITE_RESULT
    ), patch(
        "installer.cli.check_ports_available", side_effect=conflict_then_clear
    ), patch(
        "installer.cli.remove_orphaned_containers", return_value={"success": True, "error": None}
    ) as mock_cleanup, patch(
        "installer.cli.run_docker_command", return_value=mock_proc
    ):

        result = runner.invoke(
            app,
            [
                "--plain", "--tier", "light",
                "--media-path", media_path,
                "--puid", "1000", "--pgid", "1000", "--timezone", "UTC"
            ],
            input="\n\n\n\n\n\n\n\n\n\ny\ny\ny\n"
        )

    assert result.exit_code == 0, result.output
    assert "Stack is up" in result.output
    mock_cleanup.assert_called_once_with("stack")


def test_interactive_start_own_orphan_multiple_ports_confirms_once(tmp_path):
    """
    Real bug found only by testing against real orphaned containers,
    not by any mocked test: remove_orphaned_containers() tears down the
    whole orphaned project in one call, but multiple conflicting ports
    from that same project each independently reported own_orphan=True
    - asking once per port meant every port after the first just
    re-asked to clean up containers that were already gone. Confirmed
    for real: a 5-port conflict from one leftover stack needed exactly
    one confirm before the fix's own_orphan_cleaned dedup, not five.
    """

    media_path = str(tmp_path / "media")
    mock_proc = MagicMock(returncode=0)

    conflict_then_clear = [
        {
            "available": False,
            "conflicts": [7878, 8080, 8096],
            "owners": {port: 'your own orphaned containers from a previous stack (project "stack")' for port in (7878, 8080, 8096)},
            "port_services": {7878: "radarr", 8080: "qbittorrent", 8096: "jellyfin"},
            "own_orphan": {7878: True, 8080: True, 8096: True},
        },
        {"available": True, "conflicts": [], "owners": {}, "port_services": {}, "own_orphan": {}},
    ]

    with patch(
        "installer.cli.detect_system", return_value=make_system_info()
    ), patch(
        "installer.cli.detect_disk",
        return_value={"disk_free_gb": 900.0, "disk_path_checked": media_path}
    ), patch(
        "installer.cli.write_stack", return_value=READY_WRITE_RESULT
    ), patch(
        "installer.cli.check_ports_available", side_effect=conflict_then_clear
    ), patch(
        "installer.cli.remove_orphaned_containers", return_value={"success": True, "error": None}
    ) as mock_cleanup, patch(
        "installer.cli.run_docker_command", return_value=mock_proc
    ):

        # Only one "y" for the cleanup confirm, despite three
        # conflicting ports - if the dedup regresses, this run starves
        # for input on the second/third port's confirm and the
        # invocation fails instead of reaching "Stack is up".
        result = runner.invoke(
            app,
            [
                "--plain", "--tier", "light",
                "--media-path", media_path,
                "--puid", "1000", "--pgid", "1000", "--timezone", "UTC"
            ],
            input="\n\n\n\n\n\n\n\n\n\ny\ny\ny\n"
        )

    assert result.exit_code == 0, result.output
    assert "Stack is up" in result.output
    mock_cleanup.assert_called_once_with("stack")


def test_interactive_start_port_conflict_give_up_exits_1(tmp_path):

    media_path = str(tmp_path / "media")

    always_conflicted = {
        "available": False,
        "conflicts": [80],
        "owners": {80: None},
        "port_services": {80: "traefik"},
        "own_orphan": {80: False},
    }

    with patch(
        "installer.cli.detect_system", return_value=make_system_info()
    ), patch(
        "installer.cli.detect_disk",
        return_value={"disk_free_gb": 900.0, "disk_path_checked": media_path}
    ), patch(
        "installer.cli.write_stack", return_value=READY_WRITE_RESULT
    ), patch(
        "installer.cli.check_ports_available", return_value=always_conflicted
    ), patch(
        "installer.cli.run_docker_command"
    ) as mock_run_docker:

        result = runner.invoke(
            app,
            [
                "--plain", "--tier", "light",
                "--media-path", media_path,
                "--puid", "1000", "--pgid", "1000", "--timezone", "UTC"
            ],
            input="\n\n\n\n\n\n\n\n\n\ny\ny\n"
        )

    assert result.exit_code == 1
    assert "can't be remapped automatically" in result.output
    mock_run_docker.assert_not_called()


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
            "docker_installed": True, "docker_running": False, "docker_compose_v2": True
        }
    ), patch(
        "installer.cli.check_docker_ready",
        return_value={"docker_running": True, "docker_compose_v2": True}
    ), patch(
        "installer.cli.install_docker",
        return_value={"success": True, "error": None, "method": "get.docker.com", "needs_reboot": False}
    ) as mock_install, patch(
        "installer.cli.start_docker_service"
    ) as mock_start, patch(
        "installer.cli.add_user_to_docker_group",
        return_value={"success": True, "error": None}
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
            input="y\n\n\n\n\n\n\n\n\n\n\ny\n"
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
            input="\n\nn\n\n\nn\n\n\n\n\n\ny\nn\n"
        )

    assert result.exit_code == 0, result.output
    mock_write_stack.assert_called_once()

    config = mock_write_stack.call_args[0][0]
    assert config.tier.name == "medium"
    assert config.enabled_optional == set()

    mock_run_docker.assert_not_called()


def test_interactive_puid_pgid_prompt_shows_context_line(tmp_path):

    media_path = str(tmp_path / "media")

    info = make_system_info(
        disk_free_gb=100.0, ram_total_gb=4.0,
        cpu_cores_logical=2, cpu_cores_physical=2
    )

    with patch(
        "installer.cli.detect_system", return_value=info
    ), patch(
        "installer.cli.detect_disk",
        return_value={"disk_free_gb": 100.0, "disk_path_checked": media_path}
    ), patch(
        "installer.cli.write_stack", return_value=READY_WRITE_RESULT
    ) as mock_write_stack:

        result = runner.invoke(
            app,
            ["--plain", "--media-path", media_path, "--no-start"],
            input="\nn\n\nn\nn\nn\n\n\n\n\n\n\n\n\ny\n"
        )

    assert result.exit_code == 0, result.output
    assert "PUID/PGID set which user/group ID" in result.output
    mock_write_stack.assert_called_once()


def test_docker_installed_but_not_running_starts_service(tmp_path):

    media_path = str(tmp_path / "media")

    not_running = make_system_info(docker_running=False, docker_compose_v2=False)

    with patch(
        "installer.cli.detect_system", return_value=not_running
    ), patch(
        "installer.cli.detect_docker",
        return_value={
            "docker_installed": True, "docker_running": False, "docker_compose_v2": True
        }
    ), patch(
        "installer.cli.check_docker_ready",
        return_value={"docker_running": True, "docker_compose_v2": True}
    ), patch(
        "installer.cli.start_docker_service"
    ) as mock_start, patch(
        "installer.cli.add_user_to_docker_group",
        return_value={"success": True, "error": None}
    ), patch(
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
            input="y\n\n\n\n\n\n\n\n\n\n\ny\n"
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
            input="y\n\n\n\n\n\n\n\n\n\n\ny\n"
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
            input="\n\n\n\n\n\n\n\n\n\n\ny\nn\n"
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
            input="nonsense\nlight\n\n\n\n\n\n\n\n\n\n\ny\nn\n"
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
                "--non-interactive", "--yes", "--vpn", "--no-homepage"
            ]
        )

    assert result.exit_code == 0, result.output

    config = mock_write_stack.call_args[0][0]
    assert config.enabled_optional == {"gluetun"}
    assert "fill in your VPN credentials" in result.output


def test_prints_all_three_tier_compositions(tmp_path):

    media_path = str(tmp_path / "media")

    with patch(
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
                "--tier", "medium", "--media-path", media_path,
                "--non-interactive", "--yes", "--no-homepage"
            ]
        )

    assert result.exit_code == 0, result.output
    assert "Light:" in result.output
    assert "Medium:" in result.output
    assert "Heavy:" in result.output
    assert "Jellyfin" in result.output
    assert "Uptime Kuma" in result.output


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
                "--non-interactive", "--yes", "--sabnzbd", "--no-homepage", "--no-vpn"
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
                "--non-interactive", "--yes", "--recyclarr", "--no-homepage", "--no-vpn"
            ]
        )

    assert result.exit_code == 0, result.output

    config = mock_write_stack.call_args[0][0]
    assert config.enabled_optional == {"recyclarr"}


def test_non_interactive_light_with_explicit_metube_and_downtify_flags(tmp_path):

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
                "--non-interactive", "--yes", "--metube", "--downtify",
                "--no-homepage", "--no-vpn"
            ]
        )

    assert result.exit_code == 0, result.output

    config = mock_write_stack.call_args[0][0]
    assert config.enabled_optional == {"metube", "downtify"}


def test_non_interactive_netdata_defaults_off():
    """
    Unlike Gluetun (opt-out, defaults on), Netdata is deliberately
    opt-in - a real, meaningfully deeper host-access tradeoff (SYS_
    PTRACE/SYS_ADMIN, docker.sock) that shouldn't be silently enabled
    on a fresh install just because no flag was passed.
    """

    media_path = "/tmp/does-not-matter"

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
                "--non-interactive", "--yes", "--no-homepage", "--no-vpn"
            ]
        )

    assert result.exit_code == 0, result.output

    config = mock_write_stack.call_args[0][0]
    assert "netdata" not in config.enabled_optional


def test_non_interactive_light_with_explicit_netdata_flag(tmp_path):

    media_path = str(tmp_path / "media")

    with patch(
        "installer.cli.detect_system", return_value=make_system_info()
    ), patch(
        "installer.cli.detect_disk",
        return_value={"disk_free_gb": 900.0, "disk_path_checked": media_path}
    ), patch(
        "installer.cli.write_stack",
        return_value={**READY_WRITE_RESULT, "warnings": ["SYS_PTRACE"]}
    ) as mock_write_stack:

        result = runner.invoke(
            app,
            [
                "--tier", "light", "--media-path", media_path,
                "--non-interactive", "--yes", "--netdata", "--no-homepage", "--no-vpn"
            ]
        )

    assert result.exit_code == 0, result.output

    config = mock_write_stack.call_args[0][0]
    assert config.enabled_optional == {"netdata"}
    assert "SYS_PTRACE" in result.output


def test_non_interactive_light_with_explicit_homepage_flag(tmp_path):

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
                "--non-interactive", "--yes", "--homepage", "--no-vpn"
            ]
        )

    assert result.exit_code == 0, result.output

    config = mock_write_stack.call_args[0][0]
    assert config.enabled_optional == {"homepage"}


def test_non_interactive_fresh_install_defaults_homepage_enabled(tmp_path):

    media_path = str(tmp_path / "media")

    with patch(
        "installer.cli.load_previous_state", return_value=None
    ), patch(
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
                "--non-interactive", "--yes"
            ]
        )

    assert result.exit_code == 0, result.output

    config = mock_write_stack.call_args[0][0]
    # Gluetun now defaults on too (see the CLI's own real reasoning) -
    # a fresh install with no flags at all gets both real defaults.
    assert config.enabled_optional == {"homepage", "gluetun"}


def test_non_interactive_regenerate_existing_heavy_stack_preserves_homepage(tmp_path):
    """
    Backward-compatibility case: an existing Heavy-tier deployment from
    before Homepage became optional never had "homepage" tracked in
    enabled_optional (it was hardcoded non-optional). Its very next
    regenerate must not silently drop Homepage just because the tracked
    set doesn't mention it - the tier=="heavy" signal has to count too.
    """

    media_path = str(tmp_path / "media")
    previous_state = {
        "tier": "heavy",
        "media_path": media_path,
        "puid": 1000,
        "pgid": 1000,
        "timezone": "UTC",
        "enabled_optional": [],
        "gpu_vendor": None,
        "generated_at": "2026-01-01T00:00:00+00:00"
    }

    with patch(
        "installer.cli.load_previous_state", return_value=previous_state
    ), patch(
        "installer.cli.detect_system", return_value=make_system_info()
    ), patch(
        "installer.cli.detect_disk",
        return_value={"disk_free_gb": 2000.0, "disk_path_checked": media_path}
    ), patch(
        "installer.cli.write_stack", return_value=READY_WRITE_RESULT
    ) as mock_write_stack:

        result = runner.invoke(app, ["--non-interactive", "--yes"])

    assert result.exit_code == 0, result.output

    config = mock_write_stack.call_args[0][0]
    assert "homepage" in config.enabled_optional


def test_homepage_question_shown_and_declined_at_light_tier(tmp_path):

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
            input="\nn\n\n\nn\n\n\n\n\n\ny\n"
        )

    assert result.exit_code == 0, result.output
    assert "Enable Homepage dashboard" in result.output

    config = mock_write_stack.call_args[0][0]
    assert config.enabled_optional == set()


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
        "installer.cli.check_ports_available",
        return_value={"available": True, "conflicts": []}
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
            input=f"{prompted_path}\n\n\n\n\n\n\n\n\n\n\ny\nn\n"
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
            input="\n\n\n\n\n\n\n\n\n\nn\n"
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


def test_uninstall_no_stack_found_exits_1(tmp_path):

    with patch("installer.cli.STACK_DIR", tmp_path / "stack"), patch(
        "installer.cli.stack_containers_exist", return_value=False
    ):

        result = runner.invoke(app, ["uninstall"])

    assert result.exit_code == 1
    assert "No stack found" in result.output


def test_uninstall_proceeds_when_orphaned_containers_exist_without_stack_dir(tmp_path):
    """
    stack/ was deleted through some means other than a real
    `vulcan uninstall` run - real containers from a previous project
    can still exist even though the directory doesn't, confirmed a
    real, recurring scenario. `uninstall` should still act on those,
    not report "nothing to uninstall".
    """

    with patch("installer.cli.STACK_DIR", tmp_path / "stack"), patch(
        "installer.cli.stack_containers_exist", return_value=True
    ), patch(
        "installer.cli.uninstall_stack", return_value={"success": True, "error": None}
    ) as mock_uninstall:

        result = runner.invoke(app, ["uninstall", "--non-interactive", "--yes"])

    assert result.exit_code == 0, result.output
    assert "Stack removed" in result.output
    mock_uninstall.assert_called_once()


def test_uninstall_non_interactive_without_yes_exits_1(tmp_path):

    stack_dir = tmp_path / "stack"
    stack_dir.mkdir()

    with patch("installer.cli.STACK_DIR", stack_dir):

        result = runner.invoke(app, ["uninstall", "--non-interactive"])

    assert result.exit_code == 1
    assert "--yes is required" in result.output


def test_uninstall_confirm_declined_aborts(tmp_path):

    stack_dir = tmp_path / "stack"
    stack_dir.mkdir()

    with patch("installer.cli.STACK_DIR", stack_dir), patch(
        "installer.cli.uninstall_stack"
    ) as mock_uninstall:

        result = runner.invoke(app, ["uninstall"], input="n\n")

    assert result.exit_code == 0
    assert "Aborted" in result.output
    mock_uninstall.assert_not_called()


def test_uninstall_confirm_accepted_calls_uninstall_stack(tmp_path):

    stack_dir = tmp_path / "stack"
    stack_dir.mkdir()

    with patch("installer.cli.STACK_DIR", stack_dir), patch(
        "installer.cli.uninstall_stack", return_value={"success": True, "error": None}
    ) as mock_uninstall:

        result = runner.invoke(app, ["uninstall"], input="y\n")

    assert result.exit_code == 0, result.output
    assert "Stack removed" in result.output

    args, kwargs = mock_uninstall.call_args
    assert args[0] == str(stack_dir / "docker-compose.yml")
    assert args[1] == str(stack_dir / ".env")
    assert kwargs["purge_artifacts"] is False


def test_uninstall_failure_exits_1(tmp_path):

    stack_dir = tmp_path / "stack"
    stack_dir.mkdir()

    with patch("installer.cli.STACK_DIR", stack_dir), patch(
        "installer.cli.uninstall_stack",
        return_value={"success": False, "error": "Failed to stop the running stack - check `docker compose logs`."}
    ):

        result = runner.invoke(app, ["uninstall", "--non-interactive", "--yes"])

    assert result.exit_code == 1
    assert "Failed to stop the running stack" in result.output


def test_uninstall_purge_artifacts_threaded_through(tmp_path):

    stack_dir = tmp_path / "stack"
    stack_dir.mkdir()

    with patch("installer.cli.STACK_DIR", stack_dir), patch(
        "installer.cli.uninstall_stack", return_value={"success": True, "error": None}
    ) as mock_uninstall:

        result = runner.invoke(
            app, ["uninstall", "--non-interactive", "--yes", "--purge-artifacts"]
        )

    assert result.exit_code == 0, result.output
    assert mock_uninstall.call_args.kwargs["purge_artifacts"] is True


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


def test_non_interactive_homepage_private_flag(tmp_path):

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
                "--services", "jellyfin,homepage,traefik",
                "--domain", "media.example.com",
                "--homepage-private",
                "--non-interactive", "--yes"
            ]
        )

    assert result.exit_code == 0, result.output

    config = mock_write_stack.call_args[0][0]
    assert config.homepage_private is True


def test_non_interactive_homepage_private_defaults_true_on_fresh_install(tmp_path):
    """
    Recommended default (opt-out, not opt-in) - a fresh install with a
    public domain and no explicit --homepage-private/--homepage-public
    flag keeps Homepage off the public routed set by default, matching
    the interactive prompt's own default=True.
    """

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
                "--services", "jellyfin,homepage,traefik",
                "--domain", "media.example.com",
                "--non-interactive", "--yes"
            ]
        )

    assert result.exit_code == 0, result.output

    config = mock_write_stack.call_args[0][0]
    assert config.homepage_private is True


def test_non_interactive_homepage_public_flag_overrides_default(tmp_path):

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
                "--services", "jellyfin,homepage,traefik",
                "--domain", "media.example.com",
                "--homepage-public",
                "--non-interactive", "--yes"
            ]
        )

    assert result.exit_code == 0, result.output

    config = mock_write_stack.call_args[0][0]
    assert config.homepage_private is False


def test_non_interactive_cloudflare_dns_flag(tmp_path):

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
                "--cloudflare-dns", "--cloudflare-email", "me@example.com",
                "--non-interactive", "--yes"
            ]
        )

    assert result.exit_code == 0, result.output

    config = mock_write_stack.call_args[0][0]
    assert config.cloudflare_dns is True
    assert config.cloudflare_email == "me@example.com"


def test_non_interactive_cloudflare_dns_defaults_off(tmp_path):

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
    assert config.cloudflare_dns is False
    assert config.cloudflare_email is None


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


def test_non_interactive_rerun_reuses_previous_cloudflare_dns(tmp_path):

    previous_state = {
        "tier": "heavy", "media_path": str(tmp_path / "previous-media"),
        "puid": 1000, "pgid": 1000, "timezone": "UTC",
        "enabled_optional": [], "gpu_vendor": None,
        "custom_services": ["jellyfin", "traefik"],
        "domain": "media.example.com",
        "cloudflare_dns": True,
        "cloudflare_email": "me@example.com",
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
    assert config.cloudflare_dns is True
    assert config.cloudflare_email == "me@example.com"


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
            input="y\njellyfin,radarr,traefik\nmedia.example.com\nn\ny\n"
        )

    assert result.exit_code == 0, result.output
    assert "Base domain for Traefik routing" in result.output
    assert "You'll need to own this domain" in result.output

    config = mock_write_stack.call_args[0][0]
    assert config.domain == "media.example.com"


def test_interactive_cloudflare_dns_prompt_flow(tmp_path):

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
            input="y\njellyfin,radarr,traefik\nmedia.example.com\ny\nme@example.com\ny\n"
        )

    assert result.exit_code == 0, result.output
    assert "Is this domain's DNS managed by Cloudflare" in result.output
    assert "scoped Cloudflare API token" in result.output

    config = mock_write_stack.call_args[0][0]
    assert config.cloudflare_dns is True
    assert config.cloudflare_email == "me@example.com"


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


def test_non_interactive_authelia_without_auth_flags_exits_1(tmp_path):

    media_path = str(tmp_path / "media")

    with patch(
        "installer.cli.detect_system", return_value=make_system_info()
    ), patch(
        "installer.cli.detect_disk",
        return_value={"disk_free_gb": 900.0, "disk_path_checked": media_path}
    ), patch(
        "installer.cli.STACK_DIR", tmp_path / "stack"
    ):

        result = runner.invoke(
            app,
            [
                "--tier", "heavy", "--media-path", media_path,
                "--services", "jellyfin,authelia,traefik",
                "--domain", "media.example.com",
                "--non-interactive", "--yes"
            ]
        )

    assert result.exit_code == 1
    assert "--auth-username and --auth-password are required" in result.output


def test_non_interactive_authelia_with_auth_flags_hashes_and_writes(tmp_path):

    media_path = str(tmp_path / "media")

    with patch(
        "installer.cli.detect_system", return_value=make_system_info()
    ), patch(
        "installer.cli.detect_disk",
        return_value={"disk_free_gb": 900.0, "disk_path_checked": media_path}
    ), patch(
        "installer.cli.STACK_DIR", tmp_path / "stack"
    ), patch(
        "installer.cli.hash_authelia_password",
        return_value={"success": True, "error": None, "hash": "$argon2id$fake$hash"}
    ) as mock_hash, patch(
        "installer.cli.write_stack", return_value=READY_WRITE_RESULT
    ) as mock_write_stack:

        result = runner.invoke(
            app,
            [
                "--tier", "heavy", "--media-path", media_path,
                "--services", "jellyfin,authelia,traefik",
                "--domain", "media.example.com",
                "--auth-username", "admin", "--auth-password", "supersecret",
                "--non-interactive", "--yes"
            ]
        )

    assert result.exit_code == 0, result.output
    mock_hash.assert_called_once_with("supersecret")

    config = mock_write_stack.call_args[0][0]
    assert config.auth_username == "admin"
    assert config.auth_password_hash == "$argon2id$fake$hash"


def test_authelia_prompt_skipped_when_users_database_already_exists(tmp_path):

    media_path = str(tmp_path / "media")
    stack_dir = tmp_path / "stack"
    users_database_path = stack_dir / "config" / "authelia" / "users_database.yml"
    users_database_path.parent.mkdir(parents=True)
    users_database_path.write_text("users: {}\n")

    with patch(
        "installer.cli.detect_system", return_value=make_system_info()
    ), patch(
        "installer.cli.detect_disk",
        return_value={"disk_free_gb": 900.0, "disk_path_checked": media_path}
    ), patch(
        "installer.cli.STACK_DIR", stack_dir
    ), patch(
        "installer.cli.hash_authelia_password"
    ) as mock_hash, patch(
        "installer.cli.write_stack", return_value=READY_WRITE_RESULT
    ) as mock_write_stack:

        result = runner.invoke(
            app,
            [
                "--tier", "heavy", "--media-path", media_path,
                "--services", "jellyfin,authelia,traefik",
                "--domain", "media.example.com",
                "--non-interactive", "--yes"
            ]
        )

    assert result.exit_code == 0, result.output
    mock_hash.assert_not_called()

    config = mock_write_stack.call_args[0][0]
    assert config.auth_username is None
    assert config.auth_password_hash is None


def test_authelia_hash_failure_aborts_before_write_stack(tmp_path):

    media_path = str(tmp_path / "media")

    with patch(
        "installer.cli.detect_system", return_value=make_system_info()
    ), patch(
        "installer.cli.detect_disk",
        return_value={"disk_free_gb": 900.0, "disk_path_checked": media_path}
    ), patch(
        "installer.cli.STACK_DIR", tmp_path / "stack"
    ), patch(
        "installer.cli.hash_authelia_password",
        return_value={"success": False, "error": "Failed to hash password via authelia's own CLI.", "hash": None}
    ), patch(
        "installer.cli.write_stack"
    ) as mock_write_stack:

        result = runner.invoke(
            app,
            [
                "--tier", "heavy", "--media-path", media_path,
                "--services", "jellyfin,authelia,traefik",
                "--domain", "media.example.com",
                "--auth-username", "admin", "--auth-password", "supersecret",
                "--non-interactive", "--yes"
            ]
        )

    assert result.exit_code == 1
    assert "Failed to hash password" in result.output
    mock_write_stack.assert_not_called()


def test_interactive_authelia_prompt_shows_context_line(tmp_path):

    media_path = str(tmp_path / "media")
    stack_dir = tmp_path / "stack"

    with patch(
        "installer.cli.detect_system", return_value=make_system_info()
    ), patch(
        "installer.cli.detect_disk",
        return_value={"disk_free_gb": 900.0, "disk_path_checked": media_path}
    ), patch(
        "installer.cli.STACK_DIR", stack_dir
    ), patch(
        "installer.cli.hash_authelia_password",
        return_value={"success": True, "error": None, "hash": "$argon2id$fake$hash"}
    ), patch(
        "installer.cli.write_stack", return_value=READY_WRITE_RESULT
    ) as mock_write_stack:

        result = runner.invoke(
            app,
            [
                "--plain", "--tier", "heavy", "--media-path", media_path,
                "--puid", "1000", "--pgid", "1000", "--timezone", "UTC", "--no-start"
            ],
            input="y\njellyfin,authelia,traefik\nmedia.example.com\nn\n\nsupersecret\nsupersecret\ny\n"
        )

    assert result.exit_code == 0, result.output
    assert "won't be shown again" in result.output

    config = mock_write_stack.call_args[0][0]
    assert config.auth_username == "admin"


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
            input="\n\n\n\n\n\n\n\n\n\ny\n"
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
            input="\nn\ny\n\nn\n\n\n\n\n\ny\n"
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
            input="\nn\n\ny\nn\n\n\n\n\n\ny\n"
        )

    assert result.exit_code == 0, result.output
    assert "Enable Recyclarr" in result.output

    config = mock_write_stack.call_args[0][0]
    assert config.enabled_optional == {"recyclarr"}
