from unittest.mock import MagicMock, patch

import yaml

from installer.generate import (
    GenerationConfig,
    default_puid_pgid,
    default_timezone,
    enabled_service_keys,
    load_previous_state,
    render_authelia_configuration,
    render_authelia_users_database,
    render_compose,
    render_decluttarr_config,
    render_env,
    render_homepage_services,
    render_stack_summary,
    resolve_ports,
    save_state,
    write_stack,
)
from installer.tiers import TIERS


def make_config(
    tier_name: str,
    enabled_optional: set[str] | None = None,
    gpu_vendor: str | None = None,
    custom_services: set[str] | None = None,
    domain: str | None = None,
    cloudflare_dns: bool = False,
    cloudflare_email: str | None = None,
    auth_username: str | None = None,
    auth_password_hash: str | None = None,
    port_overrides: dict[str, int] | None = None
) -> GenerationConfig:

    return GenerationConfig(
        tier=TIERS[tier_name],
        media_path="/mnt/media",
        puid=1000,
        pgid=1000,
        timezone="America/New_York",
        enabled_optional=enabled_optional or set(),
        gpu_vendor=gpu_vendor,
        custom_services=custom_services,
        domain=domain,
        cloudflare_dns=cloudflare_dns,
        cloudflare_email=cloudflare_email,
        auth_username=auth_username,
        auth_password_hash=auth_password_hash,
        port_overrides=port_overrides or {}
    )


def test_default_puid_pgid_reads_real_ids():

    with patch("installer.generate.os.getuid", return_value=1001), patch(
        "installer.generate.os.getgid", return_value=1002
    ):

        assert default_puid_pgid() == (1001, 1002)


def test_enabled_service_keys_light_tier():

    keys = enabled_service_keys(make_config("light"))

    assert keys == {"jellyfin", "radarr", "sonarr", "prowlarr", "qbittorrent"}


def test_enabled_service_keys_medium_without_gluetun():

    keys = enabled_service_keys(make_config("medium"))

    assert keys == {
        "jellyfin", "radarr", "sonarr", "prowlarr", "qbittorrent",
        "jellyseerr", "bazarr", "flaresolverr"
    }


def test_enabled_service_keys_medium_with_gluetun():

    keys = enabled_service_keys(make_config("medium", {"gluetun"}))

    assert "gluetun" in keys
    assert len(keys) == 9


def test_enabled_service_keys_light_with_sabnzbd():

    keys = enabled_service_keys(make_config("light", {"sabnzbd"}))

    assert "sabnzbd" in keys
    assert len(keys) == 6


def test_enabled_service_keys_light_with_recyclarr():

    keys = enabled_service_keys(make_config("light", {"recyclarr"}))

    assert "recyclarr" in keys
    assert len(keys) == 6


def test_enabled_service_keys_custom_services_overrides_tier_entirely():

    custom = {"jellyfin", "homepage", "watchtower"}
    keys = enabled_service_keys(make_config("light", custom_services=custom))

    assert keys == custom


def test_enabled_service_keys_custom_services_none_falls_back_to_tier():

    keys = enabled_service_keys(make_config("light", custom_services=None))

    assert keys == {"jellyfin", "radarr", "sonarr", "prowlarr", "qbittorrent"}


def test_render_compose_light_only_includes_light_services():

    output = render_compose(make_config("light"))

    for name in ("jellyfin", "radarr", "sonarr", "prowlarr", "qbittorrent"):
        assert f"container_name: {name}" in output

    for name in ("jellyseerr", "bazarr", "flaresolverr", "gluetun"):
        assert f"container_name: {name}" not in output


def test_render_compose_medium_without_gluetun_gives_qbittorrent_its_own_ports():

    output = render_compose(make_config("medium"))

    assert 'network_mode: "service:gluetun"' not in output
    assert "container_name: gluetun" not in output

    qbittorrent_block = output.split("qbittorrent:", 1)[1].split("jellyseerr:", 1)[0]
    assert "8080:8080" in qbittorrent_block


def test_render_compose_medium_with_gluetun_routes_qbittorrent_through_it():

    output = render_compose(make_config("medium", {"gluetun"}))

    assert "container_name: gluetun" in output

    qbittorrent_block = output.split("qbittorrent:", 1)[1].split("jellyseerr:", 1)[0]
    assert 'network_mode: "service:gluetun"' in qbittorrent_block
    assert "ports:" not in qbittorrent_block


def test_render_compose_medium_without_sabnzbd_omits_it():

    output = render_compose(make_config("medium"))

    assert "container_name: sabnzbd" not in output


def test_render_compose_medium_with_sabnzbd_uses_remapped_port():

    output = render_compose(make_config("medium", {"sabnzbd"}))

    assert "container_name: sabnzbd" in output

    sabnzbd_block = output.split("sabnzbd:", 1)[1].split("jellyseerr:", 1)[0]
    assert '"8081:8080"' in sabnzbd_block
    assert "${MEDIA_PATH}:/data" in sabnzbd_block


def test_resolve_ports_returns_defaults_when_no_overrides():

    ports = resolve_ports(make_config("light"))

    assert ports["jellyfin"] == 8096
    assert ports["qbittorrent"] == 8080
    assert ports["sabnzbd"] == 8081


def test_resolve_ports_override_wins_over_default():

    ports = resolve_ports(make_config("light", port_overrides={"jellyfin": 9096}))

    assert ports["jellyfin"] == 9096
    # every other service's default is untouched by one override
    assert ports["radarr"] == 7878


def test_resolve_ports_has_no_traefik_entry():
    """
    Traefik's 80/443 are deliberately out of remap scope - see
    resolve_ports()'s own docstring - so it should never appear as a
    remappable key even with no overrides at all.
    """

    assert "traefik" not in resolve_ports(make_config("heavy"))


def test_render_compose_jellyfin_uses_port_override():

    output = render_compose(make_config("light", port_overrides={"jellyfin": 9096}))

    jellyfin_block = output.split("jellyfin:", 1)[1].split("radarr:", 1)[0]
    assert '"9096:8096"' in jellyfin_block
    assert "8096:8096" not in jellyfin_block


def test_render_compose_gluetun_port_follows_qbittorrent_override():
    """
    Gluetun's own ports block is qBittorrent's effective port when
    Gluetun is active - the override key is "qbittorrent", not
    "gluetun" (see check_ports_available()'s port_services mapping),
    and the compose template reuses ports['qbittorrent'] in both
    places for exactly that reason.
    """

    output = render_compose(make_config("medium", {"gluetun"}, port_overrides={"qbittorrent": 9080}))

    gluetun_block = output.split("gluetun:", 1)[1].split("lidarr:", 1)[0]
    assert '"9080:8080"' in gluetun_block


def test_render_compose_sabnzbd_port_override_leaves_container_port_fixed():

    output = render_compose(make_config("light", {"sabnzbd"}, port_overrides={"sabnzbd": 9081}))

    sabnzbd_block = output.split("sabnzbd:", 1)[1].split("recyclarr:", 1)[0]
    assert '"9081:8080"' in sabnzbd_block


def test_render_compose_no_override_keeps_default_port():

    output = render_compose(make_config("light"))

    jellyfin_block = output.split("jellyfin:", 1)[1].split("radarr:", 1)[0]
    assert '"8096:8096"' in jellyfin_block


def test_render_compose_medium_without_recyclarr_omits_it():

    output = render_compose(make_config("medium"))

    assert "container_name: recyclarr" not in output


def test_render_compose_medium_with_recyclarr_uses_pinned_image_and_user():

    output = render_compose(make_config("medium", {"recyclarr"}))

    assert "container_name: recyclarr" in output

    recyclarr_block = output.split("recyclarr:", 1)[1].split("jellyseerr:", 1)[0]
    assert "image: ghcr.io/recyclarr/recyclarr:8" in recyclarr_block
    assert 'user: "${PUID}:${PGID}"' in recyclarr_block
    assert "PUID=${PUID}" not in recyclarr_block


def test_render_compose_medium_without_decluttarr_omits_it():

    output = render_compose(make_config("medium"))

    assert "container_name: decluttarr" not in output


def test_render_compose_medium_with_decluttarr_mounts_config():

    output = render_compose(make_config("medium", {"decluttarr"}))

    decluttarr_block = _service_block(output, "decluttarr", "jellyseerr")
    assert "image: ghcr.io/manimatter/decluttarr:latest" in decluttarr_block
    assert "./config/decluttarr/config.yaml:/app/config/config.yaml" in decluttarr_block


def test_render_compose_medium_without_maintainerr_omits_it():

    output = render_compose(make_config("medium"))

    assert "container_name: maintainerr" not in output


