from installer.detect import SystemInfo
from installer.tiers import ALL_SERVICES, TIERS, recommend_tier, tier_description


def make_system_info(
    cores: int,
    ram_gb: float,
    disk_gb: float
) -> SystemInfo:

    return SystemInfo(
        cpu_cores_physical=cores,
        cpu_cores_logical=cores,
        cpu_model="Fake CPU",
        ram_total_gb=ram_gb,
        ram_available_gb=ram_gb,
        disk_free_gb=disk_gb,
        disk_path_checked="/",
        gpu_vendor=None,
        docker_installed=True,
        docker_running=True,
        docker_compose_v2=True,
        architecture="x86_64",
        os_id="fedora",
        os_pretty_name="Fedora Linux 44"
    )


def test_exact_threshold_recommends_light():

    result = recommend_tier(make_system_info(cores=2, ram_gb=4, disk_gb=100))

    assert result.tier.name == "light"
    assert result.meets_minimum is True


def test_exact_threshold_recommends_medium():

    result = recommend_tier(make_system_info(cores=4, ram_gb=8, disk_gb=500))

    assert result.tier.name == "medium"
    assert result.meets_minimum is True


def test_exact_threshold_recommends_heavy():

    result = recommend_tier(make_system_info(cores=6, ram_gb=16, disk_gb=1000))

    assert result.tier.name == "heavy"
    assert result.meets_minimum is True
    assert "highest available tier" in result.explanation


def test_disk_shortfall_alone_caps_at_medium():

    result = recommend_tier(make_system_info(cores=6, ram_gb=16, disk_gb=999))

    assert result.tier.name == "medium"
    assert result.meets_minimum is True
    assert "disk" in result.explanation
    assert "cores" not in result.explanation
    assert "RAM" not in result.explanation


def test_multi_resource_shortfall_lists_all_gaps():

    result = recommend_tier(make_system_info(cores=6, ram_gb=8, disk_gb=500))

    assert result.tier.name == "medium"
    assert result.meets_minimum is True
    assert "RAM" in result.explanation
    assert "disk" in result.explanation
    assert "cores" not in result.explanation


def test_below_light_still_recommends_light_but_flags_it():

    result = recommend_tier(make_system_info(cores=1, ram_gb=2, disk_gb=50))

    assert result.tier.name == "light"
    assert result.meets_minimum is False
    assert "cores" in result.explanation
    assert "RAM" in result.explanation
    assert "disk" in result.explanation


def test_medium_services_include_all_light_services_plus_additions():

    light_keys = {service.key for service in TIERS["light"].services}
    medium_keys = {service.key for service in TIERS["medium"].services}

    assert light_keys.issubset(medium_keys)
    assert medium_keys - light_keys == {
        "jellyseerr", "bazarr", "flaresolverr"
    }


def test_heavy_services_include_all_medium_services_plus_additions():

    medium_keys = {service.key for service in TIERS["medium"].services}
    heavy_keys = {service.key for service in TIERS["heavy"].services}

    assert medium_keys.issubset(heavy_keys)
    assert heavy_keys - medium_keys == {
        "lidarr", "readarr", "traefik", "authelia", "tailscale", "uptime-kuma", "watchtower"
    }


def test_gluetun_and_lidarr_and_traefik_are_optional():

    medium_by_key = {s.key: s for s in TIERS["medium"].services}
    heavy_by_key = {s.key: s for s in TIERS["heavy"].services}

    assert medium_by_key["gluetun"].optional is True
    assert heavy_by_key["lidarr"].optional is True
    assert heavy_by_key["readarr"].optional is True
    assert heavy_by_key["traefik"].optional is True
    assert heavy_by_key["authelia"].optional is True
    assert heavy_by_key["homepage"].optional is True


def test_sabnzbd_is_optional_starting_at_light():

    light_by_key = {s.key: s for s in TIERS["light"].services}

    assert "sabnzbd" in light_by_key
    assert light_by_key["sabnzbd"].optional is True
    assert light_by_key["qbittorrent"].optional is False


def test_recyclarr_is_optional_starting_at_light():

    light_by_key = {s.key: s for s in TIERS["light"].services}

    assert "recyclarr" in light_by_key
    assert light_by_key["recyclarr"].optional is True


def test_homepage_is_optional_starting_at_light():

    light_by_key = {s.key: s for s in TIERS["light"].services}

    assert "homepage" in light_by_key
    assert light_by_key["homepage"].optional is True


def test_all_services_is_exactly_the_union_of_every_tier():

    all_keys = {service.key for service in ALL_SERVICES}
    union_keys = {
        service.key
        for tier in TIERS.values()
        for service in tier.services
    }

    assert all_keys == union_keys
    assert len(all_keys) == 22
    assert len(ALL_SERVICES) == len(all_keys)


def test_tier_description_light_lists_core_and_optional_services():

    description = tier_description(TIERS["light"])

    assert "Jellyfin" in description
    assert "Radarr" in description
    assert "- optional:" in description
    assert "SABnzbd" in description
    assert "Decluttarr" in description


def test_tier_description_reflects_real_service_membership():
    """
    Generated from the tier's own real ServiceDefinition list, not a
    hand-maintained copy - a service added to _HEAVY_SERVICES should
    show up here automatically, with no separate description to update.
    """

    for tier in TIERS.values():

        description = tier_description(tier)

        for service in tier.services:
            assert service.display_name in description
