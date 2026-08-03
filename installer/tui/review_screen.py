from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, LoadingIndicator, Static

from installer.docker_setup import run_docker_command
from installer.generate import GenerationConfig, write_stack
from installer.post_install import pull_stack
from installer.tiers import TIERS


class ReviewScreen(Screen):

    DEFAULT_CSS = """
    ReviewScreen {
        align: center middle;
    }

    #result {
        margin: 1 0;
    }
    """

    def _build_config(self) -> GenerationConfig:

        return GenerationConfig(
            tier=TIERS[self.app.tier_name],
            media_path=self.app.media_path,
            puid=self.app.puid,
            pgid=self.app.pgid,
            timezone=self.app.timezone,
            enabled_optional=self.app.enabled_optional,
            gpu_vendor=self.app.gpu_vendor,
            custom_services=self.app.custom_services,
            domain=self.app.domain
        )

    def compose(self) -> ComposeResult:

        tier = TIERS[self.app.tier_name]

        summary = (
            f"Tier: {tier.display_name}\n"
            f"Media path: {self.app.media_path}\n"
            f"PUID/PGID: {self.app.puid}/{self.app.pgid}\n"
            f"Timezone: {self.app.timezone}\n"
            f"Gluetun VPN: {'enabled' if 'gluetun' in self.app.enabled_optional else 'disabled'}\n"
            f"SABnzbd: {'enabled' if 'sabnzbd' in self.app.enabled_optional else 'disabled'}\n"
            f"Recyclarr: {'enabled' if 'recyclarr' in self.app.enabled_optional else 'disabled'}\n"
            f"GPU passthrough: {self.app.gpu_vendor or 'disabled'}"
        )

        if self.app.custom_services is not None:
            summary += f"\nServices: {', '.join(sorted(self.app.custom_services))}"

        if self.app.domain:
            summary += f"\nDomain: {self.app.domain}"

        yield Vertical(
            Static(summary, id="summary"),
            Horizontal(
                Button("Back", id="back"),
                Button("Generate", id="generate"),
            ),
            Static("", id="result"),
            LoadingIndicator(id="loading"),
            Button("Start Stack Now", id="start", disabled=True),
            Button("Pull Images Now", id="pull", disabled=True),
            Button("Finish Without Starting", id="finish", disabled=True),
        )

    def on_mount(self) -> None:

        self.query_one("#loading", LoadingIndicator).display = False
        self.query_one("#start", Button).display = False
        self.query_one("#pull", Button).display = False
        self.query_one("#finish", Button).display = False

    def on_button_pressed(self, event: Button.Pressed) -> None:

        if event.button.id == "generate":
            self._generate()
        elif event.button.id == "finish":
            self._finish_without_starting()
        elif event.button.id == "start":
            self._start_stack()
        elif event.button.id == "pull":
            self._pull_images()
        elif event.button.id == "back":
            self.app.pop_screen()

    def _generate(self) -> None:

        self.query_one("#generate", Button).disabled = True
        result_widget = self.query_one("#result", Static)

        try:
            result = write_stack(self._build_config())
        except OSError as exc:
            result_widget.update(f"Failed to write the stack: {exc}")
            return

        self._compose_path = result["compose_path"]
        self._env_path = result["env_path"]

        lines = [f"Stack written to {result['compose_path']}"]
        lines.extend(f"! {warning}" for warning in result["warnings"])
        result_widget.update("\n".join(lines))

        for button_id in ("start", "pull", "finish"):

            button = self.query_one(f"#{button_id}", Button)
            button.display = True
            button.disabled = False

    def _finish_without_starting(self) -> None:

        self.app.exit(
            message=(
                "Run this when you're ready:\n"
                f"  docker compose -f {self._compose_path} --env-file {self._env_path} up -d"
            )
        )

    def _start_stack(self) -> None:

        self.query_one("#start", Button).disabled = True
        self.query_one("#pull", Button).disabled = True
        self.query_one("#finish", Button).disabled = True
        self.query_one("#back", Button).disabled = True
        self.query_one("#loading", LoadingIndicator).display = True

        self._run_start()

    def _pull_images(self) -> None:

        self.query_one("#start", Button).disabled = True
        self.query_one("#pull", Button).disabled = True
        self.query_one("#finish", Button).disabled = True
        self.query_one("#back", Button).disabled = True
        self.query_one("#loading", LoadingIndicator).display = True

        self._run_pull()

    @work(thread=True)
    def _run_start(self) -> None:

        proc = run_docker_command(
            [
                "docker", "compose",
                "-f", self._compose_path,
                "--env-file", self._env_path,
                "up", "-d"
            ],
            use_group_workaround=self.app.group_just_added
        )

        self.app.call_from_thread(self._start_complete, proc.returncode)

    def _start_complete(self, returncode: int) -> None:

        if returncode == 0:
            self.app.exit(message="Stack is up.")
        else:
            self.app.exit(message="Failed to start the stack - check `docker compose logs`.")

    @work(thread=True)
    def _run_pull(self) -> None:

        result = pull_stack(self._compose_path, self._env_path)

        self.app.call_from_thread(self._pull_complete, result)

    def _pull_complete(self, result: dict) -> None:

        if result["success"]:
            self.app.exit(
                message=(
                    "Images pulled. Run this when you're ready:\n"
                    f"  docker compose -f {self._compose_path} --env-file {self._env_path} up -d"
                )
            )
        else:
            self.app.exit(message=result["error"])
