"""
Deterministic tier scoring: given a SystemInfo, decide which tier
(Light/Medium/Heavy) this machine qualifies for and why. No subprocess
calls, no privilege concerns, no LLM involvement - pure decision logic
over numbers detect.py already collected.
"""

from dataclasses import dataclass

from installer.detect import SystemInfo


@dataclass
class ServiceDefinition:

    key: str
    display_name: str
    optional: bool = False


@dataclass
class TierDefinition:

    name: str
    display_name: str
    min_cores: int
    min_ram_gb: float
    min_disk_gb: float
    services: list[ServiceDefinition]


_LIGHT_SERVICES = [
    ServiceDefinition("jellyfin", "Jellyfin"),
    ServiceDefinition("radarr", "Radarr"),
    ServiceDefinition("sonarr", "Sonarr"),
    ServiceDefinition("prowlarr", "Prowlarr"),
    ServiceDefinition("qbittorrent", "qBittorrent"),
    # Tier-agnostic, not Medium+-only - qBittorrent is present starting
    # here too, and Gluetun is what actually keeps its torrent traffic
    # from exposing a real IP to the swarm. Moved up from
    # _MEDIUM_SERVICES so it protects qBittorrent at every tier that
    # has it, not just Medium/Heavy.
    ServiceDefinition("gluetun", "Gluetun (VPN)", optional=True),
    ServiceDefinition("sabnzbd", "SABnzbd", optional=True),
    ServiceDefinition("recyclarr", "Recyclarr", optional=True),
    ServiceDefinition("decluttarr", "Decluttarr (download queue cleanup)", optional=True),
    # Tier-agnostic like Decluttarr, and for the same reason: Radarr/
    # Sonarr are non-optional in every tier, so Maintainerr always has
    # something real to manage - it's the other half of the original
    # "media agent" request (unwatched/unwanted library cleanup),
    # complementary to Decluttarr's download-queue cleanup, not a
    # duplicate of it.
    ServiceDefinition("maintainerr", "Maintainerr (library cleanup)", optional=True),
    ServiceDefinition("homepage", "Homepage/Homarr dashboard", optional=True),
    # A direct owner request for a second dashboard option alongside
    # Homepage, not a replacement - a real prior-CasaOS-setup preference
    # for Dashy's more visually polished, themeable UI over Homepage's
    # more utilitarian one. Gets the identical auto-pre-seeding
    # treatment Homepage already has (see render_dashy_config() in
    # generate.py), not a lesser second-class option.
    ServiceDefinition("dashy", "Dashy dashboard", optional=True),
    # Tier-agnostic like Decluttarr/Maintainerr - a direct user request
    # for the same "automated downloader" role their old CasaOS-hosted
    # Windows VM served, done container-native instead. Output lands in
    # the media library so Jellyfin can just scan it directly.
    ServiceDefinition("metube", "MeTube (YouTube downloader)", optional=True),
    ServiceDefinition("downtify", "Downtify (Spotify downloader)", optional=True),
    # Tier-agnostic like the others above, but deliberately not
    # default-anything the way Gluetun is - real, meaningfully deeper
    # host access than any other service here (SYS_PTRACE/SYS_ADMIN,
    # read-only access to most of the host filesystem, the Docker
    # socket, network_mode: host) for real-time CPU/RAM/disk/network/
    # temperature monitoring. A genuine security tradeoff named in the
    # CLI/TUI prompt and write_stack()'s own warning, not defaulted
    # quietly either way.
    ServiceDefinition("netdata", "Netdata (system resource monitoring)", optional=True),
    # Tier-agnostic like the others above. A direct user request for a
    # self-hosted password manager to hold the growing pile of
    # per-service credentials this stack generates. Not routed through
    # Authelia even when enabled - see the compose template's own
    # comment on the vaultwarden block for why (same native-app-login
    # conflict as Jellyfin).
    ServiceDefinition("vaultwarden", "Vaultwarden (password manager)", optional=True),
]

_MEDIUM_SERVICES = _LIGHT_SERVICES + [
    ServiceDefinition("jellyseerr", "Jellyseerr"),
    ServiceDefinition("bazarr", "Bazarr"),
    ServiceDefinition("flaresolverr", "FlareSolverr"),
]

