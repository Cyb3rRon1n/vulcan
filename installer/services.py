"""
Docker resource-limit sizing for generated stacks. Separate from
tiers.py on purpose - tiers.py is scoring/display only, this module is
generation-only (the same split Atlas keeps between targets.py and
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
    "jellyseerr": "light",
    "bazarr": "light",
    "flaresolverr": "light",
    "gluetun": "light",
    "lidarr": "standard",
    "traefik": "light",
    "homepage": "light",
    "uptime-kuma": "light",
    "watchtower": "light",
}

RESOURCE_LIMITS: dict[str, dict[str, tuple[str, str]]] = {
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


def resource_limits_for(tier_name: str) -> dict[str, dict[str, str]]:

    return {
        key: {
            "cpus": RESOURCE_LIMITS[tier_name][profile][0],
            "memory": RESOURCE_LIMITS[tier_name][profile][1]
        }
        for key, profile in RESOURCE_PROFILES.items()
    }
