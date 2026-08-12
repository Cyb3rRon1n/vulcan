from smithy import HubMenuScreen, MenuItem
from textual.widgets import Button

from installer.generate import STACK_DIR
from installer.post_install import latest_backup, stack_containers_exist
from installer.tui.maintenance_screen import MaintenanceScreen
from installer.tui.restore_screen import RestoreScreen
from installer.tui.welcome_screen import WelcomeScreen


class MainMenuScreen(HubMenuScreen):
    """
    The persistent hub - a direct owner request to have the TUI behave
    like DockSTARTer's own main menu rather than a strict one-way
    wizard. Built on smithy's HubMenuScreen (extracted from this exact
    class after it was first proven here) - this subclass only owns
    Vulcan-specific menu content and gating, not layout/event-wiring.
    """

    MENU_TITLE = "Vulcan"

    def menu_items(self) -> list[MenuItem]:

        return [
            MenuItem(
                "guided-setup", "Guided Setup",
                tooltip="Detect your hardware and generate (or reconfigure) a media stack.",
                on_select=lambda screen: screen.app.push_screen(WelcomeScreen())
            ),
            MenuItem(
                "update-stack", "Update Stack",
                tooltip="Pull the latest images and recreate containers for the existing stack.",
                on_select=lambda screen: screen.app.push_screen(MaintenanceScreen.for_update())
            ),
            MenuItem(
                "pull-images", "Pull Images",
                tooltip="Pull images without starting anything - prep for an offline start later.",
                on_select=lambda screen: screen.app.push_screen(MaintenanceScreen.for_pull())
            ),
            MenuItem(
                "backup-stack", "Backup Stack",
                tooltip="Archive config/ and the compose/env files to backups/.",
                on_select=lambda screen: screen.app.push_screen(MaintenanceScreen.for_backup())
            ),
            MenuItem(
                "restore-stack", "Restore Stack",
                tooltip="Restore config/, docker-compose.yml, and .env from the most recent backup.",
                on_select=lambda screen: screen.app.push_screen(RestoreScreen())
            ),
            MenuItem(
                "uninstall-stack", "Uninstall Stack",
                tooltip="Stop the stack and delete stack/ entirely - back to a clean slate.",
                on_select=lambda screen: screen.app.push_screen(MaintenanceScreen.for_uninstall())
            ),
            MenuItem(
                "update-self", "Update Vulcan",
                tooltip="Fast-forward this Vulcan checkout to the latest origin/main.",
                on_select=lambda screen: screen.app.push_screen(MaintenanceScreen.for_update_self())
            ),
            MenuItem("exit", "Exit", tooltip="Quit Vulcan.", on_select=lambda screen: screen.app.exit()),
        ]

    def refresh_gating(self) -> None:

        compose_path = STACK_DIR / "docker-compose.yml"
        stack_exists = compose_path.exists() or stack_containers_exist(STACK_DIR.name)
        has_backups = latest_backup() is not None

        for button_id in ("update-stack", "pull-images", "backup-stack", "uninstall-stack"):
            self.query_one(f"#{button_id}", Button).disabled = not stack_exists

        self.query_one("#restore-stack", Button).disabled = not has_backups
