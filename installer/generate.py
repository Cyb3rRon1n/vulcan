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
from datetime import UTC, datetime
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

# Every service with its own routable web UI - the single source of
# truth both Homepage's tile groups (below) and the Traefik template's
# per-service labels (templates/docker-compose.yml.j2) draw from,
# closing a real drift risk this project has hit before (the "17 known
# services" count going stale, twice - see CLAUDE.md). "traefik" and
# "homepage" both appear here despite neither routing/tiling itself the
# normal way: Traefik gets a tile (pointing at its own dashboard) but no
# per-service label block of its own, Homepage gets a label block (it's
# routable like anything else) but no tile of itself. So each consumer
# below derives its own view by excluding just itself -
# WEB_FACING_SERVICES - {"traefik"} is exactly the set of services with
# a `{% if 'traefik' in enabled and domain %}` label block in the
# template, and WEB_FACING_SERVICES - {"homepage"} is exactly the flat
# union of _HOMEPAGE_GROUPS's values - both checked by
# tests/test_generate.py so the two can't silently drift apart again.
WEB_FACING_SERVICES: frozenset[str] = frozenset({
    "jellyfin", "radarr", "sonarr", "prowlarr", "qbittorrent", "sabnzbd",
    "jellyseerr", "bazarr", "lidarr", "readarr", "maintainerr", "authelia",
    "uptime-kuma", "traefik", "homepage", "dashy", "audiobookshelf",
})

# Homepage tile groups - grouping/ordering is presentation-specific and
# stays hand-written, but its flattened membership is cross-checked
# against WEB_FACING_SERVICES above by test_generate.py. "dashy" lives
# here too (in Infrastructure, alongside Traefik) since Homepage tiles
# it like any other enabled web-facing service when both dashboards are
# turned on - it just never appears in its own group, the same
# self-exclusion "homepage" already gets everywhere this table is used.
_HOMEPAGE_GROUPS: dict[str, list[str]] = {
    "Media": ["jellyfin", "jellyseerr", "audiobookshelf"],
    "Media Management": ["radarr", "sonarr", "lidarr", "readarr", "prowlarr", "bazarr", "maintainerr"],
    "Downloads": ["qbittorrent", "sabnzbd"],
    "Monitoring": ["uptime-kuma"],
    "Security": ["authelia"],
    "Infrastructure": ["traefik", "dashy"],
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
    "homepage": 3000,
    "authelia": 9091,
    "maintainerr": 6246,
    # Dashy's own real documented convention (its example
    # docker-compose.yml, confirmed by fetching it directly) publishes
    # host port 4000 against its container's internal 8080.
    "dashy": 4000,
    # Audiobookshelf's own documented default (confirmed via its real
    # docker-compose.yml and official docs) - host 13378, container 80.
    "audiobookshelf": 13378,
    # Deliberately no "traefik" entry - its dashboard has no
    # independent host-published port (see _service_href()'s
    # api.insecure security note), so it has no non-routed fallback
    # the way every other service here does.
}

# Container-internal ports, for one service to tell another where to
# reach it over the compose network - deliberately a separate table
# from _HOMEPAGE_PORTS above, not a reuse: _HOMEPAGE_PORTS is the
# host-published, user-browser-facing, remappable side, and it
# genuinely differs from the container-internal side for SABnzbd
# (8081 published vs. 8080 internal, to avoid qBittorrent's own 8080) -
# reusing it here would generate a real wrong URL for that one case.
_ARR_CONTAINER_PORTS: dict[str, int] = {
    "jellyfin": 8096,
    "radarr": 7878,
    "sonarr": 8989,
    "lidarr": 8686,
    "readarr": 8787,
    "qbittorrent": 8080,
    "sabnzbd": 8080,
}

# Dashy's own icon field genuinely accepts a plain image URL (confirmed
# via its real docs, unlike Homepage which bundles the Dashboard Icons
# set internally and only needs a bare filename) - reusing the same
# public Dashboard Icons CDN Homepage's own icons already come from
# keeps both dashboards' tiles visually consistent with zero new
# mapping table, and every key used below was checked to actually
# resolve against it before relying on it.
_DASHY_ICON_URL = "https://cdn.jsdelivr.net/gh/walkxcode/dashboard-icons/png/{key}.png"

