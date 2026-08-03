import socket
from unittest.mock import patch

from installer.preflight import check_ports_available


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

    assert result == {"available": True, "conflicts": []}


def test_check_ports_available_reports_conflicts(tmp_path):

    compose_path = tmp_path / "docker-compose.yml"
    compose_path.write_text(COMPOSE_TWO_SERVICES)

    with patch("installer.preflight._port_in_use", side_effect=lambda port: port == 7878):
        result = check_ports_available(str(compose_path))

    assert result == {"available": False, "conflicts": [7878]}


def test_check_ports_available_checks_every_port_in_multi_port_service(tmp_path):

    compose_path = tmp_path / "docker-compose.yml"
    compose_path.write_text(COMPOSE_MULTI_PORT_SERVICE)

    with patch("installer.preflight._port_in_use", return_value=True):
        result = check_ports_available(str(compose_path))

    assert result == {"available": False, "conflicts": [80, 443]}


def test_check_ports_available_service_with_no_ports_key_does_not_crash(tmp_path):

    compose_path = tmp_path / "docker-compose.yml"
    compose_path.write_text(COMPOSE_NO_PORTS_SERVICE)

    with patch("installer.preflight._port_in_use", return_value=False):
        result = check_ports_available(str(compose_path))

    assert result == {"available": True, "conflicts": []}


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

        result = check_ports_available(str(compose_path))

    assert result == {"available": False, "conflicts": [real_port]}
