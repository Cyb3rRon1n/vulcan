from textual import events
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Static

from installer.generate import STACK_DIR
from installer.post_install import latest_backup, stack_containers_exist
from installer.tui.maintenance_screen import MaintenanceScreen
from installer.tui.restore_screen import RestoreScreen
from installer.tui.welcome_screen import WelcomeScreen


class MainMenuScreen(Screen):
    """
    The persistent hub - a direct owner request to have the TUI behave
    like DockSTARTer's own main menu rather than a strict one-way
    wizard. Every action pushes its own screen; a "Back to Main Menu"
    button on each just pops back here, reusing the exact
    self.app.pop_screen() convention every screen in this codebase
    already follows - no new navigation model, just a new root screen
    for existing ones to return to.
    """

    DEFAULT_CSS = """
    MainMenuScreen Button {
        width: 60;
        margin-bottom: 1;
    }
    """

    def compose(self) -> ComposeResult:

        # VerticalScroll, not a plain Vertical with align: center middle -
        # same fix ReviewScreen/TierConfigScreen/ServiceSelectionScreen
        # already established for the identical problem (content genuinely
        # exceeding the 80x24 test viewport - 8 buttons plus their own
        # margins pushes Exit out of the fixed viewport, confirmed by a
        # real Pilot.click() OutOfBounds failure, not assumed). align:
        # center middle is dropped for the same reason - it fights a
        # scrollable root. Buttons are direct children of the
        # VerticalScroll (no extra nested Vertical wrapper) - an inner
        # Vertical here was found, live, to mismeasure its own auto
        # height against its children's real total span, capping the
        # scrollable region short and leaving Exit genuinely
        # unreachable; matches ServiceSelectionScreen/TierConfigScreen's
        # own flat-children structure under their VerticalScroll roots.
        yield VerticalScroll(
            Static("Vulcan", id="title"),
            Static("", id="menu-help"),
            Button(
                "Guided Setup", id="guided-setup",
                tooltip="Detect your hardware and generate (or reconfigure) a media stack."
            ),
            Button(
                "Update Stack", id="update-stack",
                tooltip="Pull the latest images and recreate containers for the existing stack."
            ),
            Button(
                "Pull Images", id="pull-images",
                tooltip="Pull images without starting anything - prep for an offline start later."
            ),
            Button(
                "Backup Stack", id="backup-stack",
                tooltip="Archive config/ and the compose/env files to backups/."
            ),
            Button(
                "Restore Stack", id="restore-stack",
                tooltip="Restore config/, docker-compose.yml, and .env from the most recent backup."
            ),
            Button(
                "Uninstall Stack", id="uninstall-stack",
                tooltip="Stop the stack and delete stack/ entirely - back to a clean slate."
            ),
            Button(
                "Update Vulcan", id="update-self",
                tooltip="Fast-forward this Vulcan checkout to the latest origin/main."
            ),
            Button("Exit", id="exit", tooltip="Quit Vulcan."),
        )

    def on_mount(self) -> None:
        self._refresh_gating()

    def on_screen_resume(self, event: events.ScreenResume) -> None:
        """
        Popping back here from a sub-screen reveals this already-
        mounted instance rather than remounting it (confirmed via
        Textual's own real ScreenResume/pop_screen source, same
        "revealed, not remounted" behavior CLAUDE.md already documents
        for Back navigation elsewhere) - so button gating computed once
        in compose()/on_mount() would go stale the moment, say, a first
        backup is taken and "Restore Stack" should become enabled.
        Re-checked every time this screen is resumed, not just once.
        """
        self._refresh_gating()

    def _refresh_gating(self) -> None:

        compose_path = STACK_DIR / "docker-compose.yml"
        stack_exists = compose_path.exists() or stack_containers_exist(STACK_DIR.name)
        has_backups = latest_backup() is not None

        for button_id in ("update-stack", "pull-images", "backup-stack", "uninstall-stack"):
            self.query_one(f"#{button_id}", Button).disabled = not stack_exists

        self.query_one("#restore-stack", Button).disabled = not has_backups

    def on_descendant_focus(self, event: events.DescendantFocus) -> None:
        """
        Keyboard-accessible equivalent of the mouse-only tooltip - same
        DescendantFocus pattern TierConfigScreen/ServiceSelectionScreen
        already established, reused rather than inventing a second
        mechanism.
        """

        self.query_one("#menu-help", Static).update(event.widget.tooltip or "")

    def on_button_pressed(self, event: Button.Pressed) -> None:

        if event.button.id == "guided-setup":
            self.app.push_screen(WelcomeScreen())
        elif event.button.id == "update-stack":
            self.app.push_screen(MaintenanceScreen.for_update())
        elif event.button.id == "pull-images":
            self.app.push_screen(MaintenanceScreen.for_pull())
        elif event.button.id == "backup-stack":
            self.app.push_screen(MaintenanceScreen.for_backup())
        elif event.button.id == "restore-stack":
            self.app.push_screen(RestoreScreen())
        elif event.button.id == "uninstall-stack":
            self.app.push_screen(MaintenanceScreen.for_uninstall())
        elif event.button.id == "update-self":
            self.app.push_screen(MaintenanceScreen.for_update_self())
        elif event.button.id == "exit":
            self.app.exit()