# One real, plain-language sentence per service - gethomepage.dev's own
# documented `description:` field, shown under the tile name so a tile
# is identifiable by what it does, not just its (sometimes opaque, e.g.
# "Prowlarr") name. Covers every key that can ever appear in
# _HOMEPAGE_GROUPS above - a KeyError here means a group was extended
# without adding the matching description, same "every real key stays
# in sync" discipline _HOMEPAGE_PORTS already follows.
_HOMEPAGE_DESCRIPTIONS: dict[str, str] = {
    "jellyfin": "Stream your movies, TV, and music",
    "jellyseerr": "Request new movies and shows",
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
    "dashy": "Alternative dashboard to Homepage",
    "audiobookshelf": "Stream your audiobooks and podcasts",
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
    cloudflare_dns: bool = False
    cloudflare_email: str | None = None
    port_overrides: dict[str, int] = field(default_factory=dict)
    watchtower_notification_url: str | None = None


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
        "cloudflare_dns": config.cloudflare_dns,
        "cloudflare_email": config.cloudflare_email,
        "port_overrides": config.port_overrides,
        "generated_at": datetime.now(UTC).isoformat()
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


def watchtower_notification_configured(output_dir: Path = STACK_DIR) -> bool:
    """
    Whether a real Watchtower notification URL already exists in
    stack/.env - used by the CLI/TUI to skip re-prompting on a
    regenerate, the same "already configured, leave it alone" rule
    Authelia's users_database.yml check already follows. Never returns
    the value itself, only whether one exists - a Shoutrrr URL embeds a
    real credential (e.g. discord://token@channel), the same class as
    TS_AUTHKEY/CF_DNS_API_TOKEN, which this project never echoes back
    at a prompt.
    """

    return bool(_preserved_vpn_value(Path(output_dir), "WATCHTOWER_NOTIFICATION_URL", ""))


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

    if "traefik" in enabled and config.domain:
        hosts.append(f"homepage.{config.domain}")

    return ",".join(hosts)


def render_compose(
    config: GenerationConfig, host_ip: str | None = None, watchtower_notification_url: str = ""
) -> str:

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
        cloudflare_dns=config.cloudflare_dns,
        cloudflare_email=config.cloudflare_email,
        ports=resolve_ports(config),
        # Deliberately no placeholder here, unlike Gluetun/Tailscale/
        # Cloudflare's "changeme" defaults - notifications aren't
        # required for Watchtower to function (it just updates
        # silently without them), and this project has already hit one
        # real Watchtower crash-loop bug (see the DOCKER_API_VERSION
        # fix above) with no live Docker here to verify Shoutrrr's own
        # tolerance for a garbage URL string. Omitting the env var
        # entirely when unconfigured is Watchtower's own long-standing
        # default behavior, already known safe.
        watchtower_notification_url=watchtower_notification_url
    )


def render_env(
    config: GenerationConfig,
    vpn_service_provider: str = "changeme",
    vpn_type: str = "wireguard",
    wireguard_private_key: str = "changeme",
    tailscale_authkey: str = "changeme",
    cloudflare_dns_api_token: str = "changeme",
    cloudflare_acme_email: str = "changeme@example.com",
    watchtower_notification_url: str = ""
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
        tailscale_enabled="tailscale" in enabled,
        tailscale_authkey=tailscale_authkey,
        cloudflare_dns_enabled=config.cloudflare_dns,
        cloudflare_dns_api_token=cloudflare_dns_api_token,
        cloudflare_acme_email=cloudflare_acme_email,
        watchtower_enabled="watchtower" in enabled,
        watchtower_notification_url=watchtower_notification_url
    )


def _service_href(key: str, config: GenerationConfig, host_ip: str | None) -> str | None:

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

    routed = "traefik" in enabled and config.domain and not qbittorrent_via_gluetun

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

    return yaml.safe_dump(groups, sort_keys=False)


