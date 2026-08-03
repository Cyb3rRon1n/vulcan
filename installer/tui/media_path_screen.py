from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Input, Static

from installer.detect import detect_disk, detect_media_redundancy
from installer.tui.tier_config_screen import TierConfigScreen


class MediaPathScreen(Screen):

    DEFAULT_CSS = """
    MediaPathScreen {
        align: center middle;
    }

    #media-path-error {
        margin: 1 0;
    }
    """

    def compose(self) -> ComposeResult:

        default_path = (
            self.app.previous_state["media_path"] if self.app.previous_state
            else str(Path.home() / "media")
        )

        yield Vertical(
            Static("Where should your media library live?", id="title"),
            Input(value=default_path, id="media-path-input"),
            Static("", id="media-path-error"),
            Horizontal(
                Button("Back", id="back"),
                Button("Continue", id="continue"),
            ),
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:

        if event.button.id == "back":
            self.app.pop_screen()
            return

        if event.button.id != "continue":
            return

        raw_path = self.query_one("#media-path-input", Input).value
        media_path = str(Path(raw_path).expanduser().resolve())
        error = self.query_one("#media-path-error", Static)

        try:
            Path(media_path).mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            error.update(f"Can't create media path '{media_path}': {exc}")
            return

        disk_info = detect_disk(media_path)
        self.app.system_info.disk_free_gb = disk_info["disk_free_gb"]
        self.app.system_info.disk_path_checked = disk_info["disk_path_checked"]
        self.app.media_path = media_path
        self.app.media_redundancy = detect_media_redundancy(media_path)

        self.app.push_screen(TierConfigScreen())
