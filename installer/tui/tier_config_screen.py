from textual import events
from textual.app import ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Checkbox, Input, RadioButton, RadioSet, Static

from installer.generate import default_puid_pgid, default_timezone
from installer.tiers import TIERS, recommend_tier, tier_description
from installer.tui.review_screen import ReviewScreen
from installer.tui.service_selection_screen import ServiceSelectionScreen


class TierConfigScreen(Screen):
    """
    Root is a VerticalScroll, not a plain Vertical - the same fix
    ReviewScreen already established for the identical problem
    (content genuinely exceeding the 80x24 test viewport once enough
    optional-service checkboxes exist). align: center middle is
    dropped for the same reason ReviewScreen dropped it - it fights a
    scrollable root, and centering doesn't make sense once content can
    genuinely overflow and scroll.
    """

    DEFAULT_CSS = """
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

        # Defaults to True (opt-out) on a fresh install - see the CLI's
        # identical change for the real reasoning (qBittorrent is
        # exposed without it, at every tier, and this used to only
        # even be reachable at Medium tier in the default flow).
        gluetun_default = "gluetun" in previous["enabled_optional"] if previous else True
        sabnzbd_default = "sabnzbd" in previous["enabled_optional"] if previous else False
        recyclarr_default = "recyclarr" in previous["enabled_optional"] if previous else False
        homepage_default = (
            ("homepage" in previous["enabled_optional"]) or (previous.get("tier") == "heavy")
            if previous else True
        )
        metube_default = "metube" in previous["enabled_optional"] if previous else False
        downtify_default = "downtify" in previous["enabled_optional"] if previous else False
        netdata_default = "netdata" in previous["enabled_optional"] if previous else False
        vaultwarden_default = "vaultwarden" in previous["enabled_optional"] if previous else False
        dashy_default = "dashy" in previous["enabled_optional"] if previous else False
        gpu_default = bool(previous.get("gpu_vendor")) if previous else True

        gpu_vendor = self.app.system_info.gpu_vendor
        gpu_label = f"Enable GPU passthrough ({gpu_vendor})" if gpu_vendor else "Enable GPU passthrough"

        yield VerticalScroll(
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
                        "Recommended - without it, torrent traffic exposes your real IP to "
                        "the swarm. You'll need your VPN provider's credentials afterward - "
                        "setup guide per provider: "
                        "https://github.com/qdm12/gluetun-wiki/tree/main/setup/providers"
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
            Horizontal(
                Checkbox(
                    "Enable MeTube (YouTube downloader)", value=metube_default, id="metube-check",
                    tooltip="Downloads land in stack/media/youtube - add a Jellyfin library pointed there to watch them."
                ),
                Checkbox(
                    "Enable Downtify (Spotify downloader)", value=downtify_default, id="downtify-check",
                    tooltip="No Spotify account or API key needed - paste a track/album/playlist URL to download it."
                ),
            ),
            Checkbox(
                "Enable Netdata (system monitoring)", value=netdata_default, id="netdata-check",
                tooltip=(
                    "Real-time CPU/RAM/disk/network/temperature dashboards - needs real, "
                    "deeper host access than anything else here (SYS_PTRACE/SYS_ADMIN, "
                    "read-only host filesystem, the Docker socket) to see all of that."
                )
            ),
            Checkbox(
                "Enable Vaultwarden (password manager)", value=vaultwarden_default, id="vaultwarden-check",
                tooltip=(
                    "Self-hosted, Bitwarden-compatible password manager - a good first stop "
                    "after install to save every other service's login. Not routed through "
                    "Authelia even if enabled, same reason as Jellyfin."
                )
            ),
            Checkbox(
                "Enable Dashy (second dashboard)", value=dashy_default, id="dashy-check",
                tooltip=(
                    "A second, more visually customizable dashboard alongside Homepage - "
                    "same auto-pre-seeded tiles for every enabled service."
                )
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
            id="tier-config-root",
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

        # Gluetun is no longer tier-gated (used to only show at Medium) -
        # qBittorrent is present at every tier, and so is the real IP
        # exposure Gluetun protects against, so the checkbox is just
        # always visible now, same as SABnzbd/Recyclarr/Homepage.
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
        # auto-focuses the first focusable widget right after mount,
        # firing DescendantFocus and immediately clobbering the line
        # above back to "" if that widget has no tooltip of its own.
        # Keeping both the RadioSet's tooltip AND the new VerticalScroll
        # root's own tooltip in sync here means that auto-focus event
        # reads the same correct text instead of clearing it, regardless
        # of which of the two actually ends up being auto-focused - the
        # root itself became a second real candidate the moment it
        # switched from a plain Vertical to a focusable VerticalScroll
        # (added so #continue stays reachable once enough optional-
        # service checkboxes exist to overflow the test viewport).
        self.query_one("#tier-set", RadioSet).tooltip = description
        self.query_one("#tier-config-root", VerticalScroll).tooltip = description

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

        if self.query_one("#gluetun-check", Checkbox).value:
            enabled_optional.add("gluetun")

        if self.query_one("#sabnzbd-check", Checkbox).value:
            enabled_optional.add("sabnzbd")

        if self.query_one("#recyclarr-check", Checkbox).value:
            enabled_optional.add("recyclarr")

        if self.query_one("#homepage-check", Checkbox).value:
            enabled_optional.add("homepage")

        if self.query_one("#metube-check", Checkbox).value:
            enabled_optional.add("metube")

        if self.query_one("#downtify-check", Checkbox).value:
            enabled_optional.add("downtify")

        if self.query_one("#netdata-check", Checkbox).value:
            enabled_optional.add("netdata")

        if self.query_one("#vaultwarden-check", Checkbox).value:
            enabled_optional.add("vaultwarden")

        if self.query_one("#dashy-check", Checkbox).value:
            enabled_optional.add("dashy")

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