def test_render_compose_medium_with_maintainerr_mounts_media_and_config():

    output = render_compose(make_config("medium", {"maintainerr"}))

    maintainerr_block = _service_block(output, "maintainerr", "jellyseerr")
    assert "image: ghcr.io/maintainerr/maintainerr:latest" in maintainerr_block
    assert 'user: "${PUID}:${PGID}"' in maintainerr_block
    assert "./config/maintainerr:/opt/data" in maintainerr_block
    # Read-write, and at the same internal path Radarr/Sonarr/qBittorrent
    # already use - Maintainerr's leftover-folder cleanup needs to see
    # media at the same path those apps report it at, not a separate
    # read-only mount like Jellyfin/Bazarr get.
    assert "${MEDIA_PATH}:/data" in maintainerr_block
    assert '"8080:8080"' not in maintainerr_block


def test_render_compose_maintainerr_uses_port_override():

    output = render_compose(make_config("medium", {"maintainerr"}, port_overrides={"maintainerr": 7246}))

    maintainerr_block = _service_block(output, "maintainerr", "jellyseerr")
    assert '"7246:6246"' in maintainerr_block


def test_render_compose_heavy_includes_all_new_services():

    output = render_compose(
        make_config("heavy", enabled_optional={"lidarr", "readarr", "traefik", "homepage"})
    )

    for name in ("lidarr", "readarr", "traefik", "homepage", "uptime-kuma", "watchtower"):
        assert f"container_name: {name}" in output


def test_render_compose_readarr_uses_pinned_nightly_image():

    output = render_compose(make_config("heavy", enabled_optional={"readarr"}))

    assert "image: lscr.io/linuxserver/readarr:0.4.19-nightly" in output
    assert '"8787:8787"' in output


def test_render_compose_medium_excludes_heavy_only_services():

    output = render_compose(make_config("medium"))

    for name in ("lidarr", "traefik", "homepage", "uptime-kuma", "watchtower"):
        assert f"container_name: {name}" not in output


def test_render_compose_heavy_without_optional_extras_excludes_lidarr_traefik_and_homepage():

    output = render_compose(make_config("heavy"))

    assert "container_name: lidarr" not in output
    assert "container_name: readarr" not in output
    assert "container_name: traefik" not in output
    assert "container_name: homepage" not in output


def test_render_compose_homepage_allowed_hosts_always_includes_localhost():

    output = render_compose(make_config("heavy", enabled_optional={"homepage"}))

    assert "HOMEPAGE_ALLOWED_HOSTS=localhost:3000" in output


def test_render_compose_homepage_allowed_hosts_includes_real_host_ip_when_known():

    output = render_compose(
        make_config("heavy", enabled_optional={"homepage"}), host_ip="192.168.1.100"
    )

    assert "HOMEPAGE_ALLOWED_HOSTS=localhost:3000,192.168.1.100:3000" in output


def test_render_compose_homepage_allowed_hosts_includes_routed_domain():

    output = render_compose(
        make_config("heavy", enabled_optional={"homepage", "traefik"}, domain="media.example.com"),
        host_ip="192.168.1.100"
    )

    assert "HOMEPAGE_ALLOWED_HOSTS=localhost:3000,192.168.1.100:3000,homepage.media.example.com" in output


def test_render_compose_homepage_allowed_hosts_omits_domain_without_traefik_routing():

    output = render_compose(
        make_config("heavy", enabled_optional={"homepage"}, domain="media.example.com"),
        host_ip="192.168.1.100"
    )

    assert "homepage.media.example.com" not in output


def _jellyfin_block(output: str) -> str:

    return output.split("jellyfin:", 1)[1].split("  radarr:", 1)[0]


def _service_block(output: str, name: str, next_name: str) -> str:

    return output.split(f"{name}:", 1)[1].split(f"{next_name}:", 1)[0]


def test_render_compose_no_domain_omits_traefik_labels_even_when_enabled():

    output = render_compose(make_config("heavy", enabled_optional={"traefik"}))

    assert "traefik.enable" not in output
    assert "traefik.http.routers" not in output


def test_render_compose_domain_without_traefik_omits_labels():

    output = render_compose(make_config("heavy", domain="media.example.com"))

    assert "traefik.enable" not in output


def test_render_compose_domain_adds_routing_labels_to_every_directly_networked_service():

    output = render_compose(
        make_config(
            "heavy",
            enabled_optional={"traefik", "lidarr", "readarr", "homepage"},
            domain="media.example.com"
        )
    )

    expected_ports = {
        "jellyfin": 8096,
        "radarr": 7878,
        "sonarr": 8989,
        "prowlarr": 9696,
        "jellyseerr": 5055,
        "bazarr": 6767,
        "lidarr": 8686,
        "readarr": 8787,
        "homepage": 3000,
        "uptime-kuma": 3001,
    }

    for name, port in expected_ports.items():

        assert f"traefik.http.routers.{name}.rule=Host(`{name}.media.example.com`)" in output
        assert f"traefik.http.services.{name}.loadbalancer.server.port={port}" in output


def test_render_compose_domain_does_not_route_internal_only_services():

    output = render_compose(
        make_config(
            "heavy",
            enabled_optional={"traefik", "flaresolverr", "lidarr"},
            domain="media.example.com"
        )
    )

    for name in ("flaresolverr", "recyclarr", "watchtower", "gluetun"):
        assert f"traefik.http.routers.{name}." not in output


def test_render_compose_qbittorrent_routed_when_gluetun_disabled():

    output = render_compose(
        make_config("heavy", enabled_optional={"traefik"}, domain="media.example.com")
    )

    qbittorrent_block = _service_block(output, "qbittorrent", "jellyseerr")
    assert "traefik.http.routers.qbittorrent.rule=Host(`qbittorrent.media.example.com`)" in qbittorrent_block
    assert "traefik.http.services.qbittorrent.loadbalancer.server.port=8080" in qbittorrent_block


def test_render_compose_qbittorrent_not_routed_when_gluetun_enabled():

    output = render_compose(
        make_config(
            "heavy", enabled_optional={"traefik", "gluetun"}, domain="media.example.com"
        )
    )

    qbittorrent_block = _service_block(output, "qbittorrent", "jellyseerr")
    assert "traefik" not in qbittorrent_block

    # every other enabled service still gets routed
    assert "traefik.http.routers.jellyfin.rule" in output


def test_render_compose_sabnzbd_uses_internal_port_not_remapped_host_port():

    output = render_compose(
        make_config("heavy", enabled_optional={"traefik", "sabnzbd"}, domain="media.example.com")
    )

    sabnzbd_block = _service_block(output, "sabnzbd", "jellyseerr")
    assert "traefik.http.services.sabnzbd.loadbalancer.server.port=8080" in sabnzbd_block
    assert "loadbalancer.server.port=8081" not in sabnzbd_block


def test_render_compose_traefik_redirects_http_to_https_only_with_domain():

    without_domain = render_compose(make_config("heavy", enabled_optional={"traefik"}))
    with_domain = render_compose(
        make_config("heavy", enabled_optional={"traefik"}, domain="media.example.com")
    )

    assert "redirections.entrypoint.to=websecure" not in without_domain
    assert "redirections.entrypoint.to=websecure" in with_domain


def test_render_compose_traefik_api_flags_always_present_regardless_of_domain():
    """
    --api.dashboard=true just enables the feature - harmless with no
    domain, since nothing can route to it without one anyway. Only the
    routing labels themselves are domain-gated.
    """

    without_domain = render_compose(make_config("heavy", enabled_optional={"traefik"}))
    with_domain = render_compose(
        make_config("heavy", enabled_optional={"traefik"}, domain="media.example.com")
    )

    assert "--api=true" in without_domain
    assert "--api.dashboard=true" in without_domain
    assert "--api=true" in with_domain
    assert "--api.dashboard=true" in with_domain


def test_render_compose_traefik_dashboard_routed_with_domain():

    output = render_compose(
        make_config("heavy", enabled_optional={"traefik"}, domain="media.example.com")
    )

    traefik_block = _service_block(output, "traefik", "authelia")

    assert (
        "traefik.http.routers.dashboard.rule=Host(`traefik.media.example.com`) && "
        "(PathPrefix(`/api`) || PathPrefix(`/dashboard`))"
    ) in traefik_block
    assert "traefik.http.routers.dashboard.service=api@internal" in traefik_block
    assert "traefik.http.routers.dashboard.entrypoints=websecure" in traefik_block
    assert "traefik.http.routers.dashboard.tls=true" in traefik_block


def test_render_compose_traefik_dashboard_omitted_without_domain():

    output = render_compose(make_config("heavy", enabled_optional={"traefik"}))

    assert "routers.dashboard" not in output
    assert "api@internal" not in output


