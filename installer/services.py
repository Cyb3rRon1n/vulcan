"""
Docker resource-limit sizing for generated stacks. Separate from
tiers.py on purpose - tiers.py is scoring/display only, this module is
generation-only (the same split Lanxang keeps between targets.py and
registry.py). Each service declares its own typical footprint once
(RESOURCE_PROFILES); RESOURCE_LIMITS scales every profile together per
tier, so adding a tier or a service never means hand-tuning a full
tier x service matrix by hand.
"""

RESOURCE_PROFILES: dict[str, str] = {
    "jellyfin": "heavy",
    "radarr": "standard",
    "sonarr": "standard",
    "prowlarr": "light",
    "qbittorrent": "standard",
    "sabnzbd": "standard",
    "recyclarr": "light",
    "decluttarr": "light",
    "maintainerr": "light",
    "atlas": "light",
    "seerr": "light",
    "bazarr": "light",
    "flaresolverr": "light",
    # A headless Firefox per solve (~2GB RSS measured) - light/standard limits OOM it.
    "byparr": "heavy",
    # faster-whisper speech-to-text; the medium model sat at ~2.7GB RSS on a live host.
    "whisper": "heavy",
    "gluetun": "light",
    "lidarr": "standard",
    "readarr": "standard",
    "traefik": "light",
    "authelia": "light",
    "crowdsec": "light",
    "tailscale": "light",
    "homepage": "light",
    "uptime-kuma": "light",
    "watchtower": "light",
    "metube": "standard",
    "downtify": "standard",
    "netdata": "light",
    "glances": "light",
    "ntfy": "light",
    "navidrome": "light",
    "komga": "standard",
    "kavita": "standard",
    "suwayomi": "standard",
    "mylar3": "light",
    "lazylibrarian": "light",
    "slskd": "light",
    "calibre-web-automated": "standard",
    "vaultwarden": "light",
    # Confirmed live: ~47MB idle via `docker stats` against a real
    # started container - genuinely light, same bucket as Homepage.
    "dashy": "light",
    "cloudflared": "light",
    "filebrowser": "light",
    "pihole": "light",
    "tracearr": "standard",
    "threadfin": "light",
    "portainer": "light",
    "adguardhome": "light",
    "guacamole": "standard",
}

RESOURCE_LIMITS: dict[str, dict[str, tuple[str, str]]] = {
    "travel": {
        "light": ("0.5", "256m"),
        "standard": ("1.0", "512m"),
        "heavy": ("1.5", "1g")
    },
    "light": {
        "light": ("0.5", "256m"),
        "standard": ("1.0", "512m"),
        "heavy": ("1.5", "1g")
    },
    "medium": {
        "light": ("1.0", "512m"),
        "standard": ("1.5", "1g"),
        "heavy": ("2.5", "2g")
    },
    "heavy": {
        "light": ("1.5", "1g"),
        "standard": ("2.0", "1.5g"),
        "heavy": ("4.0", "4g")
    },
}


def _travel_limits(cores: int, ram_gb: float) -> dict[str, tuple[str, str]]:
    """A travel box runs little besides Vulcan, so its limits are shares of the
    real host, never below Light's: light services 1/4 core + 6% RAM, standard
    1/2 core + 12%, heavy (Jellyfin) every core + 40%."""

    mb = ram_gb * 1024

    return {
        "light": (f"{max(0.5, cores * 0.25):.1f}", f"{max(256, int(mb * 0.06))}m"),
        "standard": (f"{max(1.0, cores * 0.5):.1f}", f"{max(512, int(mb * 0.12))}m"),
        "heavy": (f"{max(1.5, float(cores)):.1f}", f"{max(1024, int(mb * 0.4))}m"),
    }


def resource_limits_for(
    tier_name: str, cpu_count: int | None = None, ram_gb: float | None = None
) -> dict[str, dict[str, str]]:

    table = (
        _travel_limits(cpu_count, ram_gb) if tier_name == "travel" and cpu_count and ram_gb
        else RESOURCE_LIMITS[tier_name]
    )

    return {
        key: {"cpus": table[profile][0], "memory": table[profile][1]}
        for key, profile in RESOURCE_PROFILES.items()
    }
