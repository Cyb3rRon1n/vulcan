"""
Jinja2 rendering: takes the chosen tier + configuration answers and
renders templates/docker-compose.yml.j2 and templates/env.j2 into a
real stack/docker-compose.yml and stack/.env for the user's machine.
Pure-ish: write_stack() does real file I/O but never prompts or
confirms - that's the CLI layer's job (Phase 1 slice 5), the same
split Atlas keeps between config/writer.py and the atlas init command.
"""

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from datetime import timezone as dt_timezone
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader

from installer.detect import detect_host_ip, detect_render_group_gid
from installer.services import resource_limits_for
from installer.tiers import ALL_SERVICES, TIERS, TierDefinition


TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
STACK_DIR = Path("stack")
STATE_FILENAME = ".vulcan-state.json"

# Homepage tile groups/ports - deliberately mirrors the same web-facing
# service set the Traefik template's per-service labels already target
# (minus Homepage itself), not a shared constant with that template -
# see CLAUDE.md for why. Ports here are each service's own host-published
# port (what a browser actually hits), not the container-internal port
# Traefik's labels use - the opposite convention, and it matters for
# SABnzbd specifically (8081 here, not its internal 8080).
_HOMEPAGE_GROUPS: dict[str, list[str]] = {
    "Media": ["jellyfin", "jellyseerr"],
    "Media Management": ["radarr", "sonarr", "lidarr", "readarr", "prowlarr", "bazarr"],
    "Downloads": ["qbittorrent", "sabnzbd"],
    "Monitoring": ["uptime-kuma"],
}

_HOMEPAGE_PORTS: dict[str, int] = {
    "jellyfin": 8096,
    "radarr": 7878,
    "sonarr": 8989,
    "prowlarr": 9696,
    "qbittorrent": 8080,
    "sabnzbd": 8081,
    "jellyseerr": 5055,
    "bazarr": 6767,
    "lidarr": 8686,
    "readarr": 8787,
    "uptime-kuma": 3001,
}


@dataclass
class GenerationConfig:

    tier: TierDefinition
    media_path: str
    puid: int
    pgid: int
    timezone: str
    enabled_optional: set[str] = field(default_factory=set)
    gpu_vendor: str | None = None
    custom_services: set[str] | None = None
    domain: str | None = None


def default_puid_pgid() -> tuple[int, int]:

    return os.getuid(), os.getgid()


def default_timezone() -> str:

    try:
        return Path("/etc/timezone").read_text().strip()
    except OSError:
        pass

    try:
        target = Path("/etc/localtime").resolve()
        return str(target).split("zoneinfo/", 1)[1]
    except (OSError, IndexError):
        return "UTC"


def enabled_service_keys(config: GenerationConfig) -> set[str]:

    if config.custom_services is not None:
        return config.custom_services

    return {
        service.key for service in config.tier.services
        if not service.optional or service.key in config.enabled_optional
    }


def save_state(config: GenerationConfig, output_dir: Path) -> None:

    state = {
        "tier": config.tier.name,
        "media_path": config.media_path,
        "puid": config.puid,
        "pgid": config.pgid,
        "timezone": config.timezone,
        "enabled_optional": sorted(config.enabled_optional),
        "gpu_vendor": config.gpu_vendor,
        "custom_services": (
            sorted(config.custom_services) if config.custom_services is not None else None
        ),
        "domain": config.domain,
        "generated_at": datetime.now(dt_timezone.utc).isoformat()
    }

    (output_dir / STATE_FILENAME).write_text(json.dumps(state, indent=2))


def load_previous_state(output_dir: Path) -> dict | None:
    """
    Never raises - missing file, corrupt JSON, or an unknown tier name
    (e.g. hand-edited) all just mean "no usable previous state."
    """

    try:

        state = json.loads((output_dir / STATE_FILENAME).read_text())
        assert state["tier"] in TIERS
        return state

    except (OSError, json.JSONDecodeError, KeyError, AssertionError):
        return None


