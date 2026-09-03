import re
from unittest.mock import MagicMock, patch

import yaml

from installer.generate import (
    TEMPLATES_DIR,
    WALKTHROUGH_URL,
    WEB_FACING_SERVICES,
    GenerationConfig,
    _HOMEPAGE_GROUPS,
    default_puid_pgid,
    default_timezone,
    enabled_service_keys,
    load_previous_state,
    render_authelia_configuration,
    render_authelia_users_database,
    render_compose,
    render_decluttarr_config,
    render_env,
    render_dashy_config,
    render_homepage_services,
    render_setup_order,
    render_stack_summary,
    resolve_ports,
    save_state,
    write_stack,
)
from installer.tiers import ALL_SERVICES, TIERS


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
    auth_users: list[dict] | None = None,
    port_overrides: dict[str, int] | None = None,
    homepage_private: bool = False,
    dashy_private: bool = False
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
        auth_users=auth_users or [],
        port_overrides=port_overrides or {},
        homepage_private=homepage_private,
        dashy_private=dashy_private
    )


def test_default_puid_pgid_reads_real_ids():

    with patch("installer.generate.os.getuid", return_value=1001), patch(
        "installer.generate.os.getgid", return_value=1002
    ):

        assert default_puid_pgid() == (1001, 1002)


def test_enabled_service_keys_light_tier():

    keys = enabled_service_keys(make_config("light"))

    assert keys == {"jellyfin", "radarr", "sonarr", "prowlarr", "qbittorrent", "filebrowser"}


def test_enabled_service_keys_medium_without_gluetun():

    keys = enabled_service_keys(make_config("medium"))

    assert keys == {
        "jellyfin", "radarr", "sonarr", "prowlarr", "qbittorrent",
        "seerr", "bazarr", "flaresolverr", "filebrowser"
    }


def test_enabled_service_keys_medium_with_gluetun():

    keys = enabled_service_keys(make_config("medium", {"gluetun"}))

    assert "gluetun" in keys
    assert len(keys) == 10


def test_enabled_service_keys_light_with_sabnzbd():

    keys = enabled_service_keys(make_config("light", {"sabnzbd"}))

    assert "sabnzbd" in keys
    assert len(keys) == 7


def test_enabled_service_keys_light_with_recyclarr():

    keys = enabled_service_keys(make_config("light", {"recyclarr"}))

    assert "recyclarr" in keys
    assert len(keys) == 7


def test_enabled_service_keys_custom_services_overrides_tier_entirely():

    custom = {"jellyfin", "homepage", "watchtower"}
    keys = enabled_service_keys(make_config("light", custom_services=custom))

    assert keys == custom


def test_enabled_service_keys_custom_services_none_falls_back_to_tier():

    keys = enabled_service_keys(make_config("light", custom_services=None))

    assert keys == {"jellyfin", "radarr", "sonarr", "prowlarr", "qbittorrent", "filebrowser"}


def test_render_compose_light_only_includes_light_services():

    output = render_compose(make_config("light"))

    for name in ("jellyfin", "radarr", "sonarr", "prowlarr", "qbittorrent"):
        assert f"container_name: {name}" in output

    for name in ("seerr", "bazarr", "flaresolverr", "gluetun"):
        assert f"container_name: {name}" not in output


def test_render_compose_medium_without_gluetun_gives_qbittorrent_its_own_ports():

    output = render_compose(make_config("medium"))

    assert 'network_mode: "service:gluetun"' not in output
    assert "container_name: gluetun" not in output

    qbittorrent_block = output.split("qbittorrent:", 1)[1].split("seerr:", 1)[0]
    assert "8080:8080" in qbittorrent_block


def test_render_compose_medium_with_gluetun_routes_qbittorrent_through_it():

    output = render_compose(make_config("medium", {"gluetun"}))

    assert "container_name: gluetun" in output

    qbittorrent_block = output.split("qbittorrent:", 1)[1].split("seerr:", 1)[0]
    assert 'network_mode: "service:gluetun"' in qbittorrent_block
    assert "ports:" not in qbittorrent_block
    # Wait for gluetun's VPN to be up, not just its container to exist -
    # otherwise runc can't attach qbittorrent to the shared netns.
    assert "condition: service_healthy" in qbittorrent_block


def test_render_compose_medium_without_sabnzbd_omits_it():

    output = render_compose(make_config("medium"))

    assert "container_name: sabnzbd" not in output


def test_render_compose_medium_with_sabnzbd_uses_remapped_port():

    output = render_compose(make_config("medium", {"sabnzbd"}))

    assert "container_name: sabnzbd" in output

    sabnzbd_block = output.split("sabnzbd:", 1)[1].split("seerr:", 1)[0]
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

    recyclarr_block = output.split("recyclarr:", 1)[1].split("seerr:", 1)[0]
    assert "image: ghcr.io/recyclarr/recyclarr:8" in recyclarr_block
    assert 'user: "${PUID}:${PGID}"' in recyclarr_block
    assert "PUID=${PUID}" not in recyclarr_block


def test_render_compose_medium_without_decluttarr_omits_it():

    output = render_compose(make_config("medium"))

    assert "container_name: decluttarr" not in output


def test_render_compose_medium_with_decluttarr_mounts_config():

    output = render_compose(make_config("medium", {"decluttarr"}))

    decluttarr_block = _service_block(output, "decluttarr", "seerr")
    assert "image: ghcr.io/manimatter/decluttarr:latest" in decluttarr_block
    assert "./config/decluttarr/config.yaml:/app/config/config.yaml" in decluttarr_block


def test_render_compose_medium_without_maintainerr_omits_it():

    output = render_compose(make_config("medium"))

    assert "container_name: maintainerr" not in output


def test_render_compose_medium_with_maintainerr_mounts_media_and_config():

    output = render_compose(make_config("medium", {"maintainerr"}))

    maintainerr_block = _service_block(output, "maintainerr", "seerr")
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

    maintainerr_block = _service_block(output, "maintainerr", "seerr")
    assert '"7246:6246"' in maintainerr_block


