from unittest.mock import MagicMock, patch

from textual.widgets import Button, Checkbox, Input, RadioSet, Static

from installer.detect import SystemInfo
from installer.tui.app import VulcanApp
from installer.tui.docker_screen import DockerReadyScreen
from installer.tui.media_path_screen import MediaPathScreen
from installer.tui.tier_config_screen import TierConfigScreen
from installer.tui.welcome_screen import WelcomeScreen


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


async def test_welcome_screen_shows_loading_then_detected_values():

    info = make_system_info(cpu_cores_logical=8, gpu_vendor="nvidia")

    with patch(
        "installer.tui.welcome_screen.detect_system", return_value=info
    ), patch(
        "installer.tui.welcome_screen.load_previous_state", return_value=None
    ):

        app = VulcanApp()

        async with app.run_test() as pilot:

            screen = app.screen
            assert isinstance(screen, WelcomeScreen)

            await app.workers.wait_for_complete()
            await pilot.pause()

            assert screen.query_one("#continue", Button).disabled is False

            results = screen.query_one("#results", Static).content
            assert "8 logical cores" in results
            assert "GPU: nvidia" in results
            assert app.system_info is info


async def test_welcome_screen_shows_previous_state_note():

    previous = {"tier": "medium", "generated_at": "2026-07-01T12:00:00+00:00"}

    with patch(
        "installer.tui.welcome_screen.detect_system", return_value=make_system_info()
    ), patch(
        "installer.tui.welcome_screen.load_previous_state", return_value=previous
    ):

        app = VulcanApp()

        async with app.run_test() as pilot:

            await app.workers.wait_for_complete()
            await pilot.pause()

            note = app.screen.query_one("#previous-note", Static).content
            assert "Found an existing medium stack" in note
            assert app.previous_state == previous


async def test_welcome_screen_no_previous_state_leaves_note_empty():

    with patch(
        "installer.tui.welcome_screen.detect_system", return_value=make_system_info()
    ), patch(
        "installer.tui.welcome_screen.load_previous_state", return_value=None
    ):

        app = VulcanApp()

        async with app.run_test() as pilot:

            await app.workers.wait_for_complete()
            await pilot.pause()

            note = app.screen.query_one("#previous-note", Static).content
            assert note == ""


async def test_continue_navigates_to_docker_ready_screen():

    with patch(
        "installer.tui.welcome_screen.detect_system", return_value=make_system_info()
    ), patch(
        "installer.tui.welcome_screen.load_previous_state", return_value=None
    ):

        app = VulcanApp()

        async with app.run_test() as pilot:

            await app.workers.wait_for_complete()
            await pilot.pause()

            await pilot.click("#continue")
            await pilot.pause()

            assert isinstance(app.screen, DockerReadyScreen)


async def _launch_at_docker_screen(info: SystemInfo):
    """
    Shared setup landing directly on DockerReadyScreen with a given
    SystemInfo. VulcanApp.on_mount() always pushes WelcomeScreen first,
    whose own background detection worker would otherwise race with -
    and silently clobber - the system_info set here, so WelcomeScreen's
    real detect_system()/load_previous_state() are mocked and awaited
    to completion before DockerReadyScreen is pushed and the fake info
    is substituted in.
    """

    with patch(
        "installer.tui.welcome_screen.detect_system", return_value=make_system_info()
    ), patch(
        "installer.tui.welcome_screen.load_previous_state", return_value=None
    ):

        app = VulcanApp()
        ctx = app.run_test()
        pilot = await ctx.__aenter__()

        await app.workers.wait_for_complete()
        await pilot.pause()

    app.system_info = info
    app.push_screen(DockerReadyScreen())
    await pilot.pause()

    return app, pilot, ctx


async def test_docker_ready_screen_already_ready():

    app, pilot, ctx = await _launch_at_docker_screen(make_system_info())

    try:

        status = app.screen.query_one("#docker-status", Static).content
        assert status == "Docker is ready."
        assert app.screen.query_one("#continue", Button).disabled is False
        assert app.screen.query_one("#action", Button).display is False

    finally:
        await ctx.__aexit__(None, None, None)


async def test_docker_ready_screen_not_installed_shows_install_button():

    info = make_system_info(
        docker_installed=False, docker_running=False, docker_compose_v2=False
    )

    with patch(
        "installer.tui.docker_screen.install_plan_for",
        return_value={"method": "get.docker.com", "description": "curl ... | sh"}
    ):

        app, pilot, ctx = await _launch_at_docker_screen(info)

        try:

            action = app.screen.query_one("#action", Button)
            assert action.display is True
            assert action.label.plain == "Install Docker"
            assert app.screen.query_one("#continue", Button).disabled is True

        finally:
            await ctx.__aexit__(None, None, None)