def _preserved_vpn_value(output_dir: Path, key: str, default: str) -> str:

    try:
        existing = (output_dir / ".env").read_text()
    except OSError:
        return default

    for line in existing.splitlines():

        if line.startswith(f"{key}="):

            value = line.split("=", 1)[1]
            return value if value != "changeme" else default

    return default


def _jinja_env() -> Environment:

    return Environment(
        loader=FileSystemLoader(TEMPLATES_DIR),
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
        autoescape=False
    )


def render_compose(config: GenerationConfig) -> str:

    template = _jinja_env().get_template("docker-compose.yml.j2")

    return template.render(
        enabled=enabled_service_keys(config),
        limits=resource_limits_for(config.tier.name),
        gpu_vendor=config.gpu_vendor,
        render_gid=(
            detect_render_group_gid() if config.gpu_vendor in ("amd", "intel") else None
        ),
        domain=config.domain
    )


def render_env(
    config: GenerationConfig,
    vpn_service_provider: str = "changeme",
    vpn_type: str = "wireguard",
    wireguard_private_key: str = "changeme"
) -> str:

    template = _jinja_env().get_template("env.j2")

    return template.render(
        media_path=config.media_path,
        puid=config.puid,
        pgid=config.pgid,
        timezone=config.timezone,
        gluetun_enabled="gluetun" in config.enabled_optional,
        vpn_service_provider=vpn_service_provider,
        vpn_type=vpn_type,
        wireguard_private_key=wireguard_private_key
    )


def _service_href(key: str, config: GenerationConfig, host_ip: str | None) -> str:

    enabled = enabled_service_keys(config)
    routed = "traefik" in enabled and config.domain

    if routed:
        return f"https://{key}.{config.domain}"

    return f"http://{host_ip or 'localhost'}:{_HOMEPAGE_PORTS[key]}"


def render_homepage_services(config: GenerationConfig, host_ip: str | None) -> str:

    enabled = enabled_service_keys(config)
    display_names = {service.key: service.display_name for service in ALL_SERVICES}

    groups = []

    for group_name, keys in _HOMEPAGE_GROUPS.items():

        items = []

        for key in keys:

            if key not in enabled:
                continue

            href = _service_href(key, config, host_ip)
            items.append({display_names[key]: {"href": href, "icon": f"{key}.png"}})

        if items:
            groups.append({group_name: items})

    return yaml.safe_dump(groups, sort_keys=False)


def _uptime_kuma_reference(config: GenerationConfig, host_ip: str | None) -> str:

    enabled = enabled_service_keys(config)
    display_names = {service.key: service.display_name for service in ALL_SERVICES}

    lines = [
        f"  {display_names[key]}: {_service_href(key, config, host_ip)}"
        for keys in _HOMEPAGE_GROUPS.values()
        for key in keys
        if key in enabled and key != "uptime-kuma"
    ]

    kuma_href = _service_href("uptime-kuma", config, host_ip)

    return (
        f"Uptime Kuma needs one-time setup: visit {kuma_href}, create an account, "
        "then add a monitor for each service you want to track. Your enabled services:\n"
        + "\n".join(lines)
    )


