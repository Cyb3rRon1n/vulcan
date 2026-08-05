from textual import events
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Checkbox, Input, RadioButton, RadioSet, Static

from installer.generate import default_puid_pgid, default_timezone
from installer.tiers import TIERS, recommend_tier, tier_description
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
                RadioButton(
                    "Light", id="light", value=default_tier == "light",
                    tooltip=tier_description(TIERS["light"])
                ),
                RadioButton(
                    "Medium", id="medium", value=default_tier == "medium",
                    tooltip=tier_description(TIERS["medium"])
                ),
                RadioButton(
                    "Heavy", id="heavy", value=default_tier == "heavy",
                    tooltip=tier_description(TIERS["heavy"])
                ),
                id="tier-set"
            ),
            Horizontal(
                Checkbox(
                    "Enable SABnzbd (Usenet downloader)", value=sabnzbd_default, id="sabnzbd-check",
                    tooltip=(
                        "Needs your Usenet provider's server details entered through its own "
                        "setup wizard on first login before it can download anything."
                    )
                ),
                Checkbox(
                    "Enable Recyclarr (TRaSH Guides sync)", value=recyclarr_default, id="recyclarr-check",
                    tooltip=(
                        "Syncs TRaSH Guides quality/format settings into Radarr/Sonarr - needs "
                        "each app's real API key added to its config after first start."
                    )
                ),
            ),
            Horizontal(
                Checkbox(
                    "Enable Gluetun VPN", value=gluetun_default, id="gluetun-check",
                    tooltip=(
                        "You'll need your VPN provider's credentials afterward - setup guide "
                        "per provider: https://github.com/qdm12/gluetun-wiki/tree/main/setup/providers"
                    )
                ),
                Checkbox(
                    gpu_label, value=gpu_default, id="gpu-check",
                    tooltip="Passes the detected GPU through to Jellyfin for hardware transcoding."
                ),
                Checkbox(
                    "Enable Homepage dashboard", value=homepage_default, id="homepage-check",
                    tooltip="A dashboard with tiles linking to every enabled service - pre-seeded automatically, safe to accept."
                ),
            ),
            Input(
                value=str(default_puid), type="integer", placeholder="PUID", id="puid-input",
                tooltip="User ID the containers run as - matters for file ownership on your media library. Defaults to your own user."
            ),
            Input(
                value=str(default_pgid), type="integer", placeholder="PGID", id="pgid-input",
                tooltip="Group ID the containers run as - same as PUID, defaults to your own user's group."
            ),
            Input(
                value=default_tz, placeholder="Timezone", id="timezone-input",
                tooltip="IANA timezone name (e.g. America/New_York) - used by every container for correct local timestamps."
            ),
            Static("", id="tier-error"),
            Horizontal(
                Button("Back", id="back"),
                Button("Continue", id="continue"),
                Button("Customize Services", id="customize"),
            ),
        )

    def on_mount(self) -> None:
        self._update_visibility(self._current_tier_id())

    def on_descendant_focus(self, event: events.DescendantFocus) -> None:
        """
        Keyboard-accessible equivalent of the mouse-only tooltip - Focus/
        Blur don't bubble, but DescendantFocus does, so this fires once
        per Tab regardless of which widget gained focus. Reuses
        #tier-error (already part of the layout) rather than adding a
        new row - can overwrite an unread validation error on the next
        Tab, an accepted tradeoff over a stickier design.
        """

        self.query_one("#tier-error", Static).update(event.widget.tooltip or "")

    def _current_tier_id(self) -> str:
        return self.query_one("#tier-set", RadioSet).pressed_button.id

    def _update_visibility(self, tier_id: str) -> None:

        gpu_vendor = self.app.system_info.gpu_vendor

        self.query_one("#gluetun-check", Checkbox).display = tier_id == "medium"
        self.query_one("#gpu-check", Checkbox).display = tier_id == "heavy" and bool(gpu_vendor)

        # Reuses #tier-error rather than a new row - there's no room for
        # one (this screen's #continue/#back already sit at the bottom
        # of the test viewport's real height budget). Same accepted
        # "can be overwritten by the next focus change" tradeoff the
        # tooltip mechanism below already has - showing what a tier
        # actually contains the moment you select it is worth that.
        description = tier_description(TIERS[tier_id])
        self.query_one("#tier-error", Static).update(description)

        # A real ordering issue found by testing, not assumed: Textual
        # auto-focuses the first focusable widget (the RadioSet itself)
        # right after mount, firing DescendantFocus and immediately
        # clobbering the line above back to "" (RadioSet had no tooltip
        # of its own). Keeping the RadioSet's own tooltip in sync here
        # means that auto-focus event reads the same correct text
        # instead of clearing it - no flicker, no special-casing the
        # mount-vs-change path.
        self.query_one("#tier-set", RadioSet).tooltip = description

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
