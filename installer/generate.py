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
import secrets
from dataclasses import dataclass, field
from datetime import datetime
from datetime import timezone as dt_timezone
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader

from installer.auth import generate_authelia_secrets
from installer.detect import detect_host_ip, detect_render_group_gid
from installer.services import resource_limits_for
from installer.tiers import ALL_SERVICES, TIERS, TierDefinition


TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
STACK_DIR = Path("stack")
STATE_FILENAME = ".vulcan-state.json"

# Raw GitHub URL, not a mkdocs/GitHub Pages site - no such site exists yet
# for this project, and standing one up (a docs build, CI workflow, Pages
# config) is a separate real decision, not implied by adding a doc file.
# A raw blob URL renders as real Markdown in-browser (GitHub does that
# automatically) and needs no extra infrastructure, so every link below
# points here until/unless a real docs site is built.
WALKTHROUGH_URL = "https://github.com/Cyb3rRon1n/vulcan/blob/main/docs/walkthrough.md"

# CrowdSec's own acquis.yaml, telling it what log to read and how to
# label it - real content confirmed against the crowdsec-bouncer-
# traefik-plugin's own example acquis.yaml, not guessed. Completely
# static (no per-install variable ever belongs in it - the log path is
# fixed by the compose template's own volume mount, not user-chosen),
# so this is a plain constant rather than a .j2 template like Decluttarr's
# config.yaml, which genuinely has per-install values to fill in.
_CROWDSEC_ACQUIS = "filenames:\n  - /var/log/traefik/access.log\nlabels:\n  type: traefik\n"

# Seeded once into config/homepage/widgets.yaml. `disk: /media` reads the
# media array (mounted read-only into the homepage container); without
# that mount the widget would report the container rootfs instead.
_HOMEPAGE_WIDGETS = (
    "- resources:\n"
    "    cpu: true\n"
    "    memory: true\n"
    "    disk: /media\n"
    "- search:\n"
    "    provider: duckduckgo\n"
    "    target: _blank\n"
)

# Every service with its own routable web UI - the single source of
# truth both Homepage's tile groups (below) and the Traefik template's
# per-service labels (templates/docker-compose.yml.j2) draw from,
# closing a real drift risk this project has hit before (the "17 known
# services" count going stale, twice - see CLAUDE.md). "traefik",
# "homepage", and "dashy" all appear here despite none of them routing/
# tiling itself the normal way: Traefik gets a tile (pointing at its own
# dashboard) but no per-service label block of its own, Homepage and
# Dashy each get a label block (routable like anything else) but no
# tile of themselves - two independent dashboards, neither self-tiling,
# same as Homepage never tiled itself before Dashy existed. So each
# consumer below derives its own view by excluding just itself -
# WEB_FACING_SERVICES - {"traefik"} is exactly the set of services with
# a `{% if 'traefik' in enabled and domain %}` label block in the
# template, and WEB_FACING_SERVICES - {"homepage", "dashy"} is exactly
# the flat union of _HOMEPAGE_GROUPS's values - both checked by
# tests/test_generate.py so the two can't silently drift apart again.
WEB_FACING_SERVICES: frozenset[str] = frozenset({
    "jellyfin", "radarr", "sonarr", "prowlarr", "qbittorrent", "sabnzbd",
    "seerr", "bazarr", "lidarr", "readarr", "maintainerr", "authelia",
    "uptime-kuma", "traefik", "homepage", "metube", "downtify", "vaultwarden",
    "dashy", "filebrowser", "sportarr", "tracearr", "threadfin", "portainer",
    "adguardhome",
})

# Services that require admin-group membership when Authelia RBAC is active.
# Jellyfin and Seerr are deliberately excluded: Jellyfin because
# forward-auth breaks native apps (jellyfin/jellyfin#16956), Seerr
# because it's the media request UI that non-admin users need to access.
# Authelia itself is always accessible for login. Vaultwarden is excluded
# for the same native-app reason as Jellyfin.
ADMIN_ONLY_SERVICES: frozenset[str] = frozenset({
    "radarr", "sonarr", "prowlarr", "qbittorrent", "sabnzbd",
    "bazarr", "lidarr", "readarr", "maintainerr", "traefik",
    "homepage", "dashy", "metube", "downtify", "uptime-kuma",
    "netdata", "vaultwarden", "decluttarr", "recyclarr", "filebrowser",
})

# Homepage tile groups - grouping/ordering is presentation-specific and
# stays hand-written, but its flattened membership is cross-checked
# against WEB_FACING_SERVICES above by test_generate.py.
_HOMEPAGE_GROUPS: dict[str, list[str]] = {
    "Media": ["jellyfin", "seerr"],
    "Media Management": ["radarr", "sonarr", "lidarr", "readarr", "prowlarr", "bazarr", "maintainerr", "sportarr"],
    "Downloads": ["qbittorrent", "sabnzbd", "metube", "downtify"],
    "Live TV": ["threadfin"],
    "Monitoring": ["uptime-kuma", "tracearr", "netdata"],
    "Security": ["authelia", "vaultwarden"],
    "Infrastructure": ["traefik", "filebrowser", "portainer", "adguardhome"],
}

_HOMEPAGE_PORTS: dict[str, int] = {
    "jellyfin": 8096,
    "radarr": 7878,
    "sonarr": 8989,
    "prowlarr": 9696,
    "qbittorrent": 8080,
    "sabnzbd": 8081,
    "seerr": 5055,
    "bazarr": 6767,
    "lidarr": 8686,
    "readarr": 8787,
    "uptime-kuma": 3001,
    "homepage": 3000,
    "authelia": 9091,
    "maintainerr": 6246,
    "metube": 8081,
    "downtify": 8000,
    "vaultwarden": 8222,
    "dashy": 4000,
    "filebrowser": 8082,
    "pihole": 8053,
    "sportarr": 1867,
    "tracearr": 3002,
    "threadfin": 34400,
    "portainer": 9000,
    "adguardhome": 3000,
    "recyclarr": 9898,
    "decluttarr": 9899,
    "flaresolverr": 8191,
    "netdata": 19999,
    "watchtower": 8080,
    "gluetun": 8888,
    "tailscale": 41641,
    "cloudflared": 8080,
    "crowdsec": 8080,
    # Deliberately no "traefik" entry - its dashboard has no
    # independent host-published port (see _service_href()'s
    # api.insecure security note), so it has no non-routed fallback
    # the way every other service here does.
}