async def test_docker_ready_screen_unsupported_distro_shows_no_action():

    info = make_system_info(
        docker_installed=False, docker_running=False, docker_compose_v2=False,
        os_id="gentoo"
    )

    with patch("installer.tui.docker_screen.install_plan_for", return_value=None):

        app, pilot, ctx = await _launch_at_docker_screen(info)

        try:

            status = app.screen.query_one("#docker-status", Static).content
            assert "No known automatic install method" in status
            assert app.screen.query_one("#action", Button).display is False
            assert app.screen.query_one("#continue", Button).disabled is True

        finally:
            await ctx.__aexit__(None, None, None)


async def test_docker_ready_screen_install_button_runs_full_install_sequence():

    info = make_system_info(
        docker_installed=False, docker_running=False, docker_compose_v2=False
    )

    ready_state = {
        "docker_installed": True, "docker_running": True, "docker_compose_v2": True
    }

    with patch(
        "installer.tui.docker_screen.install_plan_for",
        return_value={"method": "get.docker.com", "description": "curl ... | sh"}
    ), patch(
        "installer.tui.docker_screen.install_docker"
    ) as mock_install, patch(
        "installer.tui.docker_screen.start_docker_service"
    ) as mock_start, patch(
        "installer.tui.docker_screen.add_user_to_docker_group"
    ) as mock_add_group, patch(
        "installer.tui.docker_screen.ensure_compose_v2"
    ) as mock_compose, patch(
        "installer.tui.docker_screen.detect_docker", return_value=ready_state
    ):

        app, pilot, ctx = await _launch_at_docker_screen(info)

        try:

            await pilot.click("#action")
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()

            mock_install.assert_called_once()
            mock_start.assert_called_once()
            mock_add_group.assert_called_once()
            mock_compose.assert_called_once()

            assert app.group_just_added is True
            assert app.system_info.docker_installed is True
            assert app.system_info.docker_running is True
            assert app.system_info.docker_compose_v2 is True

            status = app.screen.query_one("#docker-status", Static).content
            assert status == "Docker is ready."
            assert app.screen.query_one("#continue", Button).disabled is False

        finally:
            await ctx.__aexit__(None, None, None)


async def test_docker_ready_screen_not_running_only_starts_service():

    info = make_system_info(docker_running=False)

    ready_state = {
        "docker_installed": True, "docker_running": True, "docker_compose_v2": True
    }

    with patch(
        "installer.tui.docker_screen.start_docker_service"
    ) as mock_start, patch(
        "installer.tui.docker_screen.install_docker"
    ) as mock_install, patch(
        "installer.tui.docker_screen.detect_docker", return_value=ready_state
    ):

        app, pilot, ctx = await _launch_at_docker_screen(info)

        try:

            action = app.screen.query_one("#action", Button)
            assert action.label.plain == "Start Docker service"

            await pilot.click("#action")
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()

            mock_start.assert_called_once()
            mock_install.assert_not_called()
            assert app.group_just_added is False

        finally:
            await ctx.__aexit__(None, None, None)


async def test_docker_ready_screen_no_compose_only_installs_compose():

    info = make_system_info(docker_compose_v2=False)

    ready_state = {
        "docker_installed": True, "docker_running": True, "docker_compose_v2": True
    }

    with patch(
        "installer.tui.docker_screen.ensure_compose_v2"
    ) as mock_compose, patch(
        "installer.tui.docker_screen.start_docker_service"
    ) as mock_start, patch(
        "installer.tui.docker_screen.detect_docker", return_value=ready_state
    ):

        app, pilot, ctx = await _launch_at_docker_screen(info)

        try:

            action = app.screen.query_one("#action", Button)
            assert action.label.plain == "Install Docker Compose v2"

            await pilot.click("#action")
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()

            mock_compose.assert_called_once()
            mock_start.assert_not_called()

        finally:
            await ctx.__aexit__(None, None, None)


async def test_docker_ready_screen_continue_navigates_to_media_path_screen():

    app, pilot, ctx = await _launch_at_docker_screen(make_system_info())

    try:

        await pilot.click("#continue")
        await pilot.pause()

        assert isinstance(app.screen, MediaPathScreen)

    finally:
        await ctx.__aexit__(None, None, None)


