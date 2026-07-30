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

    def on_mount(self) -> None:
        self.push_screen(WelcomeScreen())