def test_render_compose_heavy_includes_all_new_services():

    output = render_compose(
        make_config("heavy", enabled_optional={
            "lidarr", "readarr", "traefik", "homepage", "uptime-kuma", "watchtower"
        })
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
            enabled_optional={"traefik", "lidarr", "readarr", "homepage", "uptime-kuma"},
            domain="media.example.com"
        )
    )

    expected_ports = {
        "jellyfin": 8096,
        "radarr": 7878,
        "sonarr": 8989,
        "prowlarr": 9696,
        "seerr": 5055,
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

    qbittorrent_block = _service_block(output, "qbittorrent", "seerr")
    assert "traefik.http.routers.qbittorrent.rule=Host(`qbittorrent.media.example.com`)" in qbittorrent_block
    assert "traefik.http.services.qbittorrent.loadbalancer.server.port=8080" in qbittorrent_block


def test_render_compose_qbittorrent_not_routed_when_gluetun_enabled():

    output = render_compose(
        make_config(
            "heavy", enabled_optional={"traefik", "gluetun"}, domain="media.example.com"
        )
    )

    qbittorrent_block = _service_block(output, "qbittorrent", "seerr")
    assert "traefik" not in qbittorrent_block

    # every other enabled service still gets routed
    assert "traefik.http.routers.jellyfin.rule" in output


def test_render_compose_sabnzbd_uses_internal_port_not_remapped_host_port():

    output = render_compose(
        make_config("heavy", enabled_optional={"traefik", "sabnzbd"}, domain="media.example.com")
    )

    sabnzbd_block = _service_block(output, "sabnzbd", "seerr")
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


def test_render_compose_crowdsec_creates_service_with_bouncer_middleware():

    output = render_compose(
        make_config("heavy", enabled_optional={"traefik", "crowdsec"}, domain="media.example.com")
    )

    crowdsec_block = _service_block(output, "crowdsec", "watchtower")

    assert "image: crowdsecurity/crowdsec:latest" in crowdsec_block
    assert "COLLECTIONS=crowdsecurity/traefik" in crowdsec_block
    assert "BOUNCER_KEY_TRAEFIK=${CROWDSEC_BOUNCER_KEY}" in crowdsec_block
    assert "traefik.http.middlewares.crowdsec.plugin.bouncer.enabled=true" in crowdsec_block
    assert "traefik.http.middlewares.crowdsec.plugin.bouncer.crowdseclapikey=${CROWDSEC_BOUNCER_KEY}" in crowdsec_block

    traefik_block = _service_block(output, "traefik", "crowdsec")
    assert "--accesslog=true" in traefik_block
    assert "--accesslog.filepath=/var/log/traefik/access.log" in traefik_block
    assert "github.com/maxlerebourg/crowdsec-bouncer-traefik-plugin" in traefik_block
    assert "./config/traefik/logs:/var/log/traefik" in traefik_block


def test_render_compose_omits_crowdsec_when_disabled():

    output = render_compose(make_config("heavy", enabled_optional={"traefik"}, domain="media.example.com"))

    assert "container_name: crowdsec" not in output
    assert "--accesslog" not in output
    assert "crowdsec-bouncer-traefik-plugin" not in output


def test_render_compose_crowdsec_without_traefik_omits_bouncer_wiring():

    output = render_compose(make_config("heavy", enabled_optional={"crowdsec"}))

    # "watchtower" (not "authelia") as the end boundary - authelia isn't
    # enabled in this test, so it wouldn't appear in output at all and
    # the split would run to end-of-file instead of just this block.
    crowdsec_block = _service_block(output, "crowdsec", "watchtower")

    assert "plugin.bouncer" not in crowdsec_block
    assert "depends_on" not in crowdsec_block
    # The engine itself still renders (it's harmless standalone, just
    # has nothing to protect yet - see write_stack()'s own warning for
    # this exact case) - only the Traefik-specific wiring is gated.
    assert "image: crowdsecurity/crowdsec:latest" in crowdsec_block


def test_render_compose_radarr_gets_combined_crowdsec_and_authelia_middlewares():

    output = render_compose(
        make_config(
            "heavy", enabled_optional={"traefik", "crowdsec", "authelia"},
            domain="media.example.com"
        )
    )

    assert "traefik.http.routers.radarr.middlewares=crowdsec@docker,authelia@docker" in output


def test_render_compose_radarr_gets_crowdsec_only_middleware_without_authelia():

    output = render_compose(
        make_config("heavy", enabled_optional={"traefik", "crowdsec"}, domain="media.example.com")
    )

    assert "traefik.http.routers.radarr.middlewares=crowdsec@docker" in output
    assert "authelia@docker" not in output


def test_render_compose_jellyfin_gets_crowdsec_middleware_despite_authelia_exclusion():
    """
    Jellyfin/Vaultwarden are deliberately excluded from authelia@docker
    (native-app browser-redirect conflict), but crowdsec@docker is
    IP-reputation blocking, not an auth challenge - it doesn't share
    that conflict, so both still get it.
    """

    output = render_compose(
        make_config(
            "heavy", enabled_optional={"traefik", "crowdsec", "authelia"},
            domain="media.example.com"
        )
    )

    jellyfin_block = _service_block(output, "jellyfin", "radarr")

    assert "traefik.http.routers.jellyfin.middlewares=crowdsec@docker" in jellyfin_block
    assert "authelia@docker" not in jellyfin_block


def test_render_compose_tailscale_uses_host_networking():

    output = render_compose(make_config("heavy", enabled_optional={"tailscale"}))

    tailscale_block = _service_block(output, "tailscale", "homepage")

    assert "network_mode: host" in tailscale_block
    assert "TS_AUTHKEY=${TS_AUTHKEY}" in tailscale_block
    assert "/dev/net/tun:/dev/net/tun" in tailscale_block
    assert "NET_ADMIN" in tailscale_block
    assert "NET_RAW" in tailscale_block


def test_tailscale_accept_dns_off_when_a_local_dns_server_is_in_the_stack():
    # network_mode: host - TS_ACCEPT_DNS=true would rewrite the host
    # resolver, taking it away from pihole/adguardhome.
    with_pihole = render_compose(make_config("heavy", custom_services={"tailscale", "pihole"}))
    assert "TS_ACCEPT_DNS=false" in _service_block(with_pihole, "tailscale", "homepage")

    solo = render_compose(make_config("heavy", custom_services={"tailscale", "jellyfin"}))
    assert "TS_ACCEPT_DNS=true" in _service_block(solo, "tailscale", "jellyfin")


def test_gluetun_and_tailscale_coexist():
    # container-scoped egress VPN + host-mode ingress mesh - no longer
    # mutually exclusive (installer.cli._SERVICE_CONFLICTS).
    output = render_compose(make_config(
        "heavy", custom_services={"gluetun", "tailscale", "qbittorrent", "jellyfin"}
    ))
    assert "container_name: gluetun" in output
    assert "container_name: tailscale" in output
    assert "network_mode: \"service:gluetun\"" in output  # qbittorrent still routes through gluetun


def test_render_compose_omits_tailscale_when_disabled():

    output = render_compose(make_config("light"))

    assert "container_name: tailscale" not in output


def test_render_compose_cloudflared_points_at_traefik():

    output = render_compose(make_config(
        "heavy", enabled_optional={"traefik", "cloudflared", "crowdsec"}, domain="media.example.com"
    ))

    cloudflared_block = _service_block(output, "cloudflared", "crowdsec")

    assert "cloudflare/cloudflared:latest" in cloudflared_block
    assert "tunnel --no-autoupdate run --token ${TUNNEL_TOKEN}" in cloudflared_block
    assert "depends_on" in cloudflared_block
    assert "- traefik" in cloudflared_block
    assert "ports:" not in cloudflared_block

    assert "--entrypoints.tunnel.address=:8081" in output
    assert "traefik.http.routers.jellyfin.entrypoints=websecure,tunnel" in output


def test_render_compose_omits_tunnel_entrypoint_when_cloudflared_disabled():

    output = render_compose(make_config("heavy", enabled_optional={"traefik"}, domain="media.example.com"))

    assert "container_name: cloudflared" not in output
    assert "entrypoints.tunnel" not in output
    assert "traefik.http.routers.jellyfin.entrypoints=websecure\"" in output


def test_render_compose_metube_and_downtify_mount_into_media_library():

    output = render_compose(make_config("light", enabled_optional={"metube", "downtify"}))

    metube_block = _service_block(output, "metube", "downtify")
    downtify_block = _service_block(output, "downtify", "recyclarr")

    assert "${MEDIA_PATH}/media/youtube:/downloads" in metube_block
    assert "PUID=${PUID}" in metube_block

    assert "${MEDIA_PATH}/media/music/downtify:/downloads" in downtify_block
    assert "./config/downtify:/data" in downtify_block


def test_render_compose_omits_metube_and_downtify_when_disabled():

    output = render_compose(make_config("light"))

    assert "container_name: metube" not in output
    assert "container_name: downtify" not in output


def test_render_compose_netdata_uses_host_networking_and_deep_host_access():

    output = render_compose(make_config("light", enabled_optional={"netdata"}))

    netdata_block = _service_block(output, "netdata", "homepage")

    assert "network_mode: host" in netdata_block
    assert "pid: host" in netdata_block
    assert "SYS_PTRACE" in netdata_block
    assert "SYS_ADMIN" in netdata_block
    assert "apparmor:unconfined" in netdata_block
    assert "/var/run/docker.sock:/var/run/docker.sock:ro" in netdata_block
    assert "/proc:/host/proc:ro" in netdata_block


def test_render_compose_netdata_never_gets_traefik_labels():
    """
    Unlike every other web-facing service, netdata must never get a
    Traefik router block - network_mode: host means it has no Docker-
    network identity for Traefik's provider to discover (the compose
    template has no {% if 'traefik' in enabled %} block for it at all).
    """

    output = render_compose(
        make_config(
            "heavy", enabled_optional={"netdata", "traefik"},
            domain="media.example.com"
        )
    )

    assert "traefik.http.routers.netdata" not in output


def test_render_compose_homepage_private_omits_traefik_labels():

    output = render_compose(
        make_config(
            "heavy", enabled_optional={"homepage", "traefik"},
            domain="media.example.com", homepage_private=True
        )
    )

    assert "traefik.http.routers.homepage" not in output


def test_render_compose_homepage_public_by_default_keeps_traefik_labels():

    output = render_compose(
        make_config(
            "heavy", enabled_optional={"homepage", "traefik"},
            domain="media.example.com"
        )
    )

    assert "traefik.http.routers.homepage.rule=Host(`homepage.media.example.com`)" in output


def test_render_compose_dashy_creates_service_with_no_puid_pgid():

    output = render_compose(make_config("heavy", enabled_optional={"dashy"}))
    block = _service_block(output, "dashy", "uptime-kuma")

    assert "image: lissy93/dashy:latest" in block
    assert "PUID" not in block
    assert "PGID" not in block
    assert "./config/dashy/conf.yml:/app/user-data/conf.yml" in block


def test_render_compose_dashy_gets_authelia_middleware_like_homepage():
    """
    Unlike Jellyfin/Vaultwarden, Dashy has no native mobile/desktop app
    of its own to conflict with Authelia's browser-redirect login -
    it's a plain web dashboard, same as Homepage, so it gets the normal
    authelia@docker middleware when both are enabled.
    """

    output = render_compose(
        make_config(
            "heavy", enabled_optional={"dashy", "authelia", "traefik"},
            domain="media.example.com"
        )
    )
    block = _service_block(output, "dashy", "uptime-kuma")

    assert "authelia@docker" in block


def test_render_compose_dashy_private_omits_traefik_labels():

    output = render_compose(
        make_config(
            "heavy", enabled_optional={"dashy", "traefik"},
            domain="media.example.com", dashy_private=True
        )
    )

    assert "traefik.http.routers.dashy" not in output


def test_render_compose_dashy_public_by_default_keeps_traefik_labels():

    output = render_compose(
        make_config(
            "heavy", enabled_optional={"dashy", "traefik"},
            domain="media.example.com"
        )
    )

    assert "traefik.http.routers.dashy.rule=Host(`dashy.media.example.com`)" in output


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


# --- security_opt: no-new-privileges hardening ---


def test_every_rendered_service_has_no_new_privileges():
    """
    Broad hardening pass (ODS-inspired: it applies this across every
    one of its own services) - no-new-privileges only blocks a process
    from gaining *new* privileges at exec time (e.g. via a setuid
    binary), it doesn't touch capabilities a container already has via
    cap_add/network_mode, so it's safe even for gluetun (NET_ADMIN),
    tailscale (NET_ADMIN/NET_RAW, host networking), and netdata
    (SYS_PTRACE/SYS_ADMIN, host networking) - confirmed by rendering
    every one of them here and parsing the result as real YAML, not
    just grepping the template.
    """

    all_keys = {s.key for s in ALL_SERVICES}
    config = make_config("heavy", custom_services=all_keys, gpu_vendor="nvidia", domain="example.com")

    output = render_compose(config)
    data = yaml.safe_load(output)

    assert set(data["services"].keys()) == all_keys | {"unbound"}

    for name, service in data["services"].items():
        assert "no-new-privileges:true" in service.get("security_opt", []), (
            f"{name} is missing no-new-privileges"
        )


def test_netdata_keeps_apparmor_unconfined_alongside_no_new_privileges():
    """
    Regression lock: netdata already had its own security_opt entry
    (apparmor:unconfined, needed for its deep host-monitoring access) -
    the hardening pass must extend that list, not silently clobber it
    with a second security_opt: key (which real YAML would just let
    the second one win, silently dropping the first).
    """

    output = render_compose(make_config("heavy", {"netdata"}))
    data = yaml.safe_load(output)

    assert data["services"]["netdata"]["security_opt"] == [
        "apparmor:unconfined", "no-new-privileges:true"
    ]


# --- cap_drop: ALL on all 28 services ---
#
# ROADMAP.md's cap_drop entry: deliberately not attempted alongside the
# no-new-privileges pass above, since a blanket drop risks breaking a
# linuxserver.io image's s6-overlay root -> PUID/PGID handoff (or another
# image's own root-level init step), and doing it safely needed real
# container starts to verify, not a guess. Every one of the 28 services was
# tested for real: `docker run --cap-drop=ALL` against the real image
# first, then capabilities iterated back in one at a time until clean
# (checked via docker logs for permission/capability errors, not just
# "did it stay running"). Three shapes emerged:

# The 9 linuxserver.io s6-overlay images, plus 4 other PUID/PGID-style
# images that turned out to need the identical set: an ownership fixup
# (CHOWN/DAC_OVERRIDE/FOWNER) and a root -> PUID/PGID privilege drop
# (SETGID/SETUID).
FIVE_CAP_SERVICES = {
    "jellyfin", "radarr", "sonarr", "prowlarr", "qbittorrent",
    "sabnzbd", "bazarr", "lidarr", "readarr",
    "metube", "authelia", "homepage", "uptime-kuma", "filebrowser",
    "sportarr", "threadfin", "tracearr", "crowdsec",
}
FIVE_CAP_SET = ["CHOWN", "DAC_OVERRIDE", "FOWNER", "SETGID", "SETUID"]

# Plain Go/Node/Python entrypoints that started and ran cleanly with zero
# added capabilities - no privilege-drop or ownership-fixup step to
# support, verified against the real image with no cap_add at all.
ZERO_CAP_SERVICES = {
    "vaultwarden", "recyclarr", "decluttarr", "maintainerr",
    "seerr", "flaresolverr", "traefik", "cloudflared",
    "dashy", "watchtower",
}

# Special-cased services whose real, single-purpose cap_add already existed
# before this pass (VPN tunneling, host mesh networking, host process/cgroup
# monitoring) - each verified under cap_drop: ALL with that existing set,
# not researched from a blank slate.
SPECIAL_CAP_SERVICES = {
    "gluetun": ["NET_ADMIN", "NET_RAW", "DAC_OVERRIDE"],
    "tailscale": ["NET_ADMIN", "NET_RAW"],
    "unbound": ["NET_BIND_SERVICE", "SETGID", "SETUID"],
    "pihole": ["CHOWN", "DAC_OVERRIDE", "FOWNER", "NET_BIND_SERVICE", "NET_ADMIN", "SETGID", "SETUID"],
    # netdata's own apps.plugin/debugfs.plugin log wanting CAP_DAC_READ_SEARCH
    # directly ("should run with...") - without it they degrade silently
    # rather than crash, so adding it is a real functionality gain over the
    # pre-existing SYS_PTRACE/SYS_ADMIN alone, not just noise suppression.
    "netdata": [
        "CHOWN", "DAC_OVERRIDE", "DAC_READ_SEARCH", "FOWNER", "SETGID", "SETUID",
        "SYS_PTRACE", "SYS_ADMIN",
    ],
    # AdGuard Home's binary carries file-based cap_net_bind_service/cap_net_raw
    # (dropped ALL blocks the exec), and its first-run data-dir setup needs
    # DAC_OVERRIDE once ALL is dropped - all three verified live against the
    # real image under cap_drop: ALL + no-new-privileges.
    "adguardhome": ["NET_BIND_SERVICE", "NET_RAW", "DAC_OVERRIDE"],
    # Portainer runs as root and only needs the ownership fixup for its
    # bind-mounted /data (no root->PUID drop, so no SETGID/SETUID) -
    # verified live against a real bind mount under cap_drop: ALL.
    "portainer": ["CHOWN", "DAC_OVERRIDE", "FOWNER"],
    # downtify runs its FastAPI app as root and writes its sqlite DB into
    # the bind-mounted /data - under cap_drop: ALL a root process loses
    # CAP_DAC_OVERRIDE and can't write a dir it doesn't own ("unable to
    # open database file", crash-loop). Verified live: DAC_OVERRIDE alone
    # is enough (it doesn't chown). Found on an Ubuntu homelab; the
    # earlier zero-cap claim had been tested against a managed volume.
    "downtify": ["DAC_OVERRIDE"],
}

ALL_CAPPED_SERVICES = FIVE_CAP_SERVICES | ZERO_CAP_SERVICES | set(SPECIAL_CAP_SERVICES)


def test_five_cap_services_drop_all_and_add_back_the_verified_minimal_set():
    config = make_config("heavy", custom_services=FIVE_CAP_SERVICES)
    output = render_compose(config)
    data = yaml.safe_load(output)

    assert set(data["services"].keys()) == FIVE_CAP_SERVICES

    for name, service in data["services"].items():
        assert service.get("cap_drop") == ["ALL"], f"{name} is missing cap_drop: ALL"
        assert service.get("cap_add") == FIVE_CAP_SET, f"{name} has an unexpected cap_add set"


def test_zero_cap_services_drop_all_with_no_cap_add():
    config = make_config("heavy", custom_services=ZERO_CAP_SERVICES, domain="example.com")
    output = render_compose(config)
    data = yaml.safe_load(output)

    assert set(data["services"].keys()) == ZERO_CAP_SERVICES

    for name, service in data["services"].items():
        assert service.get("cap_drop") == ["ALL"], f"{name} is missing cap_drop: ALL"
        assert "cap_add" not in service, f"{name} unexpectedly has a cap_add"


def test_special_cap_services_drop_all_and_keep_their_own_verified_set():
    config = make_config("heavy", custom_services=set(SPECIAL_CAP_SERVICES))
    output = render_compose(config)
    data = yaml.safe_load(output)

    assert set(data["services"].keys()) == set(SPECIAL_CAP_SERVICES)

    for name, expected_caps in SPECIAL_CAP_SERVICES.items():
        service = data["services"][name]
        assert service.get("cap_drop") == ["ALL"], f"{name} is missing cap_drop: ALL"
        assert service.get("cap_add") == expected_caps, f"{name} has an unexpected cap_add set"


def test_every_service_has_cap_drop_all():
    """
    Regression lock, all 35 services: this pass covers every service known
    to ALL_SERVICES, not a subset - a future service added without a
    cap_drop entry should fail here rather than silently ship unhardened.
    """
    assert ALL_CAPPED_SERVICES == {s.key for s in ALL_SERVICES} | {"unbound"}

    all_keys = {s.key for s in ALL_SERVICES}
    config = make_config("heavy", custom_services=all_keys, gpu_vendor="nvidia", domain="example.com")
    output = render_compose(config)
    data = yaml.safe_load(output)

    assert set(data["services"].keys()) == all_keys | {"unbound"}

    for name, service in data["services"].items():
        assert service.get("cap_drop") == ["ALL"], f"{name} is missing cap_drop: ALL"


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


def test_render_env_generates_random_crowdsec_bouncer_key_when_enabled():

    output = render_env(make_config("heavy", {"crowdsec"}))

    match = re.search(r"CROWDSEC_BOUNCER_KEY=([0-9a-f]{64})", output)
    assert match is not None


def test_render_env_accepts_explicit_crowdsec_bouncer_key():

    output = render_env(make_config("heavy", {"crowdsec"}), crowdsec_bouncer_key="a-real-preserved-key")

    assert "CROWDSEC_BOUNCER_KEY=a-real-preserved-key" in output


def test_render_env_omits_crowdsec_when_disabled():

    output = render_env(make_config("light"))

    assert "CROWDSEC_BOUNCER_KEY" not in output


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
                "jellyfin", "seerr", "radarr", "sonarr", "lidarr", "readarr",
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
    tile = groups["Media Management"]["Maintainerr"]

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
    nothing real to link to, so it shouldn't get a dead tile. The
    "Guides" group (a link back to the walkthrough doc) is always
    present regardless - documentation, not a service with an
    enabled/disabled state.
    """

    output = render_homepage_services(
        make_config("heavy", custom_services={"traefik"}),
        host_ip=None
    )

    parsed = yaml.safe_load(output)
    assert len(parsed) == 1
    assert list(parsed[0].keys()) == ["Guides"]


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

    # "Guides" is always present too (a link back to the walkthrough
    # doc, not a service with an enabled/disabled state) - this test is
    # specifically about *service* groups being omitted when empty.
    assert group_names == ["Media", "Guides"]


def test_render_homepage_services_output_is_valid_yaml():

    output = render_homepage_services(
        make_config(
            "heavy",
            custom_services={
                "jellyfin", "radarr", "sonarr", "prowlarr", "qbittorrent",
                "sabnzbd", "seerr", "bazarr", "lidarr", "readarr", "uptime-kuma"
            }
        ),
        host_ip=None
    )

    parsed = yaml.safe_load(output)

    assert isinstance(parsed, list)
    assert len(parsed) == 5


def test_render_dashy_config_creates_tiles_for_enabled_services():

    output = render_dashy_config(
        make_config("heavy", custom_services={"jellyfin", "radarr"}),
        host_ip="192.168.1.50"
    )

    parsed = yaml.safe_load(output)

    assert parsed["pageInfo"]["title"]
    assert parsed["appConfig"]["theme"]

    media_section = next(section for section in parsed["sections"] if section["name"] == "Media")
    titles = [item["title"] for item in media_section["items"]]

    assert "Jellyfin" in titles

    jellyfin_item = next(item for item in media_section["items"] if item["title"] == "Jellyfin")

    assert jellyfin_item["url"] == "http://192.168.1.50:8096"
    assert jellyfin_item["icon"] == "favicon"


def test_render_dashy_config_never_self_tiles():

    output = render_dashy_config(
        make_config("heavy", custom_services={"jellyfin", "dashy"}),
        host_ip=None
    )

    parsed = yaml.safe_load(output)
    all_titles = {item["title"] for section in parsed["sections"] for item in section["items"]}

    assert "Dashy" not in all_titles


def test_render_dashy_config_always_includes_walkthrough_guide_tile():

    output = render_dashy_config(
        make_config("heavy", custom_services={"jellyfin"}),
        host_ip=None
    )

    parsed = yaml.safe_load(output)
    guides = next(section for section in parsed["sections"] if section["name"] == "Guides")

    assert guides["items"][0]["url"] == WALKTHROUGH_URL


def test_render_dashy_config_output_is_valid_yaml():

    output = render_dashy_config(
        make_config(
            "heavy",
            custom_services={
                "jellyfin", "radarr", "sonarr", "prowlarr", "qbittorrent",
                "sabnzbd", "seerr", "bazarr", "lidarr", "readarr", "uptime-kuma"
            }
        ),
        host_ip=None
    )

    parsed = yaml.safe_load(output)

    assert isinstance(parsed, dict)
    assert isinstance(parsed["sections"], list)
    assert len(parsed["sections"]) == 5


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
    assert any("Seerr" in w for w in result["warnings"])

    compose_path = output_dir / "docker-compose.yml"
    env_path = output_dir / ".env"

    assert compose_path.read_text() == render_compose(config)
    assert env_path.read_text() == render_env(config)

    for key in ("jellyfin", "radarr", "sonarr", "prowlarr", "qbittorrent",
                "seerr", "bazarr", "flaresolverr", "filebrowser"):
        assert (output_dir / "config" / key).is_dir()

    assert (media_path / "downloads").is_dir()
    assert (media_path / "media" / "movies").is_dir()
    assert (media_path / "media" / "tv").is_dir()
    assert (media_path / "media" / "music").is_dir()
    assert (media_path / "media" / "books").is_dir()


def test_pihole_unbound_dns_wiring(tmp_path):
    """pihole shares unbound's netns; both want :53. unbound must be
    moved to :5335 (a config file write_stack drops in) and pihole's
    v6 upstream must point at it - shipped once as an empty string,
    which broke every lookup."""
    output_dir = tmp_path / "stack"
    config = GenerationConfig(
        tier=TIERS["heavy"],
        media_path=str(tmp_path / "m"),
        puid=1000, pgid=1000, timezone="UTC",
        enabled_optional=set(),
        custom_services={"pihole"},
    )

    write_stack(config, output_dir=output_dir)

    conf = output_dir / "config" / "pihole" / "unbound" / "99-pihole-port.conf"
    assert conf.is_file()
    assert "port: 5335" in conf.read_text()

    services = yaml.safe_load((output_dir / "docker-compose.yml").read_text())["services"]
    pihole_env = services["pihole"]["environment"]
    assert "FTLCONF_dns_upstreams=127.0.0.1#5335" in pihole_env
    assert "FTLCONF_dns_upstreams=" not in pihole_env  # not the empty-string form

    # hand-edited override survives a regenerate
    conf.write_text("server:\n    port: 9999\n")
    write_stack(config, output_dir=output_dir)
    assert "port: 9999" in conf.read_text()


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


def test_write_stack_warns_cloudflared_without_traefik(tmp_path):

    config = GenerationConfig(
        tier=TIERS["heavy"],
        media_path=str(tmp_path / "media-root"),
        puid=1000,
        pgid=1000,
        timezone="UTC",
        enabled_optional={"cloudflared"}
    )

    result = write_stack(config, output_dir=tmp_path / "stack")

    assert any(
        "Cloudflare Tunnel is enabled but Traefik isn't" in warning
        for warning in result["warnings"]
    )


def test_write_stack_warns_cloudflared_needs_real_token(tmp_path):

    config = GenerationConfig(
        tier=TIERS["heavy"],
        media_path=str(tmp_path / "media-root"),
        puid=1000,
        pgid=1000,
        timezone="UTC",
        enabled_optional={"traefik", "cloudflared"}
    )

    result = write_stack(config, output_dir=tmp_path / "stack")

    assert any("TUNNEL_TOKEN" in warning for warning in result["warnings"])


def test_write_stack_no_cloudflared_warning_when_disabled(tmp_path):

    config = GenerationConfig(
        tier=TIERS["light"],
        media_path=str(tmp_path / "media-root"),
        puid=1000,
        pgid=1000,
        timezone="UTC",
        enabled_optional=set()
    )

    result = write_stack(config, output_dir=tmp_path / "stack")

    assert not any("Cloudflare Tunnel" in warning for warning in result["warnings"])


def test_write_stack_warns_when_netdata_enabled(tmp_path):

    config = GenerationConfig(
        tier=TIERS["light"],
        media_path=str(tmp_path / "media-root"),
        puid=1000,
        pgid=1000,
        timezone="UTC",
        enabled_optional={"netdata"}
    )

    result = write_stack(config, output_dir=tmp_path / "stack")

    assert any("SYS_PTRACE" in warning or "SYS_ADMIN" in warning for warning in result["warnings"])
    assert any("19999" in warning for warning in result["warnings"])


def test_write_stack_no_netdata_warning_when_disabled(tmp_path):

    config = GenerationConfig(
        tier=TIERS["light"],
        media_path=str(tmp_path / "media-root"),
        puid=1000,
        pgid=1000,
        timezone="UTC",
        enabled_optional=set()
    )

    result = write_stack(config, output_dir=tmp_path / "stack")

    assert not any("SYS_PTRACE" in warning for warning in result["warnings"])


def test_write_stack_warns_when_metube_and_downtify_enabled(tmp_path):

    config = GenerationConfig(
        tier=TIERS["light"],
        media_path=str(tmp_path / "media-root"),
        puid=1000,
        pgid=1000,
        timezone="UTC",
        enabled_optional={"metube", "downtify"}
    )

    result = write_stack(config, output_dir=tmp_path / "stack")

    assert any("media/youtube" in warning for warning in result["warnings"])
    assert any("media/music/downtify" in warning for warning in result["warnings"])


def test_write_stack_creates_youtube_and_downtify_media_directories(tmp_path):

    config = GenerationConfig(
        tier=TIERS["light"],
        media_path=str(tmp_path / "media-root"),
        puid=1000,
        pgid=1000,
        timezone="UTC",
        enabled_optional=set()
    )

    write_stack(config, output_dir=tmp_path / "stack")

    assert (tmp_path / "media-root" / "media" / "youtube").is_dir()
    assert (tmp_path / "media-root" / "media" / "music" / "downtify").is_dir()


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


def test_write_stack_creates_dashy_conf_yml_on_first_generate(tmp_path):

    config = GenerationConfig(
        tier=TIERS["heavy"],
        media_path=str(tmp_path / "media-root"),
        puid=1000,
        pgid=1000,
        timezone="UTC",
        enabled_optional={"dashy"}
    )

    with patch("installer.generate.detect_host_ip", return_value="192.168.1.50"):
        result = write_stack(config, output_dir=tmp_path / "stack")

    conf_yml_path = tmp_path / "stack" / "config" / "dashy" / "conf.yml"

    assert conf_yml_path.is_file()
    assert "192.168.1.50" in conf_yml_path.read_text()
    assert any("Dashy was pre-seeded" in warning for warning in result["warnings"])


def test_write_stack_no_dashy_conf_yml_when_disabled(tmp_path):

    config = GenerationConfig(
        tier=TIERS["light"],
        media_path=str(tmp_path / "media-root"),
        puid=1000,
        pgid=1000,
        timezone="UTC",
        enabled_optional=set()
    )

    result = write_stack(config, output_dir=tmp_path / "stack")

    conf_yml_path = tmp_path / "stack" / "config" / "dashy" / "conf.yml"

    assert not conf_yml_path.exists()
    assert not any("Dashy was pre-seeded" in warning for warning in result["warnings"])


def test_write_stack_never_overwrites_existing_dashy_conf_yml(tmp_path):

    config = GenerationConfig(
        tier=TIERS["heavy"],
        media_path=str(tmp_path / "media-root"),
        puid=1000,
        pgid=1000,
        timezone="UTC",
        enabled_optional={"dashy"}
    )

    with patch("installer.generate.detect_host_ip", return_value="192.168.1.50"):
        write_stack(config, output_dir=tmp_path / "stack")

    conf_yml_path = tmp_path / "stack" / "config" / "dashy" / "conf.yml"
    conf_yml_path.write_text("# hand-edited by the user\npageInfo:\n  title: Mine\n")

    with patch("installer.generate.detect_host_ip", return_value="192.168.1.50"):
        result = write_stack(config, output_dir=tmp_path / "stack")

    assert conf_yml_path.read_text() == "# hand-edited by the user\npageInfo:\n  title: Mine\n"
    assert not any("Dashy was pre-seeded" in warning for warning in result["warnings"])


def test_write_stack_uptime_kuma_reference_lists_enabled_services(tmp_path):

    config = GenerationConfig(
        tier=TIERS["heavy"],
        media_path=str(tmp_path / "media-root"),
        puid=1000,
        pgid=1000,
        timezone="UTC",
        enabled_optional={"uptime-kuma"}
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
        enabled_optional={"traefik", "uptime-kuma"},
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


def test_render_stack_summary_lists_each_service_once():
    """radarr and sonarr each sit in two _HOMEPAGE_GROUPS buckets (Events
    and Media Processing), and homepage is emitted explicitly *and* sits
    in a group - the summary must still list every service exactly once."""

    output = render_stack_summary(
        make_config("heavy", custom_services={"homepage", "radarr", "sonarr", "jellyfin"}),
        host_ip="192.168.1.50",
    )

    lines = [line for line in output.splitlines() if line.strip()]

    assert len(lines) == len(set(lines))
    assert sum("Radarr:" in line for line in lines) == 1
    assert sum("Sonarr:" in line for line in lines) == 1
    assert sum(line.startswith("  Homepage") for line in lines) == 1


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


def test_render_stack_summary_netdata_always_direct_host_link_even_with_traefik_domain():
    """
    Unlike every other web-facing service, netdata's link must stay a
    direct http://<host>:19999 URL even when Traefik+domain routing is
    active for everything else - network_mode: host means it's never
    actually routed (see the compose-template test for the same real
    reason), so a routed https://netdata.<domain> link would be dead.
    """

    output = render_stack_summary(
        make_config(
            "heavy",
            custom_services={"netdata", "homepage", "traefik"},
            domain="media.example.com"
        ),
        host_ip="192.168.1.50"
    )

    assert "Netdata: http://192.168.1.50:19999" in output
    assert "netdata.media.example.com" not in output


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


def test_render_setup_order_empty_when_nothing_enabled():

    output = render_setup_order(
        make_config("heavy", custom_services={"watchtower"}),
        host_ip=None
    )

    assert output == ""


def test_render_setup_order_puts_vaultwarden_first_and_links_walkthrough():

    output = render_setup_order(
        make_config(
            "heavy",
            custom_services={"vaultwarden", "jellyfin", "authelia", "prowlarr"}
        ),
        host_ip="192.168.1.50"
    )

    assert output.startswith("Suggested setup order")
    assert "1. Vaultwarden (http://192.168.1.50:8222)" in output
    assert output.index("1. Vaultwarden") < output.index("Prowlarr")
    assert WALKTHROUGH_URL in output


def test_render_setup_order_jellyfin_step_mentions_authelia_exclusion_only_when_authelia_enabled():

    with_authelia = render_setup_order(
        make_config("heavy", custom_services={"jellyfin", "authelia"}),
        host_ip=None
    )
    without_authelia = render_setup_order(
        make_config("heavy", custom_services={"jellyfin"}),
        host_ip=None
    )

    assert "not behind Authelia" in with_authelia
    assert "not behind Authelia" not in without_authelia


def test_render_setup_order_numbers_are_gapless_when_steps_are_skipped():

    output = render_setup_order(
        make_config("heavy", custom_services={"jellyfin", "homepage"}),
        host_ip=None
    )

    assert "1. Jellyfin" in output
    assert "2. Homepage" in output


def test_render_homepage_services_always_includes_walkthrough_guide_tile():

    output = render_homepage_services(
        make_config("heavy", custom_services={"jellyfin"}),
        host_ip=None
    )

    parsed = yaml.safe_load(output)
    guides = next(group["Guides"] for group in parsed if "Guides" in group)

    assert guides[0]["Setup Walkthrough"]["href"] == WALKTHROUGH_URL


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


def test_render_env_cloudflared_token_default_placeholder():

    output = render_env(make_config("heavy", {"traefik", "cloudflared"}))

    assert "TUNNEL_TOKEN=changeme" in output


def test_render_env_omits_tunnel_token_when_cloudflared_disabled():

    output = render_env(make_config("heavy", {"traefik"}))

    assert "TUNNEL_TOKEN" not in output


def test_render_env_accepts_preserved_tunnel_token():

    output = render_env(
        make_config("heavy", {"traefik", "cloudflared"}),
        tunnel_token="a-real-tunnel-token"
    )

    assert "TUNNEL_TOKEN=a-real-tunnel-token" in output


def test_render_env_wireguard_addresses_defaults_empty():

    output = render_env(make_config("medium", {"gluetun"}))

    assert "WIREGUARD_ADDRESSES=\n" in output


def test_render_env_accepts_preserved_wireguard_addresses():

    output = render_env(
        make_config("medium", {"gluetun"}),
        wireguard_addresses="10.64.222.21/32"
    )

    assert "WIREGUARD_ADDRESSES=10.64.222.21/32" in output


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


def test_write_stack_persists_warnings_into_state_file(tmp_path):

    config = GenerationConfig(
        tier=TIERS["heavy"],
        media_path=str(tmp_path / "media-root"),
        puid=1000,
        pgid=1000,
        timezone="UTC",
        gpu_vendor="nvidia",
    )

    result = write_stack(config, output_dir=tmp_path / "stack")
    state = load_previous_state(tmp_path / "stack")

    assert result["warnings"]
    assert state["warnings"] == result["warnings"]


def test_write_stack_regenerate_clears_stale_warnings(tmp_path):

    nvidia_config = GenerationConfig(
        tier=TIERS["heavy"],
        media_path=str(tmp_path / "media-root"),
        puid=1000,
        pgid=1000,
        timezone="UTC",
        gpu_vendor="nvidia",
    )
    write_stack(nvidia_config, output_dir=tmp_path / "stack")

    no_gpu_config = GenerationConfig(
        tier=TIERS["light"],
        media_path=str(tmp_path / "media-root"),
        puid=1000,
        pgid=1000,
        timezone="UTC",
    )
    write_stack(no_gpu_config, output_dir=tmp_path / "stack")

    state = load_previous_state(tmp_path / "stack")

    assert state["warnings"] == []


def test_render_authelia_users_database_output_shape():

    output = render_authelia_users_database("admin", "admin", "$argon2id$fake$hash")
    parsed = yaml.safe_load(output)

    assert parsed["users"]["admin"]["password"] == "$argon2id$fake$hash"
    assert parsed["users"]["admin"]["displayname"] == "admin"
    assert parsed["users"]["admin"]["disabled"] is False
    assert parsed["users"]["admin"]["groups"] == ["admin"]


def test_render_authelia_configuration_uses_domain_for_session_cookie():

    output = render_authelia_configuration(
        make_config("heavy", custom_services={"authelia", "traefik"}, domain="media.example.com"),
        host_ip="192.168.1.100"
    )
    parsed = yaml.safe_load(output)

    cookie = parsed["session"]["cookies"][0]
    assert cookie["domain"] == "media.example.com"
    assert cookie["authelia_url"] == "https://authelia.media.example.com"
    assert "default_redirection_url" not in cookie
    assert parsed["access_control"]["default_policy"] == "one_factor"
    # RBAC: traefik is in ADMIN_ONLY_SERVICES, so a rule is generated
    rules = parsed["access_control"].get("rules", [])
    traefik_rules = [r for r in rules if "traefik." in r.get("domain", "")]
    assert len(traefik_rules) == 1
    assert traefik_rules[0]["subject"] == ["group:admin"]
    assert "jwt_secret" not in parsed.get("identity_validation", {}).get("reset_password", {})
    assert "secret" not in parsed["session"]
    assert "encryption_key" not in parsed["storage"]


def test_render_authelia_configuration_falls_back_to_host_ip_without_domain():

    # Real bug found via a live ARM64 verification run: rendering `domain`
    # verbatim with no domain configured produced a literal "domain: 'None'",
    # which Authelia's own config validator fatally rejects (a cookie domain
    # needs a period or to be a real IP) - it crash-looped instead of
    # starting, contradicting write_stack()'s own warning that it "starts
    # but does nothing useful" without Traefik + a domain. `authelia_url` is
    # a separate, *required* field (confirmed by re-testing against a real
    # container after first trying to omit it) - it falls back to Authelia's
    # own container port directly rather than a fictional "authelia.<ip>"
    # subdomain, which wouldn't resolve to anything.
    output = render_authelia_configuration(
        make_config("heavy", custom_services={"authelia"}, domain=None),
        host_ip="192.168.1.100"
    )
    parsed = yaml.safe_load(output)

    cookie = parsed["session"]["cookies"][0]
    assert cookie["domain"] == "192.168.1.100"
    assert cookie["authelia_url"] == "https://192.168.1.100:9091"
    assert "default_redirection_url" not in cookie


def test_render_authelia_configuration_falls_back_to_loopback_without_domain_or_host_ip():

    output = render_authelia_configuration(
        make_config("heavy", custom_services={"authelia"}, domain=None),
        host_ip=None
    )
    parsed = yaml.safe_load(output)

    assert parsed["session"]["cookies"][0]["domain"] == "127.0.0.1"


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
        ),
        host_ip="192.168.1.100"
    )
    parsed = yaml.safe_load(output)

    assert parsed["session"]["cookies"][0]["default_redirection_url"] == "https://homepage.media.example.com"


def test_render_authelia_configuration_rbac_rules_for_admin_only_services():

    output = render_authelia_configuration(
        make_config(
            "heavy",
            custom_services={"authelia", "traefik", "radarr", "sonarr", "prowlarr",
                              "jellyfin", "seerr"},
            domain="media.example.com"
        ),
        host_ip="192.168.1.100"
    )
    parsed = yaml.safe_load(output)

    rules = parsed["access_control"].get("rules", [])
    rule_domains = {r["domain"] for r in rules}

    # Admin-only services should have deny rules
    for svc in ("radarr", "sonarr", "prowlarr", "traefik"):
        assert f"{svc}.media.example.com" in rule_domains

    # Media services should NOT have rules (fall through to default_policy)
    for svc in ("jellyfin", "seerr"):
        assert f"{svc}.media.example.com" not in rule_domains

    # All rules should require admin group
    for rule in rules:
        assert rule["subject"] == ["group:admin"]


def test_render_authelia_configuration_no_rules_without_domain():

    output = render_authelia_configuration(
        make_config(
            "heavy",
            custom_services={"authelia", "traefik", "radarr"},
            domain=None
        ),
        host_ip="192.168.1.100"
    )
    parsed = yaml.safe_load(output)

    assert "rules" not in parsed["access_control"]


def test_render_authelia_users_database_multiple_users():

    additional = [
        {"username": "friend", "password_hash": "$argon2id$fake$hash2", "groups": ["media"]},
        {"username": "guest", "password_hash": "$argon2id$fake$hash3", "groups": ["media"]},
    ]
    output = render_authelia_users_database(
        "admin", "Admin User", "$argon2id$fake$hash1",
        additional_users=additional
    )
    parsed = yaml.safe_load(output)

    assert len(parsed["users"]) == 3
    assert parsed["users"]["admin"]["groups"] == ["admin"]
    assert parsed["users"]["friend"]["groups"] == ["media"]
    assert parsed["users"]["guest"]["groups"] == ["media"]


def test_render_authelia_users_database_admin_only():

    output = render_authelia_users_database("admin", "admin", "$argon2id$fake$hash")
    parsed = yaml.safe_load(output)

    assert len(parsed["users"]) == 1
    assert parsed["users"]["admin"]["groups"] == ["admin"]


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


def test_write_stack_creates_crowdsec_acquis_file_on_first_generate(tmp_path):

    config = GenerationConfig(
        tier=TIERS["heavy"],
        media_path=str(tmp_path / "media-root"),
        puid=1000,
        pgid=1000,
        timezone="UTC",
        enabled_optional={"traefik", "crowdsec"},
        domain="media.example.com"
    )

    write_stack(config, output_dir=tmp_path / "stack")

    acquis_path = tmp_path / "stack" / "config" / "crowdsec" / "etc" / "acquis.yaml"
    assert acquis_path.is_file()

    parsed = yaml.safe_load(acquis_path.read_text())
    assert parsed["filenames"] == ["/var/log/traefik/access.log"]
    assert parsed["labels"]["type"] == "traefik"


def test_write_stack_never_overwrites_existing_crowdsec_acquis(tmp_path):

    config = GenerationConfig(
        tier=TIERS["heavy"],
        media_path=str(tmp_path / "media-root"),
        puid=1000,
        pgid=1000,
        timezone="UTC",
        enabled_optional={"traefik", "crowdsec"},
        domain="media.example.com"
    )

    write_stack(config, output_dir=tmp_path / "stack")

    acquis_path = tmp_path / "stack" / "config" / "crowdsec" / "etc" / "acquis.yaml"
    acquis_path.write_text("# hand-edited\n")

    write_stack(config, output_dir=tmp_path / "stack")

    assert acquis_path.read_text() == "# hand-edited\n"


def test_write_stack_warns_when_crowdsec_enabled_without_traefik_domain(tmp_path):

    config = GenerationConfig(
        tier=TIERS["heavy"],
        media_path=str(tmp_path / "media-root"),
        puid=1000,
        pgid=1000,
        timezone="UTC",
        enabled_optional={"crowdsec"}
    )

    result = write_stack(config, output_dir=tmp_path / "stack")

    assert any("no traffic for it to protect yet" in warning for warning in result["warnings"])


def test_write_stack_no_crowdsec_unrouted_warning_when_traefik_and_domain_active(tmp_path):

    config = GenerationConfig(
        tier=TIERS["heavy"],
        media_path=str(tmp_path / "media-root"),
        puid=1000,
        pgid=1000,
        timezone="UTC",
        enabled_optional={"traefik", "crowdsec"},
        domain="media.example.com"
    )

    result = write_stack(config, output_dir=tmp_path / "stack")

    assert not any("no traffic for it to protect yet" in warning for warning in result["warnings"])
    assert any("watching Traefik's access log" in warning for warning in result["warnings"])


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

    assert groups["Security"]["Authelia"]["href"] == "https://authelia.media.example.com"


def test_homepage_groups_match_web_facing_services():
    """_HOMEPAGE_GROUPS's flattened membership must stay exactly
    WEB_FACING_SERVICES minus Homepage and Dashy themselves (neither
    dashboard tiles itself), plus one real, documented exception:
    netdata gets a tile (network_mode: host means it has a real
    reachable web UI) but is deliberately never in WEB_FACING_SERVICES,
    since that set specifically means "gets Homepage/Dashy AND Traefik
    routing" and netdata can never get the latter (no Docker-network
    identity for Traefik's provider to discover under host networking)
    - see _service_href()'s own netdata special-case. Every other drift
    risk (see WEB_FACING_SERVICES's own comment in generate.py) is
    still caught here."""

    flattened = {key for keys in _HOMEPAGE_GROUPS.values() for key in keys}

    assert flattened - {"netdata"} == WEB_FACING_SERVICES - {"homepage", "dashy"}


def test_traefik_template_routes_match_web_facing_services():
    """The Traefik template's per-service label blocks are the other
    half of the same drift risk - every WEB_FACING_SERVICES member
    except Traefik itself (routed via its own separate dashboard block,
    not the per-service pattern) must have a
    `traefik.http.routers.<key>.rule=Host` line in the real template."""

    template_text = (TEMPLATES_DIR / "docker-compose.yml.j2").read_text()
    routed = set(re.findall(r"traefik\.http\.routers\.([\w-]+)\.rule=Host", template_text))
    routed.discard("dashboard")  # Traefik's own router, not a per-service key
    routed.discard("vaultwarden-ws")  # Vaultwarden's secondary websocket router, not a separate service

    assert routed == WEB_FACING_SERVICES - {"traefik"}