def render_dashy_config(config: GenerationConfig, host_ip: str | None) -> str:
    """
    Dashy's real schema (confirmed by fetching its own real, current
    user-data/conf.yml directly, not assumed): pageInfo/appConfig/
    sections, each section a {name, items} pair - a genuinely different
    shape from Homepage's flat list-of-single-key-dicts groups, so this
    reuses the same _HOMEPAGE_GROUPS/_service_href() data every other
    dashboard-tile function here already does rather than duplicating a
    second copy of "which services get tiled, in what groups."
    Excludes "dashy" itself from its own Infrastructure group - it's
    only in that table so *Homepage's* tiles can include Dashy, not so
    Dashy tiles itself.
    """

    enabled = enabled_service_keys(config)
    display_names = {service.key: service.display_name for service in ALL_SERVICES}

    sections = []

    for group_name, keys in _HOMEPAGE_GROUPS.items():

        items = []

        for key in keys:

            if key == "dashy" or key not in enabled:
                continue

            href = _service_href(key, config, host_ip)

            if href is None:
                continue

            items.append({
                "title": display_names[key],
                "description": _HOMEPAGE_DESCRIPTIONS[key],
                "icon": _DASHY_ICON_URL.format(key=key),
                "url": href
            })

        if items:
            sections.append({"name": group_name, "items": items})

    return yaml.safe_dump({
        "pageInfo": {"title": "Vulcan"},
        "appConfig": {"theme": "colorful"},
        "sections": sections
    }, sort_keys=False)


def render_authelia_users_database(username: str, displayname: str, password_hash: str) -> str:

    return yaml.safe_dump({
        "users": {
            username: {
                "disabled": False,
                "displayname": displayname,
                "password": password_hash,
                "email": f"{username}@localhost",
                "groups": ["admins"]
            }
        }
    }, sort_keys=False)


def render_authelia_configuration(config: GenerationConfig, host_ip: str | None) -> str:

    template = _jinja_env().get_template("authelia-configuration.yml.j2")

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


def _container_url(key: str, enabled: set[str]) -> str:
    """
    Container-internal DNS name + port, for one service to reach
    another over the compose network - deliberately not
    resolve_ports()/_HOMEPAGE_PORTS (those are host-published,
    user-browser-facing, remappable). qBittorrent behind Gluetun has
    no network identity of its own (network_mode: service:gluetun),
    the same exception render_decluttarr_config()/_service_href()
    already carry for exactly this reason.
    """

    if key == "qbittorrent" and "gluetun" in enabled:
        return f"http://gluetun:{_ARR_CONTAINER_PORTS['qbittorrent']}"

    return f"http://{key}:{_ARR_CONTAINER_PORTS[key]}"


def _arr_setup_reference(config: GenerationConfig) -> str | None:
    """
    The real app-to-app integrations Vulcan can't wire up itself -
    Prowlarr -> *arr apps, each *arr app -> its download client(s),
    Bazarr -> Radarr/Sonarr, Jellyseerr -> Jellyfin/Radarr/Sonarr.
    Every one of these needs a real API key generated the first time
    the *target* app starts, which doesn't exist yet at generate time -
    so this can't pre-fill the connection the way Recyclarr/Decluttarr's
    base_urls are pre-filled, only tell the user exactly where to paste
    it once they have it. Returns None when nothing enabled actually
    has a real pairing to report, so write_stack() adds no warning at
    all rather than an empty one.
    """

    enabled = enabled_service_keys(config)
    display_names = {service.key: service.display_name for service in ALL_SERVICES}
    lines = []

    arr_apps = [key for key in ("radarr", "sonarr", "lidarr", "readarr") if key in enabled]

    if "prowlarr" in enabled and arr_apps:

        lines.append("  Prowlarr -> add under Settings > Apps:")
        lines.extend(f"    {display_names[key]}: {_container_url(key, enabled)}" for key in arr_apps)

    download_clients = [key for key in ("qbittorrent", "sabnzbd") if key in enabled]

    for arr_key in arr_apps:

        if download_clients:

            lines.append(f"  {display_names[arr_key]} -> add under Settings > Download Clients:")
            lines.extend(
                f"    {display_names[key]}: {_container_url(key, enabled)}" for key in download_clients
            )

    bazarr_targets = [key for key in ("radarr", "sonarr") if key in enabled]

    if "bazarr" in enabled and bazarr_targets:

        lines.append("  Bazarr -> connect under Settings > Radarr/Sonarr:")
        lines.extend(f"    {display_names[key]}: {_container_url(key, enabled)}" for key in bazarr_targets)

    jellyseerr_targets = [key for key in ("jellyfin", "radarr", "sonarr") if key in enabled]

    if "jellyseerr" in enabled and jellyseerr_targets:

        lines.append("  Jellyseerr -> connect through its own setup wizard:")
        lines.extend(
            f"    {display_names[key]}: {_container_url(key, enabled)}" for key in jellyseerr_targets
        )

    if not lines:
        return None

    return (
        "Connect your *arr apps to finish setup - each connection still needs a real API key "
        "pasted in from the target app's own Settings > General page (Vulcan can't generate "
        "these, they're only created the first time each app starts):\n" + "\n".join(lines)
    )


