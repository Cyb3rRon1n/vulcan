from textual.app import App

from installer.detect import SystemInfo
from installer.tui.welcome_screen import WelcomeScreen


class VulcanApp(App):
    """
    Session state lives here, not threaded through screen constructors -
    each screen reads/writes these directly via self.app.*, the same
    role GenerationConfig plays by the end of the CLI's run_install().
    """

    TITLE = "Vulcan"

    def __init__(self) -> None:

        super().__init__()

        self.system_info: SystemInfo | None = None
        self.previous_state: dict | None = None
        self.group_just_added: bool = False

        self.media_path: str | None = None
        self.tier_name: str | None = None
        self.enabled_optional: set[str] = set()
        self.gpu_vendor: str | None = None
        self.puid: int | None = None
        self.pgid: int | None = None
        self.timezone: str | None = None
        self.custom_services: set[str] | None = None
        self.domain: str | None = None

    def on_mount(self) -> None:
        self.push_screen(WelcomeScreen())
