from typing import Callable

from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Checkbox, LoadingIndicator, Static

from installer.generate import STACK_DIR
from installer.post_install import backup_stack, pull_stack, update_stack, uninstall_stack


class MaintenanceScreen(Screen):
    """
    Update/Pull/Backup/Uninstall share an identical shape - confirm,
    run in a background worker (the same @work(thread=True)/
    call_from_thread pattern DockerReadyScreen/ReviewScreen already
    established), show the result, offer a way back to the Main Menu.
    One parametrized screen rather than four near-duplicate files,
    since unlike the compose template's per-service blocks (which
    genuinely differ), these four actions don't - Restore is the one
    real exception (a genuine second confirm step) and stays its own
    screen (restore_screen.py) instead of being forced in here.
    """

    DEFAULT_CSS = """
    MaintenanceScreen {
        align: center middle;
    }

    #maint-confirm-text, #maint-result {
        margin: 1 0;
    }
    """

    def __init__(
        self,
        title: str,
        confirm_text: str,
        action: Callable[[], dict] | None,
        success_message: Callable[[dict], str],
        show_purge_checkbox: bool = False,
    ) -> None:

        super().__init__()

        self._title = title
        self._confirm_text = confirm_text
        self._action = action
        self._success_message = success_message
        self._show_purge_checkbox = show_purge_checkbox
        self._resolved_action: Callable[[], dict] | None = None

    @classmethod
    def for_update(cls) -> "MaintenanceScreen":

        compose_path = STACK_DIR / "docker-compose.yml"
        env_path = STACK_DIR / ".env"

        return cls(
            title="Update Stack",
            confirm_text=f"This will pull the latest images and recreate containers for {compose_path}.",
            action=lambda: update_stack(str(compose_path), str(env_path)),
            success_message=lambda result: "Stack updated.",
        )

    @classmethod
    def for_pull(cls) -> "MaintenanceScreen":

        compose_path = STACK_DIR / "docker-compose.yml"
        env_path = STACK_DIR / ".env"

        return cls(
            title="Pull Images",
            confirm_text=f"This will pull images for {compose_path} without starting anything.",
            action=lambda: pull_stack(str(compose_path), str(env_path)),
            success_message=lambda result: "Images pulled.",
        )

    @classmethod
    def for_backup(cls) -> "MaintenanceScreen":

        return cls(
            title="Backup Stack",
            confirm_text="This will archive stack/config/ and the compose/env files to backups/.",
            action=lambda: backup_stack(),
            success_message=lambda result: "\n".join(
                [f"Backup written to {result['backup_path']}"]
                + [f"! {warning}" for warning in result.get("warnings", [])]
            ),
        )

    @classmethod
    def for_uninstall(cls) -> "MaintenanceScreen":

        compose_path = STACK_DIR / "docker-compose.yml"
        env_path = STACK_DIR / ".env"

        return cls(
            title="Uninstall Stack",
            confirm_text=(
                f"This will stop the running stack (if any) and permanently delete {STACK_DIR}/ "
                "(containers, network, and all app config/data). Your media library is always "
                "left untouched."
            ),
            # Built at confirm-time instead (see _confirm()) - whether
            # to also purge backups/exports isn't known until the
            # checkbox below is read, which can't happen until the
            # screen is actually showing.
            action=None,
            success_message=lambda result: "Stack removed. Run `./install` again for a fresh setup.",
            show_purge_checkbox=True,
        )

    def compose(self) -> ComposeResult:

        children = [
            Static(self._title, id="title"),
            Static(self._confirm_text, id="maint-confirm-text"),
        ]

        if self._show_purge_checkbox:
            children.append(
                Checkbox(
                    "Also delete backups/ and exports/", value=False, id="purge-artifacts",
                    tooltip="Leave unchecked to keep your backup/export archives after uninstalling."
                )
            )

        children += [
            Static("", id="maint-result"),
            LoadingIndicator(id="loading"),
            Horizontal(
                Button("Cancel", id="cancel"),
                Button("Confirm", id="confirm"),
            ),
            Button("Back to Main Menu", id="back-to-menu", disabled=True),
        ]

        yield Vertical(*children)

    def on_mount(self) -> None:

        self.query_one("#loading", LoadingIndicator).display = False

    def on_button_pressed(self, event: Button.Pressed) -> None:

        if event.button.id == "cancel":
            self.app.pop_screen()
        elif event.button.id == "confirm":
            self._confirm()
        elif event.button.id == "back-to-menu":
            self.app.pop_screen()

    def _confirm(self) -> None:

        if self._show_purge_checkbox:

            purge_artifacts = self.query_one("#purge-artifacts", Checkbox).value
            compose_path = STACK_DIR / "docker-compose.yml"
            env_path = STACK_DIR / ".env"

            self._resolved_action = lambda: uninstall_stack(
                str(compose_path), str(env_path), purge_artifacts=purge_artifacts
            )

        else:
            self._resolved_action = self._action

        self.query_one("#cancel", Button).disabled = True
        self.query_one("#confirm", Button).disabled = True
        self.query_one("#loading", LoadingIndicator).display = True

        self._run()

    @work(thread=True)
    def _run(self) -> None:

        result = self._resolved_action()
        self.app.call_from_thread(self._complete, result)

    def _complete(self, result: dict) -> None:

        self.query_one("#loading", LoadingIndicator).display = False
        self.query_one("#back-to-menu", Button).disabled = False

        result_widget = self.query_one("#maint-result", Static)

        if result["success"]:
            result_widget.update(self._success_message(result))
        else:
            result_widget.update(result["error"])
