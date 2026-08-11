from pathlib import Path

from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Input, LoadingIndicator, Static

from installer.detect import describe_media_redundancy, detect_host_ip
from installer.docker_setup import run_docker_command
from installer.generate import (
    WALKTHROUGH_URL,
    GenerationConfig,
    render_setup_order,
    render_stack_summary,
    resolve_ports,
    write_stack,
)
from installer.post_install import pull_stack, remove_orphaned_containers
from installer.preflight import check_ports_available, format_port_conflicts
from installer.tiers import TIERS


class ReviewScreen(Screen):

    DEFAULT_CSS = """
    #result {
        margin: 1 0;
    }

    #remap-fields {
        height: auto;
        margin: 1 0;
    }

    .remap-row {
        height: auto;
    }

    .remap-label {
        width: 34;
        content-align: right middle;
        padding-right: 1;
    }

    .remap-input {
        width: 14;
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
            domain=self.app.domain,
            cloudflare_dns=self.app.cloudflare_dns,
            cloudflare_email=self.app.cloudflare_email,
            auth_username=self.app.auth_username,
            auth_password_hash=self.app.auth_password_hash,
            port_overrides=self.app.port_overrides,
            homepage_private=self.app.homepage_private
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
            f"Homepage: {'enabled' if 'homepage' in self.app.enabled_optional else 'disabled'}\n"
            f"GPU passthrough: {self.app.gpu_vendor or 'disabled'}"
        )

        # Only shown when actually enabled, not unconditionally like the
        # four services above - this screen already sits at a real,
        # measured vertical budget limit (ReviewScreen's own #continue/
        # #back/#customize live at the edge of the 80x24 test viewport,
        # see the layout-bug history elsewhere in this project), and
        # three more permanent "disabled" lines pushed real content
        # (the port-remap fields) below the fold. Matches the existing
        # "Homepage: private" line's own precedent below.
        for key, label in (
            ("metube", "MeTube"), ("downtify", "Downtify"), ("netdata", "Netdata"),
            ("vaultwarden", "Vaultwarden"),
        ):

            if key in self.app.enabled_optional:
                summary += f"\n{label}: enabled"

        if self.app.homepage_private:
            summary += "\nHomepage: private (not publicly routed)"

        if self.app.custom_services is not None:
            summary += f"\nServices: {', '.join(sorted(self.app.custom_services))}"

        if self.app.domain:
            summary += f"\nDomain: {self.app.domain}"

        if self.app.cloudflare_dns:
            summary += f"\nCloudflare DNS (real Let's Encrypt certs): enabled ({self.app.cloudflare_email})"

        if self.app.auth_username:
            summary += f"\nAuthelia admin username: {self.app.auth_username}"

        if self.app.media_redundancy is not None:

            description = describe_media_redundancy(self.app.media_redundancy)

            if description is not None:

                summary += f"\nMedia storage: {description}"

                if self.app.media_redundancy["redundant"] is False:
                    summary += "\n! No drive-level redundancy - a single drive failure would mean data loss."

        yield VerticalScroll(
            Static(summary, id="summary"),
            Horizontal(
                Button("Back", id="back"),
                Button("Generate", id="generate"),
            ),
            Static("", id="result"),
            Vertical(id="remap-fields"),
            Static("", id="remap-error"),
            Horizontal(
                Button("Apply Remap", id="apply-remap"),
                Button("Cancel Remap", id="cancel-remap"),
                id="remap-actions",
            ),
            LoadingIndicator(id="loading"),
            Horizontal(
                Button("Start Stack Now", id="start", disabled=True),
                Button("Pull Images Now", id="pull", disabled=True),
                Button("Finish Without Starting", id="finish", disabled=True),
            ),
            Horizontal(
                Button("Clean Up & Retry", id="cleanup-retry", disabled=True),
                Button("Remap Ports", id="remap-ports", disabled=True),
                id="conflict-actions",
            ),
        )

    def on_mount(self) -> None:

        self.query_one("#loading", LoadingIndicator).display = False
        self.query_one("#start", Button).display = False
        self.query_one("#pull", Button).display = False
        self.query_one("#finish", Button).display = False
        self.query_one("#cleanup-retry", Button).display = False
        self.query_one("#remap-ports", Button).display = False
        self.query_one("#remap-fields", Vertical).display = False
        self.query_one("#remap-error", Static).display = False
        self.query_one("#remap-actions", Horizontal).display = False

    async def on_button_pressed(self, event: Button.Pressed) -> None:

        if event.button.id == "generate":
            self._generate()
        elif event.button.id == "finish":
            self._finish_without_starting()
        elif event.button.id == "start":
            self._start_stack()
        elif event.button.id == "pull":
            self._pull_images()
        elif event.button.id == "cleanup-retry":
            self._cleanup_and_retry()
        elif event.button.id == "remap-ports":
            await self._show_remap_fields()
        elif event.button.id == "apply-remap":
            await self._apply_remap()
        elif event.button.id == "cancel-remap":
            await self._cancel_remap()
        elif event.button.id == "back":
            self.app.pop_screen()

    def _generate(self) -> None:

        self.query_one("#generate", Button).disabled = True
        result_widget = self.query_one("#result", Static)

        self._config = self._build_config()

        try:
            result = write_stack(self._config)
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
                f"  docker compose -f {self._compose_path} --env-file {self._env_path} up -d\n\n"
                f"Once it's up, a suggested setup order for every service you enabled is here: "
                f"{WALKTHROUGH_URL}"
            )
        )

    def _start_stack(self) -> None:

        port_check = check_ports_available(self._compose_path)
        cleanup_button = self.query_one("#cleanup-retry", Button)
        remap_button = self.query_one("#remap-ports", Button)

        if not port_check["available"]:

            lines = [
                "Can't start - port(s) already in use:",
                format_port_conflicts(port_check),
            ]

            remappable = resolve_ports(self._config)

            # Own-orphan ports are handled by Clean Up & Retry, not remapping
            # (see _cleanup_and_retry) - remap only ever applies to the
            # remaining, genuinely-unrelated conflicts.
            self._remappable_conflicts = [
                port for port in port_check["conflicts"]
                if not port_check["own_orphan"].get(port)
                and port_check["port_services"].get(port) in remappable
            ]
            unremappable_conflicts = [
                port for port in port_check["conflicts"]
                if not port_check["own_orphan"].get(port)
                and port_check["port_services"].get(port) not in remappable
            ]
            self._port_check = port_check

            if any(port_check["own_orphan"].values()):

                lines.append(
                    "Some of these are your own orphaned containers from a "
                    "previous stack - \"Clean Up & Retry\" removes just those "
                    "containers, without touching this stack's files, then "
                    "tries starting again."
                )
                cleanup_button.display = True
                cleanup_button.disabled = False

            else:
                cleanup_button.display = False

            if self._remappable_conflicts:

                lines.append(
                    "\"Remap Ports\" lets you type a new host port for each "
                    "one still held by something else, then retries."
                )
                remap_button.display = True
                remap_button.disabled = False

            else:
                remap_button.display = False

            if unremappable_conflicts:

                lines.append(
                    "Port(s) " + ", ".join(str(p) for p in unremappable_conflicts)
                    + " can't be remapped automatically - free them manually and retry."
                )

            self.query_one("#result", Static).update("\n".join(lines))
            return

        cleanup_button.display = False
        remap_button.display = False
        self.query_one("#remap-fields", Vertical).display = False
        self.query_one("#remap-error", Static).display = False
        self.query_one("#remap-actions", Horizontal).display = False
        self.query_one("#start", Button).disabled = True
        self.query_one("#pull", Button).disabled = True
        self.query_one("#finish", Button).disabled = True
        self.query_one("#back", Button).disabled = True
        self.query_one("#loading", LoadingIndicator).display = True

        self._run_start()

    def _cleanup_and_retry(self) -> None:

        result = remove_orphaned_containers(Path(self._compose_path).parent.name)

        if not result["success"]:
            self.query_one("#result", Static).update(result["error"])
            return

        self.query_one("#cleanup-retry", Button).display = False
        self._start_stack()

    async def _show_remap_fields(self) -> None:

        container = self.query_one("#remap-fields", Vertical)
        await container.remove_children()

        for port in self._remappable_conflicts:

            service_key = self._port_check["port_services"][port]

            await container.mount(
                Horizontal(
                    Static(f"New port for {service_key} (currently {port}):", classes="remap-label"),
                    Input(placeholder=str(port), id=f"remap-input-{port}", classes="remap-input"),
                    classes="remap-row",
                )
            )

        # Apply/Cancel live in a fixed row outside the scrollable
        # container (not mounted alongside the port rows above) so
        # they stay reachable regardless of how many ports scroll past
        # #remap-fields's own max-height - a real OutOfBounds failure,
        # reproduced with 3+ simultaneous conflicts, when they were
        # dynamically mounted inside it instead.
        container.display = True
        self.query_one("#remap-error", Static).update("")
        self.query_one("#remap-error", Static).display = True
        self.query_one("#remap-actions", Horizontal).display = True
        self.query_one("#remap-ports", Button).disabled = True

    async def _apply_remap(self) -> None:

        error_widget = self.query_one("#remap-error", Static)
        remappable = resolve_ports(self._config)
        existing_values = set(remappable.values())
        seen_new_ports: set[int] = set()
        new_overrides: dict[str, int] = {}

        for port in self._remappable_conflicts:

            service_key = self._port_check["port_services"][port]
            raw = self.query_one(f"#remap-input-{port}", Input).value.strip()

            if not raw:
                continue

            try:
                new_port = int(raw)
            except ValueError:
                error_widget.update(f"'{raw}' isn't a valid port number for {service_key} - not applied.")
                return

            if new_port in existing_values or new_port in seen_new_ports:
                error_widget.update(
                    f"Port {new_port} is already used by another service in this stack - not applied."
                )
                return

            seen_new_ports.add(new_port)
            new_overrides[service_key] = new_port

        if not new_overrides:
            error_widget.update("Enter at least one new port, or Cancel Remap.")
            return

        self._config.port_overrides.update(new_overrides)

        try:
            result = write_stack(self._config)
        except OSError as exc:
            error_widget.update(f"Failed to write the stack: {exc}")
            return

        self._compose_path = result["compose_path"]
        self._env_path = result["env_path"]

        await self._hide_remap_fields()
        self._start_stack()

    async def _cancel_remap(self) -> None:

        await self._hide_remap_fields()

    async def _hide_remap_fields(self) -> None:

        container = self.query_one("#remap-fields", Vertical)
        await container.remove_children()
        container.display = False
        self.query_one("#remap-error", Static).display = False
        self.query_one("#remap-actions", Horizontal).display = False
        self.query_one("#remap-ports", Button).disabled = False

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

            host_ip = detect_host_ip()
            summary = render_stack_summary(self._config, host_ip)
            setup_order = render_setup_order(self._config, host_ip)

            message = "Stack is up:\n" + summary if summary else "Stack is up."

            if setup_order:
                message += f"\n\n{setup_order}"

            # Printed to the real terminal after the TUI itself tears
            # down (Textual's own App.exit(message=...) mechanism,
            # already used for the plain "Stack is up" case above) -
            # genuinely plain, freely selectable/copyable terminal
            # text, not rendered inside the live TUI where a terminal's
            # own mouse-drag text selection would fight Textual's own
            # mouse handling instead.
            self.app.exit(message=message)

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
