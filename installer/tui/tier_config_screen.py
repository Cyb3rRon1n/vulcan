from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Button, Checkbox, Input, RadioButton, RadioSet, Static

from installer.generate import default_puid_pgid, default_timezone
from installer.tiers import recommend_tier


class TierConfigScreen(Screen):

    DEFAULT_CSS = """
    TierConfigScreen {
        align: center middle;
    }

    #tier-error {
        margin: 1 0;
    }
    """

    def compose(self) -> ComposeResult:

        recommendation = recommend_tier(self.app.system_info)
        previous = self.app.previous_state

        default_tier = previous["tier"] if previous else recommendation.tier.name

        default_puid, default_pgid = default_puid_pgid()
        default_tz = default_timezone()

        if previous:
            default_puid = previous["puid"]
            default_pgid = previous["pgid"]
            default_tz = previous["timezone"]

        gluetun_default = "gluetun" in previous["enabled_optional"] if previous else False
        gpu_default = bool(previous.get("gpu_vendor")) if previous else True

        gpu_vendor = self.app.system_info.gpu_vendor
        gpu_label = f"Enable GPU passthrough ({gpu_vendor})" if gpu_vendor else "Enable GPU passthrough"

        yield Vertical(
            Static(
                f"Recommended tier: {recommendation.tier.display_name} - "
                f"{recommendation.explanation}",
                id="recommendation"
            ),
            RadioSet(
                RadioButton("Light", id="light", value=default_tier == "light"),
                RadioButton("Medium", id="medium", value=default_tier == "medium"),
                RadioButton("Heavy", id="heavy", value=default_tier == "heavy"),
                id="tier-set"
            ),
            Checkbox("Enable Gluetun VPN", value=gluetun_default, id="gluetun-check"),
            Checkbox(gpu_label, value=gpu_default, id="gpu-check"),
            Input(value=str(default_puid), type="integer", placeholder="PUID", id="puid-input"),
            Input(value=str(default_pgid), type="integer", placeholder="PGID", id="pgid-input"),
            Input(value=default_tz, placeholder="Timezone", id="timezone-input"),
            Static("", id="tier-error"),
            Button("Continue", id="continue"),
        )

    def on_mount(self) -> None:
        self._update_visibility(self._current_tier_id())

    def _current_tier_id(self) -> str:
        return self.query_one("#tier-set", RadioSet).pressed_button.id

    def _update_visibility(self, tier_id: str) -> None:

        gpu_vendor = self.app.system_info.gpu_vendor

        self.query_one("#gluetun-check", Checkbox).display = tier_id == "medium"
        self.query_one("#gpu-check", Checkbox).display = tier_id == "heavy" and bool(gpu_vendor)

    def on_radio_set_changed(self, event: RadioSet.Changed) -> None:
        self._update_visibility(event.pressed.id)

    def on_button_pressed(self, event: Button.Pressed) -> None:

        if event.button.id != "continue":
            return

        error = self.query_one("#tier-error", Static)

        try:
            puid = int(self.query_one("#puid-input", Input).value)
            pgid = int(self.query_one("#pgid-input", Input).value)
        except ValueError:
            error.update("PUID and PGID must both be numbers.")
            return

        tier_id = self._current_tier_id()
        enabled_optional = set()

        if tier_id == "medium" and self.query_one("#gluetun-check", Checkbox).value:
            enabled_optional.add("gluetun")

        gpu_vendor_to_use = None

        if (
            tier_id == "heavy"
            and self.app.system_info.gpu_vendor
            and self.query_one("#gpu-check", Checkbox).value
        ):
            gpu_vendor_to_use = self.app.system_info.gpu_vendor

        self.app.tier_name = tier_id
        self.app.enabled_optional = enabled_optional
        self.app.gpu_vendor = gpu_vendor_to_use
        self.app.puid = puid
        self.app.pgid = pgid
        self.app.timezone = self.query_one("#timezone-input", Input).value

        self.app.exit(
            message=(
                "Review & generate isn't built yet - re-run with --plain "
                "for the complete flow."
            )
        )
