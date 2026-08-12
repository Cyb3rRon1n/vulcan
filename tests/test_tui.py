import shutil
import subprocess
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

from textual.containers import Horizontal
from textual.widgets import (
    Button,
    Checkbox,
    Input,
    LoadingIndicator,
    RadioButton,
    RadioSet,
    SelectionList,
    Static,
)

from installer.detect import SystemInfo
from installer.tui.app import VulcanApp
from installer.tui.docker_screen import DockerReadyScreen
from installer.tui.main_menu_screen import MainMenuScreen
from installer.tui.maintenance_screen import MaintenanceScreen
from installer.tui.media_path_screen import MediaPathScreen
from installer.tui.restore_screen import RestoreScreen
from installer.tui.review_screen import ReviewScreen
from installer.tui.service_selection_screen import ServiceSelectionScreen
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
        os_pretty_name="Fedora Linux 44",
        os_is_atomic=False
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

            app.push_screen(WelcomeScreen())
            await pilot.pause()

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

            app.push_screen(WelcomeScreen())
            await pilot.pause()

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

            app.push_screen(WelcomeScreen())
            await pilot.pause()

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

            app.push_screen(WelcomeScreen())
            await pilot.pause()

            await app.workers.wait_for_complete()
            await pilot.pause()

            await pilot.click("#continue")
            await pilot.pause()

            assert isinstance(app.screen, DockerReadyScreen)


async def test_welcome_screen_offline_checkbox_defaults_to_online():

    with patch(
        "installer.tui.welcome_screen.detect_system", return_value=make_system_info()
    ), patch(
        "installer.tui.welcome_screen.load_previous_state", return_value=None
    ):

        app = VulcanApp()

        async with app.run_test() as pilot:

            app.push_screen(WelcomeScreen())
            await pilot.pause()

            await app.workers.wait_for_complete()
            await pilot.pause()

            await pilot.click("#continue")
            await pilot.pause()

            assert app.offline is False


async def test_welcome_screen_offline_checkbox_sets_app_offline():

    with patch(
        "installer.tui.welcome_screen.detect_system", return_value=make_system_info()
    ), patch(
        "installer.tui.welcome_screen.load_previous_state", return_value=None
    ):

        app = VulcanApp()

        async with app.run_test() as pilot:

            app.push_screen(WelcomeScreen())
            await pilot.pause()

            await app.workers.wait_for_complete()
            await pilot.pause()

            await pilot.click("#offline-check")
            await pilot.click("#continue")
            await pilot.pause()

            assert app.offline is True


async def _launch_at_docker_screen(info: SystemInfo, offline: bool = False):
    """
    Shared setup landing directly on DockerReadyScreen with a given
    SystemInfo. VulcanApp.on_mount() pushes MainMenuScreen first; this
    explicitly pushes WelcomeScreen on top of it (mirroring a real
    "Guided Setup" click) before pushing DockerReadyScreen, so Back
    navigation from DockerReadyScreen still lands on WelcomeScreen, not
    MainMenuScreen, matching what a real user's navigation path would
    produce. WelcomeScreen's own background detection worker would
    otherwise race with - and silently clobber - the system_info set
    here, so its real detect_system()/load_previous_state() are mocked
    and awaited to completion before DockerReadyScreen is pushed and
    the fake info is substituted in. offline is set before pushing too,
    since render_state() reads it synchronously from on_mount().
    """

    with patch(
        "installer.tui.welcome_screen.detect_system", return_value=make_system_info()
    ), patch(
        "installer.tui.welcome_screen.load_previous_state", return_value=None
    ):

        app = VulcanApp()
        ctx = app.run_test()
        pilot = await ctx.__aenter__()

        app.push_screen(WelcomeScreen())
        await pilot.pause()

        await app.workers.wait_for_complete()
        await pilot.pause()

    app.system_info = info
    app.offline = offline
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


async def test_docker_ready_screen_offline_shows_no_action():

    info = make_system_info(
        docker_installed=False, docker_running=False, docker_compose_v2=False
    )

    with patch("installer.tui.docker_screen.install_plan_for") as mock_plan:

        app, pilot, ctx = await _launch_at_docker_screen(info, offline=True)

        try:

            status = app.screen.query_one("#docker-status", Static).content
            assert "No internet access" in status
            assert app.screen.query_one("#action", Button).display is False
            assert app.screen.query_one("#continue", Button).disabled is True
            mock_plan.assert_not_called()

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
        return_value={"method": "get.docker.com", "description": "curl ... | sh", "needs_reboot": False}
    ), patch(
        "installer.tui.docker_screen.install_docker",
        return_value={"success": True, "error": None, "method": "get.docker.com", "needs_reboot": False}
    ) as mock_install, patch(
        "installer.tui.docker_screen.start_docker_service"
    ) as mock_start, patch(
        "installer.tui.docker_screen.add_user_to_docker_group"
    ) as mock_add_group, patch(
        "installer.tui.docker_screen.ensure_compose_v2"
    ) as mock_compose, patch(
        "installer.tui.docker_screen.detect_docker",
        return_value={"docker_installed": True, "docker_running": False, "docker_compose_v2": True}
    ), patch(
        "installer.tui.docker_screen.check_docker_ready",
        return_value={"docker_running": True, "docker_compose_v2": True}
    ) as mock_ready:

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
            mock_ready.assert_called_once_with(use_group_workaround=True)

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
    """
    The exact bug found live against a real Bazzite host in the
    sibling Anvil project: Docker installed by a previous run (the
    atomic-OS reboot-split case) never got its user added to the
    docker group before this fix, since group-adding only happened
    alongside a fresh install. This branch must now also add the group
    and route the re-check through check_docker_ready's group-
    workaround (a plain detect_docker() call right after usermod -aG
    would still see this process's own stale group list).
    """

    info = make_system_info(docker_running=False)

    not_yet_state = {
        "docker_installed": True, "docker_running": False, "docker_compose_v2": True
    }
    ready_state = {"docker_running": True, "docker_compose_v2": True}

    with patch(
        "installer.tui.docker_screen.start_docker_service"
    ) as mock_start, patch(
        "installer.tui.docker_screen.install_docker"
    ) as mock_install, patch(
        "installer.tui.docker_screen.add_user_to_docker_group"
    ) as mock_group, patch(
        "installer.tui.docker_screen.detect_docker", return_value=not_yet_state
    ), patch(
        "installer.tui.docker_screen.check_docker_ready", return_value=ready_state
    ) as mock_ready:

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
            mock_group.assert_called_once()
            mock_ready.assert_called_once_with(use_group_workaround=True)
            assert app.group_just_added is True

            status = app.screen.query_one("#docker-status", Static).content
            assert status == "Docker is ready."
            assert app.screen.query_one("#continue", Button).disabled is False

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


async def test_media_path_screen_continue_sets_media_redundancy(tmp_path):

    app, pilot, ctx = await _launch_at_media_path_screen(make_system_info(), None)

    try:

        media_path = str(tmp_path / "media")
        app.screen.query_one("#media-path-input", Input).value = media_path

        redundancy = {
            "device": "/dev/sda1", "filesystem": "ext4", "redundant": False,
            "redundancy_type": None, "device_count": 1
        }

        with patch(
            "installer.tui.media_path_screen.detect_disk",
            return_value={"disk_free_gb": 500.0, "disk_path_checked": media_path}
        ), patch(
            "installer.tui.media_path_screen.detect_media_redundancy",
            return_value=redundancy
        ):

            await pilot.click("#continue")
            await pilot.pause()

        assert app.media_redundancy == redundancy

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


async def test_tier_config_screen_selecting_light_hides_gpu_but_shows_gluetun():

    app, pilot, ctx = await _launch_at_tier_config_screen(make_system_info(gpu_vendor="amd"))

    try:

        await pilot.click("#light")
        await pilot.pause()

        # Gluetun is tier-agnostic now (qBittorrent is present at every
        # tier, and so is the IP exposure it protects against) - only
        # GPU passthrough stays Heavy-only.
        assert app.screen.query_one("#gluetun-check", Checkbox).display is True
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

        assert gluetun.display is True
        assert gpu.display is True
        assert gpu.value is True

    finally:
        await ctx.__aexit__(None, None, None)


async def test_tier_config_screen_selecting_heavy_without_gpu_shows_only_gluetun():

    app, pilot, ctx = await _launch_at_tier_config_screen(make_system_info(gpu_vendor=None))

    try:

        await pilot.click("#heavy")
        await pilot.pause()

        assert app.screen.query_one("#gluetun-check", Checkbox).display is True
        assert app.screen.query_one("#gpu-check", Checkbox).display is False

    finally:
        await ctx.__aexit__(None, None, None)


async def test_tier_config_screen_sabnzbd_checkbox_visible_in_every_tier():

    app, pilot, ctx = await _launch_at_tier_config_screen(make_system_info(gpu_vendor="amd"))

    try:

        for tier_id in ("#light", "#medium", "#heavy"):

            await pilot.click(tier_id)
            await pilot.pause()

            assert app.screen.query_one("#sabnzbd-check", Checkbox).display is True

    finally:
        await ctx.__aexit__(None, None, None)


async def test_tier_config_screen_continue_with_sabnzbd_checked():

    app, pilot, ctx = await _launch_at_tier_config_screen(make_system_info())

    try:

        await pilot.click("#light")
        await pilot.pause()

        # Checkbox state set directly rather than via pilot.click() - a
        # real, confirmed Textual Pilot mouse hit-testing quirk against
        # this nested Horizontal-inside-VerticalScroll layout mistargets
        # clicks onto the wrong checkbox (verified NOT an app logic bug:
        # the identical toggle via real keyboard interaction - focus() +
        # press("space") - lands on the correct widget every time).
        # These checkboxes have no on_checkbox_changed side effects of
        # their own to verify via a real click anyway - only their final
        # .value, read when #continue is pressed, matters here.
        app.screen.query_one("#sabnzbd-check", Checkbox).value = True
        app.screen.query_one("#homepage-check", Checkbox).value = False
        # Gluetun defaults on now - turn it off to isolate sabnzbd alone.
        app.screen.query_one("#gluetun-check", Checkbox).value = False
        await pilot.pause()

        app.screen.query_one("#continue", Button).scroll_visible(animate=False)
        await pilot.pause()

        await pilot.click("#continue")
        await pilot.pause()

        assert app.tier_name == "light"
        assert app.enabled_optional == {"sabnzbd"}
        assert isinstance(app.screen, ReviewScreen)

    finally:
        await ctx.__aexit__(None, None, None)


