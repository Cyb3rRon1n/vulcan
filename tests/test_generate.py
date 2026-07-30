from unittest.mock import MagicMock, patch

from installer.generate import (
    GenerationConfig,
    default_puid_pgid,
    default_timezone,
    enabled_service_keys,
    load_previous_state,
    render_compose,
    render_env,
    save_state,
    write_stack,
)
from installer.tiers import TIERS


def make_config(
    tier_name: str,
    enabled_optional: set[str] | None = None,
    gpu_vendor: str | None = None,
    custom_services: set[str] | None = None
) -> GenerationConfig:

    return GenerationConfig(
        tier=TIERS[tier_name],
        media_path="/mnt/media",
        puid=1000,
        pgid=1000,
        timezone="America/New_York",
        enabled_optional=enabled_optional or set(),
        gpu_vendor=gpu_vendor,
        custom_services=custom_services
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


def test_render_compose_heavy_includes_all_new_services():

    output = render_compose(make_config("heavy", enabled_optional={"lidarr", "traefik"}))

    for name in ("lidarr", "traefik", "homepage", "uptime-kuma", "watchtower"):
        assert f"container_name: {name}" in output


def test_render_compose_medium_excludes_heavy_only_services():

    output = render_compose(make_config("medium"))

    for name in ("lidarr", "traefik", "homepage", "uptime-kuma", "watchtower"):
        assert f"container_name: {name}" not in output


def test_render_compose_heavy_without_optional_extras_excludes_lidarr_and_traefik():

    output = render_compose(make_config("heavy"))

    assert "container_name: lidarr" not in output
    assert "container_name: traefik" not in output
    assert "container_name: homepage" in output


def _jellyfin_block(output: str) -> str:

    return output.split("jellyfin:", 1)[1].split("  radarr:", 1)[0]


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

    assert result["warnings"] != []
    assert "nvidia-container-toolkit" in result["warnings"][0]


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

    assert result["warnings"] == []


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
        enabled_optional={"lidarr", "traefik"},
        gpu_vendor="amd"
    )

    save_state(config, tmp_path)
    state = load_previous_state(tmp_path)

    assert state["tier"] == "heavy"
    assert state["media_path"] == "/mnt/media"
    assert state["puid"] == 1000
    assert state["pgid"] == 1000
    assert state["timezone"] == "America/New_York"
    assert sorted(state["enabled_optional"]) == ["lidarr", "traefik"]
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