def test_render_compose_traefik_dashboard_protected_by_authelia_when_enabled():

    output = render_compose(
        make_config(
            "heavy", enabled_optional={"traefik", "authelia"}, domain="media.example.com"
        )
    )

    traefik_block = _service_block(output, "traefik", "authelia")
    assert "traefik.http.routers.dashboard.middlewares=authelia@docker" in traefik_block


def test_render_compose_traefik_dashboard_unprotected_without_authelia():

    output = render_compose(
        make_config("heavy", enabled_optional={"traefik"}, domain="media.example.com")
    )

    assert "dashboard.middlewares" not in output


def test_render_compose_tailscale_uses_host_networking():

    output = render_compose(make_config("heavy", enabled_optional={"tailscale"}))

    tailscale_block = _service_block(output, "tailscale", "homepage")

    assert "network_mode: host" in tailscale_block
    assert "TS_AUTHKEY=${TS_AUTHKEY}" in tailscale_block
    assert "/dev/net/tun:/dev/net/tun" in tailscale_block
    assert "NET_ADMIN" in tailscale_block
    assert "NET_RAW" in tailscale_block


def test_render_compose_omits_tailscale_when_disabled():

    output = render_compose(make_config("light"))

    assert "container_name: tailscale" not in output


def test_render_compose_cloudflare_dns_adds_certresolver_flags_and_token():

    output = render_compose(
        make_config("heavy", enabled_optional={"traefik"}, domain="media.example.com", cloudflare_dns=True)
    )

    traefik_block = _service_block(output, "traefik", "authelia")

    assert "--certificatesresolvers.cloudflare.acme.dnschallenge=true" in traefik_block
    assert "--certificatesresolvers.cloudflare.acme.dnschallenge.provider=cloudflare" in traefik_block
    assert "--certificatesresolvers.cloudflare.acme.storage=/etc/traefik/acme.json" in traefik_block
    assert "CF_DNS_API_TOKEN=${CF_DNS_API_TOKEN}" in traefik_block


def test_render_compose_cloudflare_dns_uses_real_email():

    output = render_compose(
        make_config(
            "heavy", enabled_optional={"traefik"}, domain="media.example.com",
            cloudflare_dns=True, cloudflare_email="me@example.com"
        )
    )

    assert "--certificatesresolvers.cloudflare.acme.email=me@example.com" in output


def test_render_compose_cloudflare_dns_adds_certresolver_label_to_every_routed_service():

    output = render_compose(
        make_config(
            "heavy", enabled_optional={"traefik", "authelia"}, domain="media.example.com",
            cloudflare_dns=True
        )
    )

    jellyfin_block = _jellyfin_block(output)
    assert "traefik.http.routers.jellyfin.tls.certresolver=cloudflare" in jellyfin_block


def test_render_compose_omits_cloudflare_certresolver_when_disabled():

    output = render_compose(
        make_config("heavy", enabled_optional={"traefik"}, domain="media.example.com")
    )

    assert "certresolver" not in output
    assert "CF_DNS_API_TOKEN" not in output


def test_render_compose_amd_gpu_adds_device_and_group(tmp_path):

    with patch("installer.generate.detect_render_group_gid", return_value=105):
        output = render_compose(make_config("heavy", gpu_vendor="amd"))

    jellyfin_block = _jellyfin_block(output)

    assert "/dev/dri:/dev/dri" in jellyfin_block
    assert 'group_add' in jellyfin_block
    assert '"105"' in jellyfin_block
    assert "driver: nvidia" not in jellyfin_block


def test_render_compose_intel_gpu_adds_device_and_group(tmp_path):

    with patch("installer.generate.detect_render_group_gid", return_value=105):
        output = render_compose(make_config("heavy", gpu_vendor="intel"))

    jellyfin_block = _jellyfin_block(output)

    assert "/dev/dri:/dev/dri" in jellyfin_block
    assert '"105"' in jellyfin_block


def test_render_compose_nvidia_gpu_adds_reservation_under_same_deploy_key():

    output = render_compose(make_config("heavy", gpu_vendor="nvidia"))

    jellyfin_block = _jellyfin_block(output)

    assert jellyfin_block.count("deploy:") == 1
    assert "driver: nvidia" in jellyfin_block
    assert "reservations:" in jellyfin_block
    assert "/dev/dri" not in jellyfin_block


def test_render_compose_no_gpu_adds_neither():

    output = render_compose(make_config("heavy", gpu_vendor=None))

    jellyfin_block = _jellyfin_block(output)

    assert "/dev/dri" not in jellyfin_block
    assert "driver: nvidia" not in jellyfin_block
    assert "group_add" not in jellyfin_block


def test_render_env_contains_core_values():

    output = render_env(make_config("light"))

    assert "MEDIA_PATH=/mnt/media" in output
    assert "PUID=1000" in output
    assert "PGID=1000" in output
    assert "TZ=America/New_York" in output
    assert "VPN_SERVICE_PROVIDER" not in output


def test_render_env_includes_vpn_placeholders_when_gluetun_enabled():

    output = render_env(make_config("medium", {"gluetun"}))

    assert "VPN_SERVICE_PROVIDER=changeme" in output
    assert "WIREGUARD_PRIVATE_KEY=changeme" in output


def test_render_env_gluetun_comment_points_to_real_provider_docs():

    output = render_env(make_config("medium", {"gluetun"}))

    assert "https://github.com/qdm12/gluetun-wiki/tree/main/setup/providers" in output
    assert "see docs" not in output


def test_render_env_includes_vpn_placeholders_when_gluetun_enabled_via_custom_mode():
    """
    Regression lock for a real, pre-existing bug found while adding
    Tailscale/Cloudflare support: this used to check
    config.enabled_optional directly, which custom mode never
    populates (it uses config.custom_services instead) - a custom-mode
    stack with Gluetun enabled rendered a compose file referencing
    ${VPN_SERVICE_PROVIDER}/etc. that .env never actually defined.
    """

    output = render_env(make_config("heavy", custom_services={"jellyfin", "gluetun"}))

    assert "VPN_SERVICE_PROVIDER=changeme" in output
    assert "WIREGUARD_PRIVATE_KEY=changeme" in output


def test_render_env_includes_tailscale_placeholder_when_enabled():

    output = render_env(make_config("heavy", {"tailscale"}))

    assert "TS_AUTHKEY=changeme" in output
    assert "https://login.tailscale.com/admin/settings/keys" in output


def test_render_env_omits_tailscale_when_disabled():

    output = render_env(make_config("light"))

    assert "TS_AUTHKEY" not in output


def test_render_env_tailscale_enabled_via_custom_mode():

    output = render_env(make_config("heavy", custom_services={"jellyfin", "tailscale"}))

    assert "TS_AUTHKEY=changeme" in output


def test_render_env_includes_cloudflare_placeholders_when_enabled():

    output = render_env(make_config("heavy", {"traefik"}, domain="media.example.com", cloudflare_dns=True))

    assert "CF_DNS_API_TOKEN=changeme" in output
    assert "CLOUDFLARE_ACME_EMAIL=changeme@example.com" in output
    assert "dash.cloudflare.com/profile/api-tokens" in output


def test_render_env_accepts_explicit_cloudflare_email():

    config = make_config("heavy", {"traefik"}, domain="media.example.com", cloudflare_dns=True)
    output = render_env(config, cloudflare_acme_email="me@example.com")

    assert "CLOUDFLARE_ACME_EMAIL=me@example.com" in output


def test_render_env_omits_cloudflare_when_disabled():

    output = render_env(make_config("heavy", {"traefik"}, domain="media.example.com"))

    assert "CF_DNS_API_TOKEN" not in output


def _homepage_groups(output: str) -> dict[str, dict[str, dict]]:

    parsed = yaml.safe_load(output)

    return {
        list(group.keys())[0]: {
            list(item.keys())[0]: list(item.values())[0] for item in list(group.values())[0]
        }
        for group in parsed
    }


def test_render_homepage_services_creates_tiles_for_enabled_services():

    output = render_homepage_services(
        make_config("heavy", custom_services={"jellyfin", "radarr", "qbittorrent", "homepage"}),
        host_ip=None
    )

    groups = _homepage_groups(output)

    assert groups["Media"]["Jellyfin"]["href"] == "http://localhost:8096"
    assert groups["Media"]["Jellyfin"]["icon"] == "jellyfin.png"
    assert groups["Media"]["Jellyfin"]["description"] == "Stream your movies, TV, and music"
    assert groups["Media Management"]["Radarr"]["href"] == "http://localhost:7878"
    assert groups["Downloads"]["qBittorrent"]["href"] == "http://localhost:8080"
    assert "Monitoring" not in groups