async def _launch_at_media_path_screen(info: SystemInfo, previous: dict | None = None):

    with patch(
        "installer.tui.welcome_screen.detect_system", return_value=make_system_info()
    ), patch(
        "installer.tui.welcome_screen.load_previous_state", return_value=None
    ):

        app = VulcanApp()
        ctx = app.run_test()
        pilot = await ctx.__aenter__()

        await app.workers.wait_for_complete()
        await pilot.pause()

    app.system_info = info
    app.previous_state = previous
    app.push_screen(MediaPathScreen())
    await pilot.pause()

    return app, pilot, ctx


async def _launch_at_tier_config_screen(
    info: SystemInfo, previous: dict | None = None, media_path: str = "/mnt/media"
):

    app, pilot, ctx = await _launch_at_media_path_screen(info, previous)

    app.media_path = media_path
    app.push_screen(TierConfigScreen())
    await pilot.pause()

    return app, pilot, ctx


async def test_media_path_screen_default_value_from_previous_state():

    previous = {"media_path": "/mnt/previous-media"}
    app, pilot, ctx = await _launch_at_media_path_screen(make_system_info(), previous)

    try:

        value = app.screen.query_one("#media-path-input", Input).value
        assert value == "/mnt/previous-media"

    finally:
        await ctx.__aexit__(None, None, None)


async def test_media_path_screen_default_value_fallback_to_home_media():

    app, pilot, ctx = await _launch_at_media_path_screen(make_system_info(), None)

    try:

        value = app.screen.query_one("#media-path-input", Input).value
        assert value.endswith("media")

    finally:
        await ctx.__aexit__(None, None, None)


async def test_media_path_screen_continue_success_navigates_and_updates_disk_info(tmp_path):

    app, pilot, ctx = await _launch_at_media_path_screen(make_system_info(), None)

    try:

        media_path = str(tmp_path / "media")
        app.screen.query_one("#media-path-input", Input).value = media_path

        with patch(
            "installer.tui.media_path_screen.detect_disk",
            return_value={"disk_free_gb": 500.0, "disk_path_checked": media_path}
        ):

            await pilot.click("#continue")
            await pilot.pause()

        assert isinstance(app.screen, TierConfigScreen)
        assert app.media_path == media_path
        assert app.system_info.disk_free_gb == 500.0

    finally:
        await ctx.__aexit__(None, None, None)


async def test_media_path_screen_mkdir_failure_shows_error_and_stays():

    app, pilot, ctx = await _launch_at_media_path_screen(make_system_info(), None)

    try:

        app.screen.query_one("#media-path-input", Input).value = "/root/no-access-here"

        with patch(
            "installer.tui.media_path_screen.Path.mkdir",
            side_effect=OSError("permission denied")
        ):

            await pilot.click("#continue")
            await pilot.pause()

        error = app.screen.query_one("#media-path-error", Static).content
        assert "Can't create media path" in error
        assert isinstance(app.screen, MediaPathScreen)

    finally:
        await ctx.__aexit__(None, None, None)


async def test_tier_config_screen_recommended_tier_preselected_without_previous():

    info = make_system_info(
        disk_free_gb=600.0, ram_total_gb=16.0, cpu_cores_logical=6, cpu_cores_physical=6
    )
    app, pilot, ctx = await _launch_at_tier_config_screen(info, previous=None)

    try:

        radio_set = app.screen.query_one("#tier-set", RadioSet)
        assert radio_set.pressed_button.id == "medium"

    finally:
        await ctx.__aexit__(None, None, None)


async def test_tier_config_screen_previous_tier_preselected_when_present():

    previous = {
        "tier": "light", "media_path": "/mnt/x", "puid": 1000, "pgid": 1000,
        "timezone": "UTC", "enabled_optional": [], "gpu_vendor": None,
        "generated_at": "2026-01-01T00:00:00+00:00"
    }
    app, pilot, ctx = await _launch_at_tier_config_screen(make_system_info(), previous)

    try:

        radio_set = app.screen.query_one("#tier-set", RadioSet)
        assert radio_set.pressed_button.id == "light"

    finally:
        await ctx.__aexit__(None, None, None)


async def test_tier_config_screen_selecting_light_hides_both_checkboxes():

    app, pilot, ctx = await _launch_at_tier_config_screen(make_system_info(gpu_vendor="amd"))

    try:

        await pilot.click("#light")
        await pilot.pause()

        assert app.screen.query_one("#gluetun-check", Checkbox).display is False
        assert app.screen.query_one("#gpu-check", Checkbox).display is False

    finally:
        await ctx.__aexit__(None, None, None)


