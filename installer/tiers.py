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
    ServiceDefinition("sabnzbd", "SABnzbd", optional=True),
    ServiceDefinition("recyclarr", "Recyclarr", optional=True),
    ServiceDefinition("decluttarr", "Decluttarr (download queue cleanup)", optional=True),
    ServiceDefinition("homepage", "Homepage/Homarr dashboard", optional=True),
]

_MEDIUM_SERVICES = _LIGHT_SERVICES + [
    ServiceDefinition("jellyseerr", "Jellyseerr"),
    ServiceDefinition("bazarr", "Bazarr"),
    ServiceDefinition("flaresolverr", "FlareSolverr"),
    ServiceDefinition("gluetun", "Gluetun (VPN)", optional=True),
]

_HEAVY_SERVICES = _MEDIUM_SERVICES + [
    ServiceDefinition("lidarr", "Lidarr", optional=True),
    ServiceDefinition("readarr", "Readarr", optional=True),
    ServiceDefinition("traefik", "Reverse proxy (Traefik)", optional=True),
    ServiceDefinition("authelia", "Authentication (Authelia)", optional=True),
    ServiceDefinition("tailscale", "Tailscale (private remote access)", optional=True),
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