def test_render_homepage_services_reflects_port_override():
    """
    A remapped port has to change every real link to the service, not
    just the compose file - otherwise the Homepage tile (and the
    post-start summary/Uptime Kuma reference, which share the same
    _service_href()) would point at the old, now-wrong port.
    """

    output = render_homepage_services(
        make_config(
            "heavy",
            custom_services={"jellyfin", "homepage"},
            port_overrides={"jellyfin": 9096}
        ),
        host_ip=None
    )

    groups = _homepage_groups(output)

    assert groups["Media"]["Jellyfin"]["href"] == "http://localhost:9096"


def test_render_homepage_services_every_tile_has_a_real_description():
    """
    Every service that can ever get a tile needs a real, identifying
    one-liner - not just an icon and a sometimes-opaque name like
    "Prowlarr" or "Bazarr".
    """

    output = render_homepage_services(
        make_config(
            "heavy",
            custom_services={
                "jellyfin", "jellyseerr", "radarr", "sonarr", "lidarr", "readarr",
                "prowlarr", "bazarr", "qbittorrent", "sabnzbd", "uptime-kuma",
                "authelia", "traefik"
            },
            domain="media.example.com"
        ),
        host_ip=None
    )

    groups = _homepage_groups(output)

    for services in groups.values():
        for tile in services.values():
            assert isinstance(tile["description"], str)
            assert len(tile["description"]) > 0


def test_render_homepage_services_creates_readarr_tile():

    output = render_homepage_services(
        make_config("heavy", custom_services={"readarr"}),
        host_ip=None
    )

    groups = _homepage_groups(output)

    assert groups["Media Management"]["Readarr"]["href"] == "http://localhost:8787"
    assert groups["Media Management"]["Readarr"]["icon"] == "readarr.png"


def test_render_homepage_services_creates_maintainerr_tile():

    output = render_homepage_services(
        make_config("light", {"maintainerr"}),
        host_ip=None
    )

    groups = _homepage_groups(output)
    tile = groups["Media Management"]["Maintainerr (library cleanup)"]

    assert tile["href"] == "http://localhost:6246"
    assert tile["icon"] == "maintainerr.png"


def test_render_homepage_services_uses_host_ip_when_provided():

    output = render_homepage_services(
        make_config("light", custom_services={"jellyfin"}),
        host_ip="192.168.1.50"
    )

    assert "http://192.168.1.50:8096" in output


def test_render_homepage_services_sabnzbd_uses_host_published_port():

    output = render_homepage_services(
        make_config("light", custom_services={"sabnzbd"}),
        host_ip=None
    )

    assert "http://localhost:8081" in output
    assert ":8080" not in output


def test_render_homepage_services_qbittorrent_reachable_even_with_gluetun():

    output = render_homepage_services(
        make_config("medium", custom_services={"qbittorrent", "gluetun"}),
        host_ip=None
    )

    assert "http://localhost:8080" in output


def test_render_homepage_services_uses_traefik_domain_when_routed():

    output = render_homepage_services(
        make_config(
            "heavy",
            custom_services={"jellyfin", "traefik"},
            domain="media.example.com"
        ),
        host_ip=None
    )

    assert "https://jellyfin.media.example.com" in output
    assert "http://localhost" not in output


def test_render_homepage_services_creates_traefik_dashboard_tile_when_routed():

    output = render_homepage_services(
        make_config("heavy", custom_services={"traefik"}, domain="media.example.com"),
        host_ip=None
    )

    parsed = yaml.safe_load(output)
    group_names = [list(group.keys())[0] for group in parsed]

    assert "Infrastructure" in group_names
    assert "https://traefik.media.example.com" in output


def test_render_homepage_services_omits_traefik_tile_without_domain():
    """
    Traefik's dashboard has no independent host-published port (it's
    routing-only, no --api.insecure=true) - with no domain, there's
    nothing real to link to, so it shouldn't get a dead tile.
    """

    output = render_homepage_services(
        make_config("heavy", custom_services={"traefik"}),
        host_ip=None
    )

    parsed = yaml.safe_load(output)
    assert parsed == []


def test_render_homepage_services_qbittorrent_uses_host_port_not_broken_route_when_gluetun_and_traefik_both_active():
    """
    Regression lock for a real bug found while adding the Traefik
    dashboard tile: qBittorrent's own Traefik labels are skipped
    whenever Gluetun is active (network_mode: service:gluetun has no
    network identity for Traefik's Docker provider to discover), but
    _service_href() didn't know that - with Traefik+domain also
    active, it generated https://qbittorrent.<domain>, a real dead
    link (no matching router exists). It must fall back to the real
    working host-port URL instead, the same URL it already correctly
    uses when Traefik isn't routing at all.
    """

    output = render_homepage_services(
        make_config(
            "heavy",
            custom_services={"qbittorrent", "gluetun", "traefik"},
            domain="media.example.com"
        ),
        host_ip=None
    )

    assert "http://localhost:8080" in output
    assert "https://qbittorrent.media.example.com" not in output


def test_render_homepage_services_omits_empty_groups():

    output = render_homepage_services(
        make_config("light", custom_services={"jellyfin"}),
        host_ip=None
    )

    parsed = yaml.safe_load(output)
    group_names = [list(group.keys())[0] for group in parsed]

    assert group_names == ["Media"]


def test_render_homepage_services_output_is_valid_yaml():

    output = render_homepage_services(
        make_config(
            "heavy",
            custom_services={
                "jellyfin", "radarr", "sonarr", "prowlarr", "qbittorrent",
                "sabnzbd", "jellyseerr", "bazarr", "lidarr", "readarr", "uptime-kuma"
            }
        ),
        host_ip=None
    )

    parsed = yaml.safe_load(output)

    assert isinstance(parsed, list)
    assert len(parsed) == 4


def test_write_stack_writes_files_and_creates_directories(tmp_path):

    media_path = tmp_path / "media-root"
    output_dir = tmp_path / "stack"

    config = GenerationConfig(
        tier=TIERS["medium"],
        media_path=str(media_path),
        puid=1000,
        pgid=1000,
        timezone="UTC",
        enabled_optional=set()
    )

    result = write_stack(config, output_dir=output_dir)

    assert result["success"] is True
    assert result["warnings"] == []

    compose_path = output_dir / "docker-compose.yml"
    env_path = output_dir / ".env"

    assert compose_path.read_text() == render_compose(config)
    assert env_path.read_text() == render_env(config)

    for key in ("jellyfin", "radarr", "sonarr", "prowlarr", "qbittorrent",
                "jellyseerr", "bazarr", "flaresolverr"):
        assert (output_dir / "config" / key).is_dir()

    assert (media_path / "downloads").is_dir()
    assert (media_path / "media" / "movies").is_dir()
    assert (media_path / "media" / "tv").is_dir()
    assert (media_path / "media" / "music").is_dir()
    assert (media_path / "media" / "books").is_dir()


def test_write_stack_warns_when_tailscale_enabled(tmp_path):

    config = GenerationConfig(
        tier=TIERS["heavy"],
        media_path=str(tmp_path / "media-root"),
        puid=1000,
        pgid=1000,
        timezone="UTC",
        enabled_optional={"tailscale"}
    )

    result = write_stack(config, output_dir=tmp_path / "stack")

    assert any("TS_AUTHKEY" in warning for warning in result["warnings"])


def test_write_stack_no_tailscale_warning_when_disabled(tmp_path):

    config = GenerationConfig(
        tier=TIERS["light"],
        media_path=str(tmp_path / "media-root"),
        puid=1000,
        pgid=1000,
        timezone="UTC",
        enabled_optional=set()
    )

    result = write_stack(config, output_dir=tmp_path / "stack")

    assert not any("TS_AUTHKEY" in warning for warning in result["warnings"])


def test_write_stack_warns_when_cloudflare_dns_enabled(tmp_path):

    config = GenerationConfig(
        tier=TIERS["heavy"],
        media_path=str(tmp_path / "media-root"),
        puid=1000,
        pgid=1000,
        timezone="UTC",
        enabled_optional={"traefik"},
        domain="media.example.com",
        cloudflare_dns=True
    )

    result = write_stack(config, output_dir=tmp_path / "stack")

    assert any("CF_DNS_API_TOKEN" in warning for warning in result["warnings"])


def test_write_stack_warns_when_cloudflare_dns_enabled_without_domain(tmp_path):

    config = GenerationConfig(
        tier=TIERS["heavy"],
        media_path=str(tmp_path / "media-root"),
        puid=1000,
        pgid=1000,
        timezone="UTC",
        enabled_optional={"traefik"},
        cloudflare_dns=True
    )

    result = write_stack(config, output_dir=tmp_path / "stack")

    assert any(
        "isn't routing with a domain configured" in warning for warning in result["warnings"]
    )
    assert not any("CF_DNS_API_TOKEN" in warning for warning in result["warnings"])