async def test_tier_config_screen_selecting_medium_shows_only_gluetun():

    app, pilot, ctx = await _launch_at_tier_config_screen(make_system_info(gpu_vendor="amd"))

    try:

        await pilot.click("#medium")
        await pilot.pause()

        assert app.screen.query_one("#gluetun-check", Checkbox).display is True
        assert app.screen.query_one("#gpu-check", Checkbox).display is False

    finally:
        await ctx.__aexit__(None, None, None)


async def test_tier_config_screen_selecting_heavy_with_gpu_shows_only_gpu_checked_by_default():

    app, pilot, ctx = await _launch_at_tier_config_screen(make_system_info(gpu_vendor="amd"))

    try:

        await pilot.click("#heavy")
        await pilot.pause()

        gluetun = app.screen.query_one("#gluetun-check", Checkbox)
        gpu = app.screen.query_one("#gpu-check", Checkbox)

        assert gluetun.display is False
        assert gpu.display is True
        assert gpu.value is True

    finally:
        await ctx.__aexit__(None, None, None)


async def test_tier_config_screen_selecting_heavy_without_gpu_shows_neither():

    app, pilot, ctx = await _launch_at_tier_config_screen(make_system_info(gpu_vendor=None))

    try:

        await pilot.click("#heavy")
        await pilot.pause()

        assert app.screen.query_one("#gluetun-check", Checkbox).display is False
        assert app.screen.query_one("#gpu-check", Checkbox).display is False

    finally:
        await ctx.__aexit__(None, None, None)


async def test_tier_config_screen_continue_with_medium_and_gluetun_checked():

    app, pilot, ctx = await _launch_at_tier_config_screen(make_system_info())

    try:

        await pilot.click("#medium")
        await pilot.pause()

        await pilot.click("#gluetun-check")
        await pilot.pause()

        await pilot.click("#continue")
        await pilot.pause()

        assert app.tier_name == "medium"
        assert app.enabled_optional == {"gluetun"}
        assert app.is_running is False

    finally:
        await ctx.__aexit__(None, None, None)


async def test_tier_config_screen_continue_stores_config_and_exits():

    app, pilot, ctx = await _launch_at_tier_config_screen(make_system_info(gpu_vendor="amd"))

    try:

        await pilot.click("#heavy")
        await pilot.pause()

        await pilot.click("#continue")
        await pilot.pause()

        assert app.tier_name == "heavy"
        assert app.gpu_vendor == "amd"
        assert app.puid is not None
        assert app.pgid is not None
        assert app.timezone is not None
        assert app.is_running is False

    finally:
        await ctx.__aexit__(None, None, None)


async def test_tier_config_screen_invalid_puid_shows_error_and_does_not_exit():

    app, pilot, ctx = await _launch_at_tier_config_screen(make_system_info())

    try:

        app.screen.query_one("#puid-input", Input).value = ""

        await pilot.click("#continue")
        await pilot.pause()

        error = app.screen.query_one("#tier-error", Static).content
        assert "PUID and PGID must both be numbers" in error
        assert app.is_running is True

    finally:
        await ctx.__aexit__(None, None, None)


async def test_real_detection_and_docker_ready_end_to_end(tmp_path):
    """
    Genuinely unmocked - real detect_system(), real load_previous_state(),
    real detect_docker(), real detect_disk(), real recommend_tier()
    against this actual machine, where Docker is already fully installed
    and running. Confirms the whole scaffold (worker thread ->
    call_from_thread -> screen update -> navigation) works against real
    system state, not just mocks - all the way through every screen this
    slice adds.
    """

    app = VulcanApp()

    async with app.run_test() as pilot:

        await app.workers.wait_for_complete()
        await pilot.pause()

        assert app.system_info is not None
        assert app.system_info.cpu_cores_logical is not None

        await pilot.click("#continue")
        await pilot.pause()

        assert isinstance(app.screen, DockerReadyScreen)

        status = app.screen.query_one("#docker-status", Static).content
        assert status == "Docker is ready."
        assert app.screen.query_one("#action", Button).display is False

        await pilot.click("#continue")
        await pilot.pause()

        assert isinstance(app.screen, MediaPathScreen)

        real_media_path = str(tmp_path / "real-media")
        app.screen.query_one("#media-path-input", Input).value = real_media_path

        await pilot.click("#continue")
        await pilot.pause()

        assert isinstance(app.screen, TierConfigScreen)
        assert app.media_path == real_media_path
        assert app.system_info.disk_free_gb > 0

        recommendation_text = app.screen.query_one("#recommendation", Static).content
        assert "Recommended tier:" in recommendation_text

        await pilot.click("#continue")
        await pilot.pause()

        assert app.tier_name in ("light", "medium", "heavy")
        assert app.puid is not None
        assert app.is_running is False
