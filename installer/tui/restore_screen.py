from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, LoadingIndicator, Static

from installer.docker_setup import run_docker_command
from installer.generate import STACK_DIR
from installer.post_install import latest_backup, restore_stack


class RestoreScreen(Screen):
    """
    Kept separate from MaintenanceScreen - unlike Update/Pull/Backup/
    Uninstall, cli.py's own restore() command has a real second
    decision baked in (typer.confirm("Start the restored stack now?"))
    that the other four don't, so this genuinely needs its own two-step
    flow rather than forcing MaintenanceScreen's single confirm/run
    shape to fit it.

    Scoped to latest_backup() only, matching restore's own default-to-
    latest CLI convenience - picking a specific older archive would
    need a real file-picker widget, a deliberate v1 scope boundary, not
    a silently dropped case.
    """

    DEFAULT_CSS = """
    RestoreScreen {
        align: center middle;
    }

    #restore-confirm-text, #restore-result {
        margin: 1 0;
    }
    """

    def compose(self) -> ComposeResult:

        backup_path = latest_backup()

        yield Vertical(
            Static("Restore Stack", id="title"),
            Static(self._confirm_text(backup_path), id="restore-confirm-text"),
            Static("", id="restore-result"),
            LoadingIndicator(id="loading"),
            Horizontal(
                Button("Cancel", id="cancel"),
                Button("Confirm", id="confirm"),
                id="confirm-actions",
            ),
            Horizontal(
                Button("Start It Now", id="start-now"),
                Button("Not Now", id="not-now"),
                id="start-actions",
            ),
            Button("Back to Main Menu", id="back-to-menu", disabled=True),
        )

    def _confirm_text(self, backup_path) -> str:

        if backup_path is None:
            return "No backup archives found in backups/."

        stack_exists = (STACK_DIR / "docker-compose.yml").exists()

        return (
            f"This will restore config/, docker-compose.yml, and .env in {STACK_DIR} from "
            f"{backup_path}, overwriting what's there now"
            + (", and stop the currently running stack first." if stack_exists else ".")
        )

    def on_mount(self) -> None:

        self.query_one("#loading", LoadingIndicator).display = False
        self.query_one("#start-actions", Horizontal).display = False

        if latest_backup() is None:
            self.query_one("#confirm-actions", Horizontal).display = False

    def on_button_pressed(self, event: Button.Pressed) -> None:

        if event.button.id == "cancel":
            self.app.pop_screen()
        elif event.button.id == "confirm":
            self._confirm()
        elif event.button.id == "start-now":
            self._start_now()
        elif event.button.id == "not-now":
            self._skip_start()
        elif event.button.id == "back-to-menu":
            self.app.pop_screen()

    def _confirm(self) -> None:

        self._backup_path = latest_backup()
        self._compose_path = str(STACK_DIR / "docker-compose.yml")
        self._env_path = str(STACK_DIR / ".env")

        self.query_one("#cancel", Button).disabled = True
        self.query_one("#confirm", Button).disabled = True
        self.query_one("#loading", LoadingIndicator).display = True

        self._run_restore()

    @work(thread=True)
    def _run_restore(self) -> None:

        result = restore_stack(self._backup_path, self._compose_path, self._env_path)
        self.app.call_from_thread(self._restore_complete, result)

    def _restore_complete(self, result: dict) -> None:

        self.query_one("#loading", LoadingIndicator).display = False
        result_widget = self.query_one("#restore-result", Static)

        if not result["success"]:
            result_widget.update(result["error"])
            self.query_one("#back-to-menu", Button).disabled = False
            return

        result_widget.update("Stack restored.")
        self.query_one("#confirm-actions", Horizontal).display = False
        self.query_one("#start-actions", Horizontal).display = True

    def _skip_start(self) -> None:

        self.query_one("#start-actions", Horizontal).display = False
        self.query_one("#back-to-menu", Button).disabled = False

    def _start_now(self) -> None:

        self.query_one("#start-actions", Horizontal).display = False
        self.query_one("#loading", LoadingIndicator).display = True

        self._run_start()

    @work(thread=True)
    def _run_start(self) -> None:

        proc = run_docker_command(
            ["docker", "compose", "-f", self._compose_path, "--env-file", self._env_path, "up", "-d"],
            use_group_workaround=self.app.group_just_added
        )

        self.app.call_from_thread(self._start_complete, proc.returncode)

    def _start_complete(self, returncode: int) -> None:

        self.query_one("#loading", LoadingIndicator).display = False
        self.query_one("#back-to-menu", Button).disabled = False
        result_widget = self.query_one("#restore-result", Static)

        if returncode == 0:
            result_widget.update("Stack restored and started.")
        else:
            result_widget.update(
                "Stack restored, but failed to start - check `docker compose logs`."
            )
