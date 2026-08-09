"""
Drives the real VulcanApp through each TUI screen and exports real SVG
screenshots via Textual's own App.save_screenshot() - the same
App.run_test()/Pilot harness the test suite already uses, not a mock.
Not part of the test suite; run manually (`python scripts/generate_screenshots.py`
from the repo root, with the venv active) whenever the TUI changes enough
to make docs/screenshots/ stale, and commit the regenerated SVGs.
"""

import asyncio
import shutil
from pathlib import Path
from unittest.mock import patch

from textual.widgets import Button, Checkbox, Input, SelectionList

from installer.detect import SystemInfo
from installer.tui.app import VulcanApp

OUT_DIR = Path("docs/screenshots")
OUT_DIR.mkdir(parents=True, exist_ok=True)

SCRATCH_MEDIA_PATH = Path("/tmp/vulcan-screenshot-media")

# Same reasoning as the detect_disk() patch below: whatever machine
# this actually runs on isn't necessarily representative of a target
# host (it may have no live Docker daemon at all, e.g. a CI/sandbox
# environment) - Docker readiness specifically gates the Continue
# button on DockerReadyScreen, so an unready real host would silently
# stall the whole script rather than produce a wrong screenshot.
ILLUSTRATIVE_SYSTEM_INFO = SystemInfo(
    cpu_cores_physical=6,
    cpu_cores_logical=12,
    cpu_model="Illustrative CPU",
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
    os_pretty_name="Fedora Linux"
)


async def main() -> None:

    app = VulcanApp()

    with patch(
        "installer.tui.welcome_screen.detect_system", return_value=ILLUSTRATIVE_SYSTEM_INFO
    ):

        async with app.run_test(size=(100, 36)) as pilot:

            await app.workers.wait_for_complete()
            await pilot.pause()
            app.save_screenshot("01-welcome.svg", path=str(OUT_DIR))

            await pilot.click("#continue")
            await pilot.pause()
            app.save_screenshot("02-docker-ready.svg", path=str(OUT_DIR))

            await pilot.click("#continue")
            await pilot.pause()

            media_input = app.screen.query_one("#media-path-input", Input)
            media_input.value = "/mnt/media"
            app.save_screenshot("03-media-path.svg", path=str(OUT_DIR))

            # Whatever machine this runs on, its real free disk space isn't
            # necessarily representative of a real target host's (real disk
            # detection is exercised for real elsewhere - see CLAUDE.md's
            # verification history), so the real detect_disk() call
            # MediaPathScreen's own Continue handler makes is patched to a
            # realistic value here - a real writable path is still needed
            # for the genuine mkdir() that same handler does.
            media_input.value = str(SCRATCH_MEDIA_PATH)

            with patch(
                "installer.tui.media_path_screen.detect_disk",
                return_value={"disk_free_gb": 900.0, "disk_path_checked": str(SCRATCH_MEDIA_PATH)}
            ):
                await pilot.click("#continue")
                await pilot.pause()

            # Same reasoning as the media-path Input swap above: the real
            # writable scratch path was needed for the real mkdir() to
            # succeed, but shouldn't show up in the illustrative screenshots
            # that follow.
            app.media_path = "/mnt/media"

            await pilot.click("#heavy")
            await pilot.pause()
            app.screen.query_one("#sabnzbd-check", Checkbox).value = True
            app.screen.query_one("#recyclarr-check", Checkbox).value = True
            app.save_screenshot("04-tier-config.svg", path=str(OUT_DIR))

            # TierConfigScreen's root is a real VerticalScroll (see
            # CLAUDE.md) - Continue/Back/Customize can sit below the
            # fold depending on which checkboxes are visible, so scroll
            # the target into view first, the same as a real user's
            # mouse wheel would need to.
            app.screen.query_one("#customize", Button).scroll_visible(animate=False)
            await pilot.pause()
            await pilot.click("#customize")
            await pilot.pause()

            # homepage/uptime-kuma are already pre-checked here (non-optional
            # heavy-tier defaults) - only traefik (optional) needs toggling on.
            service_list = app.screen.query_one("#service-list", SelectionList)
            service_list.toggle("traefik")
            await pilot.pause()
            app.screen.query_one("#domain-input", Input).value = "media.example.com"
            app.save_screenshot("05-service-selection.svg", path=str(OUT_DIR))

            await pilot.click("#continue")
            await pilot.pause()
            app.save_screenshot("06-review.svg", path=str(OUT_DIR))

    shutil.rmtree(SCRATCH_MEDIA_PATH, ignore_errors=True)
    print(f"Wrote screenshots to {OUT_DIR}/")


asyncio.run(main())
