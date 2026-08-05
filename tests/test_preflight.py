import socket
from unittest.mock import MagicMock, patch

from installer.preflight import (
    check_ports_available,
    format_port_conflicts,
    identify_port_owner,
    port_owner_is_own_orphan,
)


COMPOSE_TWO_SERVICES = """
services:
  jellyfin:
    image: lscr.io/linuxserver/jellyfin:latest
    ports:
      - "8096:8096"
  radarr:
    image: lscr.io/linuxserver/radarr:latest
    ports:
      - "7878:7878"
"""

COMPOSE_MULTI_PORT_SERVICE = """
services:
  traefik:
    image: traefik:latest
    ports:
      - "80:80"
      - "443:443"
"""

COMPOSE_NO_PORTS_SERVICE = """
services:
  recyclarr:
    image: ghcr.io/recyclarr/recyclarr:8
"""


def test_check_ports_available_no_conflicts(tmp_path):

    compose_path = tmp_path / "docker-compose.yml"
    compose_path.write_text(COMPOSE_TWO_SERVICES)

    with patch("installer.preflight._port_in_use", return_value=False):
        result = check_ports_available(str(compose_path))

    assert result == {
        "available": True, "conflicts": [], "owners": {}, "port_services": {}, "own_orphan": {}
    }


def test_check_ports_available_reports_conflicts(tmp_path):

    compose_path = tmp_path / "docker-compose.yml"
    compose_path.write_text(COMPOSE_TWO_SERVICES)

    with patch(
        "installer.preflight._port_in_use", side_effect=lambda port: port == 7878
    ), patch(
        "installer.preflight.identify_port_owner", return_value=None
    ), patch(
        "installer.preflight.port_owner_is_own_orphan", return_value=False
    ):
        result = check_ports_available(str(compose_path))

    assert result == {
        "available": False,
        "conflicts": [7878],
        "owners": {7878: None},
        "port_services": {7878: "radarr"},
        "own_orphan": {7878: False},
    }


def test_check_ports_available_checks_every_port_in_multi_port_service(tmp_path):

    compose_path = tmp_path / "docker-compose.yml"
    compose_path.write_text(COMPOSE_MULTI_PORT_SERVICE)

    with patch(
        "installer.preflight._port_in_use", return_value=True
    ), patch(
        "installer.preflight.identify_port_owner", return_value=None
    ), patch(
        "installer.preflight.port_owner_is_own_orphan", return_value=False
    ):
        result = check_ports_available(str(compose_path))

    assert result == {
        "available": False,
        "conflicts": [80, 443],
        "owners": {80: None, 443: None},
        "port_services": {80: "traefik", 443: "traefik"},
        "own_orphan": {80: False, 443: False},
    }


def test_check_ports_available_service_with_no_ports_key_does_not_crash(tmp_path):

    compose_path = tmp_path / "docker-compose.yml"
    compose_path.write_text(COMPOSE_NO_PORTS_SERVICE)

    with patch("installer.preflight._port_in_use", return_value=False):
        result = check_ports_available(str(compose_path))

    assert result == {
        "available": True, "conflicts": [], "owners": {}, "port_services": {}, "own_orphan": {}
    }


def test_check_ports_available_real_bound_port_is_detected(tmp_path):

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as held:

        held.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        held.bind(("127.0.0.1", 0))
        held.listen(1)
        real_port = held.getsockname()[1]

        compose_path = tmp_path / "docker-compose.yml"
        compose_path.write_text(
            f'services:\n  test:\n    image: test\n    ports:\n      - "{real_port}:{real_port}"\n'
        )

        with patch(
            "installer.preflight.identify_port_owner", return_value=None
        ), patch(
            "installer.preflight.port_owner_is_own_orphan", return_value=False
        ):
            result = check_ports_available(str(compose_path))

    assert result == {
        "available": False,
        "conflicts": [real_port],
        "owners": {real_port: None},
        "port_services": {real_port: "test"},
        "own_orphan": {real_port: False},
    }


DOCKER_PS_OUTPUT_UNRELATED_CONTAINER = (
    'homepage-old\tghcr.io/gethomepage/homepage:latest\t'
    '0.0.0.0:8080->80/tcp, [::]:8080->80/tcp\t\n'
)

DOCKER_PS_OUTPUT_OWN_ORPHANED_CONTAINER = (
    'qbittorrent\tlscr.io/linuxserver/qbittorrent:latest\t'
    '0.0.0.0:8080->8080/tcp, [::]:8080->8080/tcp\tstack\n'
)

DOCKER_PS_OUTPUT_NO_MATCH = (
    'jellyfin\tlscr.io/linuxserver/jellyfin:latest\t'
    '0.0.0.0:8096->8096/tcp, [::]:8096->8096/tcp\tstack\n'
)


