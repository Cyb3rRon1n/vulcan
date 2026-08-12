from textual.app import App
from textual.theme import Theme

from installer.detect import SystemInfo
from installer.tui.welcome_screen import WelcomeScreen

# A DockSTARTer/whiptail-style palette, not Textual's own default dark
# theme - a direct owner request to have the guided TUI evoke the
# classic ncurses whiptail/dialog look (cyan panels, black background,
# red selection highlight) rather than a modern flat dark theme.
# Confirmed against Textual 8.2.8's real installed widget CSS before
# picking variable names, not assumed from generic docs: Button/
# Checkbox/RadioButton/Input/SelectionList all draw their at-rest panel
# background from $surface and their hover/focus/selected highlight
# from $primary - no widget in this codebase hardcodes a color of its
# own (confirmed via grep), so this reskins every screen at once with
# zero changes to layout or widget code.
WHIPTAIL_THEME = Theme(
    name="whiptail",
    primary="#CC5555",       # red - hover/focus/selected highlight
    secondary="#3D8FA6",     # darker cyan - secondary accents
    accent="#CC5555",
    warning="#D9A441",
    error="#CC4B4B",
    success="#4E9A51",
    foreground="#E8E8E8",    # light text on the black screen background
    background="#0A1A1D",    # near-black, softens the gap against bright cyan panels
    surface="#4FBEDB",       # cyan - the panel/box background whiptail is known for
    panel="#3D8FA6",
    dark=True,
)


class VulcanApp(App):
    """
    Session state lives here, not threaded through screen constructors -
    each screen reads/writes these directly via self.app.*, the same
    role GenerationConfig plays by the end of the CLI's run_install().
    """

    TITLE = "Vulcan"

    # Checkbox/RadioSet/RadioButton are auto-width by Textual's own
    # default CSS - they hug their label text rather than filling their
    # row, which was invisible under the original theme (background and
    # widget-surface were both similar dark grays) but reads as a
    # harsh gap under whiptail's high-contrast cyan-on-black. Width/
    # background only - no height or position rule touched, so this
    # doesn't risk the viewport-row-count layout bugs documented
    # throughout this project's history.
    CSS = """
    Checkbox, RadioSet {
        width: 100%;
        background: $surface;
    }
    """

    def __init__(self) -> None:

        super().__init__()

        self.register_theme(WHIPTAIL_THEME)
        self.theme = "whiptail"

        self.system_info: SystemInfo | None = None
        self.previous_state: dict | None = None
        self.group_just_added: bool = False
        self.offline: bool = False

        self.media_path: str | None = None
        self.media_redundancy: dict | None = None
        self.tier_name: str | None = None
        self.enabled_optional: set[str] = set()
        self.gpu_vendor: str | None = None
        self.puid: int | None = None
        self.pgid: int | None = None
        self.timezone: str | None = None
        self.custom_services: set[str] | None = None
        self.domain: str | None = None
        self.cloudflare_dns: bool = False
        self.cloudflare_email: str | None = None
        self.auth_username: str | None = None
        self.auth_password_hash: str | None = None
        self.homepage_private: bool = False
        self.dashy_private: bool = False
        self.port_overrides: dict[str, int] = {}

    def on_mount(self) -> None:
        self.push_screen(WelcomeScreen())