async def test_tier_config_screen_recyclarr_checkbox_visible_in_every_tier():

    app, pilot, ctx = await _launch_at_tier_config_screen(make_system_info(gpu_vendor="amd"))

    try:

        for tier_id in ("#light", "#medium", "#heavy"):

            await pilot.click(tier_id)
            await pilot.pause()

            assert app.screen.query_one("#recyclarr-check", Checkbox).display is True

    finally:
        await ctx.__aexit__(None, None, None)


async def test_tier_config_screen_continue_with_recyclarr_checked():

    app, pilot, ctx = await _launch_at_tier_config_screen(make_system_info())

    try:

        await pilot.click("#light")
        await pilot.pause()

        # Checkbox state set directly, not via pilot.click() - see the
        # sabnzbd test above for the real, confirmed Textual Pilot
        # mouse-mistargeting reason.
        app.screen.query_one("#recyclarr-check", Checkbox).value = True
        app.screen.query_one("#homepage-check", Checkbox).value = False
        # Gluetun defaults on now - turn it off to isolate recyclarr alone.
        app.screen.query_one("#gluetun-check", Checkbox).value = False
        await pilot.pause()

        app.screen.query_one("#continue", Button).scroll_visible(animate=False)
        await pilot.pause()

        await pilot.click("#continue")
        await pilot.pause()

        assert app.tier_name == "light"
        assert app.enabled_optional == {"recyclarr"}
        assert isinstance(app.screen, ReviewScreen)

    finally:
        await ctx.__aexit__(None, None, None)


async def test_tier_config_screen_continue_with_medium_and_gluetun_checked():

    app, pilot, ctx = await _launch_at_tier_config_screen(make_system_info())

    try:

        await pilot.click("#medium")
        await pilot.pause()

        # Checkbox state set directly, not via pilot.click() - see the
        # sabnzbd test above for the real, confirmed Textual Pilot
        # mouse-mistargeting reason. Gluetun now defaults on - leave it
        # untouched rather than setting it (which would toggle it off).
        app.screen.query_one("#homepage-check", Checkbox).value = False
        await pilot.pause()

        app.screen.query_one("#continue", Button).scroll_visible(animate=False)
        await pilot.pause()

        await pilot.click("#continue")
        await pilot.pause()

        assert app.tier_name == "medium"
        assert app.enabled_optional == {"gluetun"}
        assert isinstance(app.screen, ReviewScreen)

    finally:
        await ctx.__aexit__(None, None, None)


async def test_tier_config_screen_homepage_checkbox_defaults_enabled_fresh_install():

    app, pilot, ctx = await _launch_at_tier_config_screen(make_system_info())

    try:

        checkbox = app.screen.query_one("#homepage-check", Checkbox)
        assert checkbox.value is True
        assert checkbox.display is True

    finally:
        await ctx.__aexit__(None, None, None)


async def test_tier_config_screen_homepage_checkbox_visible_in_every_tier():

    app, pilot, ctx = await _launch_at_tier_config_screen(make_system_info(gpu_vendor="amd"))

    try:

        for tier_id in ("#light", "#medium", "#heavy"):

            await pilot.click(tier_id)
            await pilot.pause()

            assert app.screen.query_one("#homepage-check", Checkbox).display is True

    finally:
        await ctx.__aexit__(None, None, None)


async def test_tier_config_screen_regenerate_existing_heavy_stack_preserves_homepage_default():
    """
    Same backward-compatibility case as the CLI equivalent: an existing
    Heavy-tier deployment never had "homepage" tracked in
    enabled_optional (it was hardcoded non-optional before this slice),
    so the checkbox must still default checked on the very next
    regenerate, not just when enabled_optional explicitly lists it.
    """

    previous = {
        "tier": "heavy", "media_path": "/mnt/media", "puid": 1000, "pgid": 1000,
        "timezone": "UTC", "enabled_optional": [], "gpu_vendor": None
    }

    app, pilot, ctx = await _launch_at_tier_config_screen(make_system_info(), previous)

    try:

        checkbox = app.screen.query_one("#homepage-check", Checkbox)
        assert checkbox.value is True

    finally:
        await ctx.__aexit__(None, None, None)


async def test_tier_config_screen_continue_with_homepage_unchecked():

    app, pilot, ctx = await _launch_at_tier_config_screen(make_system_info())

    try:

        await pilot.click("#light")
        await pilot.pause()

        # Checkbox state set directly, not via pilot.click() - see the
        # sabnzbd test above for the real, confirmed Textual Pilot
        # mouse-mistargeting reason.
        app.screen.query_one("#homepage-check", Checkbox).value = False
        # Gluetun defaults on now - turn it off so the only thing under
        # test here is homepage being unchecked.
        app.screen.query_one("#gluetun-check", Checkbox).value = False
        await pilot.pause()

        app.screen.query_one("#continue", Button).scroll_visible(animate=False)
        await pilot.pause()

        await pilot.click("#continue")
        await pilot.pause()

        assert app.tier_name == "light"
        assert app.enabled_optional == set()
        assert isinstance(app.screen, ReviewScreen)

    finally:
        await ctx.__aexit__(None, None, None)


async def test_tier_config_screen_continue_navigates_to_review_screen():

    app, pilot, ctx = await _launch_at_tier_config_screen(make_system_info(gpu_vendor="amd"))

    try:

        await pilot.click("#heavy")
        await pilot.pause()

        app.screen.query_one("#continue", Button).scroll_visible(animate=False)
        await pilot.pause()

        await pilot.click("#continue")
        await pilot.pause()

        assert app.tier_name == "heavy"
        assert app.gpu_vendor == "amd"
        assert app.puid is not None
        assert app.pgid is not None
        assert app.timezone is not None
        assert isinstance(app.screen, ReviewScreen)

    finally:
        await ctx.__aexit__(None, None, None)


async def test_tier_config_screen_invalid_puid_shows_error_and_does_not_exit():

    app, pilot, ctx = await _launch_at_tier_config_screen(make_system_info())

    try:

        app.screen.query_one("#puid-input", Input).value = ""

        app.screen.query_one("#continue", Button).scroll_visible(animate=False)
        await pilot.pause()

        await pilot.click("#continue")
        await pilot.pause()

        error = app.screen.query_one("#tier-error", Static).content
        assert "PUID and PGID must both be numbers" in error
        assert app.is_running is True

    finally:
        await ctx.__aexit__(None, None, None)


async def test_tier_config_screen_continue_leaves_custom_services_none():

    app, pilot, ctx = await _launch_at_tier_config_screen(make_system_info())

    try:

        app.screen.query_one("#continue", Button).scroll_visible(animate=False)
        await pilot.pause()

        await pilot.click("#continue")
        await pilot.pause()

        assert isinstance(app.screen, ReviewScreen)
        assert app.custom_services is None

    finally:
        await ctx.__aexit__(None, None, None)


async def test_tier_config_screen_gluetun_and_puid_pgid_tooltips_set():

    app, pilot, ctx = await _launch_at_tier_config_screen(make_system_info())

    try:

        gluetun_tooltip = app.screen.query_one("#gluetun-check", Checkbox).tooltip
        puid_tooltip = app.screen.query_one("#puid-input", Input).tooltip
        pgid_tooltip = app.screen.query_one("#pgid-input", Input).tooltip

        assert gluetun_tooltip
        assert "gluetun-wiki" in gluetun_tooltip
        assert puid_tooltip
        assert "file ownership" in puid_tooltip
        assert pgid_tooltip

    finally:
        await ctx.__aexit__(None, None, None)


async def test_tier_config_screen_sabnzbd_recyclarr_homepage_gpu_timezone_tooltips_set():

    app, pilot, ctx = await _launch_at_tier_config_screen(make_system_info(gpu_vendor="amd"))

    try:

        assert app.screen.query_one("#sabnzbd-check", Checkbox).tooltip
        assert app.screen.query_one("#recyclarr-check", Checkbox).tooltip
        assert app.screen.query_one("#homepage-check", Checkbox).tooltip
        assert app.screen.query_one("#gpu-check", Checkbox).tooltip
        assert app.screen.query_one("#timezone-input", Input).tooltip

    finally:
        await ctx.__aexit__(None, None, None)


async def test_tier_config_screen_focus_shows_real_tooltip_in_error_line():

    app, pilot, ctx = await _launch_at_tier_config_screen(make_system_info())

    try:

        app.screen.query_one("#gluetun-check", Checkbox).focus()
        await pilot.pause()

        error_text = app.screen.query_one("#tier-error", Static).content
        assert "gluetun-wiki" in error_text

    finally:
        await ctx.__aexit__(None, None, None)


async def test_tier_config_screen_focus_clears_error_line_for_untooltipped_widget():

    app, pilot, ctx = await _launch_at_tier_config_screen(make_system_info())

    try:

        app.screen.query_one("#gluetun-check", Checkbox).focus()
        await pilot.pause()
        assert app.screen.query_one("#tier-error", Static).content != ""

        # #tier-set (the RadioSet) is deliberately no longer "untooltipped" -
        # it now carries the current tier's composition (see the dedicated
        # tests for that) - so #back is used here instead as a widget that
        # genuinely has no tooltip.
        app.screen.query_one("#back", Button).focus()
        await pilot.pause()

        assert app.screen.query_one("#tier-error", Static).content == ""

    finally:
        await ctx.__aexit__(None, None, None)


async def test_tier_config_screen_shows_default_tier_composition_on_mount():

    app, pilot, ctx = await _launch_at_tier_config_screen(make_system_info())

    try:

        error_text = app.screen.query_one("#tier-error", Static).content
        assert "Jellyfin" in error_text

    finally:
        await ctx.__aexit__(None, None, None)


async def test_tier_config_screen_selecting_a_tier_updates_composition_line():

    app, pilot, ctx = await _launch_at_tier_config_screen(make_system_info())

    try:

        app.screen.query_one("#heavy", RadioButton).value = True
        await pilot.pause()

        error_text = app.screen.query_one("#tier-error", Static).content
        assert "Uptime Kuma" in error_text

    finally:
        await ctx.__aexit__(None, None, None)


async def test_tier_config_screen_radio_buttons_have_real_composition_tooltips():

    from installer.tiers import TIERS, tier_description

    app, pilot, ctx = await _launch_at_tier_config_screen(make_system_info())

    try:

        for tier_id in ("light", "medium", "heavy"):
            button = app.screen.query_one(f"#{tier_id}", RadioButton)
            assert button.tooltip == tier_description(TIERS[tier_id])

    finally:
        await ctx.__aexit__(None, None, None)


async def test_tier_config_screen_customize_navigates_to_service_selection_screen():

    app, pilot, ctx = await _launch_at_tier_config_screen(make_system_info())

    try:

        app.screen.query_one("#customize", Button).scroll_visible(animate=False)
        await pilot.pause()

        await pilot.click("#customize")
        await pilot.pause()

        assert isinstance(app.screen, ServiceSelectionScreen)
        assert app.tier_name == "medium"
        assert app.puid is not None

    finally:
        await ctx.__aexit__(None, None, None)


