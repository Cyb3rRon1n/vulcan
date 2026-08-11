from installer.services import RESOURCE_PROFILES, resource_limits_for


def test_all_known_services_have_a_resource_profile():

    expected = {
        "jellyfin", "radarr", "sonarr", "prowlarr", "qbittorrent", "sabnzbd", "recyclarr",
        "decluttarr", "maintainerr", "jellyseerr", "bazarr", "flaresolverr", "gluetun",
        "lidarr", "readarr", "traefik", "authelia", "tailscale", "homepage", "uptime-kuma",
        "watchtower", "metube", "downtify", "netdata", "vaultwarden", "dashy"
    }

    assert set(RESOURCE_PROFILES.keys()) == expected


def test_sabnzbd_has_same_profile_as_qbittorrent():

    assert RESOURCE_PROFILES["sabnzbd"] == RESOURCE_PROFILES["qbittorrent"] == "standard"


def test_recyclarr_has_light_profile():

    assert RESOURCE_PROFILES["recyclarr"] == "light"


def test_metube_and_downtify_have_standard_profile():

    assert RESOURCE_PROFILES["metube"] == "standard"
    assert RESOURCE_PROFILES["downtify"] == "standard"


def test_netdata_has_light_profile():
    """
    Genuinely light on CPU/RAM itself - the real cost of enabling it is
    host access (SYS_PTRACE/SYS_ADMIN, docker.sock), not compute.
    """

    assert RESOURCE_PROFILES["netdata"] == "light"


def test_vaultwarden_has_light_profile():

    assert RESOURCE_PROFILES["vaultwarden"] == "light"


def test_dashy_has_light_profile():

    assert RESOURCE_PROFILES["dashy"] == "light"


def test_heavy_only_services_get_expected_profiles():

    assert RESOURCE_PROFILES["lidarr"] == "standard"
    assert RESOURCE_PROFILES["readarr"] == "standard"
    assert RESOURCE_PROFILES["traefik"] == "light"
    assert RESOURCE_PROFILES["homepage"] == "light"
    assert RESOURCE_PROFILES["uptime-kuma"] == "light"
    assert RESOURCE_PROFILES["watchtower"] == "light"


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