# One real, plain-language sentence per service - gethomepage.dev's own
# documented `description:` field, shown under the tile name so a tile
# is identifiable by what it does, not just its (sometimes opaque, e.g.
# "Prowlarr") name. Covers every key that can ever appear in
# _HOMEPAGE_GROUPS above - a KeyError here means a group was extended
# without adding the matching description, same "every real key stays
# in sync" discipline _HOMEPAGE_PORTS already follows.
_HOMEPAGE_DESCRIPTIONS: dict[str, str] = {
    "jellyfin": "Stream your movies, TV, and music",
    "seerr": "Request new movies and shows",
    "radarr": "Automatically finds and manages your movie library",
    "sonarr": "Automatically finds and manages your TV library",
    "lidarr": "Automatically finds and manages your music library",
    "readarr": "Automatically finds and manages your book library",
    "prowlarr": "Indexer manager shared by every *arr app",
    "bazarr": "Automatically finds and manages subtitles",
    "qbittorrent": "Torrent download client",
    "sabnzbd": "Usenet download client",
    "uptime-kuma": "Uptime monitoring for your services",
    "authelia": "Login protecting every routed service",
    "traefik": "Reverse proxy routing and dashboard",
    "maintainerr": "Automatically cleans up unwatched or unwanted media",
    "metube": "Download videos from YouTube, Facebook, and hundreds of other sites straight into your library",
    "downtify": "Download Spotify tracks/playlists straight into your library",
    "netdata": "Real-time CPU, RAM, disk, network, and temperature monitoring",
    "vaultwarden": "Password manager for every service login this stack creates",
    "filebrowser": "Web-based file manager for browsing and managing your media folders",
    "pihole": "DNS-level ad blocker with recursive DNS resolver (Unbound)",
    "sportarr": "Sports PVR - monitors leagues, downloads events, organizes into your media library",
    "tracearr": "Real-time stream analytics for Jellyfin/Plex/Emby (Tautulli/Jellystat replacement)",
    "threadfin": "M3U/IPTV proxy - emulates HDHomeRun tuner for Jellyfin/Plex/Emby live TV",
    "portainer": "Container management UI - deploy, monitor, and manage Docker containers",
    "adguardhome": "Network-wide ad blocking & DNS filtering with per-client stats",
    "recyclarr": "TRaSH Guides sync for Radarr/Sonarr",
    "decluttarr": "Download queue cleanup for Radarr/Sonarr",
    "flaresolverr": "CAPTCHA solver for indexers",
    "watchtower": "Automatic container updates",
    "gluetun": "VPN client for WireGuard/OpenVPN",
    "tailscale": "Private network mesh VPN",
    "cloudflared": "Cloudflare Tunnel for secure remote access",
    "crowdsec": "Intrusion protection for your services",
    "homepage": "Homarr dashboard - customizable start page for all your services",
    "dashy": "Dashy dashboard - beautiful, customizable service dashboard",
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
    auth_username: str | None = None
    auth_password_hash: str | None = None
    auth_users: list[dict] = field(default_factory=list)
    cloudflare_dns: bool = False
    cloudflare_email: str | None = None
    port_overrides: dict[str, int] = field(default_factory=dict)
    homepage_private: bool = False
    dashy_private: bool = False
    # VPN (gluetun) configuration
    vpn_service_provider: str | None = None
    vpn_type: str | None = None
    wireguard_private_key: str | None = None
    wireguard_addresses: str | None = None
    openvpn_user: str | None = None
    openvpn_password: str | None = None


def resolve_ports(config: GenerationConfig) -> dict[str, int]:
    """
    _HOMEPAGE_PORTS is already the single real registry of every
    service's default host port (used for Homepage tiles/the
    post-start summary/the Uptime Kuma reference) - port remapping
    reuses it rather than inventing a second table that could drift
    out of sync. config.port_overrides wins per-key when present; a
    conflict-remediation flow (CLI/TUI) is the only real caller that
    ever sets it. Deliberately no "traefik" key - see _HOMEPAGE_PORTS's
    own comment for why it was never in that table to begin with, and
    80/443 aren't safely remappable the same way (Let's Encrypt HTTP-01
    assumptions, and every routed https://service.domain URL scheme
    already assumes standard ports).
    """

    return {**_HOMEPAGE_PORTS, **config.port_overrides}


def _detect_port_conflicts() -> dict[str, int] | None:
    """
    Scans _HOMEPAGE_PORTS for duplicate port values (two services
    configured to use the same host port) and returns a
    port_overrides dict remapping the second-occurring service to
    the next available port above 3000, so the generated compose
    file never has two services binding to the same port. Returns
    None when there are no conflicts.
    """

    port_to_service: dict[int, str] = {}
    conflicts: dict[str, int] = {}

    for service, port in _HOMEPAGE_PORTS.items():
        if port in port_to_service:
            conflicts[service] = port
        else:
            port_to_service[port] = service

    if not conflicts:
        return None

    overrides: dict[str, int] = {}
    used_ports = set(_HOMEPAGE_PORTS.values())

    for service, port in sorted(conflicts.items(), key=lambda item: list(_HOMEPAGE_PORTS.keys()).index(item[0])):
        new_port = find_next_available_port(port, used_ports)
        if new_port is not None:
            overrides[service] = new_port
            used_ports.add(new_port)

    return overrides if overrides else None


def find_next_available_port(excluded_port: int, used_ports: set[int]) -> int | None:
    """
    Find the next available port starting from excluded_port + 1,
    skipping any already in use. No leading underscore (unlike most of
    this module's helpers) because cli.py needs it directly for live
    conflict resolution against another host process, not just this
    module's own self-contained default-table dedup.
    """

    port = excluded_port + 1
    max_port = 65535

    while port <= max_port:
        if port not in used_ports:
            return port
        port += 1

    return None


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


def save_state(
    config: GenerationConfig, output_dir: Path, warnings: list[str] | None = None
) -> None:

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
        "cloudflare_dns": config.cloudflare_dns,
        "cloudflare_email": config.cloudflare_email,
        "port_overrides": config.port_overrides,
        "homepage_private": config.homepage_private,
        "dashy_private": config.dashy_private,
        # Only ever the *last* generate's warnings, not accumulated
        # across regenerates - `vulcan install-summary` reads this back
        # to show them once, in "Setup Complete", instead of them
        # scrolling by live under a whiptail progress panel. Empty list
        # (not omitted) when write_stack() hasn't finished computing
        # them yet - see write_stack()'s own second save_state() call.
        "warnings": warnings if warnings is not None else [],
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


def _homepage_allowed_hosts(config: GenerationConfig, enabled: set[str], host_ip: str | None) -> str:
    """
    Recent Homepage images reject any request whose Host header isn't
    explicitly allowlisted (HOMEPAGE_ALLOWED_HOSTS) - found by actually
    starting a real container against a generated config, not assumed;
    without this, Homepage refuses every request outright regardless of
    how it's reached. Covers every real way Vulcan itself can put
    Homepage in front of a user: the bare host-published port (both
    "localhost" for local access and the real detected LAN IP for
    another device on the network), plus the routed Traefik hostname
    when domain routing is active.
    """

    hosts = ["localhost:3000"]

    if host_ip:
        hosts.append(f"{host_ip}:3000")

    if "traefik" in enabled and config.domain and not config.homepage_private:
        hosts.append(f"homepage.{config.domain}")

    return ",".join(hosts)


def render_compose(config: GenerationConfig, host_ip: str | None = None) -> str:

    template = _jinja_env().get_template("docker-compose.yml.j2")
    enabled = enabled_service_keys(config)

    return template.render(
        enabled=enabled,
        limits=resource_limits_for(config.tier.name),
        gpu_vendor=config.gpu_vendor,
        render_gid=(
            detect_render_group_gid() if config.gpu_vendor in ("amd", "intel") else None
        ),
        domain=config.domain,
        homepage_allowed_hosts=_homepage_allowed_hosts(config, enabled, host_ip),
        homepage_private=config.homepage_private,
        dashy_private=config.dashy_private,
        cloudflare_dns=config.cloudflare_dns,
        cloudflare_email=config.cloudflare_email,
        tunnel_entrypoints=",tunnel" if "cloudflared" in enabled else "",
        ports=resolve_ports(config)
    )


def render_env(
    config: GenerationConfig,
    vpn_service_provider: str = "changeme",
    vpn_type: str = "wireguard",
    wireguard_private_key: str = "changeme",
    wireguard_addresses: str = "",
    tailscale_authkey: str = "changeme",
    cloudflare_dns_api_token: str = "changeme",
    cloudflare_acme_email: str = "changeme@example.com",
    vaultwarden_admin_token: str | None = None,
    vaultwarden_signups_allowed: str = "true",
    crowdsec_bouncer_key: str | None = None,
    tunnel_token: str = "changeme",
    pihole_webpassword: str | None = None
) -> str:

    template = _jinja_env().get_template("env.j2")
    enabled = enabled_service_keys(config)

    return template.render(
        media_path=config.media_path,
        puid=config.puid,
        pgid=config.pgid,
        timezone=config.timezone,
        # Real, pre-existing bug fixed here: this used to check
        # config.enabled_optional directly, which custom mode never
        # populates (custom mode uses config.custom_services instead -
        # see enabled_service_keys()) - a custom-mode stack with
        # Gluetun enabled rendered a compose file referencing
        # ${VPN_SERVICE_PROVIDER}/etc. that .env never actually
        # defined. enabled_service_keys(config) is correct for both
        # the tier+enabled_optional path and the custom_services path,
        # matching what render_compose() already uses.
        gluetun_enabled="gluetun" in enabled,
        vpn_service_provider=vpn_service_provider,
        vpn_type=vpn_type,
        wireguard_private_key=wireguard_private_key,
        wireguard_addresses=wireguard_addresses,
        tailscale_enabled="tailscale" in enabled,
        tailscale_authkey=tailscale_authkey,
        cloudflare_dns_enabled=config.cloudflare_dns,
        cloudflare_dns_api_token=cloudflare_dns_api_token,
        cloudflare_acme_email=cloudflare_acme_email,
        vaultwarden_enabled="vaultwarden" in enabled,
        # Unlike Gluetun/Tailscale/Cloudflare's credentials, Vulcan can
        # generate a real admin token itself instead of a "changeme"
        # placeholder - same reasoning as Authelia's own JWT_SECRET/
        # SESSION_SECRET (installer/auth.py's generate_authelia_secrets).
        vaultwarden_admin_token=vaultwarden_admin_token or secrets.token_hex(32),
        vaultwarden_signups_allowed=vaultwarden_signups_allowed,
        crowdsec_enabled="crowdsec" in enabled,
        # Same reasoning as vaultwarden_admin_token above: this is a
        # shared secret between Traefik's bouncer plugin and CrowdSec's
        # own BOUNCER_KEY_TRAEFIK env var (which self-registers the
        # bouncer - no manual `cscli bouncers add` step needed), not a
        # credential for an external service, so Vulcan can generate a
        # real value instead of a "changeme" placeholder.
        crowdsec_bouncer_key=crowdsec_bouncer_key or secrets.token_hex(32),
        cloudflared_enabled="cloudflared" in enabled,
        tunnel_token=tunnel_token,
        pihole_enabled="pihole" in enabled,
        pihole_webpassword=pihole_webpassword or secrets.token_hex(16)
    )


def _service_href(key: str, config: GenerationConfig, host_ip: str | None) -> str | None:

    if key == "netdata":

        # network_mode: host (see the compose template) - never routed
        # through Traefik (no Docker-network identity for its provider
        # to discover) and never remappable via port_overrides (the
        # image binds 19999 directly on the host, not a `ports:`
        # mapping Vulcan renders) - always a direct host-port link,
        # unconditionally, unlike every other service's routed/
        # host-port branching below.
        return f"http://{host_ip or 'localhost'}:19999"

    enabled = enabled_service_keys(config)

    # qBittorrent's own Traefik labels are skipped whenever Gluetun is
    # active (network_mode: service:gluetun has no network identity of
    # its own for Traefik's Docker provider to discover - see the
    # compose template) - a real, qbittorrent-specific exception to
    # the otherwise-generic "routed" rule below. Found and fixed while
    # adding the Traefik dashboard tile: this exception was missing
    # here even though the compose template itself already has it, so
    # a Gluetun + qBittorrent + Traefik + domain combination
    # previously generated a real dead link (a 404, no matching
    # router) instead of the working host-port fallback qBittorrent
    # actually has through Gluetun's own static port mapping.
    qbittorrent_via_gluetun = key == "qbittorrent" and "gluetun" in enabled

    # A direct user request: Homepage (and only Homepage) stays off the
    # public routed set even with Traefik+domain active for every other
    # service - the point is that a stranger who reaches the bare
    # domain lands on Jellyfin, not a dashboard listing every other
    # service running. Still reachable via its own host-published port
    # (Tailscale/LAN), just never gets a public homepage.<domain> route.
    homepage_kept_private = key == "homepage" and config.homepage_private

    # Same reasoning, same opt-out-by-default question, for Dashy -
    # a second dashboard means a second "shouldn't be the thing a
    # stranger lands on" decision, asked independently of Homepage's.
    dashy_kept_private = key == "dashy" and config.dashy_private

    routed = (
        "traefik" in enabled and config.domain
        and not qbittorrent_via_gluetun and not homepage_kept_private and not dashy_kept_private
    )

    if routed:
        return f"https://{key}.{config.domain}"

    ports = resolve_ports(config)

    if key not in ports:

        # No non-routed fallback exists for this service - e.g.
        # Traefik's own dashboard, which is only ever reachable
        # through Traefik's routing itself, never a plain host port
        # (see the "--api.insecure=true" security note this project
        # deliberately avoided).
        return None

    return f"http://{host_ip or 'localhost'}:{ports[key]}"


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

            if href is None:
                continue

            items.append({
                display_names[key]: {
                    "href": href,
                    "icon": f"{key}.png",
                    "description": _HOMEPAGE_DESCRIPTIONS[key]
                }
            })

        if items:
            groups.append({group_name: items})

    # Always present, regardless of what's enabled - documentation, not
    # a service with an enabled/disabled state. Points at the real
    # walkthrough doc in the repo (a raw GitHub URL - GitHub renders
    # Markdown blobs in-browser automatically, no mkdocs/Pages site
    # needed for this to work today).
    groups.append({
        "Guides": [{
            "Setup Walkthrough": {
                "href": WALKTHROUGH_URL,
                "icon": "github.png",
                "description": "Suggested order to configure every service after install"
            }
        }]
    })

    return yaml.safe_dump(groups, sort_keys=False)


def render_dashy_config(config: GenerationConfig, host_ip: str | None) -> str:
    """
    Dashy's second-dashboard-alongside-Homepage counterpart to
    render_homepage_services() - a direct owner request for the same
    real pre-seeded-tile treatment Homepage already gets, not a lesser
    second-class option. Reuses the exact same _HOMEPAGE_GROUPS/
    _HOMEPAGE_DESCRIPTIONS tables (one real source of truth for what
    each service's tile says, not two that could drift apart) - only
    the output shape differs, since Dashy's real config schema
    (confirmed by reading a real container's own default
    /app/user-data/conf.yml, not assumed from docs) is `sections: [{name,
    icon, items: [{title, description, url, icon}]}]`, not Homepage's
    `[{group: [{title: {href, icon, description}}]}]`. `icon: favicon`
    is a real, documented Dashy feature (auto-fetches each site's own
    favicon) - used here instead of Homepage's dashboard-icons pack
    filenames, which Dashy doesn't read the same way.
    """

    enabled = enabled_service_keys(config)
    display_names = {service.key: service.display_name for service in ALL_SERVICES}

    sections = []

    for group_name, keys in _HOMEPAGE_GROUPS.items():

        items = []

        for key in keys:

            if key not in enabled:
                continue

            href = _service_href(key, config, host_ip)

            if href is None:
                continue

            items.append({
                "title": display_names[key],
                "description": _HOMEPAGE_DESCRIPTIONS[key],
                "url": href,
                "icon": "favicon"
            })

        if items:
            sections.append({"name": group_name, "items": items})

    sections.append({
        "name": "Guides",
        "items": [{
            "title": "Setup Walkthrough",
            "description": "Suggested order to configure every service after install",
            "url": WALKTHROUGH_URL,
            "icon": "favicon"
        }]
    })

    return yaml.safe_dump({
        "pageInfo": {"title": "Vulcan"},
        "appConfig": {"theme": "colorful"},
        "sections": sections
    }, sort_keys=False)


def render_authelia_users_database(
    username: str, displayname: str, password_hash: str,
    additional_users: list[dict] | None = None
) -> str:

    users = {
        username: {
            "disabled": False,
            "displayname": displayname,
            "password": password_hash,
            "email": f"{username}@localhost",
            "groups": ["admin"]
        }
    }

    for user in (additional_users or []):
        users[user["username"]] = {
            "disabled": False,
            "displayname": user.get("displayname", user["username"]),
            "password": user["password_hash"],
            "email": f"{user['username']}@localhost",
            "groups": user.get("groups", ["media"])
        }

    return yaml.safe_dump({"users": users}, sort_keys=False)


def render_authelia_configuration(config: GenerationConfig, host_ip: str | None) -> str:

    template = _jinja_env().get_template("authelia-configuration.yml.j2")

    cookie_domain = config.domain or host_ip or "127.0.0.1"

    enabled = enabled_service_keys(config)
    admin_only = sorted(ADMIN_ONLY_SERVICES & enabled) if config.domain else []

    return template.render(
        domain=config.domain,
        cookie_domain=cookie_domain,
        homepage_enabled="homepage" in enabled,
        admin_only_services=admin_only
    )

    # Authelia's own config validator fatally rejects a session cookie
    # domain that isn't a real domain (needs a period) or a real IP address -
    # rendering config.domain verbatim produced a literal "domain: 'None'"
    # whenever Authelia was enabled without one configured, which crash-loops
    # instead of the "starts but does nothing useful" the write_stack()
    # warning promises. Falling back to the real detected host IP (or the
    # loopback address if even that's unavailable) is a valid cookie domain
    # either way, so the container genuinely starts - it just can't be
    # reached usefully without Traefik + a real domain, same as documented.
    cookie_domain = config.domain or host_ip or "127.0.0.1"

    return template.render(
        domain=config.domain,
        cookie_domain=cookie_domain,
        homepage_enabled="homepage" in enabled_service_keys(config)
    )


def render_decluttarr_config(config: GenerationConfig) -> str:

    template = _jinja_env().get_template("decluttarr-config.yaml.j2")
    enabled = enabled_service_keys(config)

    return template.render(
        enabled=enabled,
        # Decluttarr's own config schema has no environment-variable
        # substitution mechanism (confirmed by reading the real,
        # current config_example.yaml directly, not assumed - api_key
        # values are always literal strings) - so unlike every other
        # credential in this project, a real key can't live in .env.
        # qBittorrent specifically needs its real container DNS name
        # when Gluetun owns its network namespace (network_mode:
        # service:gluetun), same reasoning _service_href() already
        # applies for Homepage - "qbittorrent" isn't a resolvable
        # hostname on the Docker network in that case, "gluetun" is.
        qbittorrent_base_url=(
            "http://gluetun:8080" if "gluetun" in enabled else "http://qbittorrent:8080"
        )
    )


def _uptime_kuma_reference(config: GenerationConfig, host_ip: str | None) -> str:

    enabled = enabled_service_keys(config)
    display_names = {service.key: service.display_name for service in ALL_SERVICES}

    lines = [
        f"  {display_names[key]}: {href}"
        for keys in _HOMEPAGE_GROUPS.values()
        for key in keys
        if key in enabled and key != "uptime-kuma"
        for href in [_service_href(key, config, host_ip)]
        if href is not None
    ]

    kuma_href = _service_href("uptime-kuma", config, host_ip)

    return (
        f"Uptime Kuma needs one-time setup: visit {kuma_href}, create an account, "
        "then add a monitor for each service you want to track. Your enabled services:\n"
        + "\n".join(lines)
    )


def render_stack_summary(config: GenerationConfig, host_ip: str | None) -> str:

    enabled = enabled_service_keys(config)
    display_names = {service.key: service.display_name for service in ALL_SERVICES}

    lines = []
    # A service can appear in more than one _HOMEPAGE_GROUPS bucket
    # (radarr in Events + Media Processing, gluetun in Network +
    # Infrastructure, ...), and homepage/dashy are emitted explicitly
    # below as well as sitting in a group - list each exactly once.
    seen: set[str] = set()

    if "homepage" in enabled:
        lines.append(f"  Homepage (dashboard): {_service_href('homepage', config, host_ip)}")
        seen.add("homepage")

    if "dashy" in enabled:
        lines.append(f"  Dashy (dashboard): {_service_href('dashy', config, host_ip)}")
        seen.add("dashy")

    for keys in _HOMEPAGE_GROUPS.values():
        for key in keys:
            if key in enabled and key not in seen:
                lines.append(f"  {display_names[key]}: {_service_href(key, config, host_ip)}")
                seen.add(key)

    return "\n".join(lines)


def render_setup_order(config: GenerationConfig, host_ip: str | None) -> str:
    """
    A dependency-ordered "what to configure first" walkthrough, built
    from only the services this stack actually has enabled - real
    sequencing advice, not render_stack_summary()'s flat link list
    reordered. Config order matters here: Prowlarr's indexers before
    the *arr apps that query it, a working download client before
    anything expects one, Jellyfin's libraries before Seerr can
    request into them, dashboards last since they've nothing to show
    until everything above them is already running. Steps are numbered
    dynamically (not hardcoded "1./2./3.") so skipping a disabled
    service's step never leaves a gap in the sequence.
    """

    enabled = enabled_service_keys(config)
    display_names = {service.key: service.display_name for service in ALL_SERVICES}
    steps = []

    if "vaultwarden" in enabled:

        steps.append(
            f"Vaultwarden ({_service_href('vaultwarden', config, host_ip)}): create your "
            "account first - save every login below here as you create it, so nothing gets "
            "lost."
        )

    if "authelia" in enabled:

        steps.append(
            "Authelia: your admin login was already created during install - save it in "
            "Vaultwarden now if you enabled it above."
        )

    if "prowlarr" in enabled:

        steps.append(
            f"Prowlarr ({_service_href('prowlarr', config, host_ip)}): add your indexers "
            "first - Radarr/Sonarr/Lidarr/Readarr all query through it, so nothing else can "
            "search until this is done."
        )

    arr_apps = [key for key in ("radarr", "sonarr", "lidarr", "readarr") if key in enabled]

    if arr_apps:

        arr_list = ", ".join(
            f"{display_names[key]} ({_service_href(key, config, host_ip)})" for key in arr_apps
        )
        steps.append(
            f"{arr_list}: connect each to Prowlarr (Settings > Indexers) and set root "
            "folders, then save each app's own API key (Settings > General) into Vaultwarden."
        )

    download_clients = [key for key in ("qbittorrent", "sabnzbd") if key in enabled]

    if download_clients:

        dl_list = ", ".join(display_names[key] for key in download_clients)
        steps.append(
            f"{dl_list}: set a real login (not the image's default) and connect it to each "
            "*arr app above (Settings > Download Clients)."
        )

    if "gluetun" in enabled:

        steps.append(
            "Gluetun: if qBittorrent's web UI won't load at all (connection refused), "
            "this is why - Gluetun's firewall acts as a kill switch and blocks ALL "
            "traffic through it, including qBittorrent's own WebUI port, until the VPN "
            "actually connects. With the default VPN_SERVICE_PROVIDER/WIREGUARD_PRIVATE_KEY "
            "placeholders still in stack/.env, it never will. Set real VPN credentials, "
            "then check `docker compose logs gluetun` to confirm it connected."
        )

    if "bazarr" in enabled:

        steps.append(
            f"Bazarr ({_service_href('bazarr', config, host_ip)}): connect it to "
            "Radarr/Sonarr for subtitles once they have content to work with."
        )

    if "jellyfin" in enabled:

        authelia_note = (
            " - it's deliberately not behind Authelia even though other services are (see "
            "the warning above), so this is its real protection"
            if "authelia" in enabled else ""
        )
        steps.append(
            f"Jellyfin ({_service_href('jellyfin', config, host_ip)}): create libraries "
            "pointed at your media folders, then enable its own built-in two-factor "
            f"authentication (Dashboard > My Profile){authelia_note}."
        )

    if "seerr" in enabled:

        steps.append(
            f"Seerr ({_service_href('seerr', config, host_ip)}): connect it to "
            "Jellyfin and Radarr/Sonarr so requests can actually be fulfilled."
        )

    automation = [key for key in ("recyclarr", "decluttarr", "maintainerr") if key in enabled]

    if automation:

        auto_list = ", ".join(display_names[key] for key in automation)
        steps.append(
            f"{auto_list}: automation on top of the *arr apps - configure these last, once "
            "Radarr/Sonarr are already working correctly."
        )

    downloaders = [key for key in ("metube", "downtify") if key in enabled]

    if downloaders:

        dl_list = ", ".join(
            f"{display_names[key]} ({_service_href(key, config, host_ip)})" for key in downloaders
        )
        steps.append(
            f"{dl_list}: point a Jellyfin library at their download folders (see the "
            "warnings above for exact paths)."
        )

    dashboards = [
        key for key in ("homepage", "dashy", "uptime-kuma", "netdata", "traefik") if key in enabled
    ]

    if dashboards:

        steps.append(
            "Homepage/Dashy/Uptime Kuma/Netdata/Traefik dashboard: check these last - they "
            "only have something to show once the services above are actually running."
        )

    if not steps:
        return ""

    numbered = "\n".join(f"{index}. {step}" for index, step in enumerate(steps, start=1))

    return (
        "Suggested setup order (do these roughly in sequence - later steps depend on "
        f"earlier ones being done first):\n{numbered}"
        f"\n\nFull walkthrough with more detail: {WALKTHROUGH_URL}"
    )


def write_stack(config: GenerationConfig, output_dir: Path = STACK_DIR) -> dict:

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    compose_path = output_dir / "docker-compose.yml"
    env_path = output_dir / ".env"

    # Computed once, up front - render_compose() needs it now too
    # (HOMEPAGE_ALLOWED_HOSTS), not just the warnings/Homepage-tile
    # logic further down that already used to be its first use.
    host_ip = detect_host_ip()

    # Auto-resolve port conflicts before generating the compose file -
    # if two services (e.g. SABnzbd + MeTube) are configured to use the
    # same host port, remap the second-occurring one to the next available
    # port so the generated stack never fails on `docker compose up -d`
    # with "Bind for ... port is already allocated".
    conflicts = _detect_port_conflicts()
    if conflicts is not None:
        config.port_overrides = conflicts

    # Read any existing .env before it gets overwritten - a real Gluetun
    # VPN credential the user already filled in must survive a regenerate,
    # not get reset back to a placeholder.
    env_content = render_env(
        config,
        vpn_service_provider=_preserved_vpn_value(output_dir, "VPN_SERVICE_PROVIDER", "changeme"),
        vpn_type=_preserved_vpn_value(output_dir, "VPN_TYPE", "wireguard"),
        wireguard_private_key=_preserved_vpn_value(output_dir, "WIREGUARD_PRIVATE_KEY", "changeme"),
        wireguard_addresses=_preserved_vpn_value(output_dir, "WIREGUARD_ADDRESSES", ""),
        tailscale_authkey=_preserved_vpn_value(output_dir, "TS_AUTHKEY", "changeme"),
        cloudflare_dns_api_token=_preserved_vpn_value(output_dir, "CF_DNS_API_TOKEN", "changeme"),
        cloudflare_acme_email=_preserved_vpn_value(
            output_dir, "CLOUDFLARE_ACME_EMAIL", config.cloudflare_email or "changeme@example.com"
        ),
        # None (not a placeholder default) so render_env() only
        # generates a fresh random token when .env genuinely has none
        # yet - a real existing token, or a user's own turned-off
        # signups, must survive a regenerate the same way Gluetun's
        # real VPN credentials already do above.
        vaultwarden_admin_token=(
            _preserved_vpn_value(output_dir, "VAULTWARDEN_ADMIN_TOKEN", "") or None
        ),
        vaultwarden_signups_allowed=_preserved_vpn_value(
            output_dir, "VAULTWARDEN_SIGNUPS_ALLOWED", "true"
        ),
        crowdsec_bouncer_key=(
            _preserved_vpn_value(output_dir, "CROWDSEC_BOUNCER_KEY", "") or None
        ),
        tunnel_token=_preserved_vpn_value(output_dir, "TUNNEL_TOKEN", "changeme"),
        pihole_webpassword=(
            _preserved_vpn_value(output_dir, "PIHOLE_WEBPASSWORD", "") or None
        )
    )

    compose_path.write_text(render_compose(config, host_ip))
    env_path.write_text(env_content)
    save_state(config, output_dir)

    for key in enabled_service_keys(config):
        (output_dir / "config" / key).mkdir(parents=True, exist_ok=True)

    if "pihole" in enabled_service_keys(config):

        unbound_dir = output_dir / "config" / "pihole" / "unbound"
        unbound_dir.mkdir(parents=True, exist_ok=True)

        # klutchell/unbound listens on :53 out of the box. pihole runs in
        # unbound's network namespace (network_mode: service:unbound) and
        # pihole-FTL also wants :53 - so without this, FTL fails to bind
        # ("failed to create listening socket for port 53: Address in
        # use") and DNS is dead. The compose env already points pihole's
        # upstream at 127.0.0.1#5335; this is the other half. The image's
        # own unbound.conf `include`s custom.conf.d/*.conf, and `port:`
        # is last-wins, so this file alone moves it. Written once - a
        # hand-edited override survives a regenerate.
        unbound_conf = unbound_dir / "99-pihole-port.conf"

        if not unbound_conf.exists():
            unbound_conf.write_text("server:\n    port: 5335\n")

    if config.cloudflare_dns and "traefik" in enabled_service_keys(config):

        # Traefik requires acme.json to be mode 600, and refuses to
        # start (or silently can't obtain certs) if it's more open
        # than that - a well-documented real gotcha, not obscure.
        # Docker auto-creating a missing bind-mounted *file* is a
        # separate known trap this sidesteps entirely: this reuses the
        # existing ./config/traefik directory mount rather than a
        # dedicated acme.json file mount, so the directory always
        # exists by the time this runs. Only touched if missing -
        # never overwrite real, already-issued certificate data on a
        # regenerate.
        acme_path = output_dir / "config" / "traefik" / "acme.json"

        if not acme_path.exists():

            acme_path.write_text("{}")
            acme_path.chmod(0o600)

    media_path = Path(config.media_path)
    (media_path / "downloads").mkdir(parents=True, exist_ok=True)
    (media_path / "media" / "movies").mkdir(parents=True, exist_ok=True)
    (media_path / "media" / "tv").mkdir(parents=True, exist_ok=True)
    (media_path / "media" / "music").mkdir(parents=True, exist_ok=True)
    (media_path / "media" / "books").mkdir(parents=True, exist_ok=True)
    (media_path / "media" / "youtube").mkdir(parents=True, exist_ok=True)
    (media_path / "media" / "music" / "downtify").mkdir(parents=True, exist_ok=True)

    warnings = []

    if "homepage" in enabled_service_keys(config):

        services_yaml_path = output_dir / "config" / "homepage" / "services.yaml"

        if not services_yaml_path.exists():

            services_yaml_path.write_text(render_homepage_services(config, host_ip))

            warnings.append(
                "Homepage was pre-seeded with tiles for your enabled services at "
                "stack/config/homepage/services.yaml - edit it directly to customize "
                "further; Vulcan won't overwrite it on a later regenerate. Add "
                "per-service widgets (qBittorrent speeds, *arr queues) and API keys "
                "there; see docs/guides/homepage-widgets.md."
            )

        # A minimal top-of-page widget set: real host resources (disk
        # points at the media array via the /media:ro mount) + a search
        # box. Seeded once, never overwritten - same as services.yaml.
        widgets_yaml_path = output_dir / "config" / "homepage" / "widgets.yaml"

        if not widgets_yaml_path.exists():
            widgets_yaml_path.write_text(_HOMEPAGE_WIDGETS)

    if "dashy" in enabled_service_keys(config):

        dashy_config_path = output_dir / "config" / "dashy" / "conf.yml"

        if not dashy_config_path.exists():

            dashy_config_path.write_text(render_dashy_config(config, host_ip))

            warnings.append(
                "Dashy was pre-seeded with tiles for your enabled services at "
                "stack/config/dashy/conf.yml - edit it directly to customize further "
                "(themes, layout, more tiles); Vulcan won't overwrite it on a later "
                "regenerate. Runs as a fixed uid/gid 1000:1000 inside its container "
                "(no PUID/PGID support) - if your own PUID/PGID differ, you may need "
                "sudo to edit this file directly on the host."
            )

    if "uptime-kuma" in enabled_service_keys(config):
        warnings.append(_uptime_kuma_reference(config, host_ip))

    if "gluetun" in enabled_service_keys(config):

        # Real, pre-existing bug fixed here too, same root cause as
        # render_env()'s gluetun_enabled fix above: checking
        # config.enabled_optional directly meant a custom-mode stack
        # with Gluetun enabled never got this warning at all, even
        # though .env genuinely needed real credentials filled in.
        warnings.append(
            "Gluetun requires real VPN provider credentials in stack/.env "
            "before it will connect - see the TODO comments there."
        )

    if "tailscale" in enabled_service_keys(config):

        warnings.append(
            "Tailscale requires a real auth key in stack/.env (TS_AUTHKEY) before it will "
            "join your tailnet - generate one at "
            "https://login.tailscale.com/admin/settings/keys. Once connected, every "
            "host-published port in this stack (Jellyfin, Radarr, etc.) is reachable from "
            "any device on your tailnet at this host's Tailscale address, with no "
            "additional per-service setup."
        )

    if config.cloudflare_dns and not ("traefik" in enabled_service_keys(config) and config.domain):

        warnings.append(
            "Cloudflare DNS is enabled but Traefik isn't routing with a domain configured, "
            "so there's no certificate resolver actually in use - enable Traefik with a "
            "domain too for this to do anything."
        )

    elif config.cloudflare_dns:

        warnings.append(
            "Cloudflare DNS requires a real scoped API token in stack/.env "
            "(CF_DNS_API_TOKEN, needs Zone:DNS:Edit on your domain's zone) and a real "
            "contact email (CLOUDFLARE_ACME_EMAIL) before Traefik can request real "
            "Let's Encrypt certificates - see the TODO comments there. Until then, "
            "Traefik will fail to obtain a certificate and fall back to its self-signed "
            "default."
        )

    if "cloudflared" in enabled_service_keys(config) and "traefik" not in enabled_service_keys(config):

        warnings.append(
            "Cloudflare Tunnel is enabled but Traefik isn't - the tunnel has nothing to "
            "route to without it. Enable Traefik too."
        )

    elif "cloudflared" in enabled_service_keys(config):

        warnings.append(
            "Cloudflare Tunnel requires a real Tunnel token in stack/.env (TUNNEL_TOKEN) - "
            "create one at the Zero Trust dashboard's Networks > Tunnels > Create a tunnel > "
            "Docker tab. Then add a Public Hostname: subdomain '*' (or one per service), "
            "your domain, Service type HTTPS, URL 'traefik:8081', and under Additional "
            "application settings > TLS turn ON 'No TLS Verify' (Traefik serves its own "
            "self-signed cert on that entrypoint). HTTP (not HTTPS) 404s - every router "
            "requires TLS."
        )

        if config.domain and "authelia" in enabled_service_keys(config):

            warnings.append(
                f"After the tunnel is working, lock down admin endpoints in Zero Trust: "
                f"Access > Applications > Add an application for each management subdomain "
                f"(e.g. radarr.{config.domain}, homepage.{config.domain}) with an email OTP "
                f"or Google policy. Do NOT protect jellyfin.{config.domain} or "
                f"seerr.{config.domain} - native Jellyfin apps can't complete the "
                f"browser redirect, and Seerr uses Jellyfin's own auth. For family "
                f"access, create a second, hard-to-guess Jellyfin subdomain (e.g. "
                f"jellyfin-abc123.{config.domain}) with no Cloudflare Access policy."
            )

    if "traefik" in enabled_service_keys(config) and config.domain and "authelia" not in enabled_service_keys(config):

        warnings.append(
            f"Traefik's own dashboard is now reachable at https://traefik.{config.domain} "
            "with no login in front of it - enable Authelia too if you want that locked down, "
            "the same as every other routed service without it."
        )

    if "authelia" in enabled_service_keys(config):

        authelia_dir = output_dir / "config" / "authelia"
        generate_authelia_secrets(authelia_dir / "secrets")

        # Always regenerated, like docker-compose.yml itself - it is
        # fully derived from `config` (session cookie domain, authelia_url,
        # the per-service access_control rules, RBAC groups). Guarding it
        # with `if not exists()` meant a re-run that changed the domain
        # or the service list left Authelia rejecting every forward-auth
        # request ("no configured session cookie domain matches the url").
        # users_database.yml below stays guarded - that one holds real
        # hashed passwords a user may have hand-added.
        configuration_path = authelia_dir / "configuration.yml"
        rendered_authelia_config = render_authelia_configuration(config, host_ip)

        try:
            configuration_path.write_text(rendered_authelia_config)
        except PermissionError:
            # Authelia's official image runs as its own internal root and
            # can leave config/authelia/ root-owned - don't let one
            # un-writable file abort the whole regenerate (compose + .env
            # are already written). Warn loudly with the fix instead.
            if configuration_path.read_text() != rendered_authelia_config:
                warnings.append(
                    "Could not update stack/config/authelia/configuration.yml - it's "
                    "root-owned (Authelia's image runs as its own root). Authelia will "
                    "keep using the old domain/rules until you fix it: "
                    "`sudo chown -R $(id -u):$(id -g) stack/config/authelia` then "
                    "re-run the generate step."
                )

        users_database_path = authelia_dir / "users_database.yml"

        if not users_database_path.exists() and config.auth_username and config.auth_password_hash:

            users_database_path.write_text(
                render_authelia_users_database(
                    config.auth_username, config.auth_username, config.auth_password_hash,
                    additional_users=config.auth_users
                )
            )

        routed = "traefik" in enabled_service_keys(config) and config.domain

        if not routed:

            warnings.append(
                "Authelia is enabled but Traefik isn't routing with a domain configured, "
                "so nothing is actually protected and the login portal isn't reachable - "
                "Authelia will start but do nothing useful until Traefik and a domain are "
                "also enabled."
            )

        if config.auth_users and routed:

            warnings.append(
                f"Authelia RBAC is active: admin user '{config.auth_username}' has full access "
                f"to all services. {len(config.auth_users)} additional user(s) restricted to "
                "Jellyfin and Seerr only. Add more users by re-running with --auth-users "
                "or by editing stack/config/authelia/users_database.yml directly."
            )

    if "crowdsec" in enabled_service_keys(config):

        acquis_path = output_dir / "config" / "crowdsec" / "etc" / "acquis.yaml"

        if not acquis_path.exists():

            acquis_path.parent.mkdir(parents=True, exist_ok=True)
            acquis_path.write_text(_CROWDSEC_ACQUIS)

        routed = "traefik" in enabled_service_keys(config) and config.domain

        if not routed:

            warnings.append(
                "CrowdSec is enabled but Traefik isn't routing with a domain configured, so "
                "there's no traffic for it to protect yet - CrowdSec will start but block "
                "nothing until Traefik and a domain are also enabled."
            )

        else:

            warnings.append(
                "CrowdSec is watching Traefik's access log and will block IPs Traefik's "
                "bouncer plugin flags as malicious, on every routed service - including "
                "Jellyfin and Vaultwarden, which skip Authelia but not this. A real, "
                "randomly generated CROWDSEC_BOUNCER_KEY in stack/.env ties the two "
                "together automatically; nothing to fill in yourself. First requests after "
                "a fresh start may take a few seconds while CrowdSec finishes pulling its "
                "community blocklist collections. Traefik downloads the bouncer plugin from "
                "its own plugin catalog on first start (needs internet access, separate from "
                "the CrowdSec engine itself) - if requests aren't being filtered, check "
                "`docker compose logs traefik` for a \"Plugins are disabled\" error; this is "
                "a Traefik-side catalog issue, not something CrowdSec or Vulcan controls, and "
                "has been seen to fail even for Traefik's own official demo plugin. "
                "CrowdSec's own container has no PUID/PGID support - files under "
                "stack/config/crowdsec/ are root-owned, same as Authelia's and Dashy's."
            )

    if "sabnzbd" in enabled_service_keys(config):

        warnings.append(
            "SABnzbd needs your Usenet provider's server details entered through "
            "its own setup wizard on first login before it can download anything."
        )

    if "flaresolverr" in enabled_service_keys(config):

        warnings.append(
            "FlareSolverr needs no setup of its own, but nothing uses it until you "
            "wire it into Prowlarr: Settings > Indexers > add an Indexer Proxy > "
            "FlareSolverr, Host http://flaresolverr:8191/, give it a tag, then add "
            "that tag to each indexer that sits behind a Cloudflare challenge."
        )

    if "recyclarr" in enabled_service_keys(config):

        warnings.append(
            "Recyclarr will scaffold a starter config at stack/config/recyclarr/recyclarr.yml "
            "on first start with only a sonarr: section and placeholder values - add a radarr: "
            "section alongside it, then set each base_url/api_key to the real API key from "
            "Settings > General in that app's web UI and http://radarr:7878 / http://sonarr:8989 "
            "before it can sync anything."
        )

    if "decluttarr" in enabled_service_keys(config):

        decluttarr_config_path = output_dir / "config" / "decluttarr" / "config.yaml"

        if not decluttarr_config_path.exists():

            decluttarr_config_path.parent.mkdir(parents=True, exist_ok=True)
            decluttarr_config_path.write_text(render_decluttarr_config(config))

        warnings.append(
            "Decluttarr was pre-seeded with a starter config at "
            "stack/config/decluttarr/config.yaml - real base_urls are already filled in, but "
            "each api_key is a \"CHANGEME\" placeholder: edit the file directly and paste in "
            "the real API key from Settings > General in each app's own web UI before "
            "Decluttarr can connect. It starts in test_run: true (a dry run - nothing is "
            "actually removed) - flip that to false once you've confirmed the config is right."
        )

    if "maintainerr" in enabled_service_keys(config):

        # Unlike Decluttarr/Recyclarr, Maintainerr has no config file
        # for Vulcan to pre-seed at all - Plex/Jellyfin/Emby
        # credentials, Radarr/Sonarr API keys, and cleanup rules are
        # all entered through its own web UI setup wizard on first
        # visit. Same "needs one-time setup, no secret to invent"
        # treatment as the Uptime Kuma reference warning, just without
        # that one's per-service URL list - Maintainerr's setup wizard
        # itself is where each *arr connection gets configured, so
        # there's nothing else useful to enumerate here.
        maintainerr_href = _service_href("maintainerr", config, host_ip)

        warnings.append(
            f"Maintainerr needs one-time setup: visit {maintainerr_href}, connect it to "
            "Jellyfin (or Plex/Emby) and Radarr/Sonarr through its own setup wizard, then "
            "create your library-cleanup rules there - nothing is pre-configured."
        )

    if "metube" in enabled_service_keys(config):

        metube_href = _service_href("metube", config, host_ip)

        warnings.append(
            f"MeTube downloads land in stack/media/youtube on the host - to see them in "
            f"Jellyfin, add a library there (Dashboard > Libraries > Add Media Library, "
            f"any content type works) pointed at /data/media/youtube. Paste a video or "
            f"playlist URL at {metube_href} to start a download."
        )

    if "downtify" in enabled_service_keys(config):

        downtify_href = _service_href("downtify", config, host_ip)

        warnings.append(
            f"Downtify downloads land in stack/media/music/downtify on the host, inside "
            f"your existing Music library path so Jellyfin picks them up automatically "
            f"(no new library needed) - if Lidarr is also enabled, it may flag this "
            f"subfolder as unmapped files on its own library scans; that's cosmetic, not "
            f"destructive, since Lidarr never auto-imports or deletes anything without "
            f"confirmation. Downtify's own image has no documented PUID/PGID support, so "
            f"downloaded files may land owned by root rather than PUID/PGID like every "
            f"other service here - Jellyfin's read-only mount is unaffected, but you may "
            f"need sudo to move/delete them directly on the host. Paste a track, album, or "
            f"playlist URL at {downtify_href} - no Spotify account or API key needed."
        )

    if "netdata" in enabled_service_keys(config):

        netdata_href = _service_href("netdata", config, host_ip)

        warnings.append(
            f"Netdata has real, meaningfully deeper host access than anything else in this "
            f"stack - SYS_PTRACE/SYS_ADMIN capabilities, read-only access to most of the "
            f"host filesystem, the Docker socket, and network_mode: host (so it's reachable "
            f"directly at {netdata_href}, not through Traefik or PUID/PGID like every other "
            f"service). This is what real-time system/temperature monitoring genuinely needs, "
            f"not excessive by accident - but it's a real tradeoff worth knowing about, not "
            f"hidden. No dashboard/login is pre-configured; it's ready to view as soon as the "
            f"container starts."
        )

    if "vaultwarden" in enabled_service_keys(config):

        vaultwarden_href = _service_href("vaultwarden", config, host_ip)

        warnings.append(
            f"Vaultwarden needs one-time setup: create your account at {vaultwarden_href} "
            f"first (this is also the best first stop after any install - save every other "
            f"service's login here as you create it), then set VAULTWARDEN_SIGNUPS_ALLOWED=false "
            f"in stack/.env and restart the container to stop accepting new signups. A real, "
            f"random VAULTWARDEN_ADMIN_TOKEN was already generated into stack/.env for its "
            f"admin panel at {vaultwarden_href}/admin. Like Jellyfin, Vaultwarden is "
            f"deliberately not routed through Authelia - its own official apps (browser "
            f"extension, mobile, desktop) log in directly and can't complete a browser SSO "
            f"redirect; its own master password (plus its own optional two-factor "
            f"authentication) is the real protection layer here."
        )

    if (
        "jellyfin" in enabled_service_keys(config)
        and "authelia" in enabled_service_keys(config)
        and "traefik" in enabled_service_keys(config)
        and config.domain
    ):

        warnings.append(
            "Jellyfin is deliberately not routed through Authelia, even though other "
            "services are - forward-auth's browser-redirect login breaks native Jellyfin "
            "apps on phones and TVs, which can't complete that redirect. Relying on "
            "Jellyfin's own login is the standard workaround; consider enabling Jellyfin's "
            "own built-in two-factor authentication (Dashboard > My Profile) for real "
            "protection on this one exposed service."
        )

    if (
        "seerr" in enabled_service_keys(config)
        and "jellyfin" in enabled_service_keys(config)
    ):

        warnings.append(
            "Seerr uses Jellyfin for login - any Jellyfin user can sign in with their "
            "Jellyfin credentials (Settings > General > Enable Jellyfin Sign-In). Set default "
            "new-user permissions to REQUEST only (Settings > Users > Default Permissions) so "
            "family can request movies/shows but can't manage libraries or settings. You can "
            "also set global request limits (e.g. 3 movies/week) in the same page."
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
            "doesn't install it automatically. Install guide: "
            "https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html"
        )

    # Re-save with the now-fully-computed warnings - the first
    # save_state() call above ran before this function even knew what
    # they'd be. Cheap (a small JSON rewrite) and safe to always do,
    # not just when warnings is non-empty, so a regenerate that fixed
    # every warning also clears the stale list from a previous run.
    save_state(config, output_dir, warnings=warnings)

    return {
        "success": True,
        "compose_path": str(compose_path),
        "env_path": str(env_path),
        "warnings": warnings
    }