async def _launch_at_service_selection_screen(
    info: SystemInfo,
    tier_name: str = "light",
    previous: dict | None = None,
):

    app, pilot, ctx = await _launch_at_media_path_screen(info, previous)

    app.tier_name = tier_name
    app.push_screen(ServiceSelectionScreen())
    await pilot.pause()

    return app, pilot, ctx


async def test_service_selection_screen_prechecks_tier_default_without_previous():

    app, pilot, ctx = await _launch_at_service_selection_screen(
        make_system_info(), tier_name="medium"
    )

    try:

        selected = set(app.screen.query_one("#service-list", SelectionList).selected)
        assert selected == {
            "jellyfin", "radarr", "sonarr", "prowlarr", "qbittorrent",
            "jellyseerr", "bazarr", "flaresolverr"
        }

    finally:
        await ctx.__aexit__(None, None, None)


async def test_service_selection_screen_domain_and_auth_tooltips_set():

    app, pilot, ctx = await _launch_at_service_selection_screen(
        make_system_info(gpu_vendor="amd"), tier_name="medium"
    )

    try:

        domain_tooltip = app.screen.query_one("#domain-input", Input).tooltip
        username_tooltip = app.screen.query_one("#auth-username-input", Input).tooltip
        password_tooltip = app.screen.query_one("#auth-password-input", Input).tooltip
        gpu_tooltip = app.screen.query_one("#gpu-check", Checkbox).tooltip

        assert domain_tooltip
        assert "own this domain" in domain_tooltip
        assert username_tooltip
        assert password_tooltip
        assert "shown again" in password_tooltip
        assert gpu_tooltip

    finally:
        await ctx.__aexit__(None, None, None)


async def test_service_selection_screen_focus_shows_real_tooltip_in_result_line():

    app, pilot, ctx = await _launch_at_service_selection_screen(
        make_system_info(gpu_vendor="amd"), tier_name="medium"
    )

    try:

        gpu_check = app.screen.query_one("#gpu-check", Checkbox)
        assert gpu_check.display is True

        gpu_check.focus()
        await pilot.pause()

        result_widget = app.screen.query_one("#auth-result", Static)
        assert result_widget.display is True
        assert "transcoding" in result_widget.content

    finally:
        await ctx.__aexit__(None, None, None)


async def test_service_selection_screen_focus_clears_result_line_for_untooltipped_widget():

    app, pilot, ctx = await _launch_at_service_selection_screen(
        make_system_info(gpu_vendor="amd"), tier_name="medium"
    )

    try:

        app.screen.query_one("#gpu-check", Checkbox).focus()
        await pilot.pause()
        assert app.screen.query_one("#auth-result", Static).display is True

        app.screen.query_one("#service-list", SelectionList).focus()
        await pilot.pause()

        result_widget = app.screen.query_one("#auth-result", Static)
        assert result_widget.display is False
        assert result_widget.content == ""

    finally:
        await ctx.__aexit__(None, None, None)


async def test_service_selection_screen_prechecks_previous_custom_selection():

    previous = {
        "tier": "light", "media_path": "/mnt/x", "puid": 1000, "pgid": 1000,
        "timezone": "UTC", "enabled_optional": [], "gpu_vendor": None,
        "custom_services": ["jellyfin", "homepage"],
        "generated_at": "2026-01-01T00:00:00+00:00"
    }

    app, pilot, ctx = await _launch_at_service_selection_screen(
        make_system_info(), tier_name="light", previous=previous
    )

    try:

        selected = set(app.screen.query_one("#service-list", SelectionList).selected)
        assert selected == {"jellyfin", "homepage"}

    finally:
        await ctx.__aexit__(None, None, None)


async def test_service_selection_screen_gpu_hidden_without_gpu_detected():

    app, pilot, ctx = await _launch_at_service_selection_screen(
        make_system_info(gpu_vendor=None), tier_name="light"
    )

    try:

        assert app.screen.query_one("#gpu-check", Checkbox).display is False

    finally:
        await ctx.__aexit__(None, None, None)


async def test_service_selection_screen_gpu_hidden_when_jellyfin_not_selected():

    app, pilot, ctx = await _launch_at_service_selection_screen(
        make_system_info(gpu_vendor="amd"), tier_name="light"
    )

    try:

        service_list = app.screen.query_one("#service-list", SelectionList)
        service_list.toggle("jellyfin")
        await pilot.pause()

        assert app.screen.query_one("#gpu-check", Checkbox).display is False

    finally:
        await ctx.__aexit__(None, None, None)


async def test_service_selection_screen_gpu_shown_when_jellyfin_selected_and_gpu_detected():

    app, pilot, ctx = await _launch_at_service_selection_screen(
        make_system_info(gpu_vendor="amd"), tier_name="light"
    )

    try:

        assert app.screen.query_one("#gpu-check", Checkbox).display is True

    finally:
        await ctx.__aexit__(None, None, None)


async def test_service_selection_screen_toggling_jellyfin_back_on_reshows_gpu():

    app, pilot, ctx = await _launch_at_service_selection_screen(
        make_system_info(gpu_vendor="amd"), tier_name="light"
    )

    try:

        service_list = app.screen.query_one("#service-list", SelectionList)

        service_list.toggle("jellyfin")
        await pilot.pause()
        assert app.screen.query_one("#gpu-check", Checkbox).display is False

        service_list.toggle("jellyfin")
        await pilot.pause()
        assert app.screen.query_one("#gpu-check", Checkbox).display is True

    finally:
        await ctx.__aexit__(None, None, None)


async def test_service_selection_screen_continue_stores_services_and_gpu():

    app, pilot, ctx = await _launch_at_service_selection_screen(
        make_system_info(gpu_vendor="amd"), tier_name="light"
    )

    try:

        service_list = app.screen.query_one("#service-list", SelectionList)
        service_list.toggle("radarr")
        service_list.toggle("homepage")
        await pilot.pause()

        await pilot.click("#continue")
        await pilot.pause()

        assert isinstance(app.screen, ReviewScreen)
        assert app.custom_services == {"jellyfin", "sonarr", "prowlarr", "qbittorrent", "homepage"}
        assert app.gpu_vendor == "amd"

    finally:
        await ctx.__aexit__(None, None, None)


async def test_service_selection_screen_continue_no_gpu_vendor_when_unchecked():

    app, pilot, ctx = await _launch_at_service_selection_screen(
        make_system_info(gpu_vendor="amd"), tier_name="light"
    )

    try:

        await pilot.click("#gpu-check")
        await pilot.pause()

        await pilot.click("#continue")
        await pilot.pause()

        assert app.gpu_vendor is None

    finally:
        await ctx.__aexit__(None, None, None)


async def test_service_selection_screen_domain_hidden_without_traefik_selected():

    app, pilot, ctx = await _launch_at_service_selection_screen(
        make_system_info(), tier_name="light"
    )

    try:

        assert app.screen.query_one("#domain-input", Input).display is False

    finally:
        await ctx.__aexit__(None, None, None)


async def test_service_selection_screen_domain_shown_when_traefik_selected():

    app, pilot, ctx = await _launch_at_service_selection_screen(
        make_system_info(), tier_name="light"
    )

    try:

        service_list = app.screen.query_one("#service-list", SelectionList)
        service_list.toggle("traefik")
        await pilot.pause()

        assert app.screen.query_one("#domain-input", Input).display is True

    finally:
        await ctx.__aexit__(None, None, None)


async def test_service_selection_screen_domain_hidden_again_when_traefik_deselected():

    app, pilot, ctx = await _launch_at_service_selection_screen(
        make_system_info(), tier_name="light"
    )

    try:

        service_list = app.screen.query_one("#service-list", SelectionList)

        service_list.toggle("traefik")
        await pilot.pause()
        assert app.screen.query_one("#domain-input", Input).display is True

        service_list.toggle("traefik")
        await pilot.pause()
        assert app.screen.query_one("#domain-input", Input).display is False

    finally:
        await ctx.__aexit__(None, None, None)


async def test_service_selection_screen_cloudflare_checkbox_hidden_without_traefik():

    app, pilot, ctx = await _launch_at_service_selection_screen(
        make_system_info(), tier_name="light"
    )

    try:

        assert app.screen.query_one("#cloudflare-dns-check", Checkbox).display is False
        assert app.screen.query_one("#cloudflare-email-input", Input).display is False

    finally:
        await ctx.__aexit__(None, None, None)


async def test_service_selection_screen_cloudflare_checkbox_shown_when_traefik_selected():

    app, pilot, ctx = await _launch_at_service_selection_screen(
        make_system_info(), tier_name="light"
    )

    try:

        app.screen.query_one("#service-list", SelectionList).toggle("traefik")
        await pilot.pause()

        assert app.screen.query_one("#cloudflare-dns-check", Checkbox).display is True
        # Email input stays hidden until the checkbox itself is checked.
        assert app.screen.query_one("#cloudflare-email-input", Input).display is False

    finally:
        await ctx.__aexit__(None, None, None)


async def test_service_selection_screen_cloudflare_email_shown_when_checkbox_checked():

    app, pilot, ctx = await _launch_at_service_selection_screen(
        make_system_info(), tier_name="light"
    )

    try:

        app.screen.query_one("#service-list", SelectionList).toggle("traefik")
        await pilot.pause()

        app.screen.query_one("#cloudflare-dns-check", Checkbox).value = True
        await pilot.pause()

        assert app.screen.query_one("#cloudflare-email-input", Input).display is True

    finally:
        await ctx.__aexit__(None, None, None)


async def test_service_selection_screen_continue_stores_cloudflare_dns_and_email():

    app, pilot, ctx = await _launch_at_service_selection_screen(
        make_system_info(), tier_name="light"
    )

    try:

        app.screen.query_one("#service-list", SelectionList).toggle("traefik")
        await pilot.pause()

        app.screen.query_one("#domain-input", Input).value = "media.example.com"

        app.screen.query_one("#cloudflare-dns-check", Checkbox).value = True
        await pilot.pause()

        app.screen.query_one("#cloudflare-email-input", Input).value = "me@example.com"

        await pilot.click("#continue")
        await pilot.pause()

        assert app.cloudflare_dns is True
        assert app.cloudflare_email == "me@example.com"

    finally:
        await ctx.__aexit__(None, None, None)