def test_write_stack_creates_acme_json_with_correct_permissions(tmp_path):

    config = GenerationConfig(
        tier=TIERS["heavy"],
        media_path=str(tmp_path / "media-root"),
        puid=1000,
        pgid=1000,
        timezone="UTC",
        enabled_optional={"traefik"},
        domain="media.example.com",
        cloudflare_dns=True
    )

    output_dir = tmp_path / "stack"
    write_stack(config, output_dir=output_dir)

    acme_path = output_dir / "config" / "traefik" / "acme.json"

    assert acme_path.exists()
    assert oct(acme_path.stat().st_mode)[-3:] == "600"


def test_write_stack_never_overwrites_existing_acme_json(tmp_path):

    config = GenerationConfig(
        tier=TIERS["heavy"],
        media_path=str(tmp_path / "media-root"),
        puid=1000,
        pgid=1000,
        timezone="UTC",
        enabled_optional={"traefik"},
        domain="media.example.com",
        cloudflare_dns=True
    )

    output_dir = tmp_path / "stack"
    acme_dir = output_dir / "config" / "traefik"
    acme_dir.mkdir(parents=True)
    acme_path = acme_dir / "acme.json"
    acme_path.write_text('{"real": "certificate data"}')
    acme_path.chmod(0o600)

    write_stack(config, output_dir=output_dir)

    assert acme_path.read_text() == '{"real": "certificate data"}'


def test_write_stack_no_acme_json_without_cloudflare_dns(tmp_path):

    config = GenerationConfig(
        tier=TIERS["heavy"],
        media_path=str(tmp_path / "media-root"),
        puid=1000,
        pgid=1000,
        timezone="UTC",
        enabled_optional={"traefik"},
        domain="media.example.com"
    )

    output_dir = tmp_path / "stack"
    write_stack(config, output_dir=output_dir)

    assert not (output_dir / "config" / "traefik" / "acme.json").exists()


def test_write_stack_warns_for_readarr(tmp_path):

    config = GenerationConfig(
        tier=TIERS["heavy"],
        media_path=str(tmp_path / "media-root"),
        puid=1000,
        pgid=1000,
        timezone="UTC",
        enabled_optional=set(),
        custom_services={"readarr"}
    )

    result = write_stack(config, output_dir=tmp_path / "stack")

    assert any("pre-release nightly build" in warning for warning in result["warnings"])
    assert any("Recyclarr does not support Readarr" in warning for warning in result["warnings"])


def test_write_stack_warns_for_nvidia_gpu(tmp_path):

    config = GenerationConfig(
        tier=TIERS["heavy"],
        media_path=str(tmp_path / "media-root"),
        puid=1000,
        pgid=1000,
        timezone="UTC",
        enabled_optional=set(),
        gpu_vendor="nvidia"
    )

    result = write_stack(config, output_dir=tmp_path / "stack")

    assert any("nvidia-container-toolkit" in warning for warning in result["warnings"])
    assert any(
        "https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html" in warning
        for warning in result["warnings"]
    )


def test_write_stack_no_gpu_warning_for_amd(tmp_path):

    with patch("installer.generate.detect_render_group_gid", return_value=105):

        config = GenerationConfig(
            tier=TIERS["heavy"],
            media_path=str(tmp_path / "media-root"),
            puid=1000,
            pgid=1000,
            timezone="UTC",
            enabled_optional=set(),
            gpu_vendor="amd"
        )

        result = write_stack(config, output_dir=tmp_path / "stack")

    assert not any("nvidia" in warning.lower() for warning in result["warnings"])


def test_write_stack_warns_when_gluetun_enabled(tmp_path):

    config = GenerationConfig(
        tier=TIERS["medium"],
        media_path=str(tmp_path / "media-root"),
        puid=1000,
        pgid=1000,
        timezone="UTC",
        enabled_optional={"gluetun"}
    )

    result = write_stack(config, output_dir=tmp_path / "stack")

    assert result["warnings"] != []
    assert "gluetun" in result["warnings"][0].lower()


def test_write_stack_warns_when_sabnzbd_enabled(tmp_path):

    config = GenerationConfig(
        tier=TIERS["light"],
        media_path=str(tmp_path / "media-root"),
        puid=1000,
        pgid=1000,
        timezone="UTC",
        enabled_optional={"sabnzbd"}
    )

    result = write_stack(config, output_dir=tmp_path / "stack")

    assert result["warnings"] != []
    assert any("sabnzbd" in warning.lower() for warning in result["warnings"])
    assert (tmp_path / "stack" / "config" / "sabnzbd").is_dir()


def test_write_stack_warns_when_sabnzbd_enabled_via_custom_services(tmp_path):

    config = GenerationConfig(
        tier=TIERS["light"],
        media_path=str(tmp_path / "media-root"),
        puid=1000,
        pgid=1000,
        timezone="UTC",
        enabled_optional=set(),
        custom_services={"jellyfin", "sabnzbd"}
    )

    result = write_stack(config, output_dir=tmp_path / "stack")

    assert any("sabnzbd" in warning.lower() for warning in result["warnings"])


def test_write_stack_no_sabnzbd_warning_when_disabled(tmp_path):

    config = GenerationConfig(
        tier=TIERS["light"],
        media_path=str(tmp_path / "media-root"),
        puid=1000,
        pgid=1000,
        timezone="UTC",
        enabled_optional=set()
    )

    result = write_stack(config, output_dir=tmp_path / "stack")

    assert result["warnings"] == []


def test_write_stack_warns_when_recyclarr_enabled(tmp_path):

    config = GenerationConfig(
        tier=TIERS["light"],
        media_path=str(tmp_path / "media-root"),
        puid=1000,
        pgid=1000,
        timezone="UTC",
        enabled_optional={"recyclarr"}
    )

    result = write_stack(config, output_dir=tmp_path / "stack")

    assert result["warnings"] != []
    assert any("recyclarr" in warning.lower() for warning in result["warnings"])
    assert (tmp_path / "stack" / "config" / "recyclarr").is_dir()


def test_write_stack_warns_when_recyclarr_enabled_via_custom_services(tmp_path):

    config = GenerationConfig(
        tier=TIERS["light"],
        media_path=str(tmp_path / "media-root"),
        puid=1000,
        pgid=1000,
        timezone="UTC",
        enabled_optional=set(),
        custom_services={"jellyfin", "radarr", "sonarr", "recyclarr"}
    )

    result = write_stack(config, output_dir=tmp_path / "stack")

    assert any("recyclarr" in warning.lower() for warning in result["warnings"])


def test_write_stack_no_recyclarr_warning_when_disabled(tmp_path):

    config = GenerationConfig(
        tier=TIERS["light"],
        media_path=str(tmp_path / "media-root"),
        puid=1000,
        pgid=1000,
        timezone="UTC",
        enabled_optional=set()
    )

    result = write_stack(config, output_dir=tmp_path / "stack")

    assert result["warnings"] == []


def test_write_stack_creates_decluttarr_config_on_first_generate(tmp_path):

    config = GenerationConfig(
        tier=TIERS["light"],
        media_path=str(tmp_path / "media-root"),
        puid=1000,
        pgid=1000,
        timezone="UTC",
        enabled_optional={"decluttarr"}
    )

    result = write_stack(config, output_dir=tmp_path / "stack")

    config_path = tmp_path / "stack" / "config" / "decluttarr" / "config.yaml"
    assert config_path.is_file()
    assert any("CHANGEME" in warning for warning in result["warnings"])
    assert any("test_run: true" in warning for warning in result["warnings"])


def test_write_stack_warns_when_decluttarr_enabled_via_custom_services(tmp_path):

    config = GenerationConfig(
        tier=TIERS["light"],
        media_path=str(tmp_path / "media-root"),
        puid=1000,
        pgid=1000,
        timezone="UTC",
        enabled_optional=set(),
        custom_services={"jellyfin", "radarr", "sonarr", "decluttarr"}
    )

    result = write_stack(config, output_dir=tmp_path / "stack")

    assert any("decluttarr" in warning.lower() for warning in result["warnings"])


def test_write_stack_no_decluttarr_warning_when_disabled(tmp_path):

    config = GenerationConfig(
        tier=TIERS["light"],
        media_path=str(tmp_path / "media-root"),
        puid=1000,
        pgid=1000,
        timezone="UTC",
        enabled_optional=set()
    )

    result = write_stack(config, output_dir=tmp_path / "stack")

    assert result["warnings"] == []