def write_stack(config: GenerationConfig, output_dir: Path = STACK_DIR) -> dict:

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    compose_path = output_dir / "docker-compose.yml"
    env_path = output_dir / ".env"

    # Read any existing .env before it gets overwritten - a real Gluetun
    # VPN credential the user already filled in must survive a regenerate,
    # not get reset back to a placeholder.
    env_content = render_env(
        config,
        vpn_service_provider=_preserved_vpn_value(output_dir, "VPN_SERVICE_PROVIDER", "changeme"),
        vpn_type=_preserved_vpn_value(output_dir, "VPN_TYPE", "wireguard"),
        wireguard_private_key=_preserved_vpn_value(output_dir, "WIREGUARD_PRIVATE_KEY", "changeme")
    )

    compose_path.write_text(render_compose(config))
    env_path.write_text(env_content)
    save_state(config, output_dir)

    for key in enabled_service_keys(config):
        (output_dir / "config" / key).mkdir(parents=True, exist_ok=True)

    media_path = Path(config.media_path)
    (media_path / "downloads").mkdir(parents=True, exist_ok=True)
    (media_path / "media" / "movies").mkdir(parents=True, exist_ok=True)
    (media_path / "media" / "tv").mkdir(parents=True, exist_ok=True)
    (media_path / "media" / "music").mkdir(parents=True, exist_ok=True)
    (media_path / "media" / "books").mkdir(parents=True, exist_ok=True)

    warnings = []
    host_ip = detect_host_ip()

    if "homepage" in enabled_service_keys(config):

        services_yaml_path = output_dir / "config" / "homepage" / "services.yaml"

        if not services_yaml_path.exists():

            services_yaml_path.write_text(render_homepage_services(config, host_ip))

            warnings.append(
                "Homepage was pre-seeded with tiles for your enabled services at "
                "stack/config/homepage/services.yaml - edit it directly to customize "
                "further; Vulcan won't overwrite it on a later regenerate."
            )

    if "uptime-kuma" in enabled_service_keys(config):
        warnings.append(_uptime_kuma_reference(config, host_ip))

    if "gluetun" in config.enabled_optional:

        warnings.append(
            "Gluetun requires real VPN provider credentials in stack/.env "
            "before it will connect - see the TODO comments there."
        )

    if "sabnzbd" in enabled_service_keys(config):

        warnings.append(
            "SABnzbd needs your Usenet provider's server details entered through "
            "its own setup wizard on first login before it can download anything."
        )

    if "recyclarr" in enabled_service_keys(config):

        warnings.append(
            "Recyclarr will scaffold a starter config at stack/config/recyclarr/recyclarr.yml "
            "on first start with only a sonarr: section and placeholder values - add a radarr: "
            "section alongside it, then set each base_url/api_key to the real API key from "
            "Settings > General in that app's web UI and http://radarr:7878 / http://sonarr:8989 "
            "before it can sync anything."
        )

    if "readarr" in enabled_service_keys(config):

        warnings.append(
            "Readarr is pinned to a pre-release nightly build (lscr.io/linuxserver/readarr:0.4.19-nightly) "
            "since the project has never cut a stable release and LinuxServer's floating develop/nightly "
            "tags are currently dead - expect rougher edges than the rest of the stack. Recyclarr does not "
            "support Readarr, so its config isn't synced by Recyclarr even if you have it enabled."
        )

    if "traefik" in enabled_service_keys(config) and config.domain:

        warnings.append(
            f"Traefik is configured to route *.{config.domain} to your services, but Vulcan "
            f"doesn't create any DNS records for you - point each subdomain (e.g. "
            f"jellyfin.{config.domain}) at this host yourself. HTTPS uses Traefik's own "
            f"self-signed certificate by default (browsers will warn on first visit) - "
            f"Vulcan doesn't configure Let's Encrypt/ACME."
        )

        if "gluetun" in enabled_service_keys(config):

            warnings.append(
                "qBittorrent isn't routed through Traefik - it shares Gluetun's network "
                "namespace (network_mode: service:gluetun), which Traefik's Docker service "
                "discovery can't reliably resolve. Access it directly instead."
            )

    if config.gpu_vendor == "nvidia":

        warnings.append(
            "NVIDIA hardware transcoding requires the nvidia-container-toolkit "
            "to be installed and registered with Docker on this host - Vulcan "
            "doesn't install it automatically."
        )

    return {
        "success": True,
        "compose_path": str(compose_path),
        "env_path": str(env_path),
        "warnings": warnings
    }