async def test_service_selection_screen_continue_no_cloudflare_when_unchecked():

    app, pilot, ctx = await _launch_at_service_selection_screen(
        make_system_info(), tier_name="light"
    )

    try:

        app.screen.query_one("#service-list", SelectionList).toggle("traefik")
        await pilot.pause()

        app.screen.query_one("#domain-input", Input).value = "media.example.com"

        await pilot.click("#continue")
        await pilot.pause()

        assert app.cloudflare_dns is False
        assert app.cloudflare_email is None

    finally:
        await ctx.__aexit__(None, None, None)


async def test_service_selection_screen_continue_stores_domain_when_traefik_selected():

    app, pilot, ctx = await _launch_at_service_selection_screen(
        make_system_info(), tier_name="light"
    )

    try:

        service_list = app.screen.query_one("#service-list", SelectionList)
        service_list.toggle("traefik")
        await pilot.pause()

        app.screen.query_one("#domain-input", Input).value = "media.example.com"

        await pilot.click("#continue")
        await pilot.pause()

        assert app.domain == "media.example.com"

    finally:
        await ctx.__aexit__(None, None, None)


async def test_service_selection_screen_continue_ignores_domain_when_traefik_deselected():

    app, pilot, ctx = await _launch_at_service_selection_screen(
        make_system_info(), tier_name="light"
    )

    try:

        service_list = app.screen.query_one("#service-list", SelectionList)

        service_list.toggle("traefik")
        await pilot.pause()
        app.screen.query_one("#domain-input", Input).value = "media.example.com"

        service_list.toggle("traefik")
        await pilot.pause()

        await pilot.click("#continue")
        await pilot.pause()

        assert app.domain is None

    finally:
        await ctx.__aexit__(None, None, None)


async def test_service_selection_screen_auth_inputs_hidden_without_authelia_selected():

    app, pilot, ctx = await _launch_at_service_selection_screen(
        make_system_info(), tier_name="light"
    )

    try:

        assert app.screen.query_one("#auth-username-input", Input).display is False
        assert app.screen.query_one("#auth-password-input", Input).display is False

    finally:
        await ctx.__aexit__(None, None, None)


async def test_service_selection_screen_auth_inputs_shown_when_authelia_selected():

    app, pilot, ctx = await _launch_at_service_selection_screen(
        make_system_info(), tier_name="light"
    )

    try:

        service_list = app.screen.query_one("#service-list", SelectionList)
        service_list.toggle("authelia")
        await pilot.pause()

        assert app.screen.query_one("#auth-username-input", Input).display is True
        assert app.screen.query_one("#auth-password-input", Input).display is True

    finally:
        await ctx.__aexit__(None, None, None)


async def test_service_selection_screen_auth_inputs_hidden_when_already_configured(tmp_path):

    users_database_path = tmp_path / "stack" / "config" / "authelia" / "users_database.yml"
    users_database_path.parent.mkdir(parents=True)
    users_database_path.write_text("users: {}\n")

    with patch("installer.tui.service_selection_screen.STACK_DIR", tmp_path / "stack"):

        app, pilot, ctx = await _launch_at_service_selection_screen(
            make_system_info(), tier_name="light"
        )

        try:

            service_list = app.screen.query_one("#service-list", SelectionList)
            service_list.toggle("authelia")
            await pilot.pause()

            assert app.screen.query_one("#auth-username-input", Input).display is False
            assert app.screen.query_one("#auth-password-input", Input).display is False

        finally:
            await ctx.__aexit__(None, None, None)


async def test_service_selection_screen_continue_blank_auth_fields_shows_error():

    app, pilot, ctx = await _launch_at_service_selection_screen(
        make_system_info(), tier_name="light"
    )

    try:

        service_list = app.screen.query_one("#service-list", SelectionList)
        service_list.toggle("authelia")
        await pilot.pause()

        app.screen.query_one("#auth-password-input", Input).value = ""

        await pilot.click("#continue")
        await pilot.pause()

        assert isinstance(app.screen, ServiceSelectionScreen)
        assert "can't be blank" in app.screen.query_one("#auth-result", Static).content

    finally:
        await ctx.__aexit__(None, None, None)


async def test_service_selection_screen_continue_hashes_password_and_proceeds(tmp_path):

    with patch("installer.tui.service_selection_screen.STACK_DIR", tmp_path / "stack"), patch(
        "installer.tui.service_selection_screen.hash_authelia_password",
        return_value={"success": True, "error": None, "hash": "$argon2id$fake$hash"}
    ) as mock_hash:

        app, pilot, ctx = await _launch_at_service_selection_screen(
            make_system_info(), tier_name="light"
        )

        try:

            service_list = app.screen.query_one("#service-list", SelectionList)
            service_list.toggle("authelia")
            await pilot.pause()

            app.screen.query_one("#auth-username-input", Input).value = "admin"
            app.screen.query_one("#auth-password-input", Input).value = "supersecret"

            await pilot.click("#continue")
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()

            mock_hash.assert_called_once_with("supersecret")
            assert isinstance(app.screen, ReviewScreen)
            assert app.auth_username == "admin"
            assert app.auth_password_hash == "$argon2id$fake$hash"

        finally:
            await ctx.__aexit__(None, None, None)


async def test_service_selection_screen_continue_hash_failure_stays_and_shows_error(tmp_path):

    with patch("installer.tui.service_selection_screen.STACK_DIR", tmp_path / "stack"), patch(
        "installer.tui.service_selection_screen.hash_authelia_password",
        return_value={"success": False, "error": "Failed to hash password via authelia's own CLI.", "hash": None}
    ):

        app, pilot, ctx = await _launch_at_service_selection_screen(
            make_system_info(), tier_name="light"
        )

        try:

            service_list = app.screen.query_one("#service-list", SelectionList)
            service_list.toggle("authelia")
            await pilot.pause()

            app.screen.query_one("#auth-username-input", Input).value = "admin"
            app.screen.query_one("#auth-password-input", Input).value = "supersecret"

            await pilot.click("#continue")
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()

            assert isinstance(app.screen, ServiceSelectionScreen)
            assert "Failed to hash password" in app.screen.query_one("#auth-result", Static).content
            assert app.screen.query_one("#continue", Button).disabled is False
            assert app.screen.query_one("#back", Button).disabled is False
            assert app.screen.query_one("#auth-loading", LoadingIndicator).display is False

        finally:
            await ctx.__aexit__(None, None, None)


async def test_review_screen_summary_includes_services_when_custom():

    app, pilot, ctx = await _launch_at_review_screen(
        make_system_info(), custom_services={"jellyfin", "homepage"}
    )

    try:

        summary = app.screen.query_one("#summary", Static).content
        assert "Services: homepage, jellyfin" in summary

    finally:
        await ctx.__aexit__(None, None, None)


async def test_review_screen_summary_omits_services_line_when_not_custom():

    app, pilot, ctx = await _launch_at_review_screen(make_system_info(), custom_services=None)

    try:

        summary = app.screen.query_one("#summary", Static).content
        assert "Services:" not in summary

    finally:
        await ctx.__aexit__(None, None, None)


async def test_review_screen_summary_includes_domain_when_set():

    app, pilot, ctx = await _launch_at_review_screen(
        make_system_info(), custom_services={"jellyfin", "traefik"}, domain="media.example.com"
    )

    try:

        summary = app.screen.query_one("#summary", Static).content
        assert "Domain: media.example.com" in summary

    finally:
        await ctx.__aexit__(None, None, None)


async def test_review_screen_summary_omits_domain_line_when_not_set():

    app, pilot, ctx = await _launch_at_review_screen(make_system_info(), domain=None)

    try:

        summary = app.screen.query_one("#summary", Static).content
        assert "Domain:" not in summary

    finally:
        await ctx.__aexit__(None, None, None)


async def test_review_screen_build_config_includes_custom_services():

    app, pilot, ctx = await _launch_at_review_screen(
        make_system_info(), custom_services={"jellyfin", "homepage"}
    )

    try:

        config = app.screen._build_config()
        assert config.custom_services == {"jellyfin", "homepage"}

    finally:
        await ctx.__aexit__(None, None, None)


async def _launch_at_review_screen(
    info: SystemInfo,
    tier_name: str = "light",
    media_path: str = "/mnt/media",
    puid: int = 1000,
    pgid: int = 1000,
    timezone: str = "UTC",
    enabled_optional: set | None = None,
    gpu_vendor: str | None = None,
    custom_services: set | None = None,
    domain: str | None = None,
    media_redundancy: dict | None = None,
):

    app, pilot, ctx = await _launch_at_tier_config_screen(info, previous=None, media_path=media_path)

    app.tier_name = tier_name
    app.puid = puid
    app.pgid = pgid
    app.timezone = timezone
    app.enabled_optional = enabled_optional if enabled_optional is not None else set()
    app.gpu_vendor = gpu_vendor
    app.custom_services = custom_services
    app.domain = domain
    app.media_redundancy = media_redundancy

    app.push_screen(ReviewScreen())
    await pilot.pause()

    return app, pilot, ctx


REVIEW_WRITE_RESULT = {
    "success": True,
    "compose_path": "/scratch/stack/docker-compose.yml",
    "env_path": "/scratch/stack/.env",
    "warnings": []
}


async def test_review_screen_shows_correct_summary():

    app, pilot, ctx = await _launch_at_review_screen(
        make_system_info(), tier_name="medium", media_path="/mnt/media",
        puid=1000, pgid=1000, timezone="America/New_York",
        enabled_optional={"gluetun"}, gpu_vendor=None
    )

    try:

        summary = app.screen.query_one("#summary", Static).content
        assert "Tier: Medium" in summary
        assert "Media path: /mnt/media" in summary
        assert "PUID/PGID: 1000/1000" in summary
        assert "Timezone: America/New_York" in summary
        assert "Gluetun VPN: enabled" in summary
        assert "SABnzbd: disabled" in summary
        assert "GPU passthrough: disabled" in summary

    finally:
        await ctx.__aexit__(None, None, None)


async def test_review_screen_shows_media_storage_warning_when_not_redundant():

    app, pilot, ctx = await _launch_at_review_screen(
        make_system_info(), tier_name="medium", media_path="/mnt/media",
        media_redundancy={
            "device": "/dev/sda1", "filesystem": "ext4", "redundant": False,
            "redundancy_type": None, "device_count": 1
        }
    )

    try:

        summary = app.screen.query_one("#summary", Static).content
        assert "Media storage: /dev/sda1 (ext4, single device - no redundancy)" in summary
        assert "No drive-level redundancy" in summary

    finally:
        await ctx.__aexit__(None, None, None)


async def test_review_screen_shows_media_storage_without_warning_when_redundant():

    app, pilot, ctx = await _launch_at_review_screen(
        make_system_info(), tier_name="medium", media_path="/mnt/media",
        media_redundancy={
            "device": "/dev/md0", "filesystem": "ext4", "redundant": True,
            "redundancy_type": "raid1", "device_count": 2
        }
    )

    try:

        summary = app.screen.query_one("#summary", Static).content
        assert "Media storage: /dev/md0 (ext4, raid1, 2 devices)" in summary
        assert "No drive-level redundancy" not in summary

    finally:
        await ctx.__aexit__(None, None, None)