def test_write_stack_never_overwrites_existing_decluttarr_config(tmp_path):

    config = GenerationConfig(
        tier=TIERS["light"],
        media_path=str(tmp_path / "media-root"),
        puid=1000,
        pgid=1000,
        timezone="UTC",
        enabled_optional={"decluttarr"}
    )

    write_stack(config, output_dir=tmp_path / "stack")

    config_path = tmp_path / "stack" / "config" / "decluttarr" / "config.yaml"
    config_path.write_text("# hand-edited, real API keys filled in\n")

    write_stack(config, output_dir=tmp_path / "stack")

    assert config_path.read_text() == "# hand-edited, real API keys filled in\n"


def test_write_stack_warns_when_maintainerr_enabled(tmp_path):
    """
    Unlike Decluttarr/Recyclarr, Maintainerr has no config file for
    Vulcan to pre-seed at all - the warning is purely a "go do the
    one-time setup wizard" pointer, the same shape the Uptime Kuma
    reference warning already established.
    """

    config = GenerationConfig(
        tier=TIERS["light"],
        media_path=str(tmp_path / "media-root"),
        puid=1000,
        pgid=1000,
        timezone="UTC",
        enabled_optional={"maintainerr"}
    )

    result = write_stack(config, output_dir=tmp_path / "stack")

    warning = next(w for w in result["warnings"] if "maintainerr" in w.lower())
    assert "one-time setup" in warning
    assert "http://" in warning
    assert not (tmp_path / "stack" / "config" / "maintainerr" / "config.yaml").exists()


def test_write_stack_no_maintainerr_warning_when_disabled(tmp_path):

    config = GenerationConfig(
        tier=TIERS["light"],
        media_path=str(tmp_path / "media-root"),
        puid=1000,
        pgid=1000,
        timezone="UTC",
        enabled_optional=set()
    )

    result = write_stack(config, output_dir=tmp_path / "stack")

    assert result["warnings"] == []


def test_write_stack_warns_when_traefik_domain_configured(tmp_path):

    config = GenerationConfig(
        tier=TIERS["heavy"],
        media_path=str(tmp_path / "media-root"),
        puid=1000,
        pgid=1000,
        timezone="UTC",
        enabled_optional={"traefik"},
        domain="media.example.com"
    )

    result = write_stack(config, output_dir=tmp_path / "stack")

    assert any("media.example.com" in warning for warning in result["warnings"])
    assert any("self-signed certificate" in warning for warning in result["warnings"])
    assert not any("isn't routed through Traefik" in warning for warning in result["warnings"])


def test_write_stack_no_traefik_warning_without_domain(tmp_path):

    config = GenerationConfig(
        tier=TIERS["heavy"],
        media_path=str(tmp_path / "media-root"),
        puid=1000,
        pgid=1000,
        timezone="UTC",
        enabled_optional={"traefik"}
    )

    result = write_stack(config, output_dir=tmp_path / "stack")

    assert not any("traefik" in warning.lower() for warning in result["warnings"])


def test_write_stack_warns_about_qbittorrent_when_traefik_domain_and_gluetun_combined(tmp_path):

    config = GenerationConfig(
        tier=TIERS["heavy"],
        media_path=str(tmp_path / "media-root"),
        puid=1000,
        pgid=1000,
        timezone="UTC",
        enabled_optional={"traefik", "gluetun"},
        domain="media.example.com"
    )

    result = write_stack(config, output_dir=tmp_path / "stack")

    assert any("qbittorrent" in warning.lower() for warning in result["warnings"])
    assert any("network_mode" in warning for warning in result["warnings"])


def test_write_stack_creates_homepage_services_yaml_on_first_generate(tmp_path):

    config = GenerationConfig(
        tier=TIERS["heavy"],
        media_path=str(tmp_path / "media-root"),
        puid=1000,
        pgid=1000,
        timezone="UTC",
        enabled_optional={"homepage"}
    )

    with patch("installer.generate.detect_host_ip", return_value="192.168.1.50"):
        result = write_stack(config, output_dir=tmp_path / "stack")

    services_yaml_path = tmp_path / "stack" / "config" / "homepage" / "services.yaml"

    assert services_yaml_path.is_file()
    assert "192.168.1.50" in services_yaml_path.read_text()
    assert any("pre-seeded" in warning for warning in result["warnings"])


def test_write_stack_no_homepage_services_yaml_when_disabled(tmp_path):

    config = GenerationConfig(
        tier=TIERS["light"],
        media_path=str(tmp_path / "media-root"),
        puid=1000,
        pgid=1000,
        timezone="UTC",
        enabled_optional=set()
    )

    result = write_stack(config, output_dir=tmp_path / "stack")

    services_yaml_path = tmp_path / "stack" / "config" / "homepage" / "services.yaml"

    assert not services_yaml_path.exists()
    assert not any("pre-seeded" in warning for warning in result["warnings"])


def test_write_stack_never_overwrites_existing_homepage_services_yaml(tmp_path):

    config = GenerationConfig(
        tier=TIERS["heavy"],
        media_path=str(tmp_path / "media-root"),
        puid=1000,
        pgid=1000,
        timezone="UTC",
        enabled_optional={"homepage"}
    )

    with patch("installer.generate.detect_host_ip", return_value="192.168.1.50"):
        write_stack(config, output_dir=tmp_path / "stack")

    services_yaml_path = tmp_path / "stack" / "config" / "homepage" / "services.yaml"
    services_yaml_path.write_text("# hand-edited by the user\n- My Group: []\n")

    with patch("installer.generate.detect_host_ip", return_value="192.168.1.50"):
        result = write_stack(config, output_dir=tmp_path / "stack")

    assert services_yaml_path.read_text() == "# hand-edited by the user\n- My Group: []\n"
    assert not any("pre-seeded" in warning for warning in result["warnings"])


def test_write_stack_uptime_kuma_reference_lists_enabled_services(tmp_path):

    config = GenerationConfig(
        tier=TIERS["heavy"],
        media_path=str(tmp_path / "media-root"),
        puid=1000,
        pgid=1000,
        timezone="UTC",
        enabled_optional=set()
    )

    with patch("installer.generate.detect_host_ip", return_value="192.168.1.50"):
        result = write_stack(config, output_dir=tmp_path / "stack")

    kuma_warnings = [w for w in result["warnings"] if "one-time setup" in w]
    assert len(kuma_warnings) == 1

    reference = kuma_warnings[0]
    assert "http://192.168.1.50:3001" in reference
    assert "Radarr: http://192.168.1.50:7878" in reference
    assert "Sonarr: http://192.168.1.50:8989" in reference
    assert "Uptime Kuma: " not in reference


def test_write_stack_uptime_kuma_reference_uses_traefik_domain(tmp_path):

    config = GenerationConfig(
        tier=TIERS["heavy"],
        media_path=str(tmp_path / "media-root"),
        puid=1000,
        pgid=1000,
        timezone="UTC",
        enabled_optional={"traefik"},
        domain="media.example.com"
    )

    result = write_stack(config, output_dir=tmp_path / "stack")

    kuma_warnings = [w for w in result["warnings"] if "one-time setup" in w]
    assert len(kuma_warnings) == 1

    reference = kuma_warnings[0]
    assert "https://uptime-kuma.media.example.com" in reference
    assert "Radarr: https://radarr.media.example.com" in reference
    assert "http://" not in reference


def test_write_stack_no_uptime_kuma_reference_when_disabled(tmp_path):

    config = GenerationConfig(
        tier=TIERS["light"],
        media_path=str(tmp_path / "media-root"),
        puid=1000,
        pgid=1000,
        timezone="UTC",
        enabled_optional=set()
    )

    result = write_stack(config, output_dir=tmp_path / "stack")

    assert not any("one-time setup" in warning for warning in result["warnings"])


def test_render_stack_summary_lists_homepage_first_when_enabled():

    output = render_stack_summary(
        make_config("heavy", custom_services={"homepage", "jellyfin", "radarr"}),
        host_ip="192.168.1.50"
    )

    lines = output.splitlines()

    assert lines[0] == "  Homepage (dashboard): http://192.168.1.50:3000"
    assert "  Jellyfin: http://192.168.1.50:8096" in lines
    assert "  Radarr: http://192.168.1.50:7878" in lines


def test_render_stack_summary_omits_homepage_when_disabled():

    output = render_stack_summary(
        make_config("heavy", custom_services={"jellyfin", "radarr"}),
        host_ip="192.168.1.50"
    )

    assert "Homepage" not in output
    assert "  Jellyfin: http://192.168.1.50:8096" in output
    assert "  Radarr: http://192.168.1.50:7878" in output


