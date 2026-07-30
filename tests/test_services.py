from installer.services import RESOURCE_PROFILES, resource_limits_for


def test_all_phase_one_services_have_a_resource_profile():

    expected = {
        "jellyfin", "radarr", "sonarr", "prowlarr", "qbittorrent",
        "jellyseerr", "bazarr", "flaresolverr", "gluetun"
    }

    assert set(RESOURCE_PROFILES.keys()) == expected


def test_resource_limits_for_light_tier():

    limits = resource_limits_for("light")

    assert limits["prowlarr"] == {"cpus": "0.5", "memory": "256m"}
    assert limits["radarr"] == {"cpus": "1.0", "memory": "512m"}
    assert limits["jellyfin"] == {"cpus": "1.5", "memory": "1g"}


def test_resource_limits_for_medium_tier():

    limits = resource_limits_for("medium")

    assert limits["prowlarr"] == {"cpus": "1.0", "memory": "512m"}
    assert limits["radarr"] == {"cpus": "1.5", "memory": "1g"}
    assert limits["jellyfin"] == {"cpus": "2.5", "memory": "2g"}


def test_resource_limits_for_heavy_tier():

    limits = resource_limits_for("heavy")

    assert limits["prowlarr"] == {"cpus": "1.5", "memory": "1g"}
    assert limits["jellyfin"] == {"cpus": "4.0", "memory": "4g"}
