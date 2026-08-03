from unittest.mock import MagicMock, patch

import yaml

from installer.generate import (
    GenerationConfig,
    default_puid_pgid,
    default_timezone,
    enabled_service_keys,
    load_previous_state,
    render_compose,
    render_env,
    render_homepage_services,
    save_state,
    write_stack,
)
from installer.tiers import TIERS


def make_config(
    tier_name: str,
    enabled_optional: set[str] | None = None,
    gpu_vendor: str | None = None,
    custom_services: set[str] | None = None,
    domain: str | None = None
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
        domain=domain
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


def test_render_compose_heavy_includes_all_new_services():

    output = render_compose(make_config("heavy", enabled_optional={"lidarr", "readarr", "traefik"}))

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


def test_render_compose_heavy_without_optional_extras_excludes_lidarr_and_traefik():

    output = render_compose(make_config("heavy"))

    assert "container_name: lidarr" not in output
    assert "container_name: readarr" not in output
    assert "container_name: traefik" not in output
    assert "container_name: homepage" in output


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
            enabled_optional={"traefik", "lidarr", "readarr"},
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
    assert groups["Media Management"]["Radarr"]["href"] == "http://localhost:7878"
    assert groups["Downloads"]["qBittorrent"]["href"] == "http://localhost:8080"
    assert "Monitoring" not in groups


def test_render_homepage_services_creates_readarr_tile():

    output = render_homepage_services(
        make_config("heavy", custom_services={"readarr"}),
        host_ip=None
    )

    groups = _homepage_groups(output)

    assert groups["Media Management"]["Readarr"]["href"] == "http://localhost:8787"
    assert groups["Media Management"]["Readarr"]["icon"] == "readarr.png"


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
    assert not any("qbittorrent" in warning.lower() for warning in result["warnings"])


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
        enabled_optional=set()
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
        enabled_optional=set()
    )

    with patch("installer.generate.detect_host_ip", return_value="192.168.1.50"):
        write_stack(config, output_dir=tmp_path / "stack")

    services_yaml_path = tmp_path / "stack" / "config" / "homepage" / "services.yaml"
    services_yaml_path.write_text("# hand-edited by the user\n- My Group: []\n")

    with patch("installer.generate.detect_host_ip", return_value="192.168.1.50"):
        result = write_stack(config, output_dir=tmp_path / "stack")

    assert services_yaml_path.read_text() == "# hand-edited by the user\n- My Group: []\n"
    assert not any("pre-seeded" in warning for warning in result["warnings"])


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