def test_render_stack_summary_uses_traefik_domain():

    output = render_stack_summary(
        make_config(
            "heavy",
            custom_services={"homepage", "jellyfin", "traefik"},
            domain="media.example.com"
        ),
        host_ip="192.168.1.50"
    )

    assert "Homepage (dashboard): https://homepage.media.example.com" in output
    assert "Jellyfin: https://jellyfin.media.example.com" in output
    assert "http://" not in output


def test_render_stack_summary_excludes_non_web_facing_services():

    output = render_stack_summary(
        make_config(
            "heavy",
            custom_services={"jellyfin", "recyclarr", "watchtower", "gluetun", "flaresolverr"}
        ),
        host_ip="192.168.1.50"
    )

    assert "Recyclarr" not in output
    assert "Watchtower" not in output
    assert "Gluetun" not in output
    assert "FlareSolverr" not in output
    assert "  Jellyfin: http://192.168.1.50:8096" in output


def test_default_timezone_reads_etc_timezone():

    with patch("installer.generate.Path") as mock_path_cls:

        mock_path_cls.return_value.read_text.return_value = "America/New_York\n"

        assert default_timezone() == "America/New_York"


def test_default_timezone_falls_back_to_localtime_symlink():

    def path_side_effect(arg):

        mock = MagicMock()

        if arg == "/etc/timezone":
            mock.read_text.side_effect = OSError("no such file")
        elif arg == "/etc/localtime":
            mock.resolve.return_value = MagicMock(
                __str__=lambda self: "/usr/share/zoneinfo/Europe/London"
            )

        return mock

    with patch("installer.generate.Path", side_effect=path_side_effect):

        assert default_timezone() == "Europe/London"


def test_default_timezone_falls_back_to_utc():

    def path_side_effect(arg):

        mock = MagicMock()

        if arg == "/etc/timezone":
            mock.read_text.side_effect = OSError("no such file")
        elif arg == "/etc/localtime":
            mock.resolve.side_effect = OSError("no such file")

        return mock

    with patch("installer.generate.Path", side_effect=path_side_effect):

        assert default_timezone() == "UTC"


def test_save_and_load_previous_state_round_trip(tmp_path):

    config = GenerationConfig(
        tier=TIERS["heavy"],
        media_path="/mnt/media",
        puid=1000,
        pgid=1000,
        timezone="America/New_York",
        enabled_optional={"lidarr", "readarr", "traefik"},
        gpu_vendor="amd"
    )

    save_state(config, tmp_path)
    state = load_previous_state(tmp_path)

    assert state["tier"] == "heavy"
    assert state["media_path"] == "/mnt/media"
    assert state["puid"] == 1000
    assert state["pgid"] == 1000
    assert state["timezone"] == "America/New_York"
    assert sorted(state["enabled_optional"]) == ["lidarr", "readarr", "traefik"]
    assert state["gpu_vendor"] == "amd"
    assert state["custom_services"] is None
    assert "generated_at" in state


def test_save_and_load_previous_state_round_trips_port_overrides(tmp_path):

    config = GenerationConfig(
        tier=TIERS["light"],
        media_path="/mnt/media",
        puid=1000,
        pgid=1000,
        timezone="UTC",
        port_overrides={"jellyfin": 9096, "qbittorrent": 9080}
    )

    save_state(config, tmp_path)
    state = load_previous_state(tmp_path)

    assert state["port_overrides"] == {"jellyfin": 9096, "qbittorrent": 9080}


def test_save_and_load_previous_state_round_trips_custom_services(tmp_path):

    config = GenerationConfig(
        tier=TIERS["light"],
        media_path="/mnt/media",
        puid=1000,
        pgid=1000,
        timezone="UTC",
        custom_services={"jellyfin", "homepage", "watchtower"}
    )

    save_state(config, tmp_path)
    state = load_previous_state(tmp_path)

    assert sorted(state["custom_services"]) == ["homepage", "jellyfin", "watchtower"]


def test_load_previous_state_missing_file_returns_none(tmp_path):

    assert load_previous_state(tmp_path) is None


def test_load_previous_state_corrupt_json_returns_none(tmp_path):

    (tmp_path / ".vulcan-state.json").write_text("{not valid json")

    assert load_previous_state(tmp_path) is None


def test_load_previous_state_unknown_tier_returns_none(tmp_path):

    (tmp_path / ".vulcan-state.json").write_text('{"tier": "ultra"}')

    assert load_previous_state(tmp_path) is None


def test_render_env_defaults_match_original_placeholders():

    output = render_env(make_config("medium", {"gluetun"}))

    assert "VPN_SERVICE_PROVIDER=changeme" in output
    assert "VPN_TYPE=wireguard" in output
    assert "WIREGUARD_PRIVATE_KEY=changeme" in output


def test_render_env_accepts_preserved_vpn_values():

    output = render_env(
        make_config("medium", {"gluetun"}),
        vpn_service_provider="mullvad",
        vpn_type="wireguard",
        wireguard_private_key="real-secret-key-value"
    )

    assert "VPN_SERVICE_PROVIDER=mullvad" in output
    assert "WIREGUARD_PRIVATE_KEY=real-secret-key-value" in output
    assert "changeme" not in output


def test_write_stack_preserves_real_vpn_credentials_on_regenerate(tmp_path):

    media_path = tmp_path / "media-root"
    output_dir = tmp_path / "stack"
    output_dir.mkdir()

    (output_dir / ".env").write_text(
        "MEDIA_PATH=/old/path\n"
        "PUID=1000\n"
        "PGID=1000\n"
        "TZ=UTC\n"
        "VPN_SERVICE_PROVIDER=mullvad\n"
        "VPN_TYPE=wireguard\n"
        "WIREGUARD_PRIVATE_KEY=a-real-private-key\n"
    )

    config = GenerationConfig(
        tier=TIERS["heavy"],
        media_path=str(media_path),
        puid=1000,
        pgid=1000,
        timezone="UTC",
        enabled_optional={"gluetun"}
    )

    write_stack(config, output_dir=output_dir)

    env_content = (output_dir / ".env").read_text()

    assert "VPN_SERVICE_PROVIDER=mullvad" in env_content
    assert "WIREGUARD_PRIVATE_KEY=a-real-private-key" in env_content

    state = load_previous_state(output_dir)
    assert state["tier"] == "heavy"


def test_write_stack_does_not_preserve_placeholder_vpn_values(tmp_path):

    media_path = tmp_path / "media-root"
    output_dir = tmp_path / "stack"
    output_dir.mkdir()

    (output_dir / ".env").write_text(
        "MEDIA_PATH=/old/path\n"
        "PUID=1000\n"
        "PGID=1000\n"
        "TZ=UTC\n"
        "VPN_SERVICE_PROVIDER=changeme\n"
        "VPN_TYPE=wireguard\n"
        "WIREGUARD_PRIVATE_KEY=changeme\n"
    )

    config = GenerationConfig(
        tier=TIERS["medium"],
        media_path=str(media_path),
        puid=1000,
        pgid=1000,
        timezone="UTC",
        enabled_optional={"gluetun"}
    )

    write_stack(config, output_dir=output_dir)

    env_content = (output_dir / ".env").read_text()

    assert "VPN_SERVICE_PROVIDER=changeme" in env_content
    assert "WIREGUARD_PRIVATE_KEY=changeme" in env_content


def test_write_stack_writes_state_file(tmp_path):

    config = GenerationConfig(
        tier=TIERS["light"],
        media_path=str(tmp_path / "media-root"),
        puid=1000,
        pgid=1000,
        timezone="UTC"
    )

    write_stack(config, output_dir=tmp_path / "stack")

    state = load_previous_state(tmp_path / "stack")

    assert state is not None
    assert state["tier"] == "light"


def test_render_authelia_users_database_output_shape():

    output = render_authelia_users_database("admin", "admin", "$argon2id$fake$hash")
    parsed = yaml.safe_load(output)

    assert parsed["users"]["admin"]["password"] == "$argon2id$fake$hash"
    assert parsed["users"]["admin"]["displayname"] == "admin"
    assert parsed["users"]["admin"]["disabled"] is False
    assert parsed["users"]["admin"]["groups"] == ["admins"]


def test_render_authelia_configuration_uses_domain_for_session_cookie():

    output = render_authelia_configuration(
        make_config("heavy", custom_services={"authelia", "traefik"}, domain="media.example.com")
    )
    parsed = yaml.safe_load(output)

    cookie = parsed["session"]["cookies"][0]
    assert cookie["domain"] == "media.example.com"
    assert cookie["authelia_url"] == "https://authelia.media.example.com"
    assert "default_redirection_url" not in cookie
    assert parsed["access_control"]["default_policy"] == "one_factor"
    assert "rules" not in parsed["access_control"]
    assert "jwt_secret" not in parsed.get("identity_validation", {}).get("reset_password", {})
    assert "secret" not in parsed["session"]
    assert "encryption_key" not in parsed["storage"]


