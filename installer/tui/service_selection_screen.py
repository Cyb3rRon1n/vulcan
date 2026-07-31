from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Button, Checkbox, Input, SelectionList, Static
from textual.widgets.selection_list import Selection

from installer.tiers import ALL_SERVICES, TIERS
from installer.tui.review_screen import ReviewScreen


class ServiceSelectionScreen(Screen):

    DEFAULT_CSS = """
    ServiceSelectionScreen {
        align: center middle;
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

        yield Vertical(
            Static("Select services to include", id="title"),
            SelectionList(*selections, id="service-list"),
            Checkbox(gpu_label, value=gpu_default, id="gpu-check"),
            Input(
                value=default_domain or "",
                placeholder="Base domain, e.g. media.example.com",
                id="domain-input"
            ),
            Button("Continue", id="continue"),
        )

    def on_mount(self) -> None:
        self._update_gpu_visibility()
        self._update_domain_visibility()

    def on_selection_list_selected_changed(self, event: SelectionList.SelectedChanged) -> None:
        self._update_gpu_visibility()
        self._update_domain_visibility()

    def _update_gpu_visibility(self) -> None:

        selected = set(self.query_one("#service-list", SelectionList).selected)
        gpu_vendor = self.app.system_info.gpu_vendor

        self.query_one("#gpu-check", Checkbox).display = "jellyfin" in selected and bool(gpu_vendor)

    def _update_domain_visibility(self) -> None:

        selected = set(self.query_one("#service-list", SelectionList).selected)

        self.query_one("#domain-input", Input).display = "traefik" in selected

    def on_button_pressed(self, event: Button.Pressed) -> None:

        if event.button.id != "continue":
            return

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

        self.app.push_screen(ReviewScreen())
