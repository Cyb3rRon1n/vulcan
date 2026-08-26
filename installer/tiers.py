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
    ServiceDefinition("filebrowser", "FileBrowser (file manager)"),
    ServiceDefinition("gluetun", "Gluetun (VPN)", optional=True),
    ServiceDefinition("sabnzbd", "SABnzbd", optional=True),
    ServiceDefinition("recyclarr", "Recyclarr", optional=True),
    ServiceDefinition("decluttarr", "Decluttarr (download queue cleanup)", optional=True),
    ServiceDefinition("maintainerr", "Maintainerr", optional=True),
    ServiceDefinition("homepage", "Homepage/Homarr dashboard", optional=True),
    ServiceDefinition("dashy", "Dashy dashboard", optional=True),
    ServiceDefinition("metube", "MeTube", optional=True),
    ServiceDefinition("downtify", "Downtify", optional=True),
    ServiceDefinition("netdata", "Netdata", optional=True),
    ServiceDefinition("vaultwarden", "Vaultwarden", optional=True),
    ServiceDefinition("pihole", "Pi-hole + Unbound (DNS ad-blocker)", optional=True),
]

_MEDIUM_SERVICES = _LIGHT_SERVICES + [
    ServiceDefinition("seerr", "Seerr (media requests)"),
    ServiceDefinition("bazarr", "Bazarr"),
    ServiceDefinition("flaresolverr", "FlareSolverr"),
    ServiceDefinition("tracearr", "Tracearr (stream analytics)", optional=True),
    ServiceDefinition("uptime-kuma", "Uptime Kuma", optional=True),
    ServiceDefinition("watchtower", "Watchtower", optional=True),
    ServiceDefinition("threadfin", "Threadfin (IPTV proxy)", optional=True),
]

_HEAVY_SERVICES = _MEDIUM_SERVICES + [
    ServiceDefinition("lidarr", "Lidarr", optional=True),
    ServiceDefinition("readarr", "Readarr", optional=True),
    ServiceDefinition("traefik", "Traefik", optional=True),
    ServiceDefinition("authelia", "Authelia", optional=True),
    ServiceDefinition("crowdsec", "Intrusion protection (CrowdSec)", optional=True),
    ServiceDefinition("tailscale", "Tailscale (private remote access)", optional=True),
    ServiceDefinition("cloudflared", "Cloudflare Tunnel", optional=True),
    ServiceDefinition("sportarr", "Sportarr (sports PVR)", optional=True),
]

TIERS: dict[str, TierDefinition] = {
    "light": TierDefinition("light", "Light", 2, 4, 100, _LIGHT_SERVICES),
    "medium": TierDefinition("medium", "Medium", 4, 8, 500, _MEDIUM_SERVICES),
    "heavy": TierDefinition("heavy", "Heavy", 6, 16, 1000, _HEAVY_SERVICES),
}


ALL_SERVICES: list[ServiceDefinition] = _HEAVY_SERVICES

_ORDERED_HIGH_TO_LOW = ["heavy", "medium", "light"]


def tier_description(tier: TierDefinition) -> str:
    """
    Generated from the tier's real ServiceDefinition list, not
    hand-written - a hardcoded copy would have gone stale the moment
    services were added or moved between tiers.
    """

    core = [s.display_name for s in tier.services if not s.optional]
    optional = [s.display_name for s in tier.services if s.optional]

    lines = [
        f"[bold]{tier.display_name} tier[/bold]"
        f" ({tier.min_cores}+ cores, {tier.min_ram_gb:.0f}GB+ RAM, "
        f"{tier.min_disk_gb}GB+ free disk):",
        "",
    ]

    if core:
        lines.append("[bold]Core:[/bold] " + ", ".join(core))
    if optional:
        lines.append("[bold]Optional:[/bold] " + ", ".join(optional))

    return "\n".join(lines)


def recommend_tier(info: SystemInfo) -> str:
    """
    Deterministic tier recommendation from detected hardware.
    Returns the highest tier whose every minimum is met.
    """

    cores = info.cpu_cores_logical or info.cpu_cores_physical or 0

    for tier_name in _ORDERED_HIGH_TO_LOW:
        tier = TIERS[tier_name]
        if (
            cores >= tier.min_cores
            and info.memory_gb >= tier.min_ram_gb
            and info.disk_free_gb >= tier.min_disk_gb
        ):
            return tier_name

    return "light"


def tier_upgrade_hints(info: SystemInfo, current: str) -> list[str]:
    """
    If the user is on a lower tier, explain what hardware would
    unlock the next one - concrete, not aspirational.
    """

    idx = _ORDERED_HIGH_TO_LOW.index(current)
    if idx == 0:
        return []

    cores = info.cpu_cores_logical or info.cpu_cores_physical or 0
    next_tier = TIERS[_ORDERED_HIGH_TO_LOW[idx - 1]]
    hints = []

    if cores < next_tier.min_cores:
        hints.append(f"{next_tier.min_cores}+ CPU cores (you have {cores})")
    if info.memory_gb < next_tier.min_ram_gb:
        hints.append(f"{next_tier.min_ram_gb:.0f}GB+ RAM (you have {info.memory_gb:.1f}GB)")
    if info.disk_free_gb < next_tier.min_disk_gb:
        hints.append(f"{next_tier.min_disk_gb}GB+ free disk (you have {info.disk_free_gb:.0f}GB)")

    return hints