_HEAVY_SERVICES = _MEDIUM_SERVICES + [
    ServiceDefinition("lidarr", "Lidarr", optional=True),
    ServiceDefinition("readarr", "Readarr", optional=True),
    ServiceDefinition("traefik", "Reverse proxy (Traefik)", optional=True),
    ServiceDefinition("authelia", "Authentication (Authelia)", optional=True),
    # Custom-mode only, same placement as Authelia/Traefik - genuinely
    # useful only once Traefik is routing real traffic (it blocks
    # malicious IPs at the edge, before they ever reach a login page).
    # Unlike Authelia, it's not gated behind the native-app-login
    # conflict - IP-reputation/behavior blocking doesn't break Jellyfin/
    # Vaultwarden's native apps the way a browser-redirect auth
    # challenge does, so it applies to every routed service including
    # those two (see the compose template's own comments on each).
    ServiceDefinition("crowdsec", "Intrusion protection (CrowdSec)", optional=True),
    ServiceDefinition("tailscale", "Tailscale (private remote access)", optional=True),
    # Custom-mode only, requires Traefik (see write_stack()'s own warning) -
    # points at Traefik as its single upstream rather than routing each
    # service itself, so it inherits every existing router/TLS/middleware
    # decision instead of duplicating it. Removes the need to forward
    # ports 80/443 from the router at all; --cloudflare-dns's real
    # certificates and this are independent (the tunnel's own internal
    # entrypoint to Traefik is plain HTTP - Cloudflare's edge already
    # terminated public TLS by the time traffic reaches it).
    ServiceDefinition("cloudflared", "Cloudflare Tunnel", optional=True),
    ServiceDefinition("uptime-kuma", "Uptime Kuma"),
    ServiceDefinition("watchtower", "Watchtower"),
]

TIERS: dict[str, TierDefinition] = {
    "light": TierDefinition("light", "Light", 2, 4, 100, _LIGHT_SERVICES),
    "medium": TierDefinition("medium", "Medium", 4, 8, 500, _MEDIUM_SERVICES),
    "heavy": TierDefinition("heavy", "Heavy", 6, 16, 1000, _HEAVY_SERVICES),
}

# Heavy's own list is already the flat union of all three tiers (Medium =
# Light + 4, Heavy = Medium + 5) - this is the full catalog custom-mode
# service selection picks from, not a separate registry.
ALL_SERVICES: list[ServiceDefinition] = _HEAVY_SERVICES

_ORDERED_HIGH_TO_LOW = ["heavy", "medium", "light"]


def tier_description(tier: TierDefinition) -> str:
    """
    Generated from the tier's real ServiceDefinition list, not
    hand-written - a hardcoded copy would have gone stale the moment
    a service was added (this project has hit that exact class of
    staleness multiple times with hand-maintained service counts
    elsewhere in the docs). Core services always render; optional ones
    only listed if the tier actually has any (Light's core-only list
    reads cleaner without a trailing "- optional:" when every optional
    service still shows via its own checkbox anyway).
    """

    core = [service.display_name for service in tier.services if not service.optional]
    optional = [service.display_name for service in tier.services if service.optional]

    description = ", ".join(core)

    if optional:
        description += " - optional: " + ", ".join(optional)

    return description


@dataclass
class Recommendation:

    tier: TierDefinition
    meets_minimum: bool
    explanation: str


def _shortfalls(cores: int, system_info: SystemInfo, tier: TierDefinition) -> list[str]:

    gaps = []

    if cores < tier.min_cores:
        gaps.append(f"{cores} cores (needs {tier.min_cores})")

    if system_info.ram_total_gb < tier.min_ram_gb:
        gaps.append(f"{system_info.ram_total_gb:.1f}GB RAM (needs {tier.min_ram_gb}GB)")

    if system_info.disk_free_gb < tier.min_disk_gb:
        gaps.append(f"{system_info.disk_free_gb:.1f}GB free disk (needs {tier.min_disk_gb}GB)")

    return gaps


def _next_tier_up(tier: TierDefinition) -> TierDefinition | None:

    index = _ORDERED_HIGH_TO_LOW.index(tier.name)

    if index == 0:
        return None

    return TIERS[_ORDERED_HIGH_TO_LOW[index - 1]]


def _explain(
    cores: int,
    system_info: SystemInfo,
    tier: TierDefinition,
    next_tier: TierDefinition | None
) -> str:

    if next_tier is None:
        return f"Qualifies for {tier.display_name} - the highest available tier."

    gaps = _shortfalls(cores, system_info, next_tier)

    if not gaps:
        return f"Qualifies for {tier.display_name}."

    return (
        f"Qualifies for {tier.display_name}. Short of {next_tier.display_name}: "
        f"{', '.join(gaps)}."
    )


def _explain_shortfall(cores: int, system_info: SystemInfo, light: TierDefinition) -> str:

    gaps = _shortfalls(cores, system_info, light)

    return (
        f"Below the recommended minimum for {light.display_name}: {', '.join(gaps)}. "
        f"{light.display_name} will still be set up, but expect it to be tight."
    )


def recommend_tier(system_info: SystemInfo) -> Recommendation:

    cores = system_info.cpu_cores_logical or system_info.cpu_cores_physical or 0

    for name in _ORDERED_HIGH_TO_LOW:

        tier = TIERS[name]

        if (
            cores >= tier.min_cores
            and system_info.ram_total_gb >= tier.min_ram_gb
            and system_info.disk_free_gb >= tier.min_disk_gb
        ):

            return Recommendation(
                tier=tier,
                meets_minimum=True,
                explanation=_explain(cores, system_info, tier, _next_tier_up(tier))
            )

    light = TIERS["light"]

    return Recommendation(
        tier=light,
        meets_minimum=False,
        explanation=_explain_shortfall(cores, system_info, light)
    )
