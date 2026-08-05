from textual import events, work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Checkbox, Input, LoadingIndicator, SelectionList, Static
from textual.widgets.selection_list import Selection

from installer.auth import hash_authelia_password
from installer.generate import STACK_DIR
from installer.tiers import ALL_SERVICES, TIERS
from installer.tui.review_screen import ReviewScreen


class ServiceSelectionScreen(Screen):

    DEFAULT_CSS = """
    ServiceSelectionScreen {
        align: center middle;
    }

    #service-list {
        height: 6;
    }

    #auth-result {
        margin: 1 0;
    }
    """

    def compose(self) -> ComposeResult:

        previous = self.app.previous_state
        previous_custom = previous.get("custom_services") if previous else None
        chosen_tier = TIERS[self.app.tier_name]

        default_set = (
            set(previous_custom) if previous_custom is not None
            else {service.key for service in chosen_tier.services if not service.optional}
        )

        selections = [
            Selection(service.display_name, service.key, service.key in default_set)
            for service in ALL_SERVICES
        ]

        gpu_vendor = self.app.system_info.gpu_vendor
        gpu_label = f"Enable GPU passthrough ({gpu_vendor})" if gpu_vendor else "Enable GPU passthrough"
        gpu_default = bool(previous.get("gpu_vendor")) if previous else True

        default_domain = previous.get("domain") if previous else None
        default_cloudflare_dns = bool(previous.get("cloudflare_dns")) if previous else False
        default_cloudflare_email = previous.get("cloudflare_email") if previous else None

        yield Vertical(
            Static("Select services to include", id="title"),
            SelectionList(*selections, id="service-list"),
            Checkbox(
                gpu_label, value=gpu_default, id="gpu-check",
                tooltip="Passes the detected GPU through to Jellyfin for hardware transcoding."
            ),
            Input(
                value=default_domain or "",
                placeholder="Base domain, e.g. media.example.com",
                id="domain-input",
                tooltip=(
                    "You'll need to own this domain and point its subdomains at this host "
                    "yourself - Vulcan doesn't create DNS records for you."
                )
            ),
            Checkbox(
                "Domain's DNS is on Cloudflare - use real Let's Encrypt certificates",
                value=default_cloudflare_dns, id="cloudflare-dns-check",
                tooltip=(
                    "Instead of Traefik's self-signed default certificate. You'll need a "
                    "scoped Cloudflare API token (Zone:DNS:Edit) in stack/.env afterward."
                )
            ),
            Input(
                value=default_cloudflare_email or "",
                placeholder="Contact email for Let's Encrypt",
                id="cloudflare-email-input",
                tooltip="Let's Encrypt uses this for certificate expiry notices."
            ),
            Input(
                value="admin",
                placeholder="Authelia admin username",
                id="auth-username-input",
                tooltip="Creates the login you'll use for every Traefik-routed service."
            ),
            Input(
                placeholder="Authelia admin password",
                password=True,
                id="auth-password-input",
                tooltip="Remember this - it won't be shown again."
            ),
            Static("", id="auth-result"),
            LoadingIndicator(id="auth-loading"),
            Horizontal(
                Button("Back", id="back"),
                Button("Continue", id="continue"),
            ),
        )

    def on_mount(self) -> None:
        self.query_one("#auth-loading", LoadingIndicator).display = False
        self.query_one("#auth-result", Static).display = False
        self._update_gpu_visibility()
        self._update_domain_visibility()
        self._update_auth_visibility()

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:

        if event.checkbox.id == "cloudflare-dns-check":
            self._update_domain_visibility()

    def on_descendant_focus(self, event: events.DescendantFocus) -> None:
        """
        Keyboard-accessible equivalent of the mouse-only tooltip - see
        TierConfigScreen's identical handler for the DescendantFocus
        reasoning. #auth-result is display-toggled (added last slice to
        save a row), so this toggles it too rather than always showing
        an empty line - can overwrite an unread validation/hash-failure
        error on the next Tab, same accepted tradeoff.
        """

        tooltip = event.widget.tooltip
        result_widget = self.query_one("#auth-result", Static)

        result_widget.update(tooltip or "")
        result_widget.display = bool(tooltip)

    def on_selection_list_selected_changed(self, event: SelectionList.SelectedChanged) -> None:
        self._update_gpu_visibility()
        self._update_domain_visibility()
        self._update_auth_visibility()

    def _update_gpu_visibility(self) -> None:

        selected = set(self.query_one("#service-list", SelectionList).selected)
        gpu_vendor = self.app.system_info.gpu_vendor

        self.query_one("#gpu-check", Checkbox).display = "jellyfin" in selected and bool(gpu_vendor)

    def _update_domain_visibility(self) -> None:

        selected = set(self.query_one("#service-list", SelectionList).selected)
        traefik_selected = "traefik" in selected

        self.query_one("#domain-input", Input).display = traefik_selected

        cloudflare_check = self.query_one("#cloudflare-dns-check", Checkbox)
        cloudflare_check.display = traefik_selected

        self.query_one("#cloudflare-email-input", Input).display = (
            traefik_selected and cloudflare_check.value
        )

    def _authelia_needs_setup(self) -> bool:

        selected = set(self.query_one("#service-list", SelectionList).selected)

        if "authelia" not in selected:
            return False

        users_database_path = STACK_DIR / "config" / "authelia" / "users_database.yml"

        return not users_database_path.exists()

    def _update_auth_visibility(self) -> None:

        needs_setup = self._authelia_needs_setup()

        self.query_one("#auth-username-input", Input).display = needs_setup
        self.query_one("#auth-password-input", Input).display = needs_setup

    def on_button_pressed(self, event: Button.Pressed) -> None:

        if event.button.id == "back":
            self.app.pop_screen()
            return

        if event.button.id != "continue":
            return

        if self._authelia_needs_setup():
            self._start_auth_setup()
            return

        self._continue_without_auth_setup()

    def _continue_without_auth_setup(self) -> None:

        self.app.auth_username = None
        self.app.auth_password_hash = None

        self._finish_and_push()

    def _finish_and_push(self) -> None:

        selected = set(self.query_one("#service-list", SelectionList).selected)
        self.app.custom_services = selected

        gpu_checkbox = self.query_one("#gpu-check", Checkbox)

        self.app.gpu_vendor = (
            self.app.system_info.gpu_vendor
            if gpu_checkbox.display and gpu_checkbox.value
            else None
        )

        domain_input = self.query_one("#domain-input", Input)

        self.app.domain = (
            (domain_input.value.strip() or None) if domain_input.display else None
        )

        cloudflare_check = self.query_one("#cloudflare-dns-check", Checkbox)
        cloudflare_email_input = self.query_one("#cloudflare-email-input", Input)

        self.app.cloudflare_dns = bool(
            cloudflare_check.display and cloudflare_check.value and self.app.domain
        )
        self.app.cloudflare_email = (
            (cloudflare_email_input.value.strip() or None)
            if self.app.cloudflare_dns else None
        )

        self.app.push_screen(ReviewScreen())

    def _start_auth_setup(self) -> None:

        username = self.query_one("#auth-username-input", Input).value.strip()
        password = self.query_one("#auth-password-input", Input).value

        result_widget = self.query_one("#auth-result", Static)

        if not username or not password:
            result_widget.update("Authelia admin username and password can't be blank.")
            result_widget.display = True
            return

        result_widget.update("")
        result_widget.display = False
        self._pending_auth_username = username

        self.query_one("#back", Button).disabled = True
        self.query_one("#continue", Button).disabled = True
        self.query_one("#auth-loading", LoadingIndicator).display = True

        self._run_hash(password)

    @work(thread=True)
    def _run_hash(self, password: str) -> None:

        result = hash_authelia_password(password)

        self.app.call_from_thread(self._hash_complete, result)

    def _hash_complete(self, result: dict) -> None:

        self.query_one("#back", Button).disabled = False
        self.query_one("#continue", Button).disabled = False
        self.query_one("#auth-loading", LoadingIndicator).display = False

        if not result["success"]:
            result_widget = self.query_one("#auth-result", Static)
            result_widget.update(result["error"])
            result_widget.display = True
            return

        self.app.auth_username = self._pending_auth_username
        self.app.auth_password_hash = result["hash"]

        self._finish_and_push()