def test_identify_port_owner_finds_unrelated_container():

    proc = MagicMock(returncode=0, stdout=DOCKER_PS_OUTPUT_UNRELATED_CONTAINER)

    with patch("installer.preflight.subprocess.run", return_value=proc):
        owner = identify_port_owner(8080)

    assert 'container "homepage-old"' in owner
    assert "ghcr.io/gethomepage/homepage:latest" in owner


def test_identify_port_owner_recognizes_own_orphaned_project():

    proc = MagicMock(returncode=0, stdout=DOCKER_PS_OUTPUT_OWN_ORPHANED_CONTAINER)

    with patch("installer.preflight.subprocess.run", return_value=proc):
        owner = identify_port_owner(8080, own_project_name="stack")

    assert "your own orphaned containers" in owner
    assert "vulcan uninstall" in owner


def test_identify_port_owner_treats_matching_project_as_unrelated_when_no_own_project_given():

    proc = MagicMock(returncode=0, stdout=DOCKER_PS_OUTPUT_OWN_ORPHANED_CONTAINER)

    with patch("installer.preflight.subprocess.run", return_value=proc):
        owner = identify_port_owner(8080)

    assert 'container "qbittorrent"' in owner
    assert "your own orphaned" not in owner


def test_identify_port_owner_returns_none_when_no_container_matches():

    proc = MagicMock(returncode=0, stdout=DOCKER_PS_OUTPUT_NO_MATCH)

    with patch("installer.preflight.subprocess.run", return_value=proc):
        owner = identify_port_owner(8080)

    assert owner is None


def test_identify_port_owner_returns_none_on_docker_failure():

    proc = MagicMock(returncode=1, stdout="")

    with patch("installer.preflight.subprocess.run", return_value=proc):
        owner = identify_port_owner(8080)

    assert owner is None


def test_port_owner_is_own_orphan_true_for_matching_project():

    proc = MagicMock(returncode=0, stdout=DOCKER_PS_OUTPUT_OWN_ORPHANED_CONTAINER)

    with patch("installer.preflight.subprocess.run", return_value=proc):
        assert port_owner_is_own_orphan(8080, own_project_name="stack") is True


def test_port_owner_is_own_orphan_false_for_unrelated_container():

    proc = MagicMock(returncode=0, stdout=DOCKER_PS_OUTPUT_UNRELATED_CONTAINER)

    with patch("installer.preflight.subprocess.run", return_value=proc):
        assert port_owner_is_own_orphan(8080, own_project_name="stack") is False


def test_port_owner_is_own_orphan_false_when_no_container_found():

    proc = MagicMock(returncode=0, stdout=DOCKER_PS_OUTPUT_NO_MATCH)

    with patch("installer.preflight.subprocess.run", return_value=proc):
        assert port_owner_is_own_orphan(8080, own_project_name="stack") is False


def test_port_owner_is_own_orphan_false_with_no_own_project_given():

    proc = MagicMock(returncode=0, stdout=DOCKER_PS_OUTPUT_OWN_ORPHANED_CONTAINER)

    with patch("installer.preflight.subprocess.run", return_value=proc):
        assert port_owner_is_own_orphan(8080, own_project_name=None) is False


def test_check_ports_available_maps_gluetun_port_to_qbittorrent_key(tmp_path):
    """
    Gluetun's own ports block is qBittorrent's effective port when
    Gluetun is active - the remediation flow needs to offer to remap
    "qbittorrent" (the real GenerationConfig.port_overrides key), not
    a "gluetun" key the template never reads.
    """

    compose_path = tmp_path / "docker-compose.yml"
    compose_path.write_text(
        "services:\n  gluetun:\n    image: qmcgaw/gluetun\n    ports:\n      - \"8080:8080\"\n"
    )

    with patch(
        "installer.preflight._port_in_use", return_value=True
    ), patch(
        "installer.preflight.identify_port_owner", return_value=None
    ), patch(
        "installer.preflight.port_owner_is_own_orphan", return_value=False
    ):
        result = check_ports_available(str(compose_path))

    assert result["port_services"] == {8080: "qbittorrent"}


def test_format_port_conflicts_shows_identified_owner():

    port_check = {
        "available": False,
        "conflicts": [8080],
        "owners": {8080: 'container "homepage-old" (image ghcr.io/gethomepage/homepage:latest)'}
    }

    formatted = format_port_conflicts(port_check)

    assert "8080" in formatted
    assert "homepage-old" in formatted


def test_format_port_conflicts_shows_unidentified_hint():

    port_check = {"available": False, "conflicts": [9999], "owners": {9999: None}}

    formatted = format_port_conflicts(port_check)

    assert "9999" in formatted
    assert "not identified as a Docker container" in formatted


def test_format_port_conflicts_lists_every_conflicting_port():

    port_check = {
        "available": False,
        "conflicts": [80, 443],
        "owners": {80: None, 443: 'container "traefik-old" (image traefik:latest)'}
    }

    formatted = format_port_conflicts(port_check)

    assert "80" in formatted
    assert "443" in formatted
    assert "traefik-old" in formatted
