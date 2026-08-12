from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Checkbox, LoadingIndicator, Static

from installer.detect import SystemInfo, detect_system
from installer.generate import STACK_DIR, load_previous_state
from installer.tui.docker_screen import DockerReadyScreen


class WelcomeScreen(Screen):

    DEFAULT_CSS = """
    WelcomeScreen {
        align: center middle;
    }

    #results {
        margin: 1 0;
    }
    """

    def compose(self) -> ComposeResult:

        yield Vertical(
            Static("Detecting your system...", id="title"),
            LoadingIndicator(id="loading"),
            Static("", id="results"),
            Static("", id="previous-note"),
            Checkbox("No internet access on this machine", value=False, id="offline-check"),
            Horizontal(
                # Gains a real Back button here for the first time - this
                # screen used to be the true root, with "nothing before
                # it"; now MainMenuScreen is, so it needs one, following
                # the same self.app.pop_screen() pattern every other
                # screen's Back button already uses.
                Button("Back", id="back"),
                Button("Continue", id="continue", disabled=True),
            ),
        )

    def on_mount(self) -> None:
        self.run_detection()

    @work(thread=True)
    def run_detection(self) -> None:

        info = detect_system()
        previous = load_previous_state(STACK_DIR)

        self.app.call_from_thread(self.detection_complete, info, previous)

    def detection_complete(self, info: SystemInfo, previous: dict | None) -> None:

        self.app.system_info = info
        self.app.previous_state = previous

        # The TUI has no port-remap UI of its own (see ReviewScreen's
        # "Clean Up & Retry" - only the own-orphan case gets one) but a
        # previous port_overrides still needs to survive a regenerate,
        # the same re-run-safe rule every other field here follows.
        if previous and previous.get("port_overrides"):
            self.app.port_overrides = dict(previous["port_overrides"])

        self.query_one("#loading", LoadingIndicator).display = False

        self.query_one("#results", Static).update(
            f"CPU: {info.cpu_cores_logical} logical cores ({info.cpu_model or 'unknown'})\n"
            f"RAM: {info.ram_total_gb}GB total\n"
            f"GPU: {info.gpu_vendor or 'none detected'}\n"
            f"OS: {info.os_pretty_name or info.os_id or 'unknown'} ({info.architecture})"
        )

        if previous is not None:

            self.query_one("#previous-note", Static).update(
                f"Found an existing {previous['tier']} stack, generated "
                f"{previous['generated_at']}. Using it as defaults - pass flags to override."
            )

        self.query_one("#continue", Button).disabled = False

    def on_button_pressed(self, event: Button.Pressed) -> None:

        if event.button.id == "continue":
            self.app.offline = self.query_one("#offline-check", Checkbox).value
            self.app.push_screen(DockerReadyScreen())
        elif event.button.id == "back":
            self.app.pop_screen()