def _arr_notification_reference(config: GenerationConfig) -> str | None:
    """
    Radarr/Sonarr/Lidarr/Readarr's own notification integrations
    (Discord, ntfy, Gotify, Apprise, and more) live under Settings >
    Connect in each app's own UI - stored in that app's database, the
    same reason _arr_setup_reference() can't pre-fill Prowlarr's own
    sync either. Nothing for Vulcan to generate here, just a pointer so
    it's not a "go figure this out yourself" gap. Watchtower's own
    notification wiring (see write_stack()) is the one real exception
    in this stack - a plain env var, not a database-backed UI setting.
    """

    enabled = enabled_service_keys(config)
    arr_apps = [key for key in ("radarr", "sonarr", "lidarr", "readarr") if key in enabled]

    if not arr_apps:
        return None

    display_names = {service.key: service.display_name for service in ALL_SERVICES}
    names = ", ".join(display_names[key] for key in arr_apps)

    return (
        f"{names} can each send their own notifications (Discord, ntfy, Gotify, Apprise, and "
        "more) under Settings > Connect in their own UI - there's no config file for Vulcan to "
        "pre-fill here, since these are stored in each app's own database."
    )


def render_stack_summary(config: GenerationConfig, host_ip: str | None) -> str:

    enabled = enabled_service_keys(config)
    display_names = {service.key: service.display_name for service in ALL_SERVICES}

    lines = []

    if "homepage" in enabled:
        lines.append(f"  Homepage (dashboard): {_service_href('homepage', config, host_ip)}")

    if "dashy" in enabled:
        lines.append(f"  Dashy (dashboard): {_service_href('dashy', config, host_ip)}")

    lines.extend(
        f"  {display_names[key]}: {_service_href(key, config, host_ip)}"
        for keys in _HOMEPAGE_GROUPS.values()
        for key in keys
        # "dashy" is only in _HOMEPAGE_GROUPS so Homepage's own tiles
        # can include it - it already got its own explicit line above,
        # same self-exclusion reasoning "homepage" gets by simply never
        # being a member of this table to begin with.
        if key in enabled and key != "dashy"
    )

    return "\n".join(lines)


