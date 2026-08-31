"""
Phase 6 - Configure. After a stack is built (stack/docker-compose.yml +
.env written) and before it's started, walk the user through the
credentials the enabled services need but don't have yet: VPN provider
+ key (gluetun), base domain (traefik), tunnel token (cloudflared),
auth key (tailscale), admin passwords (pihole/adguardhome).

Writes stack/.env and stops. No validation - Phase 7 (start) surfaces a
bad VPN key or an unresolved domain clearly enough, and a DNS/uptime
check here would just be wrong offline.

Both front ends call configure_pending() at the same point: cli.py's
run_install between _build and _start, and menu.sh's first-run wizard as
step 6 (it stays a day-2 menu item too).
"""

import typer

from installer.generate import STACK_DIR, enabled_service_keys


console = None  # set by cli.py when it imports; falls back to typer.echo


# service -> (env keys it needs, one-line hint shown before prompting)
_CREDENTIALS: dict[str, tuple[list[str], str]] = {
    "gluetun": (
        ["VPN_SERVICE_PROVIDER", "VPN_TYPE", "WIREGUARD_PRIVATE_KEY", "WIREGUARD_ADDRESSES"],
        "Your VPN provider's WireGuard details. Providers: "
        "https://github.com/qdm12/gluetun-wiki/tree/main/setup/providers",
    ),
    "traefik": (["DOMAIN"], "Base domain with DNS A records pointing at this host (blank to skip)."),
    "cloudflared": (["CLOUDFLARE_TUNNEL_TOKEN"], "Tunnel token from Cloudflare Zero Trust (starts 'ey...')."),
    "tailscale": (["TAILSCALE_AUTHKEY"], "Reusable auth key from the Tailscale admin console."),
    "pihole": (["PIHOLE_PASSWORD"], "Admin password for the Pi-hole web UI."),
    "adguardhome": (["ADGUARDHOME_PASSWORD"], "Admin password for the AdGuard Home web UI."),
}

# treated as "not really set" - the generate.py placeholder values
_PLACEHOLDERS = {"", "changeme", "changeme-please"}

# Keys that are genuinely fine to leave blank - their absence alone never
# makes a service "pending". WIREGUARD_ADDRESSES: some providers (e.g.
# Mullvad) assign it server-side. DOMAIN: "blank to skip" per its own hint,
# and it normally comes from --domain, not this walkthrough. They're still
# written when an answer is supplied and the service is pending anyway.
_OPTIONAL_KEYS = {"WIREGUARD_ADDRESSES", "DOMAIN"}


def _read_env() -> dict[str, str]:
    path = STACK_DIR / ".env"
    if not path.exists():
        return {}
    values = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            values[k.strip()] = v.strip()
    return values


def _write_env(updates: dict[str, str]) -> None:
    path = STACK_DIR / ".env"
    lines = path.read_text().splitlines() if path.exists() else []
    seen = set()
    out = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in updates:
                out.append(f"{key}={updates[key]}")
                seen.add(key)
                continue
        out.append(line)
    for key, value in updates.items():
        if key not in seen:
            out.append(f"{key}={value}")
    path.write_text("\n".join(out) + "\n")


def _is_set(env: dict[str, str], key: str) -> bool:
    return env.get(key, "") not in _PLACEHOLDERS


def pending_credentials(config) -> list[dict]:
    enabled = enabled_service_keys(config)
    env = _read_env()
    pending = []
    for service, (keys, hint) in _CREDENTIALS.items():
        if service not in enabled:
            continue
        missing = [k for k in keys if not _is_set(env, k)]
        if any(k not in _OPTIONAL_KEYS for k in missing):
            pending.append({"service": service, "keys": keys, "missing": missing, "hint": hint})
    return pending


def configure_pending(config, non_interactive: bool, answers: dict | None = None) -> dict:
    answers = answers or {}
    pending = pending_credentials(config)

    updates: dict[str, str] = {}
    still_blank: list[str] = []

    for item in pending:
        for key in item["missing"]:
            if key in answers and answers[key] != "":
                updates[key] = answers[key]
            elif not non_interactive:
                typer.echo(f"\n{item['service']}: {item['hint']}")
                value = typer.prompt(key, default="", show_default=False)
                if value:
                    updates[key] = value
                else:
                    still_blank.append(key)
            else:
                still_blank.append(key)

    if updates:
        _write_env(updates)

    return {"written": sorted(updates), "still_blank": still_blank}
