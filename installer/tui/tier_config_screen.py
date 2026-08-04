from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Checkbox, Input, RadioButton, RadioSet, Static

from installer.generate import default_puid_pgid, default_timezone
from installer.tiers import recommend_tier
from installer.tui.review_screen import ReviewScreen
from installer.tui.service_selection_screen import ServiceSelectionScreen


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
        sabnzbd_default = "sabnzbd" in previous["enabled_optional"] if previous else False
        recyclarr_default = "recyclarr" in previous["enabled_optional"] if previous else False
        homepage_default = (
            ("homepage" in previous["enabled_optional"]) or (previous.get("tier") == "heavy")
            if previous else True
        )
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
            Horizontal(
                Checkbox(
                    "Enable SABnzbd (Usenet downloader)", value=sabnzbd_default, id="sabnzbd-check"
                ),
                Checkbox(
                    "Enable Recyclarr (TRaSH Guides sync)", value=recyclarr_default, id="recyclarr-check"
                ),
            ),
            Horizontal(
                Checkbox("Enable Gluetun VPN", value=gluetun_default, id="gluetun-check"),
                Checkbox(gpu_label, value=gpu_default, id="gpu-check"),
                Checkbox(
                    "Enable Homepage dashboard", value=homepage_default, id="homepage-check"
                ),
            ),
            Input(value=str(default_puid), type="integer", placeholder="PUID", id="puid-input"),
            Input(value=str(default_pgid), type="integer", placeholder="PGID", id="pgid-input"),
            Input(value=default_tz, placeholder="Timezone", id="timezone-input"),
            Static("", id="tier-error"),
            Horizontal(
                Button("Back", id="back"),
                Button("Continue", id="continue"),
                Button("Customize Services", id="customize"),
            ),
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

    def _parse_puid_pgid(self) -> tuple[int, int] | None:

        error = self.query_one("#tier-error", Static)

        try:
            puid = int(self.query_one("#puid-input", Input).value)
            pgid = int(self.query_one("#pgid-input", Input).value)
        except ValueError:
            error.update("PUID and PGID must both be numbers.")
            return None

        return puid, pgid

    def _store_common_fields(self, puid: int, pgid: int) -> None:

        self.app.tier_name = self._current_tier_id()
        self.app.puid = puid
        self.app.pgid = pgid
        self.app.timezone = self.query_one("#timezone-input", Input).value

    def on_button_pressed(self, event: Button.Pressed) -> None:

        if event.button.id == "back":
            self.app.pop_screen()
            return

        if event.button.id not in ("continue", "customize"):
            return

        parsed = self._parse_puid_pgid()

        if parsed is None:
            return

        puid, pgid = parsed

        if event.button.id == "customize":

            self._store_common_fields(puid, pgid)
            self.app.push_screen(ServiceSelectionScreen())
            return

        tier_id = self._current_tier_id()
        enabled_optional = set()

        if tier_id == "medium" and self.query_one("#gluetun-check", Checkbox).value:
            enabled_optional.add("gluetun")

        if self.query_one("#sabnzbd-check", Checkbox).value:
            enabled_optional.add("sabnzbd")

        if self.query_one("#recyclarr-check", Checkbox).value:
            enabled_optional.add("recyclarr")

        if self.query_one("#homepage-check", Checkbox).value:
            enabled_optional.add("homepage")

        gpu_vendor_to_use = None

        if (
            tier_id == "heavy"
            and self.app.system_info.gpu_vendor
            and self.query_one("#gpu-check", Checkbox).value
        ):
            gpu_vendor_to_use = self.app.system_info.gpu_vendor

        self._store_common_fields(puid, pgid)
        self.app.enabled_optional = enabled_optional
        self.app.gpu_vendor = gpu_vendor_to_use
        self.app.custom_services = None

        self.app.push_screen(ReviewScreen())