async def test_review_screen_omits_media_storage_line_when_unknown():

    app, pilot, ctx = await _launch_at_review_screen(
        make_system_info(), tier_name="medium", media_path="/mnt/media",
        media_redundancy=None
    )

    try:

        summary = app.screen.query_one("#summary", Static).content
        assert "Media storage" not in summary

    finally:
        await ctx.__aexit__(None, None, None)


async def test_review_screen_shows_sabnzbd_enabled_in_summary():

    app, pilot, ctx = await _launch_at_review_screen(
        make_system_info(), tier_name="light", media_path="/mnt/media",
        puid=1000, pgid=1000, timezone="UTC",
        enabled_optional={"sabnzbd"}, gpu_vendor=None
    )

    try:

        summary = app.screen.query_one("#summary", Static).content
        assert "SABnzbd: enabled" in summary

    finally:
        await ctx.__aexit__(None, None, None)


async def test_review_screen_shows_recyclarr_enabled_in_summary():

    app, pilot, ctx = await _launch_at_review_screen(
        make_system_info(), tier_name="light", media_path="/mnt/media",
        puid=1000, pgid=1000, timezone="UTC",
        enabled_optional={"recyclarr"}, gpu_vendor=None
    )

    try:

        summary = app.screen.query_one("#summary", Static).content
        assert "Recyclarr: enabled" in summary

    finally:
        await ctx.__aexit__(None, None, None)


async def test_review_screen_generate_success_reveals_start_and_finish_buttons():

    app, pilot, ctx = await _launch_at_review_screen(make_system_info())

    try:

        with patch(
            "installer.tui.review_screen.write_stack", return_value=REVIEW_WRITE_RESULT
        ):

            await pilot.click("#generate")
            await pilot.pause()

        result = app.screen.query_one("#result", Static).content
        assert "Stack written to" in result

        assert app.screen.query_one("#start", Button).display is True
        assert app.screen.query_one("#finish", Button).display is True
        assert app.screen.query_one("#generate", Button).disabled is True

    finally:
        await ctx.__aexit__(None, None, None)


async def test_review_screen_generate_shows_warnings():

    result_with_warning = {**REVIEW_WRITE_RESULT, "warnings": ["fill in your VPN credentials"]}

    app, pilot, ctx = await _launch_at_review_screen(make_system_info())

    try:

        with patch(
            "installer.tui.review_screen.write_stack", return_value=result_with_warning
        ):

            await pilot.click("#generate")
            await pilot.pause()

        result = app.screen.query_one("#result", Static).content
        assert "fill in your VPN credentials" in result

    finally:
        await ctx.__aexit__(None, None, None)


async def test_review_screen_generate_failure_shows_error_no_buttons():

    app, pilot, ctx = await _launch_at_review_screen(make_system_info())

    try:

        with patch(
            "installer.tui.review_screen.write_stack",
            side_effect=OSError("permission denied")
        ):

            await pilot.click("#generate")
            await pilot.pause()

        result = app.screen.query_one("#result", Static).content
        assert "Failed to write the stack" in result

        assert app.screen.query_one("#start", Button).display is False
        assert app.screen.query_one("#finish", Button).display is False

    finally:
        await ctx.__aexit__(None, None, None)


async def test_review_screen_finish_without_starting_exits_with_command_message():

    app, pilot, ctx = await _launch_at_review_screen(make_system_info())

    try:

        with patch(
            "installer.tui.review_screen.write_stack", return_value=REVIEW_WRITE_RESULT
        ):

            await pilot.click("#generate")
            await pilot.pause()

            await pilot.click("#finish")
            await pilot.pause()

        assert app.is_running is False

    finally:
        await ctx.__aexit__(None, None, None)


async def test_review_screen_start_stack_success_exits_cleanly():

    mock_proc = MagicMock(returncode=0)

    app, pilot, ctx = await _launch_at_review_screen(make_system_info())
    app.group_just_added = True

    try:

        with patch(
            "installer.tui.review_screen.write_stack", return_value=REVIEW_WRITE_RESULT
        ):

            await pilot.click("#generate")
            await pilot.pause()

        with patch(
            "installer.tui.review_screen.check_ports_available",
            return_value={"available": True, "conflicts": []}
        ), patch(
            "installer.tui.review_screen.run_docker_command", return_value=mock_proc
        ) as mock_run_docker:

            await pilot.click("#start")
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()

        args, kwargs = mock_run_docker.call_args
        command = args[0]

        assert command[:2] == ["docker", "compose"]
        assert "up" in command and "-d" in command
        assert kwargs["use_group_workaround"] is True
        assert app.is_running is False

    finally:
        await ctx.__aexit__(None, None, None)


async def test_review_screen_start_stack_success_exit_message_lists_service_urls():

    mock_proc = MagicMock(returncode=0)

    app, pilot, ctx = await _launch_at_review_screen(make_system_info())

    try:

        with patch(
            "installer.tui.review_screen.write_stack", return_value=REVIEW_WRITE_RESULT
        ):

            await pilot.click("#generate")
            await pilot.pause()

        with patch(
            "installer.tui.review_screen.check_ports_available",
            return_value={"available": True, "conflicts": []}
        ), patch(
            "installer.tui.review_screen.detect_host_ip", return_value="192.168.1.50"
        ), patch(
            "installer.tui.review_screen.run_docker_command", return_value=mock_proc
        ), patch.object(
            app, "exit"
        ) as mock_exit:

            await pilot.click("#start")
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()

        message = mock_exit.call_args[1]["message"]

        assert "Stack is up" in message
        assert "Jellyfin: http://192.168.1.50:8096" in message
        assert "Radarr: http://192.168.1.50:7878" in message

    finally:
        await ctx.__aexit__(None, None, None)


async def test_review_screen_start_stack_failure_exits_with_failure_message():

    mock_proc = MagicMock(returncode=1)

    app, pilot, ctx = await _launch_at_review_screen(make_system_info())

    try:

        with patch(
            "installer.tui.review_screen.write_stack", return_value=REVIEW_WRITE_RESULT
        ):

            await pilot.click("#generate")
            await pilot.pause()

        with patch(
            "installer.tui.review_screen.check_ports_available",
            return_value={"available": True, "conflicts": []}
        ), patch(
            "installer.tui.review_screen.run_docker_command", return_value=mock_proc
        ):

            await pilot.click("#start")
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()

        assert app.is_running is False

    finally:
        await ctx.__aexit__(None, None, None)


async def test_review_screen_start_stack_port_conflict_stays_interactive():

    app, pilot, ctx = await _launch_at_review_screen(make_system_info())

    try:

        with patch(
            "installer.tui.review_screen.write_stack", return_value=REVIEW_WRITE_RESULT
        ):

            await pilot.click("#generate")
            await pilot.pause()

        with patch(
            "installer.tui.review_screen.check_ports_available",
            return_value={
                "available": False,
                "conflicts": [8080],
                "owners": {8080: None},
                "port_services": {8080: "qbittorrent"},
                "own_orphan": {8080: False},
            }
        ), patch(
            "installer.tui.review_screen.run_docker_command"
        ) as mock_run_docker:

            await pilot.click("#start")
            await pilot.pause()

        mock_run_docker.assert_not_called()
        assert app.is_running is True

        result = app.screen.query_one("#result", Static).content
        assert "8080" in result

        assert app.screen.query_one("#start", Button).disabled is False
        assert app.screen.query_one("#pull", Button).disabled is False
        assert app.screen.query_one("#finish", Button).disabled is False
        assert app.screen.query_one("#back", Button).disabled is False
        assert app.screen.query_one("#cleanup-retry", Button).display is False

    finally:
        await ctx.__aexit__(None, None, None)


async def test_review_screen_own_orphan_conflict_shows_cleanup_button_and_retries():
    """
    The TUI's real, narrower treatment of port-conflict override: no
    interactive remap sub-flow (see CLAUDE.md for why), but the
    auto-cleanable "own orphaned containers" case gets a real button
    that removes just those containers and retries the start.
    """

    app, pilot, ctx = await _launch_at_review_screen(make_system_info())

    try:

        with patch(
            "installer.tui.review_screen.write_stack", return_value=REVIEW_WRITE_RESULT
        ):

            await pilot.click("#generate")
            await pilot.pause()

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

        mock_proc = MagicMock(returncode=0)

        with patch(
            "installer.tui.review_screen.check_ports_available", side_effect=conflict_then_clear
        ), patch(
            "installer.tui.review_screen.remove_orphaned_containers",
            return_value={"success": True, "error": None}
        ) as mock_cleanup, patch(
            "installer.tui.review_screen.run_docker_command", return_value=mock_proc
        ):

            await pilot.click("#start")
            await pilot.pause()

            assert app.screen.query_one("#cleanup-retry", Button).display is True

            await pilot.click("#cleanup-retry")
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()

        mock_cleanup.assert_called_once_with("stack")
        assert app.is_running is False

    finally:
        await ctx.__aexit__(None, None, None)


async def test_review_screen_remap_button_shown_for_unrelated_conflict():

    app, pilot, ctx = await _launch_at_review_screen(make_system_info())

    try:

        with patch(
            "installer.tui.review_screen.write_stack", return_value=REVIEW_WRITE_RESULT
        ):

            await pilot.click("#generate")
            await pilot.pause()

        with patch(
            "installer.tui.review_screen.check_ports_available",
            return_value={
                "available": False,
                "conflicts": [8080],
                "owners": {8080: 'container "nginx" (image nginx:alpine)'},
                "port_services": {8080: "qbittorrent"},
                "own_orphan": {8080: False},
            }
        ):

            await pilot.click("#start")
            await pilot.pause()

        assert app.screen.query_one("#remap-ports", Button).display is True
        assert app.screen.query_one("#cleanup-retry", Button).display is False

    finally:
        await ctx.__aexit__(None, None, None)


