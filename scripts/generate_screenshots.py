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

from textual.widgets import Checkbox, Input, SelectionList

from installer.tui.app import VulcanApp

OUT_DIR = Path("docs/screenshots")
OUT_DIR.mkdir(parents=True, exist_ok=True)

SCRATCH_MEDIA_PATH = Path("/tmp/vulcan-screenshot-media")


async def main() -> None:

    app = VulcanApp()

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