def write_stack(config: GenerationConfig, output_dir: Path = STACK_DIR) -> dict:

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    compose_path = output_dir / "docker-compose.yml"
    env_path = output_dir / ".env"

    # Computed once, up front - render_compose() needs it now too
    # (HOMEPAGE_ALLOWED_HOSTS), not just the warnings/Homepage-tile
    # logic further down that already used to be its first use.
    host_ip = detect_host_ip()

    # Same preservation as every other real credential below - a value
    # already typed in on a previous run survives a regenerate. Unlike
    # those, the fallback is "" (nothing), never "changeme" - see
    # render_compose()'s own comment for why this one is genuinely
    # unconfigured-by-default rather than a placeholder.
    watchtower_notification_url = _preserved_vpn_value(
        output_dir, "WATCHTOWER_NOTIFICATION_URL", config.watchtower_notification_url or ""
    )

    # Read any existing .env before it gets overwritten - a real Gluetun
    # VPN credential the user already filled in must survive a regenerate,
    # not get reset back to a placeholder.
    env_content = render_env(
        config,
        vpn_service_provider=_preserved_vpn_value(output_dir, "VPN_SERVICE_PROVIDER", "changeme"),
        vpn_type=_preserved_vpn_value(output_dir, "VPN_TYPE", "wireguard"),
        wireguard_private_key=_preserved_vpn_value(output_dir, "WIREGUARD_PRIVATE_KEY", "changeme"),
        tailscale_authkey=_preserved_vpn_value(output_dir, "TS_AUTHKEY", "changeme"),
        cloudflare_dns_api_token=_preserved_vpn_value(output_dir, "CF_DNS_API_TOKEN", "changeme"),
        cloudflare_acme_email=_preserved_vpn_value(
            output_dir, "CLOUDFLARE_ACME_EMAIL", config.cloudflare_email or "changeme@example.com"
        ),
        watchtower_notification_url=watchtower_notification_url
    )

    compose_path.write_text(render_compose(config, host_ip, watchtower_notification_url))
    env_path.write_text(env_content)
    save_state(config, output_dir)

    for key in enabled_service_keys(config):
        (output_dir / "config" / key).mkdir(parents=True, exist_ok=True)

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
    # Audiobooks are a genuinely different content type from Readarr's
    # text ebooks ("books" above) even though both loosely fall under
    # "Readarr" conceptually - Audiobookshelf serves its own separate
    # library, populated manually or some other way, not automated by
    # any *arr app in this stack. Podcasts are Audiobookshelf's own
    # second content type (it subscribes to RSS feeds itself). Both
    # created unconditionally, same as movies/tv/music/books above,
    # regardless of whether audiobookshelf itself is enabled.
    (media_path / "media" / "audiobooks").mkdir(parents=True, exist_ok=True)
    (media_path / "media" / "podcasts").mkdir(parents=True, exist_ok=True)

    warnings = []

    if "homepage" in enabled_service_keys(config):

        services_yaml_path = output_dir / "config" / "homepage" / "services.yaml"

        if not services_yaml_path.exists():

            services_yaml_path.write_text(render_homepage_services(config, host_ip))

            warnings.append(
                "Homepage was pre-seeded with tiles for your enabled services at "
                "stack/config/homepage/services.yaml - edit it directly to customize "
                "further; Vulcan won't overwrite it on a later regenerate."
            )

    if "dashy" in enabled_service_keys(config):

        dashy_config_path = output_dir / "config" / "dashy" / "conf.yml"

        if not dashy_config_path.exists():

            dashy_config_path.parent.mkdir(parents=True, exist_ok=True)
            dashy_config_path.write_text(render_dashy_config(config, host_ip))

            warnings.append(
                "Dashy was pre-seeded with tiles for your enabled services at "
                "stack/config/dashy/conf.yml - edit it directly to customize further; "
                "Vulcan won't overwrite it on a later regenerate."
            )

    arr_reference = _arr_setup_reference(config)

    if arr_reference:
        warnings.append(arr_reference)

    arr_notification_reference = _arr_notification_reference(config)

    if arr_notification_reference:
        warnings.append(arr_notification_reference)

    if "watchtower" in enabled_service_keys(config) and not watchtower_notification_url:

        warnings.append(
            "Watchtower has no update-notification URL configured - it'll still update "
            "containers silently, just won't tell you when it does. Add a Shoutrrr-format URL "
            "(e.g. discord://token@channel) via --notification-url or the TUI to enable alerts "
            "- format per service: https://containrrr.dev/shoutrrr/latest/services/overview/"
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

    if "traefik" in enabled_service_keys(config) and config.domain and "authelia" not in enabled_service_keys(config):

        warnings.append(
            f"Traefik's own dashboard is now reachable at https://traefik.{config.domain} "
            "with no login in front of it - enable Authelia too if you want that locked down, "
            "the same as every other routed service without it."
        )

    if "authelia" in enabled_service_keys(config):

        authelia_dir = output_dir / "config" / "authelia"
        generate_authelia_secrets(authelia_dir / "secrets")

        configuration_path = authelia_dir / "configuration.yml"

        if not configuration_path.exists():
            configuration_path.write_text(render_authelia_configuration(config, host_ip))

        users_database_path = authelia_dir / "users_database.yml"

        if not users_database_path.exists() and config.auth_username and config.auth_password_hash:

            users_database_path.write_text(
                render_authelia_users_database(
                    config.auth_username, config.auth_username, config.auth_password_hash
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

    return {
        "success": True,
        "compose_path": str(compose_path),
        "env_path": str(env_path),
        "warnings": warnings
    }