async def test_review_screen_remap_flow_applies_new_port_and_starts():
    """
    The real interactive-remap sub-flow the TUI never had before: type a
    replacement host port into a dynamically mounted Input, apply it,
    and the stack regenerates and retries starting - same shape as the
    CLI's --plain remap prompt, adapted to the TUI's widget model.
    """

    app, pilot, ctx = await _launch_at_review_screen(make_system_info())

    try:

        with patch(
            "installer.tui.review_screen.write_stack", return_value=REVIEW_WRITE_RESULT
        ):

            await pilot.click("#generate")
            await pilot.pause()

        conflict_then_clear = [
            {
                "available": False,
                "conflicts": [8080],
                "owners": {8080: 'container "nginx" (image nginx:alpine)'},
                "port_services": {8080: "qbittorrent"},
                "own_orphan": {8080: False},
            },
            {"available": True, "conflicts": [], "owners": {}, "port_services": {}, "own_orphan": {}},
        ]

        mock_proc = MagicMock(returncode=0)

        with patch(
            "installer.tui.review_screen.check_ports_available", side_effect=conflict_then_clear
        ), patch(
            "installer.tui.review_screen.write_stack", return_value=REVIEW_WRITE_RESULT
        ) as mock_write_stack, patch(
            "installer.tui.review_screen.run_docker_command", return_value=mock_proc
        ):

            await pilot.click("#start")
            await pilot.pause()

            await pilot.click("#remap-ports")
            await pilot.pause()

            input_widget = app.screen.query_one("#remap-input-8080", Input)
            input_widget.value = "9090"

            await pilot.click("#apply-remap")
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()

        assert app.port_overrides == {"qbittorrent": 9090}
        # write_stack called once for the initial generate, once for the remap
        assert mock_write_stack.call_count == 1
        assert app.is_running is False

    finally:
        await ctx.__aexit__(None, None, None)


async def test_review_screen_remap_rejects_colliding_port():

    app, pilot, ctx = await _launch_at_review_screen(make_system_info())

    try:

        with patch(
            "installer.tui.review_screen.write_stack", return_value=REVIEW_WRITE_RESULT
        ):

            await pilot.click("#generate")
            await pilot.pause()

        with patch(
            "installer.tui.review_screen.check_ports_available",
            return_value={
                "available": False,
                "conflicts": [8080],
                "owners": {8080: 'container "nginx" (image nginx:alpine)'},
                "port_services": {8080: "qbittorrent"},
                "own_orphan": {8080: False},
            }
        ), patch(
            "installer.tui.review_screen.write_stack", return_value=REVIEW_WRITE_RESULT
        ) as mock_write_stack:

            await pilot.click("#start")
            await pilot.pause()

            await pilot.click("#remap-ports")
            await pilot.pause()

            input_widget = app.screen.query_one("#remap-input-8080", Input)
            input_widget.value = "7878"  # radarr's own default port - a real collision

            await pilot.click("#apply-remap")
            await pilot.pause()

        mock_write_stack.assert_not_called()
        error = app.screen.query_one("#remap-error", Static).content
        assert "7878" in error
        assert "already used" in error

    finally:
        await ctx.__aexit__(None, None, None)


async def test_review_screen_remap_reachable_with_many_simultaneous_conflicts():
    """
    A real layout hazard, reproduced and fixed, not just reasoned about:
    with enough simultaneous conflicting ports, the dynamically-added
    rows push Apply/Cancel below the 80x24 test viewport - the exact
    class of OutOfBounds failure this project has hit before with
    TierConfigScreen (see CLAUDE.md). ReviewScreen's root container is
    a VerticalScroll for exactly this reason; a real user would need to
    scroll to see off-screen content too, so this scrolls the target
    into view first, the same as a real click would require.
    """

    app, pilot, ctx = await _launch_at_review_screen(make_system_info())

    try:

        with patch(
            "installer.tui.review_screen.write_stack", return_value=REVIEW_WRITE_RESULT
        ):

            await pilot.click("#generate")
            await pilot.pause()

        conflict_then_clear = [
            {
                "available": False,
                "conflicts": [8080, 7878, 8989],
                "owners": {8080: "x", 7878: "y", 8989: "z"},
                "port_services": {8080: "qbittorrent", 7878: "radarr", 8989: "sonarr"},
                "own_orphan": {8080: False, 7878: False, 8989: False},
            },
            {"available": True, "conflicts": [], "owners": {}, "port_services": {}, "own_orphan": {}},
        ]

        mock_proc = MagicMock(returncode=0)

        with patch(
            "installer.tui.review_screen.check_ports_available", side_effect=conflict_then_clear
        ), patch(
            "installer.tui.review_screen.write_stack", return_value=REVIEW_WRITE_RESULT
        ), patch(
            "installer.tui.review_screen.run_docker_command", return_value=mock_proc
        ):

            await pilot.click("#start")
            await pilot.pause()

            await pilot.click("#remap-ports")
            await pilot.pause()

            for port, new_port in ((8080, 9080), (7878, 9878), (8989, 9989)):
                input_widget = app.screen.query_one(f"#remap-input-{port}", Input)
                input_widget.scroll_visible(animate=False)
                await pilot.pause()
                input_widget.value = str(new_port)

            apply_button = app.screen.query_one("#apply-remap", Button)
            apply_button.scroll_visible(animate=False)
            await pilot.pause()

            await pilot.click("#apply-remap")
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()

        assert app.port_overrides == {"qbittorrent": 9080, "radarr": 9878, "sonarr": 9989}
        assert app.is_running is False

    finally:
        await ctx.__aexit__(None, None, None)


async def test_review_screen_remap_cancel_hides_fields():

    app, pilot, ctx = await _launch_at_review_screen(make_system_info())

    try:

        with patch(
            "installer.tui.review_screen.write_stack", return_value=REVIEW_WRITE_RESULT
        ):

            await pilot.click("#generate")
            await pilot.pause()

        with patch(
            "installer.tui.review_screen.check_ports_available",
            return_value={
                "available": False,
                "conflicts": [8080],
                "owners": {8080: 'container "nginx" (image nginx:alpine)'},
                "port_services": {8080: "qbittorrent"},
                "own_orphan": {8080: False},
            }
        ):

            await pilot.click("#start")
            await pilot.pause()

            await pilot.click("#remap-ports")
            await pilot.pause()

            assert app.screen.query_one("#remap-fields").display is True

            await pilot.click("#cancel-remap")
            await pilot.pause()

        assert app.screen.query_one("#remap-fields").display is False
        assert app.screen.query_one("#remap-ports", Button).disabled is False

    finally:
        await ctx.__aexit__(None, None, None)


async def test_review_screen_pull_images_success_exits_cleanly():

    app, pilot, ctx = await _launch_at_review_screen(make_system_info())

    try:

        with patch(
            "installer.tui.review_screen.write_stack", return_value=REVIEW_WRITE_RESULT
        ):

            await pilot.click("#generate")
            await pilot.pause()

        with patch(
            "installer.tui.review_screen.pull_stack",
            return_value={"success": True, "error": None}
        ) as mock_pull:

            await pilot.click("#pull")
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()

        mock_pull.assert_called_once()
        assert app.is_running is False

    finally:
        await ctx.__aexit__(None, None, None)


async def test_review_screen_pull_images_failure_exits_with_failure_message():

    app, pilot, ctx = await _launch_at_review_screen(make_system_info())

    try:

        with patch(
            "installer.tui.review_screen.write_stack", return_value=REVIEW_WRITE_RESULT
        ):

            await pilot.click("#generate")
            await pilot.pause()

        with patch(
            "installer.tui.review_screen.pull_stack",
            return_value={"success": False, "error": "Failed to pull images - check `docker compose logs`."}
        ):

            await pilot.click("#pull")
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()

        assert app.is_running is False

    finally:
        await ctx.__aexit__(None, None, None)


async def test_review_screen_generate_success_reveals_pull_button():

    app, pilot, ctx = await _launch_at_review_screen(make_system_info())

    try:

        with patch(
            "installer.tui.review_screen.write_stack", return_value=REVIEW_WRITE_RESULT
        ):

            await pilot.click("#generate")
            await pilot.pause()

        assert app.screen.query_one("#pull", Button).display is True
        assert app.screen.query_one("#pull", Button).disabled is False

    finally:
        await ctx.__aexit__(None, None, None)


async def test_docker_ready_screen_back_returns_to_welcome_screen():

    app, pilot, ctx = await _launch_at_docker_screen(make_system_info())

    try:

        await pilot.click("#back")
        await pilot.pause()

        assert isinstance(app.screen, WelcomeScreen)

    finally:
        await ctx.__aexit__(None, None, None)


async def test_docker_ready_screen_back_disabled_while_fix_running():

    info = make_system_info(
        docker_installed=False, docker_running=False, docker_compose_v2=False
    )

    def slow_install_docker(*args, **kwargs):
        time.sleep(0.2)
        return {"success": True, "error": None}

    with patch(
        "installer.tui.docker_screen.install_plan_for",
        return_value={"method": "get.docker.com", "description": "curl ... | sh"}
    ), patch(
        "installer.tui.docker_screen.install_docker", side_effect=slow_install_docker
    ), patch(
        "installer.tui.docker_screen.start_docker_service"
    ), patch(
        "installer.tui.docker_screen.add_user_to_docker_group"
    ), patch(
        "installer.tui.docker_screen.ensure_compose_v2"
    ), patch(
        "installer.tui.docker_screen.detect_docker",
        return_value={"docker_installed": True, "docker_running": True, "docker_compose_v2": True}
    ):

        app, pilot, ctx = await _launch_at_docker_screen(info)

        try:

            await pilot.click("#action")
            await pilot.pause()

            assert app.screen.query_one("#back", Button).disabled is True

            await app.workers.wait_for_complete()
            await pilot.pause()

            assert app.screen.query_one("#back", Button).disabled is False

        finally:
            await ctx.__aexit__(None, None, None)


async def test_media_path_screen_back_returns_to_docker_ready_screen():

    with patch(
        "installer.tui.welcome_screen.detect_system", return_value=make_system_info()
    ), patch(
        "installer.tui.welcome_screen.load_previous_state", return_value=None
    ):

        app = VulcanApp()

        async with app.run_test() as pilot:

            app.push_screen(WelcomeScreen())
            await pilot.pause()

            await app.workers.wait_for_complete()
            await pilot.pause()

            await pilot.click("#continue")
            await pilot.pause()
            assert isinstance(app.screen, DockerReadyScreen)

            await pilot.click("#continue")
            await pilot.pause()
            assert isinstance(app.screen, MediaPathScreen)

            await pilot.click("#back")
            await pilot.pause()

            assert isinstance(app.screen, DockerReadyScreen)


async def test_tier_config_screen_back_returns_to_media_path_screen():

    app, pilot, ctx = await _launch_at_tier_config_screen(make_system_info())

    try:

        app.screen.query_one("#back", Button).scroll_visible(animate=False)
        await pilot.pause()

        await pilot.click("#back")
        await pilot.pause()

        assert isinstance(app.screen, MediaPathScreen)

    finally:
        await ctx.__aexit__(None, None, None)


