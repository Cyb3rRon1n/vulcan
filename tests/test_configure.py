from installer.configure import pending_credentials, configure_pending
from installer.tiers import TIERS
from installer.generate import GenerationConfig


def _cfg(**kw):
    base = dict(tier=TIERS["heavy"], media_path="/tmp/m", puid=1000, pgid=1000,
               timezone="UTC", enabled_optional=set())
    base.update(kw)
    return GenerationConfig(**base)


def test_pending_lists_gluetun_when_vpn_enabled_and_env_empty(tmp_path, monkeypatch):
    monkeypatch.setattr("installer.configure.STACK_DIR", tmp_path)
    (tmp_path / ".env").write_text("PUID=1000\n")

    pending = pending_credentials(_cfg(enabled_optional={"gluetun"}))

    assert any(p["service"] == "gluetun" for p in pending)


def test_pending_skips_gluetun_when_creds_already_in_env(tmp_path, monkeypatch):
    monkeypatch.setattr("installer.configure.STACK_DIR", tmp_path)
    (tmp_path / ".env").write_text(
        "VPN_SERVICE_PROVIDER=mullvad\nVPN_TYPE=wireguard\nWIREGUARD_PRIVATE_KEY=abc\n"
    )

    pending = pending_credentials(_cfg(enabled_optional={"gluetun"}))

    assert not any(p["service"] == "gluetun" for p in pending)


def test_configure_pending_writes_answers_to_env(tmp_path, monkeypatch):
    monkeypatch.setattr("installer.configure.STACK_DIR", tmp_path)
    (tmp_path / ".env").write_text("PUID=1000\nVPN_SERVICE_PROVIDER=changeme\n")

    result = configure_pending(
        _cfg(enabled_optional={"gluetun"}),
        non_interactive=True,
        answers={"VPN_SERVICE_PROVIDER": "protonvpn", "VPN_TYPE": "wireguard",
                 "WIREGUARD_PRIVATE_KEY": "k", "WIREGUARD_ADDRESSES": "10.0.0.2/32"},
    )

    env = (tmp_path / ".env").read_text()
    assert "VPN_SERVICE_PROVIDER=protonvpn" in env
    assert "VPN_SERVICE_PROVIDER=changeme" not in env
    assert "VPN_TYPE=wireguard" in env
    assert "VPN_SERVICE_PROVIDER" in result["written"]


def test_configure_pending_reports_still_blank(tmp_path, monkeypatch):
    monkeypatch.setattr("installer.configure.STACK_DIR", tmp_path)
    (tmp_path / ".env").write_text("PUID=1000\n")

    result = configure_pending(
        _cfg(custom_services={"traefik", "cloudflared"}, enabled_optional=set()),
        non_interactive=True,
        answers={},
    )

    assert "CLOUDFLARE_TUNNEL_TOKEN" in result["still_blank"]