def test_render_decluttarr_config_includes_only_enabled_arr_instances():

    output = render_decluttarr_config(
        make_config("light", custom_services={"decluttarr", "radarr", "sonarr"})
    )
    parsed = yaml.safe_load(output)

    assert "radarr" in parsed["instances"]
    assert "sonarr" in parsed["instances"]
    assert "lidarr" not in parsed["instances"]
    assert "readarr" not in parsed["instances"]
    assert parsed["instances"]["radarr"][0]["base_url"] == "http://radarr:7878"
    assert parsed["instances"]["radarr"][0]["api_key"] == "CHANGEME"


def test_render_decluttarr_config_defaults_to_dry_run():

    output = render_decluttarr_config(make_config("light", {"decluttarr"}))
    parsed = yaml.safe_load(output)

    assert parsed["general"]["test_run"] is True


def test_render_decluttarr_config_qbittorrent_uses_gluetun_hostname_when_active():

    output = render_decluttarr_config(
        make_config("light", custom_services={"decluttarr", "radarr", "sonarr", "qbittorrent", "gluetun"})
    )
    parsed = yaml.safe_load(output)

    assert parsed["download_clients"]["qbittorrent"][0]["base_url"] == "http://gluetun:8080"


def test_render_decluttarr_config_qbittorrent_uses_own_hostname_without_gluetun():

    output = render_decluttarr_config(
        make_config("light", custom_services={"decluttarr", "radarr", "sonarr", "qbittorrent"})
    )
    parsed = yaml.safe_load(output)

    assert parsed["download_clients"]["qbittorrent"][0]["base_url"] == "http://qbittorrent:8080"


def test_render_decluttarr_config_includes_sabnzbd_when_enabled():

    output = render_decluttarr_config(
        make_config("light", custom_services={"decluttarr", "radarr", "sonarr", "sabnzbd"})
    )
    parsed = yaml.safe_load(output)

    assert parsed["download_clients"]["sabnzbd"][0]["base_url"] == "http://sabnzbd:8080"
    assert parsed["download_clients"]["sabnzbd"][0]["api_key"] == "CHANGEME"


def test_render_decluttarr_config_omits_download_clients_when_none_enabled():

    output = render_decluttarr_config(
        make_config("light", custom_services={"decluttarr", "radarr", "sonarr"})
    )
    parsed = yaml.safe_load(output)

    assert "download_clients" not in parsed


def test_render_authelia_configuration_redirects_to_homepage_when_enabled():

    output = render_authelia_configuration(
        make_config(
            "heavy",
            custom_services={"authelia", "traefik", "homepage"},
            domain="media.example.com"
        )
    )
    parsed = yaml.safe_load(output)

    assert parsed["session"]["cookies"][0]["default_redirection_url"] == "https://homepage.media.example.com"


def test_write_stack_creates_authelia_files_on_first_generate(tmp_path):

    config = GenerationConfig(
        tier=TIERS["heavy"],
        media_path=str(tmp_path / "media-root"),
        puid=1000,
        pgid=1000,
        timezone="UTC",
        enabled_optional={"authelia", "traefik"},
        domain="media.example.com",
        auth_username="admin",
        auth_password_hash="$argon2id$fake$hash"
    )

    write_stack(config, output_dir=tmp_path / "stack")

    authelia_dir = tmp_path / "stack" / "config" / "authelia"

    assert (authelia_dir / "configuration.yml").is_file()
    assert (authelia_dir / "users_database.yml").is_file()
    assert (authelia_dir / "secrets" / "JWT_SECRET").is_file()
    assert (authelia_dir / "secrets" / "SESSION_SECRET").is_file()
    assert (authelia_dir / "secrets" / "STORAGE_ENCRYPTION_KEY").is_file()

    parsed = yaml.safe_load((authelia_dir / "users_database.yml").read_text())
    assert parsed["users"]["admin"]["password"] == "$argon2id$fake$hash"


def test_write_stack_never_overwrites_existing_authelia_files(tmp_path):

    config = GenerationConfig(
        tier=TIERS["heavy"],
        media_path=str(tmp_path / "media-root"),
        puid=1000,
        pgid=1000,
        timezone="UTC",
        enabled_optional={"authelia", "traefik"},
        domain="media.example.com",
        auth_username="admin",
        auth_password_hash="$argon2id$fake$hash"
    )

    write_stack(config, output_dir=tmp_path / "stack")

    authelia_dir = tmp_path / "stack" / "config" / "authelia"
    users_database_path = authelia_dir / "users_database.yml"
    configuration_path = authelia_dir / "configuration.yml"
    jwt_secret_path = authelia_dir / "secrets" / "JWT_SECRET"

    users_database_path.write_text("# hand-edited\nusers: {}\n")
    configuration_path.write_text("# hand-edited\n")
    original_secret = jwt_secret_path.read_text()

    # A regenerate with no username/hash (mirrors a real second run, where
    # the CLI/TUI skip prompting entirely once users_database.yml exists).
    second_config = GenerationConfig(
        tier=TIERS["heavy"],
        media_path=str(tmp_path / "media-root"),
        puid=1000,
        pgid=1000,
        timezone="UTC",
        enabled_optional={"authelia", "traefik"},
        domain="media.example.com"
    )

    write_stack(second_config, output_dir=tmp_path / "stack")

    assert users_database_path.read_text() == "# hand-edited\nusers: {}\n"
    assert configuration_path.read_text() == "# hand-edited\n"
    assert jwt_secret_path.read_text() == original_secret


def test_write_stack_warns_when_authelia_enabled_without_traefik_domain(tmp_path):

    config = GenerationConfig(
        tier=TIERS["heavy"],
        media_path=str(tmp_path / "media-root"),
        puid=1000,
        pgid=1000,
        timezone="UTC",
        enabled_optional={"authelia"},
        auth_username="admin",
        auth_password_hash="$argon2id$fake$hash"
    )

    result = write_stack(config, output_dir=tmp_path / "stack")

    assert any("nothing is actually protected" in warning for warning in result["warnings"])


def test_write_stack_no_authelia_warning_when_traefik_and_domain_active(tmp_path):

    config = GenerationConfig(
        tier=TIERS["heavy"],
        media_path=str(tmp_path / "media-root"),
        puid=1000,
        pgid=1000,
        timezone="UTC",
        enabled_optional={"authelia", "traefik"},
        domain="media.example.com",
        auth_username="admin",
        auth_password_hash="$argon2id$fake$hash"
    )

    result = write_stack(config, output_dir=tmp_path / "stack")

    assert not any("nothing is actually protected" in warning for warning in result["warnings"])


def test_write_stack_warns_about_unprotected_traefik_dashboard_without_authelia(tmp_path):

    config = GenerationConfig(
        tier=TIERS["heavy"],
        media_path=str(tmp_path / "media-root"),
        puid=1000,
        pgid=1000,
        timezone="UTC",
        enabled_optional={"traefik"},
        domain="media.example.com"
    )

    result = write_stack(config, output_dir=tmp_path / "stack")

    assert any(
        "traefik.media.example.com" in warning and "no login" in warning
        for warning in result["warnings"]
    )


def test_write_stack_no_dashboard_warning_when_authelia_also_enabled(tmp_path):

    config = GenerationConfig(
        tier=TIERS["heavy"],
        media_path=str(tmp_path / "media-root"),
        puid=1000,
        pgid=1000,
        timezone="UTC",
        enabled_optional={"traefik", "authelia"},
        domain="media.example.com",
        auth_username="admin",
        auth_password_hash="$argon2id$fake$hash"
    )

    result = write_stack(config, output_dir=tmp_path / "stack")

    assert not any("no login in front of it" in warning for warning in result["warnings"])


def test_write_stack_no_dashboard_warning_without_domain(tmp_path):

    config = GenerationConfig(
        tier=TIERS["heavy"],
        media_path=str(tmp_path / "media-root"),
        puid=1000,
        pgid=1000,
        timezone="UTC",
        enabled_optional={"traefik"}
    )

    result = write_stack(config, output_dir=tmp_path / "stack")

    assert not any("no login in front of it" in warning for warning in result["warnings"])


def test_render_homepage_services_creates_authelia_tile_when_routed():

    output = render_homepage_services(
        make_config(
            "heavy",
            custom_services={"authelia", "traefik"},
            domain="media.example.com"
        ),
        host_ip=None
    )

    groups = _homepage_groups(output)

    assert groups["Security"]["Authentication (Authelia)"]["href"] == "https://authelia.media.example.com"