async def test_tier_config_screen_back_preserves_previously_entered_values():

    app, pilot, ctx = await _launch_at_tier_config_screen(make_system_info())

    try:

        app.screen.query_one("#puid-input", Input).value = "1234"

        app.screen.query_one("#continue", Button).scroll_visible(animate=False)
        await pilot.pause()

        await pilot.click("#continue")
        await pilot.pause()
        assert isinstance(app.screen, ReviewScreen)

        await pilot.click("#back")
        await pilot.pause()

        assert isinstance(app.screen, TierConfigScreen)
        assert app.screen.query_one("#puid-input", Input).value == "1234"

    finally:
        await ctx.__aexit__(None, None, None)


async def test_service_selection_screen_back_returns_to_tier_config_screen():

    app, pilot, ctx = await _launch_at_tier_config_screen(make_system_info())

    try:

        app.screen.query_one("#customize", Button).scroll_visible(animate=False)
        await pilot.pause()

        await pilot.click("#customize")
        await pilot.pause()
        assert isinstance(app.screen, ServiceSelectionScreen)

        await pilot.click("#back")
        await pilot.pause()

        assert isinstance(app.screen, TierConfigScreen)

    finally:
        await ctx.__aexit__(None, None, None)


async def test_review_screen_back_returns_to_tier_config_screen():

    app, pilot, ctx = await _launch_at_review_screen(make_system_info())

    try:

        await pilot.click("#back")
        await pilot.pause()

        assert isinstance(app.screen, TierConfigScreen)

    finally:
        await ctx.__aexit__(None, None, None)


async def test_review_screen_back_returns_to_service_selection_screen():

    app, pilot, ctx = await _launch_at_tier_config_screen(make_system_info())

    try:

        app.screen.query_one("#customize", Button).scroll_visible(animate=False)
        await pilot.pause()

        await pilot.click("#customize")
        await pilot.pause()
        assert isinstance(app.screen, ServiceSelectionScreen)

        app.screen.query_one("#continue", Button).scroll_visible(animate=False)
        await pilot.pause()

        await pilot.click("#continue")
        await pilot.pause()
        assert isinstance(app.screen, ReviewScreen)

        await pilot.click("#back")
        await pilot.pause()

        assert isinstance(app.screen, ServiceSelectionScreen)

    finally:
        await ctx.__aexit__(None, None, None)


async def test_review_screen_back_disabled_after_start_stack_clicked():

    def slow_run_docker_command(*args, **kwargs):
        time.sleep(0.2)
        return MagicMock(returncode=0)

    app, pilot, ctx = await _launch_at_review_screen(make_system_info())

    try:

        with patch(
            "installer.tui.review_screen.write_stack", return_value=REVIEW_WRITE_RESULT
        ):

            await pilot.click("#generate")
            await pilot.pause()

        with patch(
            "installer.tui.review_screen.check_ports_available",
            return_value={"available": True, "conflicts": []}
        ), patch(
            "installer.tui.review_screen.run_docker_command", side_effect=slow_run_docker_command
        ):

            await pilot.click("#start")
            await pilot.pause()

            assert app.screen.query_one("#back", Button).disabled is True

    finally:
        await ctx.__aexit__(None, None, None)


async def test_review_screen_back_disabled_after_pull_images_clicked():

    def slow_pull_stack(*args, **kwargs):
        time.sleep(0.2)
        return {"success": True, "error": None}

    app, pilot, ctx = await _launch_at_review_screen(make_system_info())

    try:

        with patch(
            "installer.tui.review_screen.write_stack", return_value=REVIEW_WRITE_RESULT
        ):

            await pilot.click("#generate")
            await pilot.pause()

        with patch(
            "installer.tui.review_screen.pull_stack", side_effect=slow_pull_stack
        ):

            await pilot.click("#pull")
            await pilot.pause()

            assert app.screen.query_one("#back", Button).disabled is True

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

        app.push_screen(WelcomeScreen())
        await pilot.pause()

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

        app.screen.query_one("#continue", Button).scroll_visible(animate=False)
        await pilot.pause()

        await pilot.click("#continue")
        await pilot.pause()

        assert isinstance(app.screen, ReviewScreen)
        assert app.tier_name in ("light", "medium", "heavy")
        assert app.puid is not None

        # Real write_stack() call - lands in the real repo's stack/ dir
        # (write_stack()'s own default), same as a real `./install --tui`
        # run would produce. Removed in the finally block below so the
        # test suite stays side-effect-free across repeated runs.
        try:

            await pilot.click("#generate")
            await pilot.pause()

            result = app.screen.query_one("#result", Static).content
            assert "Stack written to" in result

            stack_dir = Path("stack")
            assert (stack_dir / "docker-compose.yml").exists()
            assert (stack_dir / ".env").exists()

            validation = subprocess.run(
                [
                    "docker", "compose",
                    "-f", str(stack_dir / "docker-compose.yml"),
                    "--env-file", str(stack_dir / ".env"),
                    "config"
                ],
                capture_output=True
            )
            assert validation.returncode == 0, validation.stderr.decode()

            await pilot.click("#finish")
            await pilot.pause()

            assert app.is_running is False

        finally:
            shutil.rmtree(Path("stack"), ignore_errors=True)


# --- MainMenuScreen -----------------------------------------------------
#
# STACK_DIR/latest_backup/stack_containers_exist are all patched at
# installer.tui.main_menu_screen's own namespace (the importing
# module - see the "mock at the importing module's namespace"
# convention above) rather than touching real relative stack/backups/
# directories or calling real `docker ps` - this project's own
# established exception is real-infrastructure checks, and these are
# pure gating-logic tests, not that.

async def _launch_main_menu(stack_exists: bool, has_backups: bool):
    """
    stack_exists is faked via stack_containers_exist() rather than a
    real compose_path.exists() check - _refresh_gating()'s own
    condition is "compose_path.exists() OR stack_containers_exist(...)",
    so controlling the second half is equivalent without needing a
    real file on disk, and keeps STACK_DIR pointed at a guaranteed-
    nonexistent path throughout.
    """

    with patch(
        "installer.tui.main_menu_screen.STACK_DIR", Path("nonexistent-stack")
    ), patch(
        "installer.tui.main_menu_screen.stack_containers_exist", return_value=stack_exists
    ), patch(
        "installer.tui.main_menu_screen.latest_backup",
        return_value=(Path("backups/fake.tar.gz") if has_backups else None)
    ):

        app = VulcanApp()
        ctx = app.run_test()
        pilot = await ctx.__aenter__()
        await pilot.pause()

    return app, pilot, ctx


async def test_main_menu_is_the_initial_screen():

    app, pilot, ctx = await _launch_main_menu(stack_exists=False, has_backups=False)

    try:
        assert isinstance(app.screen, MainMenuScreen)
    finally:
        await ctx.__aexit__(None, None, None)


async def test_main_menu_disables_stack_actions_without_existing_stack():

    app, pilot, ctx = await _launch_main_menu(stack_exists=False, has_backups=False)

    try:

        for button_id in ("update-stack", "pull-images", "backup-stack", "uninstall-stack"):
            assert app.screen.query_one(f"#{button_id}", Button).disabled is True

        assert app.screen.query_one("#restore-stack", Button).disabled is True
        assert app.screen.query_one("#guided-setup", Button).disabled is False
        # Updates Vulcan itself, not a generated stack - never gated on
        # stack_exists; update_vulcan_self() has its own real (not-a-
        # git-checkout) refusal path instead.
        assert app.screen.query_one("#update-self", Button).disabled is False

    finally:
        await ctx.__aexit__(None, None, None)


async def test_main_menu_enables_stack_actions_with_existing_stack():

    app, pilot, ctx = await _launch_main_menu(stack_exists=True, has_backups=False)

    try:

        for button_id in ("update-stack", "pull-images", "backup-stack", "uninstall-stack"):
            assert app.screen.query_one(f"#{button_id}", Button).disabled is False

        assert app.screen.query_one("#restore-stack", Button).disabled is True

    finally:
        await ctx.__aexit__(None, None, None)


async def test_main_menu_enables_restore_when_a_backup_exists_without_a_stack():
    """
    Restore's real precondition is a backup archive, not an existing
    stack - you can restore onto a machine with nothing installed yet
    (matches cli.py restore()'s own real behavior).
    """

    app, pilot, ctx = await _launch_main_menu(stack_exists=False, has_backups=True)

    try:

        assert app.screen.query_one("#restore-stack", Button).disabled is False
        assert app.screen.query_one("#update-stack", Button).disabled is True

    finally:
        await ctx.__aexit__(None, None, None)


async def test_main_menu_guided_setup_pushes_welcome_screen():

    app, pilot, ctx = await _launch_main_menu(stack_exists=False, has_backups=False)

    try:

        await pilot.click("#guided-setup")
        await pilot.pause()

        assert isinstance(app.screen, WelcomeScreen)

    finally:
        await ctx.__aexit__(None, None, None)


async def test_main_menu_exit_quits_the_app():

    app, pilot, ctx = await _launch_main_menu(stack_exists=False, has_backups=False)

    try:

        # Exit is the last of 7 stacked buttons - past the fixed 80x24
        # test viewport, same as every other real scroll-into-view case
        # this project's own test suite already establishes elsewhere.
        app.screen.query_one("#exit", Button).scroll_visible(animate=False)
        await pilot.pause()

        await pilot.click("#exit")
        await pilot.pause()

        assert app.is_running is False

    finally:
        await ctx.__aexit__(None, None, None)


async def test_main_menu_focus_shows_tooltip_in_help_line():

    app, pilot, ctx = await _launch_main_menu(stack_exists=False, has_backups=False)

    try:

        guided_setup = app.screen.query_one("#guided-setup", Button)
        guided_setup.focus()
        await pilot.pause()

        help_line = app.screen.query_one("#menu-help", Static).content
        assert "hardware" in help_line

    finally:
        await ctx.__aexit__(None, None, None)


async def test_main_menu_gating_refreshes_on_return_from_a_sub_screen():
    """
    MainMenuScreen is revealed, not remounted, on pop_screen() (real
    Textual behavior - ScreenResume, not Mount) - so button gating
    computed once in compose()/on_mount() would go stale the moment a
    backup is taken while on a sub-screen. Confirmed here by flipping
    what latest_backup() returns mid-test and checking the button only
    updates after actually returning to the Main Menu, not before.
    """

    with patch(
        "installer.tui.main_menu_screen.STACK_DIR", Path("nonexistent-stack")
    ), patch(
        "installer.tui.main_menu_screen.stack_containers_exist", return_value=False
    ), patch(
        "installer.tui.main_menu_screen.latest_backup", return_value=None
    ) as mock_latest_backup:

        app = VulcanApp()

        async with app.run_test() as pilot:

            assert app.screen.query_one("#restore-stack", Button).disabled is True

            # A backup now exists, but MainMenuScreen hasn't been told -
            # pushing a screen on top and popping back is what should
            # trigger the real refresh, via on_screen_resume().
            mock_latest_backup.return_value = Path("backups/fake.tar.gz")

            app.push_screen(MainMenuScreen())
            await pilot.pause()
            app.pop_screen()
            await pilot.pause()

            assert app.screen.query_one("#restore-stack", Button).disabled is False


# --- MaintenanceScreen ---------------------------------------------------

async def _launch_maintenance_screen(screen: MaintenanceScreen):

    app = VulcanApp()
    ctx = app.run_test()
    pilot = await ctx.__aenter__()

    app.push_screen(screen)
    await pilot.pause()

    return app, pilot, ctx


async def test_maintenance_screen_update_confirm_runs_and_shows_success():

    with patch(
        "installer.tui.maintenance_screen.update_stack",
        return_value={"success": True, "error": None}
    ):

        app, pilot, ctx = await _launch_maintenance_screen(MaintenanceScreen.for_update())

        try:

            await pilot.click("#confirm")
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()

            assert app.screen.query_one("#maint-result", Static).content == "Stack updated."
            assert app.screen.query_one("#back-to-menu", Button).disabled is False

        finally:
            await ctx.__aexit__(None, None, None)


async def test_maintenance_screen_shows_error_on_failure():

    with patch(
        "installer.tui.maintenance_screen.pull_stack",
        return_value={"success": False, "error": "Failed to pull images - check `docker compose logs`."}
    ):

        app, pilot, ctx = await _launch_maintenance_screen(MaintenanceScreen.for_pull())

        try:

            await pilot.click("#confirm")
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()

            result = app.screen.query_one("#maint-result", Static).content
            assert "Failed to pull images" in result

        finally:
            await ctx.__aexit__(None, None, None)


async def test_maintenance_screen_cancel_pops_back():

    app, pilot, ctx = await _launch_maintenance_screen(MaintenanceScreen.for_backup())

    try:

        assert isinstance(app.screen, MaintenanceScreen)

        await pilot.click("#cancel")
        await pilot.pause()

        assert not isinstance(app.screen, MaintenanceScreen)

    finally:
        await ctx.__aexit__(None, None, None)


async def test_maintenance_screen_backup_shows_path_and_warnings():

    with patch(
        "installer.tui.maintenance_screen.backup_stack",
        return_value={
            "success": True, "error": None,
            "backup_path": "backups/vulcan-backup-20260101T000000Z.tar.gz",
            "warnings": ["This backup includes stack/.env, which may contain real credentials."]
        }
    ):

        app, pilot, ctx = await _launch_maintenance_screen(MaintenanceScreen.for_backup())

        try:

            await pilot.click("#confirm")
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()

            result = app.screen.query_one("#maint-result", Static).content
            assert "vulcan-backup-20260101T000000Z.tar.gz" in result
            assert "! This backup includes stack/.env" in result

        finally:
            await ctx.__aexit__(None, None, None)


async def test_maintenance_screen_update_self_reports_new_commit():

    with patch(
        "installer.tui.maintenance_screen.update_vulcan_self",
        return_value={
            "success": True, "error": None, "updated": True,
            "old_commit": "abc1234", "new_commit": "def5678"
        }
    ):

        app, pilot, ctx = await _launch_maintenance_screen(MaintenanceScreen.for_update_self())

        try:

            await pilot.click("#confirm")
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()

            result = app.screen.query_one("#maint-result", Static).content
            assert "abc1234" in result
            assert "def5678" in result
            assert "Restart Vulcan" in result

        finally:
            await ctx.__aexit__(None, None, None)


async def test_maintenance_screen_update_self_already_up_to_date():

    with patch(
        "installer.tui.maintenance_screen.update_vulcan_self",
        return_value={"success": True, "error": None, "updated": False, "commit": "abc1234"}
    ):

        app, pilot, ctx = await _launch_maintenance_screen(MaintenanceScreen.for_update_self())

        try:

            await pilot.click("#confirm")
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()

            result = app.screen.query_one("#maint-result", Static).content
            assert "Already up to date" in result
            assert "abc1234" in result

        finally:
            await ctx.__aexit__(None, None, None)


async def test_main_menu_update_self_pushes_maintenance_screen():

    app, pilot, ctx = await _launch_main_menu(stack_exists=False, has_backups=False)

    try:

        app.screen.query_one("#update-self", Button).scroll_visible(animate=False)
        await pilot.pause()

        await pilot.click("#update-self")
        await pilot.pause()

        assert isinstance(app.screen, MaintenanceScreen)
        assert app.screen.query_one("#title", Static).content == "Update Vulcan"

    finally:
        await ctx.__aexit__(None, None, None)


async def test_maintenance_screen_uninstall_shows_purge_checkbox():

    app, pilot, ctx = await _launch_maintenance_screen(MaintenanceScreen.for_uninstall())

    try:
        assert app.screen.query_one("#purge-artifacts", Checkbox) is not None
    finally:
        await ctx.__aexit__(None, None, None)


async def test_maintenance_screen_other_actions_have_no_purge_checkbox():

    app, pilot, ctx = await _launch_maintenance_screen(MaintenanceScreen.for_update())

    try:
        assert len(app.screen.query("#purge-artifacts")) == 0
    finally:
        await ctx.__aexit__(None, None, None)


async def test_maintenance_screen_uninstall_passes_purge_artifacts_flag():

    mock_uninstall = MagicMock(return_value={"success": True, "error": None})

    with patch("installer.tui.maintenance_screen.uninstall_stack", mock_uninstall):

        app, pilot, ctx = await _launch_maintenance_screen(MaintenanceScreen.for_uninstall())

        try:

            await pilot.click("#purge-artifacts")
            await pilot.click("#confirm")
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()

            assert mock_uninstall.call_args.kwargs["purge_artifacts"] is True

        finally:
            await ctx.__aexit__(None, None, None)


async def test_maintenance_screen_uninstall_defaults_purge_artifacts_false():

    mock_uninstall = MagicMock(return_value={"success": True, "error": None})

    with patch("installer.tui.maintenance_screen.uninstall_stack", mock_uninstall):

        app, pilot, ctx = await _launch_maintenance_screen(MaintenanceScreen.for_uninstall())

        try:

            await pilot.click("#confirm")
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()

            assert mock_uninstall.call_args.kwargs["purge_artifacts"] is False

        finally:
            await ctx.__aexit__(None, None, None)


async def test_maintenance_screen_back_to_menu_returns_to_main_menu():

    with patch(
        "installer.tui.maintenance_screen.update_stack",
        return_value={"success": True, "error": None}
    ):

        app = VulcanApp()

        async with app.run_test() as pilot:

            app.push_screen(MaintenanceScreen.for_update())
            await pilot.pause()

            await pilot.click("#confirm")
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()

            await pilot.click("#back-to-menu")
            await pilot.pause()

            assert isinstance(app.screen, MainMenuScreen)


# --- RestoreScreen ---------------------------------------------------------

async def _launch_restore_screen(has_backups: bool = True):

    with patch(
        "installer.tui.restore_screen.latest_backup",
        return_value=(Path("backups/fake.tar.gz") if has_backups else None)
    ):

        app = VulcanApp()
        ctx = app.run_test()
        pilot = await ctx.__aenter__()

        app.push_screen(RestoreScreen())
        await pilot.pause()

    return app, pilot, ctx


async def test_restore_screen_no_backups_hides_confirm():

    app, pilot, ctx = await _launch_restore_screen(has_backups=False)

    try:

        assert app.screen.query_one("#confirm-actions", Horizontal).display is False
        assert "No backup archives found" in app.screen.query_one("#restore-confirm-text", Static).content

    finally:
        await ctx.__aexit__(None, None, None)


async def test_restore_screen_confirm_runs_restore_and_shows_start_prompt():

    with patch(
        "installer.tui.restore_screen.restore_stack",
        return_value={"success": True, "error": None}
    ):

        app, pilot, ctx = await _launch_restore_screen()

        try:

            await pilot.click("#confirm")
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()

            assert app.screen.query_one("#restore-result", Static).content == "Stack restored."
            assert app.screen.query_one("#confirm-actions", Horizontal).display is False
            assert app.screen.query_one("#start-actions", Horizontal).display is True

        finally:
            await ctx.__aexit__(None, None, None)


async def test_restore_screen_restore_failure_shows_error_and_enables_back():

    with patch(
        "installer.tui.restore_screen.restore_stack",
        return_value={"success": False, "error": "Backup file not found"}
    ):

        app, pilot, ctx = await _launch_restore_screen()

        try:

            await pilot.click("#confirm")
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()

            assert "Backup file not found" in app.screen.query_one("#restore-result", Static).content
            assert app.screen.query_one("#back-to-menu", Button).disabled is False
            assert app.screen.query_one("#start-actions", Horizontal).display is False

        finally:
            await ctx.__aexit__(None, None, None)


async def test_restore_screen_not_now_skips_start():

    with patch(
        "installer.tui.restore_screen.restore_stack",
        return_value={"success": True, "error": None}
    ):

        app, pilot, ctx = await _launch_restore_screen()

        try:

            await pilot.click("#confirm")
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()

            await pilot.click("#not-now")
            await pilot.pause()

            assert app.screen.query_one("#start-actions", Horizontal).display is False
            assert app.screen.query_one("#back-to-menu", Button).disabled is False

        finally:
            await ctx.__aexit__(None, None, None)


async def test_restore_screen_start_now_runs_compose_up():

    mock_proc = MagicMock()
    mock_proc.returncode = 0

    with patch(
        "installer.tui.restore_screen.restore_stack",
        return_value={"success": True, "error": None}
    ), patch(
        "installer.tui.restore_screen.run_docker_command", return_value=mock_proc
    ):

        app, pilot, ctx = await _launch_restore_screen()

        try:

            await pilot.click("#confirm")
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()

            await pilot.click("#start-now")
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()

            assert app.screen.query_one("#restore-result", Static).content == "Stack restored and started."
            assert app.screen.query_one("#back-to-menu", Button).disabled is False

        finally:
            await ctx.__aexit__(None, None, None)


async def test_restore_screen_start_now_start_failure_shows_message():

    mock_proc = MagicMock()
    mock_proc.returncode = 1

    with patch(
        "installer.tui.restore_screen.restore_stack",
        return_value={"success": True, "error": None}
    ), patch(
        "installer.tui.restore_screen.run_docker_command", return_value=mock_proc
    ):

        app, pilot, ctx = await _launch_restore_screen()

        try:

            await pilot.click("#confirm")
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()

            await pilot.click("#start-now")
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()

            result = app.screen.query_one("#restore-result", Static).content
            assert "failed to start" in result

        finally:
            await ctx.__aexit__(None, None, None)
