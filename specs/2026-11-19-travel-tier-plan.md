# Travel Tier Implementation Plan

**Goal:** Add a fourth, explicitly chosen tier, `travel`: a small box you carry. It plays from local drives with no internet, can be reached as `<hostname>.local` on any network, can drive a TV through a Kodi kiosk, and catches up on new media when it gets online (self-download, or `vulcan travel sync` from the home Vulcan over Tailscale).

**Architecture:** The tier lives in the existing engine: `tiers.py` (definition, never recommended), `services.py` (limits sized from the host, pinned images) and `generate.py` (offline-safe compose, `.local` links). The host-side pieces (Avahi, systemd timers, the rsync sync, the Kodi kiosk) go in one new engine module, `installer/travel.py`. Its plan builders are pure and `run_privileged` is the only thing that executes. `cli.py` gets the flags, a `vulcan travel` sub-app (`setup`, `sync`) and `vulcan doctor`. `menu.sh` gets a Travel entry in both tier menus and a Travel checklist.

**Tech stack:** Python 3.11+ stdlib (subprocess, socket, ipaddress, json, zipfile, urllib, tempfile, pwd, grp), Typer + Rich, Jinja2, PyYAML (all existing deps). Host tools: rsync and ssh (already needed by the media assistant and off-box backups), systemd, Avahi, Kodi. pytest and bats.

**Spec:** `specs/2026-11-19-travel-tier-design.md`

## Global constraints

- Tier name: `travel` (display name `Travel`).
- Default hostname: `vulcan`. The box answers as `<hostname>.local`.
- Flags: `--kiosk/--no-kiosk`, `--travel-ip IP`, `--hostname NAME`. This plan also adds `--self-download/--no-self-download` and `--home-sync/--no-home-sync` (see Ruling 1).
- Timer names: `vulcan-media-register.timer` (hourly, runs `vulcan media register`), `vulcan-travel-sync.timer` (hourly, runs `vulcan travel sync --if-reachable`). Kiosk unit: `vulcan-kiosk.service`.
- Minimums: 2 cores / 4 GB RAM / 64 GB free.
- Hardware: x86-64 supported and verified in v1. Raspberry Pi 5 (arm64) is experimental and documented as such.
- Travel is never auto-recommended. It is left out of `recommend_tier()` and `_next_tier_up()`.
- A travel stack never renders Traefik, Authelia, CrowdSec, Cloudflared or Watchtower, and refuses `--domain`.
- Travel compose: pinned image tags, `pull_policy: missing` on every service, no Watchtower. Nothing needs the internet to start.
- Commits, PRs and code carry no AI attribution: no `Co-Authored-By` trailer, no "generated with" line.
- vulcan CI, which every task must pass before its PR: `ruff check .` · `python -m pytest tests/ -v --cov=installer` · `shellcheck -S warning installer/menu.sh` · `shellcheck -S warning install` · `bats tests/test_menu.bats` · `bats tests/test_install.bats` · `bats tests/test_menu_pty.bats`.
- House rules (CLAUDE.md): engine modules never prompt or print, they return plain dicts. Console output lives in `cli.py`. Tests run from an isolated `tmp_path` cwd (autouse fixture in `tests/conftest.py`). ruff is pyflakes-only.
- One PR per task. Branch from an up-to-date `main` after the previous task merges: `git switch main && git pull && git switch -c travel/<n>-<slug>`. The owner confirms each push.

**Rulings (plan vs spec).** The spec is the authority. Where it leaves something open, this plan rules as follows.
1. The TUI checklist drives `vulcan build`, so self-download and home sync need CLI switches. This plan adds `--self-download` and `--home-sync`. Each switches its group on as a unit: Sonarr, Radarr, Prowlarr, qBittorrent and gluetun, or Tailscale.
2. "`_SERVICE_DEPS` keeps qBittorrent → gluetun". A global `qbittorrent → gluetun` dependency would break every no-VPN Light/Medium/Heavy stack. So `_SERVICE_DEPS` is unchanged, and the travel self-download group always contains gluetun. qBittorrent never runs on a travel box without the VPN.
3. `vulcan doctor` does not exist yet. Task 3 creates it with the travel checks only. Other tiers print "Nothing to check".
4. "Readers/audiobooks stay ordinary optional services, off". They are not in the travel tier's list, so a plain travel build has none. Custom mode (`--services`) can still add them, and they keep `:latest` tags because only the travel set is pinned.
5. "rsync over Tailscale SSH" uses plain `ssh` to the home box over the tailnet. The home Vulcan's Tailscale is a container, so Tailscale SSH there would open a shell inside the container, not on the host with the media. Either the home host's sshd with a key, or a host-installed `tailscaled --ssh`, works. The guide covers both.
6. The spec's "media assistant's import path" is `<media path>/downloads/from-home`. Sync only fetches. The owner imports with the media assistant (`--move`). A ledger file (`stack/travel-sync-ledger.txt`) stops files that were already imported from being pulled again.
7. "Size cap" is a total per run. rsync only has a per-file cap, so the run is planned from an rsync dry-run listing.
8. A Homepage tile has one link, so the optional "by IP" links form their own **By IP** group and tab. The setup summary shows both links on each line.
9. Tailscale node name on a travel box: `<hostname>-travel`, so it doesn't collide with the home box's `vulcan` node.
10. `vulcan-media-register.timer` is installed when Sonarr or Radarr is in the stack (self-download) and removed otherwise. `vulcan media register` becomes a quiet exit-0 no-op when nothing is queued.
11. Kodi add-on: Vulcan places the Jellyfin repo and plugin zips plus a pre-written login (`data.json`). Whether Kodi enables a hand-placed add-on and installs its dependencies without a click is checked on the real box in Task 9. The fallback is a one-time "Enable" step in the guide. The add-on download needs the internet, which is why the guide says to set up at home.
12. The kiosk's Jellyfin login needs a running Jellyfin and `JELLYFIN_API_KEY`. The first build therefore installs Kodi and the unit, and the login completes on `vulcan travel setup` after the first start.
13. CEC: Vulcan writes no config. Kodi's built-in libCEC is on by default. The kiosk user joins `dialout` (USB-CEC adapters) and `cec-utils` is installed for diagnosis. Most x86 HDMI ports have no CEC without a USB-CEC adapter, and the guide says so.
14. `--no-kiosk` removes the unit only. Kodi and the kiosk user stay installed (the spec says "removes the unit").

## File structure

| File | Create/Modify | Responsibility |
|---|---|---|
| `installer/tiers.py` | Modify (~45 lines) | `travel` `TierDefinition`, `TRAVEL_SELF_DOWNLOAD`/`TRAVEL_HOME_SYNC`/`TRAVEL_EXCLUDED`, `tier_shortfalls()`, `_next_tier_up()` skips travel |
| `installer/services.py` | Modify (~45 lines) | `RESOURCE_LIMITS["travel"]`, `_travel_limits()`, `resource_limits_for(tier, cpu_count, ram_gb)`, `TRAVEL_IMAGES` |
| `installer/generate.py` | Modify (~110 lines) | `GenerationConfig` travel fields, state, `enabled_service_keys` exclusion, `link_host()`, `pin_travel_images()`, compose/env/Homepage/summary travel output |
| `templates/docker-compose.yml.j2` | Modify (~20 lines) | Jellyfin published URL, gluetun offline setting, qBittorrent start condition, Tailscale node name |
| `templates/env.j2` | Modify (~20 lines) | `TRAVEL_SYNC_*`, `KIOSK_JELLYFIN_PASSWORD` |
| `installer/travel.py` | Create (~330 lines) | input checks, `apply_steps`, `write_root_file`, Avahi steps, `doctor_checks`, timers, `host_setup`, sync engine, kiosk unit/steps, Kodi add-on + Jellyfin kiosk login |
| `installer/media/probe.py` | Modify (~4 lines) | `Prober(image=...)` so a travel box probes with its pinned Jellyfin image |
| `installer/cli.py` | Modify (~260 lines) | travel flags + validation + prompts, review lines, `link_host` everywhere, `_travel_host_setup`, `vulcan doctor`, `vulcan travel setup/sync`, media register no-op, `PREVIOUS_KIOSK` |
| `installer/menu.sh` | Modify (~60 lines) | Travel in both tier radiolists, `_guided_setup_travel_options` |
| `tests/test_tiers.py`, `tests/test_services.py`, `tests/test_generate.py`, `tests/test_cli.py`, `tests/test_media_cli.py`, `tests/test_media_probe.py` | Modify | unit tests per task |
| `tests/test_travel.py` | Create | `installer/travel.py` tests |
| `tests/test_menu.bats` | Modify | travel menu tests, `PREVIOUS_KIOSK` in `_detect` |
| `docs/guides/travel.md` | Create | the travel guide |
| `mkdocs.yml`, `docs/tiers.md`, `docs/services-catalog.md`, `README.md`, `ROADMAP.md`, `CHANGELOG.md`, `CLAUDE.md` | Modify | docs |
| `specs/2026-11-19-travel-tier-design.md`, `specs/2026-11-19-travel-tier-plan.md` | Add (Task 1 commit) | spec + this plan |

---

### Task 1: Tier definition, sizing, never recommended, CLI flags + validation, state

**Files:**
- Modify: `installer/tiers.py` (~45 lines), `installer/services.py` (~30 lines), `installer/generate.py` (~15 lines), `installer/cli.py` (~140 lines)
- Create: `installer/travel.py` (~25 lines)
- Test: `tests/test_tiers.py`, `tests/test_services.py`, `tests/test_generate.py`, `tests/test_cli.py`

**Interfaces:**
- Produces:
  - `installer.tiers`: `TIERS["travel"]`, `TRAVEL_SELF_DOWNLOAD: tuple[str, ...] = ("sonarr", "radarr", "prowlarr", "qbittorrent", "gluetun")`, `TRAVEL_HOME_SYNC: tuple[str, ...] = ("tailscale",)`, `TRAVEL_EXCLUDED: frozenset[str]`, `tier_shortfalls(system_info: SystemInfo, tier: TierDefinition) -> list[str]`
  - `installer.services.resource_limits_for(tier_name: str, cpu_count: int | None = None, ram_gb: float | None = None) -> dict[str, dict[str, str]]`
  - `GenerationConfig` fields: `ram_gb: float | None = None`, `hostname: str = "vulcan"`, `travel_ip: str | None = None`, `kiosk: bool = False`
  - state keys `hostname`, `travel_ip`, `kiosk`
  - `installer.travel.valid_hostname(name: str) -> bool`, `installer.travel.valid_ip(value: str) -> bool`
  - CLI options on `vulcan` and `vulcan build`: `--hostname`, `--travel-ip`, `--kiosk/--no-kiosk`, `--self-download/--no-self-download`, `--home-sync/--no-home-sync`. `run_install(..., hostname=None, travel_ip=None, kiosk=None, self_download=None, home_sync=None)`, plus the same five keyword params on `_gather_generation_config`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_tiers.py`:

```python
from installer.tiers import (
    TRAVEL_EXCLUDED,
    TRAVEL_HOME_SYNC,
    TRAVEL_SELF_DOWNLOAD,
    _next_tier_up,
    tier_shortfalls,
)


def test_travel_tier_definition():

    travel = TIERS["travel"]

    assert (travel.min_cores, travel.min_ram_gb, travel.min_disk_gb) == (2, 4, 64)
    assert {s.key for s in travel.services if not s.optional} == {"jellyfin", "homepage", "filebrowser"}
    assert {s.key for s in travel.services if s.optional} == set(TRAVEL_SELF_DOWNLOAD) | set(TRAVEL_HOME_SYNC)
    assert not {s.key for s in travel.services} & TRAVEL_EXCLUDED


def test_travel_is_never_recommended():

    for cores, ram, disk in [(1, 2, 10), (2, 4, 64), (4, 8, 500), (64, 512, 50000)]:
        assert recommend_tier(make_system_info(cores, ram, disk)).tier.name != "travel"


def test_next_tier_up_skips_travel():

    assert _next_tier_up(TIERS["travel"]) is None
    assert _next_tier_up(TIERS["light"]).name == "medium"


def test_tier_shortfalls_against_travel_minimums():

    assert tier_shortfalls(make_system_info(2, 4, 64), TIERS["travel"]) == []
    assert len(tier_shortfalls(make_system_info(1, 2, 32), TIERS["travel"])) == 3
```

Append to `tests/test_services.py`:

```python
def test_resource_limits_for_travel_never_raises_and_falls_back_to_light():

    assert resource_limits_for("travel") == resource_limits_for("light")


def test_travel_limits_scale_with_the_host():

    small = resource_limits_for("travel", cpu_count=2, ram_gb=4)
    big = resource_limits_for("travel", cpu_count=8, ram_gb=16)

    assert small["jellyfin"] == {"cpus": "2.0", "memory": "1638m"}
    assert big["jellyfin"] == {"cpus": "8.0", "memory": "6553m"}
    assert small["homepage"] == {"cpus": "0.5", "memory": "256m"}
    assert big["homepage"] == {"cpus": "2.0", "memory": "983m"}
    assert big["qbittorrent"] == {"cpus": "4.0", "memory": "1966m"}
```

Append to `tests/test_generate.py`:

```python
def test_travel_state_round_trips_options(tmp_path):

    config = make_config("travel", enabled_optional={"sonarr", "radarr", "prowlarr", "qbittorrent", "gluetun"})
    config.hostname, config.travel_ip, config.kiosk = "trip", "192.168.8.50", True

    save_state(config, tmp_path)
    state = load_previous_state(tmp_path)

    assert state["tier"] == "travel"
    assert (state["hostname"], state["travel_ip"], state["kiosk"]) == ("trip", "192.168.8.50", True)
    assert set(state["enabled_optional"]) == {"sonarr", "radarr", "prowlarr", "qbittorrent", "gluetun"}
```

Append to `tests/test_cli.py`:

```python
from installer.cli import _config_from_previous_state


def _build_travel(tmp_path, *extra, info=None):

    media_path = str(tmp_path / "media")

    with patch("installer.cli.detect_system", return_value=info or make_system_info()), patch(
        "installer.cli.detect_disk", return_value={"disk_free_gb": 900.0, "disk_path_checked": media_path}
    ), patch("installer.cli.write_stack", return_value=READY_WRITE_RESULT) as mock_write_stack:

        result = runner.invoke(app, [
            "build", "--tier", "travel", "--media-path", media_path, "--non-interactive", "--yes", *extra
        ])

    return result, mock_write_stack


def test_build_travel_defaults(tmp_path):

    result, mock_write_stack = _build_travel(tmp_path)

    assert result.exit_code == 0, result.output
    config = mock_write_stack.call_args[0][0]
    assert config.tier.name == "travel"
    assert (config.hostname, config.travel_ip, config.kiosk) == ("vulcan", None, False)
    assert config.enabled_optional == set()
    assert config.ram_gb == 32.0


def test_build_travel_with_every_option(tmp_path):

    result, mock_write_stack = _build_travel(
        tmp_path, "--self-download", "--home-sync", "--kiosk", "--hostname", "trip", "--travel-ip", "192.168.8.50"
    )

    assert result.exit_code == 0, result.output
    config = mock_write_stack.call_args[0][0]
    assert config.enabled_optional == {"sonarr", "radarr", "prowlarr", "qbittorrent", "gluetun", "tailscale"}
    assert (config.hostname, config.travel_ip, config.kiosk) == ("trip", "192.168.8.50", True)


def test_build_travel_rerun_keeps_previous_travel_options(tmp_path):

    previous = {**PREVIOUS_STATE, "tier": "travel", "media_path": str(tmp_path / "media"),
                "enabled_optional": ["tailscale"], "hostname": "trip", "travel_ip": "192.168.8.50", "kiosk": True}

    with patch("installer.cli.load_previous_state", return_value=previous):
        result, mock_write_stack = _build_travel(tmp_path)

    assert result.exit_code == 0, result.output
    config = mock_write_stack.call_args[0][0]
    assert config.enabled_optional == {"tailscale"}
    assert (config.hostname, config.travel_ip, config.kiosk) == ("trip", "192.168.8.50", True)


@pytest.mark.parametrize("flags, message", [
    (["--hostname", "Bad_Name"], "--hostname"),
    (["--travel-ip", "not-an-ip"], "--travel-ip"),
    (["--services", "jellyfin,watchtower"], "not part of the travel tier"),
    (["--domain", "media.example.com"], "not part of the travel tier"),
])
def test_build_travel_rejects_bad_input(tmp_path, flags, message):

    result, mock_write_stack = _build_travel(tmp_path, *flags)

    assert result.exit_code == 1
    assert message in result.output
    mock_write_stack.assert_not_called()


def test_travel_only_flags_rejected_on_home_tiers(tmp_path):

    media_path = str(tmp_path / "media")

    with patch("installer.cli.detect_system", return_value=make_system_info()), patch(
        "installer.cli.detect_disk", return_value={"disk_free_gb": 900.0, "disk_path_checked": media_path}
    ), patch("installer.cli.write_stack", return_value=READY_WRITE_RESULT):

        result = runner.invoke(app, [
            "build", "--tier", "light", "--media-path", media_path, "--non-interactive", "--yes", "--kiosk"
        ])

    assert result.exit_code == 1
    assert "only apply to --tier travel" in result.output


def test_unknown_tier_message_lists_travel(tmp_path):

    result = runner.invoke(app, [
        "build", "--tier", "bogus", "--media-path", str(tmp_path), "--non-interactive", "--yes"
    ])

    assert result.exit_code == 1
    assert "'travel'" in result.output


def test_config_from_previous_state_restores_travel_options():

    config = _config_from_previous_state(
        {**PREVIOUS_STATE, "tier": "travel", "hostname": "trip", "travel_ip": "192.168.8.50", "kiosk": True}
    )

    assert (config.tier.name, config.hostname, config.travel_ip, config.kiosk) == ("travel", "trip", "192.168.8.50", True)


def test_config_from_previous_state_defaults_travel_options_for_old_state():

    config = _config_from_previous_state(PREVIOUS_STATE)

    assert (config.hostname, config.travel_ip, config.kiosk) == ("vulcan", None, False)
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_tiers.py tests/test_services.py tests/test_generate.py tests/test_cli.py -q -k "travel"`
Expected: FAIL. Collection fails with `ImportError: cannot import name 'TRAVEL_EXCLUDED' from 'installer.tiers'`, and the CLI tests fail on `KeyError: 'travel'` / exit code 2 (`No such option: --kiosk`).

- [ ] **Step 3: Implement**

`installer/tiers.py`: change the module docstring's first sentence to:

```python
"""
Deterministic tier scoring: given a SystemInfo, decide which home tier
(Light/Medium/Heavy) this machine qualifies for and why. Travel is a
fourth tier the user picks on purpose - it is never recommended and
never part of the Light -> Medium -> Heavy ladder. No subprocess
calls, no privilege concerns, no LLM involvement - pure decision logic
over numbers detect.py already collected.
"""
```

Add after `_HEAVY_SERVICES = [...]` (before `TIERS`):

```python
# Travel: its own short list, not cumulative with Light/Medium/Heavy. The
# core plays offline; each opt-in group switches on as a unit, so the
# self-download group always brings gluetun with qBittorrent.
TRAVEL_SELF_DOWNLOAD: tuple[str, ...] = ("sonarr", "radarr", "prowlarr", "qbittorrent", "gluetun")
TRAVEL_HOME_SYNC: tuple[str, ...] = ("tailscale",)

# Home-only services a travel stack never renders, even from --services.
TRAVEL_EXCLUDED: frozenset[str] = frozenset({"traefik", "authelia", "crowdsec", "cloudflared", "watchtower"})

_TRAVEL_SERVICES = [
    ServiceDefinition("jellyfin", "Jellyfin", category="Media Server"),
    ServiceDefinition("homepage", "Homepage/Homarr dashboard", category="Dashboards"),
    ServiceDefinition("filebrowser", "FileBrowser (file manager)", category="Utilities"),
    ServiceDefinition("sonarr", "Sonarr", optional=True, category="Media Management"),
    ServiceDefinition("radarr", "Radarr", optional=True, category="Media Management"),
    ServiceDefinition("prowlarr", "Prowlarr", optional=True, category="Media Management"),
    ServiceDefinition("qbittorrent", "qBittorrent", optional=True, category="Downloaders"),
    ServiceDefinition("gluetun", "Gluetun (VPN)", optional=True, category="Infrastructure"),
    ServiceDefinition("tailscale", "Tailscale (private remote access)", optional=True, category="Infrastructure"),
]
```

Replace `TIERS`:

```python
TIERS: dict[str, TierDefinition] = {
    "light": TierDefinition("light", "Light", 2, 4, 100, _LIGHT_SERVICES),
    "medium": TierDefinition("medium", "Medium", 4, 8, 500, _MEDIUM_SERVICES),
    "heavy": TierDefinition("heavy", "Heavy", 6, 16, 1000, _HEAVY_SERVICES),
    "travel": TierDefinition("travel", "Travel", 2, 4, 64, _TRAVEL_SERVICES),
}
```

Replace `_next_tier_up`:

```python
def _next_tier_up(tier: TierDefinition) -> TierDefinition | None:

    # Travel is chosen, never climbed to - it isn't on the ladder.
    if tier.name not in _ORDERED_HIGH_TO_LOW:
        return None

    index = _ORDERED_HIGH_TO_LOW.index(tier.name)

    if index == 0:
        return None

    return TIERS[_ORDERED_HIGH_TO_LOW[index - 1]]
```

Add after `_shortfalls`:

```python
def tier_shortfalls(system_info: SystemInfo, tier: TierDefinition) -> list[str]:
    """What this host is short of for `tier`'s minimums - empty when it meets them."""

    cores = system_info.cpu_cores_logical or system_info.cpu_cores_physical or 0

    return _shortfalls(cores, system_info, tier)
```

`installer/services.py`: add a `"travel"` entry to `RESOURCE_LIMITS`. It is the fallback when the host size isn't known:

```python
    "travel": {
        "light": ("0.5", "256m"),
        "standard": ("1.0", "512m"),
        "heavy": ("1.5", "1g")
    },
```

Replace `resource_limits_for`:

```python
def _travel_limits(cores: int, ram_gb: float) -> dict[str, tuple[str, str]]:
    """A travel box runs little besides Vulcan, so its limits are shares of the
    real host, never below Light's: light services 1/4 core + 6% RAM, standard
    1/2 core + 12%, heavy (Jellyfin) every core + 40%."""

    mb = ram_gb * 1024

    return {
        "light": (f"{max(0.5, cores * 0.25):.1f}", f"{max(256, int(mb * 0.06))}m"),
        "standard": (f"{max(1.0, cores * 0.5):.1f}", f"{max(512, int(mb * 0.12))}m"),
        "heavy": (f"{max(1.5, float(cores)):.1f}", f"{max(1024, int(mb * 0.4))}m"),
    }


def resource_limits_for(
    tier_name: str, cpu_count: int | None = None, ram_gb: float | None = None
) -> dict[str, dict[str, str]]:

    table = (
        _travel_limits(cpu_count, ram_gb) if tier_name == "travel" and cpu_count and ram_gb
        else RESOURCE_LIMITS[tier_name]
    )

    return {
        key: {"cpus": table[profile][0], "memory": table[profile][1]}
        for key, profile in RESOURCE_PROFILES.items()
    }
```

Create `installer/travel.py`:

```python
"""
Travel tier: the pieces that live on the box itself, outside the Docker
stack. Pure checks and plan builders; nothing here prompts or prints.
"""

import ipaddress
import re

_HOSTNAME = re.compile(r"[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?")


def valid_hostname(name: str) -> bool:
    """One DNS label (RFC 1123): what Avahi can publish as <name>.local."""

    return bool(_HOSTNAME.fullmatch(name))


def valid_ip(value: str) -> bool:

    try:
        ipaddress.ip_address(value)
    except ValueError:
        return False

    return True
```

`installer/generate.py`:
1. Add to `GenerationConfig`, after `openvpn_password: str | None = None`:

```python
    # Travel tier only (ignored by every other tier).
    ram_gb: float | None = None
    hostname: str = "vulcan"
    travel_ip: str | None = None
    kiosk: bool = False
```

2. In `save_state()`, after `"dashy_private": config.dashy_private,` add:

```python
        "hostname": config.hostname,
        "travel_ip": config.travel_ip,
        "kiosk": config.kiosk,
```

3. In `_limits_for()`, replace `limits = resource_limits_for(config.tier.name)` with:

```python
    limits = resource_limits_for(config.tier.name, config.cpu_count, config.ram_gb)
```

`installer/cli.py`:
1. Imports. Replace the tiers import and add the travel import:

```python
from installer.tiers import (
    ALL_SERVICES,
    TIERS,
    TRAVEL_EXCLUDED,
    TRAVEL_HOME_SYNC,
    TRAVEL_SELF_DOWNLOAD,
    recommend_tier,
    tier_description,
    tier_shortfalls,
)
from installer.travel import valid_hostname, valid_ip
```

2. `_config_from_previous_state()`: after `dashy_private=previous.get("dashy_private", True),` add:

```python
        hostname=previous.get("hostname") or "vulcan",
        travel_ip=previous.get("travel_ip"),
        kiosk=bool(previous.get("kiosk")),
```

3. Both `--tier` options (`build` and `main`): change `help="light, medium, or heavy"` to `help="light, medium, heavy, or travel"`.

4. In both `build()` and `main()`, add right after the `from_plan` option (before the closing `):`):

```python
    hostname: str | None = typer.Option(
        None, "--hostname", help="Travel tier: the box's network name, reached as <name>.local (default vulcan)"
    ),
    travel_ip: str | None = typer.Option(
        None, "--travel-ip", help="Travel tier: a reserved IP for a second 'by IP' link on every tile"
    ),
    kiosk: bool | None = typer.Option(None, "--kiosk/--no-kiosk", help="Travel tier: Kodi full-screen on the TV at boot"),
    self_download: bool | None = typer.Option(
        None, "--self-download/--no-self-download",
        help="Travel tier: Sonarr, Radarr, Prowlarr and qBittorrent behind gluetun"
    ),
    home_sync: bool | None = typer.Option(
        None, "--home-sync/--no-home-sync", help="Travel tier: Tailscale + `vulcan travel sync` from your home Vulcan"
    ),
```

In both functions' `run_install(...)` calls, add after `plan_path=from_plan,`:

```python
        hostname=hostname,
        travel_ip=travel_ip,
        kiosk=kiosk,
        self_download=self_download,
        home_sync=home_sync,
```

5. `run_install` signature: replace `    dry_run: bool = False,\n    plan_path: str | None = None\n):` with:

```python
    dry_run: bool = False,
    plan_path: str | None = None,
    hostname: str | None = None,
    travel_ip: str | None = None,
    kiosk: bool | None = None,
    self_download: bool | None = None,
    home_sync: bool | None = None
):
```

Replace the tier check:

```python
    if tier is not None and tier not in TIERS:
        console.print(f"[red]--tier '{tier}' must be 'light', 'medium', 'heavy' or 'travel'.[/red]")
        raise typer.Exit(code=1)
```

Replace the `_gather_generation_config(` call's last line `            cloudflare_email, auth_username, auth_password, auth_users_raw, panel\n        )` with:

```python
            cloudflare_email, auth_username, auth_password, auth_users_raw, panel,
            hostname=hostname, travel_ip=travel_ip, kiosk=kiosk,
            self_download=self_download, home_sync=home_sync
        )
```

6. `_gather_generation_config` signature: replace `    panel: RunPanel | _NoOpPanel | None = None\n) -> GenerationConfig:` with:

```python
    panel: RunPanel | _NoOpPanel | None = None,
    hostname: str | None = None,
    travel_ip: str | None = None,
    kiosk: bool | None = None,
    self_download: bool | None = None,
    home_sync: bool | None = None
) -> GenerationConfig:
```

7. In `_gather_generation_config`, change both `for tier_name in ("light", "medium", "heavy"):` loops to `for tier_name in ("light", "medium", "heavy", "travel"):`. Replace the interactive tier prompt:

```python
        chosen_tier_name = typer.prompt("Which tier? (light/medium/heavy/travel)", default=default_choice)

        while chosen_tier_name not in TIERS:
            chosen_tier_name = typer.prompt(
                "Please enter 'light', 'medium', 'heavy' or 'travel'", default=default_choice
            )
```

8. Skip the home-tier toggle questions on travel. Run:

```bash
sed -i '/^def _gather_generation_config(/,/^def _resolve_port_conflicts(/ s/^    if custom_services_selected is None:$/    if ask_home_toggles:/' installer/cli.py
grep -c "^    if ask_home_toggles:$" installer/cli.py   # expect 10
```

Then replace `    openvpn_password = os.environ.get("OPENVPN_PASSWORD")\n\n    if ask_home_toggles:` (the second env-read block, just after `enabled_optional = set()`) with:

```python
    openvpn_password = os.environ.get("OPENVPN_PASSWORD")

    # Travel is its own shape, not a step on the Light/Medium/Heavy ladder:
    # two opt-in groups + the kiosk instead of the home-tier toggles below.
    ask_home_toggles = custom_services_selected is None and chosen_tier_name != "travel"
    hostname_value, travel_ip_value, kiosk_value = "vulcan", None, False

    if chosen_tier_name == "travel":

        blocked = sorted((custom_services_selected or set()) & TRAVEL_EXCLUDED)

        if domain is not None:
            blocked.append("--domain")

        if blocked:
            console.print(f"[red]{', '.join(blocked)}: not part of the travel tier.[/red]")
            raise typer.Exit(code=1)

        gaps = tier_shortfalls(info, chosen_tier)

        if gaps:
            panel.note(f"[yellow]! Below the Travel minimum: {', '.join(gaps)}.[/yellow]")

        hostname_value = hostname or (previous.get("hostname") if previous else None) or "vulcan"

        if hostname is None and not non_interactive:
            hostname_value = typer.prompt(
                "Name for this box on any network (reached as <name>.local)", default=hostname_value
            )

        if not valid_hostname(hostname_value):
            console.print(f"[red]--hostname '{hostname_value}' is not a valid name (a-z, 0-9, dashes).[/red]")
            raise typer.Exit(code=1)

        travel_ip_value = travel_ip if travel_ip is not None else (previous.get("travel_ip") if previous else None)

        if travel_ip is None and not non_interactive:
            travel_ip_value = typer.prompt(
                "Reserved IP for a second 'by IP' link (blank to skip)", default=travel_ip_value or ""
            ) or None

        if travel_ip_value and not valid_ip(travel_ip_value):
            console.print(f"[red]--travel-ip '{travel_ip_value}' is not an IP address.[/red]")
            raise typer.Exit(code=1)

        if custom_services_selected is None:

            previous_optional = set(previous["enabled_optional"]) if previous else set()

            for flag, keys, question in (
                (self_download, TRAVEL_SELF_DOWNLOAD,
                 "Self-download: Sonarr, Radarr, Prowlarr and qBittorrent behind a VPN?"),
                (home_sync, TRAVEL_HOME_SYNC, "Sync new media from your home Vulcan over Tailscale?"),
            ):

                default = set(keys) <= previous_optional

                if flag is not None:
                    wanted = flag
                elif non_interactive:
                    wanted = default
                else:
                    wanted = typer.confirm(question, default=default)

                if wanted:
                    enabled_optional.update(keys)

        kiosk_default = bool(previous.get("kiosk")) if previous else False

        if kiosk is not None:
            kiosk_value = kiosk
        elif non_interactive:
            kiosk_value = kiosk_default
        else:
            kiosk_value = typer.confirm("Kodi kiosk: start Kodi full-screen on the TV at boot?", default=kiosk_default)

    elif any(value is not None for value in (hostname, travel_ip, kiosk, self_download, home_sync)):

        console.print(
            "[red]These flags only apply to --tier travel: --hostname, --travel-ip, "
            "--kiosk, --self-download, --home-sync.[/red]"
        )
        raise typer.Exit(code=1)

    if ask_home_toggles:
```

9. GPU question: replace `(chosen_tier_name == "heavy" or custom_services_selected is not None)` with:

```python
        (chosen_tier_name in ("heavy", "travel") or custom_services_selected is not None)
```

10. In the returned `GenerationConfig(...)`, add after `openvpn_password=openvpn_password` (put a comma after it):

```python
        openvpn_password=openvpn_password,
        ram_gb=info.ram_total_gb,
        hostname=hostname_value,
        travel_ip=travel_ip_value,
        kiosk=kiosk_value
    )
```

11. `_build()` review: after `panel.note(f"  GPU passthrough: {config.gpu_vendor or 'disabled'}")` add:

```python
    if config.tier.name == "travel":
        panel.note(f"  Name on the network: {config.hostname}.local")
        panel.note(f"  By-IP link: {config.travel_ip or 'none'}")
        panel.note(f"  Self-download: {'enabled' if 'gluetun' in config.enabled_optional else 'disabled'}")
        panel.note(f"  Sync from home: {'enabled' if 'tailscale' in config.enabled_optional else 'disabled'}")
        panel.note(f"  Kodi kiosk: {'enabled' if config.kiosk else 'disabled'}")
```

- [ ] **Step 4: Run to verify they pass**

Run: `python -m pytest tests/test_tiers.py tests/test_services.py tests/test_generate.py tests/test_cli.py -q && python -m pytest tests/ -q && ruff check .`
Expected: PASS. Whole suite green, ruff clean.

- [ ] **Step 5: Commit**

```bash
git switch -c travel/1-tier
git add installer/tiers.py installer/services.py installer/generate.py installer/cli.py installer/travel.py \
        tests/test_tiers.py tests/test_services.py tests/test_generate.py tests/test_cli.py \
        specs/2026-11-19-travel-tier-design.md specs/2026-11-19-travel-tier-plan.md
git commit -m "feat(travel): travel tier definition, host-sized limits, flags and saved options"
```

PR (after the owner OKs the push): `git push -u origin travel/1-tier && gh pr create --title "Travel tier 1/9: tier, sizing, flags, state" --body "Adds the travel tier (never recommended), limits sized from the host, --hostname/--travel-ip/--kiosk/--self-download/--home-sync with validation, and saves them in .vulcan-state.json. Spec: specs/2026-11-19-travel-tier-design.md"`

---

### Task 2: Generate the travel stack: pinned images, `pull_policy: missing`, no Watchtower, `.local` links, by-IP links, Jellyfin published URL

**Files:**
- Modify: `installer/services.py` (~15 lines), `installer/generate.py` (~80 lines), `templates/docker-compose.yml.j2` (~3 lines), `installer/cli.py` (~3 lines)
- Test: `tests/test_generate.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: `TRAVEL_EXCLUDED`, `GenerationConfig.hostname/travel_ip` (Task 1).
- Produces: `installer.services.TRAVEL_IMAGES: dict[str, str]` (service key → pinned image ref). `installer.generate.link_host(config: GenerationConfig, detected_ip: str | None) -> str | None`. `installer.generate.pin_travel_images(compose: str) -> str`. `render_compose` passes `travel: bool` and `jellyfin_published_url: str | None` to the template.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_generate.py`:

```python
from installer.generate import link_host
from installer.services import TRAVEL_IMAGES
from installer.tiers import TRAVEL_HOME_SYNC, TRAVEL_SELF_DOWNLOAD

TRAVEL_ALL = set(TRAVEL_SELF_DOWNLOAD) | set(TRAVEL_HOME_SYNC)


def travel_config(enabled_optional=None, custom_services=None, **fields):

    config = make_config("travel", enabled_optional=enabled_optional, custom_services=custom_services)

    for key, value in fields.items():
        setattr(config, key, value)

    return config


def test_travel_compose_core_services_pinned_and_offline_safe():

    services = yaml.safe_load(render_compose(travel_config()))["services"]

    assert set(services) == {"jellyfin", "homepage", "filebrowser"}

    for name, service in services.items():
        assert service["pull_policy"] == "missing", name
        assert service["image"] == TRAVEL_IMAGES[name], name


def test_travel_compose_every_option_pinned_and_no_watchtower():

    services = yaml.safe_load(render_compose(travel_config(enabled_optional=TRAVEL_ALL)))["services"]

    assert set(services) == {"jellyfin", "homepage", "filebrowser", *TRAVEL_ALL}
    assert all(service["image"] == TRAVEL_IMAGES[name] for name, service in services.items())
    assert all(not service["image"].endswith(":latest") for service in services.values())


def test_travel_custom_mode_still_drops_home_only_services():

    config = travel_config(custom_services={"jellyfin", "homepage", "watchtower", "traefik"})

    assert enabled_service_keys(config) == {"jellyfin", "homepage"}
    assert "watchtower" not in yaml.safe_load(render_compose(config))["services"]


def test_home_tier_compose_is_not_pinned():

    compose_text = render_compose(make_config("light"))

    assert "pull_policy" not in compose_text
    assert "image: lscr.io/linuxserver/jellyfin:latest" in compose_text


def test_travel_jellyfin_published_url_uses_dot_local():

    services = yaml.safe_load(render_compose(travel_config(hostname="trip")))["services"]

    assert "JELLYFIN_PublishedServerUrl=http://trip.local:8096" in services["jellyfin"]["environment"]


def test_home_tier_jellyfin_has_no_published_url():

    services = yaml.safe_load(render_compose(make_config("light")))["services"]

    assert not any(e.startswith("JELLYFIN_PublishedServerUrl") for e in services["jellyfin"]["environment"])


def test_link_host_is_dot_local_on_travel_and_detected_ip_elsewhere():

    assert link_host(travel_config(hostname="trip"), "10.0.0.5") == "trip.local"
    assert link_host(make_config("light"), "10.0.0.5") == "10.0.0.5"


def _hrefs(groups_yaml):

    return [tile["href"] for group in yaml.safe_load(groups_yaml)
            for items in group.values() for item in items for tile in item.values()]


def test_travel_homepage_tiles_link_to_dot_local():

    config = travel_config(hostname="trip")
    hrefs = _hrefs(render_homepage_services(config, link_host(config, "10.0.0.5")))

    assert "http://trip.local:8096" in hrefs
    assert not any("10.0.0.5" in href for href in hrefs)


def test_travel_ip_adds_a_by_ip_group_tab_and_summary_link():

    config = travel_config(hostname="trip", travel_ip="192.168.8.50")
    host = link_host(config, None)
    groups = yaml.safe_load(render_homepage_services(config, host))
    by_ip = next(group["By IP"] for group in groups if "By IP" in group)

    assert {"Jellyfin (by IP)", "FileBrowser (file manager) (by IP)"} == {name for item in by_ip for name in item}
    assert "http://192.168.8.50:8096" in [tile["href"] for item in by_ip for tile in item.values()]
    assert yaml.safe_load(render_homepage_settings(config, host))["layout"]["By IP"]["tab"] == "By IP"
    assert "http://trip.local:8096  (by IP: http://192.168.8.50:8096)" in render_stack_summary(config, host)


def test_no_by_ip_group_without_travel_ip():

    config = travel_config(hostname="trip")

    assert not any("By IP" in group for group in yaml.safe_load(render_homepage_services(config, "trip.local")))


def test_travel_homepage_allows_dot_local_and_travel_ip_hosts():

    config = travel_config(hostname="trip", travel_ip="192.168.8.50")
    services = yaml.safe_load(render_compose(config, host_ip=link_host(config, None)))["services"]
    allowed = next(e for e in services["homepage"]["environment"] if e.startswith("HOMEPAGE_ALLOWED_HOSTS="))

    assert "trip.local:3000" in allowed
    assert "192.168.8.50:3000" in allowed
```

Append to `tests/test_cli.py`:

```python
def test_urls_shell_prints_dot_local_links_for_travel(tmp_path):

    state = {**PREVIOUS_STATE, "tier": "travel", "enabled_optional": [], "hostname": "trip"}

    with patch("installer.cli.STACK_DIR", tmp_path / "stack"), patch(
        "installer.cli.load_previous_state", return_value=state
    ), patch("installer.cli.detect_host_ip", return_value="192.168.1.50"):

        result = runner.invoke(app, ["urls"])

    assert result.exit_code == 0, result.output
    assert "http://trip.local:8096" in result.output
    assert "192.168.1.50" not in result.output
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_generate.py tests/test_cli.py -q -k "travel or by_ip or published_url or pinned or dot_local"`
Expected: FAIL. Collection fails with `ImportError: cannot import name 'link_host' from 'installer.generate'`.

- [ ] **Step 3: Implement**

`installer/services.py`, at the end:

```python
# Travel boxes start offline, so every image they run is a fixed tag that
# `docker compose up` never has to fetch. Current as of 2026-11-18 - bump
# these deliberately (pull each one, run the Task 9 checks) in a release.
TRAVEL_IMAGES: dict[str, str] = {
    "jellyfin": "lscr.io/linuxserver/jellyfin:12.4ubu2604-ls60",
    "homepage": "ghcr.io/gethomepage/homepage:v2.8.0",
    "filebrowser": "gtstef/filebrowser:2.0.2-stable",
    "sonarr": "lscr.io/linuxserver/sonarr:4.0.20.3014-ls5",
    "radarr": "lscr.io/linuxserver/radarr:7.0.3.10918-ls328",
    "prowlarr": "lscr.io/linuxserver/prowlarr:3.0.2.5780-ls169",
    "qbittorrent": "lscr.io/linuxserver/qbittorrent:5.3.0_v2.1.2-ls487",
    "gluetun": "qmcgaw/gluetun:v3.41.3",
    "tailscale": "tailscale/tailscale:v1.104.7",
}
```

`installer/generate.py`:
1. Add `import re` to the stdlib imports. Change the two project imports:

```python
from installer.services import TRAVEL_IMAGES, resource_limits_for
from installer.tiers import ALL_SERVICES, TIERS, TRAVEL_EXCLUDED, TierDefinition
```

2. Add `"By IP": "By IP",` to `_HOMEPAGE_TABS`.

3. Replace `enabled_service_keys` and add `link_host` after it:

```python
def enabled_service_keys(config: GenerationConfig) -> set[str]:

    if config.custom_services is not None:
        keys = config.custom_services
    else:
        keys = {
            service.key for service in config.tier.services
            if not service.optional or service.key in config.enabled_optional
        }

    # One choke point for every path in (flags, --services, --from-plan).
    if config.tier.name == "travel":
        return keys - TRAVEL_EXCLUDED

    return keys


def link_host(config: GenerationConfig, detected_ip: str | None) -> str | None:
    """Host part of every generated link. A travel box moves between networks,
    so it gets <hostname>.local (Avahi answers it anywhere) instead of the IP
    it happened to have at build time."""

    if config.tier.name == "travel":
        return f"{config.hostname}.local"

    return detected_ip
```

4. `_homepage_allowed_hosts`: before `    return ",".join(hosts)` add:

```python
    if config.travel_ip:
        hosts.append(f"{config.travel_ip}:3000")
```

5. Replace `render_compose` and add `pin_travel_images` before it:

```python
def pin_travel_images(compose: str) -> str:
    """Swap each travel service's :latest image for its pinned tag and add
    `pull_policy: missing` to every service, so an offline `up -d` never tries
    to reach a registry."""

    for ref in TRAVEL_IMAGES.values():
        compose = compose.replace(f"image: {ref.rsplit(':', 1)[0]}:latest\n", f"image: {ref}\n")

    return re.sub(r"^(    image: \S+)$", r"\1\n    pull_policy: missing", compose, flags=re.M)


def render_compose(config: GenerationConfig, host_ip: str | None = None) -> str:

    template = _jinja_env().get_template("docker-compose.yml.j2")
    enabled = enabled_service_keys(config)
    travel = config.tier.name == "travel"
    ports = resolve_ports(config)

    rendered = template.render(
        enabled=enabled,
        limits=_limits_for(config),
        gpu_vendor=config.gpu_vendor,
        render_gid=(
            detect_render_group_gid() if config.gpu_vendor in ("amd", "intel") else None
        ),
        domain=config.domain,
        homepage_allowed_hosts=_homepage_allowed_hosts(config, enabled, host_ip),
        homepage_private=config.homepage_private,
        dashy_private=config.dashy_private,
        cloudflare_dns=config.cloudflare_dns,
        cloudflare_email=config.cloudflare_email,
        tunnel_entrypoints=",tunnel" if "cloudflared" in enabled else "",
        ports=ports,
        docker_gid=detect_docker_group_gid() if "atlas" in enabled else None,
        travel=travel,
        jellyfin_published_url=f"http://{config.hostname}.local:{ports['jellyfin']}" if travel else None,
    )

    return pin_travel_images(rendered) if travel else rendered
```

6. `render_homepage_services`: after the group loop's `        if items:\n            groups.append({group_name: items})` and before the `# Always present, regardless of what's enabled` comment, add:

```python

    # Travel: a Homepage tile carries one link, so the "by IP" twins (for
    # devices that can't resolve .local) get their own group and tab.
    if config.travel_ip:

        by_ip = []

        for key in dict.fromkeys(k for keys in _HOMEPAGE_GROUPS.values() for k in keys):

            href = _service_href(key, config, config.travel_ip) if key in enabled else None

            if href:
                by_ip.append({f"{display_names[key]} (by IP)": {
                    "href": href,
                    "icon": _HOMEPAGE_ICONS.get(key, f"{key}.png"),
                    "description": f"Same as above, at {config.travel_ip}",
                }})

        if by_ip:
            groups.append({"By IP": by_ip})
```

7. `_homepage_populated_groups`: before `    populated.append("Guides")` add:

```python
    if config.travel_ip and any(key in enabled for keys in _HOMEPAGE_GROUPS.values() for key in keys):
        populated.append("By IP")
```

8. Replace `render_stack_summary`:

```python
def render_stack_summary(config: GenerationConfig, host_ip: str | None) -> str:

    enabled = enabled_service_keys(config)
    display_names = {service.key: service.display_name for service in ALL_SERVICES}

    def line(label: str, key: str) -> str:

        href = _service_href(key, config, host_ip)

        if config.travel_ip and href:
            href += f"  (by IP: {_service_href(key, config, config.travel_ip)})"

        return f"  {label}: {href}"

    lines = []
    # homepage/dashy are emitted explicitly below as well as sitting in a
    # group - list each exactly once.
    seen: set[str] = set()

    if "homepage" in enabled:
        lines.append(line("Homepage (dashboard)", "homepage"))
        seen.add("homepage")

    if "dashy" in enabled:
        lines.append(line("Dashy (dashboard)", "dashy"))
        seen.add("dashy")

    for keys in _HOMEPAGE_GROUPS.values():
        for key in keys:
            if key in enabled and key not in seen:
                lines.append(line(display_names[key], key))
                seen.add(key)

    return "\n".join(lines)
```

9. `write_stack`: replace `    host_ip = detect_host_ip()` with:

```python
    host_ip = link_host(config, detect_host_ip())
```

`templates/docker-compose.yml.j2`: in the `jellyfin:` service, replace

```
      - TZ=${TZ}
    volumes:
      - ./config/jellyfin:/config
```

with

```
      - TZ=${TZ}
{% if jellyfin_published_url %}
      # What Jellyfin tells apps its address is - the .local name, never a
      # build-time IP that the next network won't have.
      - JELLYFIN_PublishedServerUrl={{ jellyfin_published_url }}
{% endif %}
    volumes:
      - ./config/jellyfin:/config
```

`installer/cli.py`: add `link_host,` to the `from installer.generate import (...)` list. Then route every link through it:

```bash
sed -i 's/(config, detect_host_ip())/(config, link_host(config, detect_host_ip()))/g' installer/cli.py
grep -c "link_host(config, detect_host_ip())" installer/cli.py   # expect 7
```

- [ ] **Step 4: Run to verify they pass**

Run: `python -m pytest tests/test_generate.py tests/test_cli.py -q && python -m pytest tests/ -q && ruff check .`
Expected: PASS. The existing Homepage/summary/compose tests stay green. Home tiers render byte-identical except for the summary helper, whose output is unchanged.

- [ ] **Step 5: Commit**

```bash
git switch -c travel/2-generate
git add installer/services.py installer/generate.py installer/cli.py templates/docker-compose.yml.j2 \
        tests/test_generate.py tests/test_cli.py
git commit -m "feat(travel): offline-safe compose with pinned images, .local links and by-IP tiles"
```

PR: `git push -u origin travel/2-generate && gh pr create --title "Travel tier 2/9: generate the travel stack" --body "Pinned images + pull_policy: missing, no Watchtower/home-only services, .local links everywhere, optional by-IP group, Jellyfin published URL."`

---

### Task 3: Host Avahi install/enable, `vulcan travel setup`, `vulcan doctor`

**Files:**
- Modify: `installer/travel.py` (~110 lines), `installer/cli.py` (~75 lines)
- Create: `tests/test_travel.py`
- Test: `tests/test_travel.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: `installer.deps._family_for`, `installer.deps._INSTALL_CMD`, `installer.shell.run_privileged`, `installer.detect.detect_os`, saved state `hostname`/`kiosk` (Task 1).
- Produces (all in `installer.travel`):
  - `apply_steps(steps: list[list[str]], run=run_privileged) -> dict` → `{"ok": bool, "error": str | None}`
  - `write_root_file(path: str, content: str, run=run_privileged) -> dict` → `{"success", "error"}`
  - `avahi_steps(os_id: str | None, os_is_atomic: bool, hostname: str) -> list[list[str]] | None`
  - `host_setup(services: set[str], hostname: str, kiosk: bool, os_info: dict, run=run_privileged, write=write_root_file, exists=os.path.exists, user_exists: bool | None = None, groups: list[str] | None = None) -> list[dict]`. Each row is `{"step": str, "ok": bool, "error": str | None, "skipped": bool}`.
  - `doctor_checks(hostname: str, run_capture=subprocess.run, resolve=socket.getaddrinfo) -> list[dict]`. Each row is `{"name", "ok", "fix"}`.
- Produces (cli): `_travel_host_setup(config: GenerationConfig, panel=None) -> bool`, `travel_app` (`vulcan travel setup`), `vulcan doctor`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_travel.py`:

```python
import socket
import subprocess

from installer.travel import apply_steps, avahi_steps, doctor_checks, host_setup

DEBIAN = {"os_id": "debian", "os_is_atomic": False, "architecture": "x86_64"}


def fake_runner(fail_on=None):

    calls = []

    def run(argv):
        calls.append(argv)
        ok = argv != fail_on
        return {"success": ok, "error": None if ok else "exit code 1"}

    return calls, run


def fake_write(written):

    def write(path, content, run):
        written[path] = content
        return {"success": True, "error": None}

    return write


def test_avahi_steps_per_family():

    assert avahi_steps("ubuntu", False, "trip") == [
        ["apt-get", "install", "-y", "avahi-daemon", "libnss-mdns"],
        ["hostnamectl", "set-hostname", "trip"],
        ["systemctl", "enable", "--now", "avahi-daemon"],
    ]
    assert avahi_steps("fedora", False, "trip")[0] == ["dnf", "install", "-y", "avahi", "nss-mdns"]
    assert avahi_steps("fedora", True, "trip") == [
        ["hostnamectl", "set-hostname", "trip"],
        ["systemctl", "enable", "--now", "avahi-daemon"],
    ]
    assert avahi_steps("gentoo", False, "trip") is None


def test_apply_steps_stops_at_the_first_failure():

    calls, run = fake_runner(fail_on=["b"])
    result = apply_steps([["a"], ["b"], ["c"]], run)

    assert result == {"ok": False, "error": "b: exit code 1"}
    assert calls == [["a"], ["b"]]


def test_host_setup_runs_avahi():

    calls, run = fake_runner()
    results = host_setup({"jellyfin"}, "trip", False, DEBIAN, run=run, write=fake_write({}), exists=lambda p: False)

    assert results[0] == {"step": "avahi (trip.local)", "ok": True, "error": None, "skipped": False}
    assert ["hostnamectl", "set-hostname", "trip"] in calls


def test_host_setup_reports_an_unsupported_distro():

    calls, run = fake_runner()
    results = host_setup({"jellyfin"}, "trip", False, {"os_id": "gentoo", "os_is_atomic": False},
                         run=run, write=fake_write({}), exists=lambda p: False)

    assert results[0]["ok"] is False and "avahi" in results[0]["error"]
    assert calls == []


def test_doctor_checks_pass():

    def active(argv, **kw):
        return subprocess.CompletedProcess(argv, 0, "active\n", "")

    checks = doctor_checks("trip", run_capture=active, resolve=lambda host, port: [("ok",)])

    assert [c["ok"] for c in checks] == [True, True]


def test_doctor_checks_fail_with_plain_fixes():

    def inactive(argv, **kw):
        return subprocess.CompletedProcess(argv, 3, "inactive\n", "")

    def no_resolve(host, port):
        raise socket.gaierror("Name or service not known")

    checks = doctor_checks("trip", run_capture=inactive, resolve=no_resolve)

    assert [c["ok"] for c in checks] == [False, False]
    assert "systemctl enable --now avahi-daemon" in checks[0]["fix"]
    assert "trip.local" in checks[1]["name"]
    assert "libnss-mdns" in checks[1]["fix"]
```

Append to `tests/test_cli.py`:

```python
import installer.cli as cli_module

REAL_TRAVEL_HOST_SETUP = cli_module._travel_host_setup
TRAVEL_STATE = {**PREVIOUS_STATE, "tier": "travel", "enabled_optional": [], "hostname": "trip", "kiosk": False}


@pytest.fixture(autouse=True)
def _no_real_travel_host_setup():
    """Travel builds run host steps through sudo (Avahi, timers, kiosk) -
    never from the test suite."""

    with patch("installer.cli._travel_host_setup", return_value=True) as mock:
        yield mock


def test_build_travel_runs_host_setup(tmp_path, _no_real_travel_host_setup):

    result, _ = _build_travel(tmp_path)

    assert result.exit_code == 0, result.output
    assert _no_real_travel_host_setup.call_args[0][0].hostname == "vulcan"


def test_build_home_tier_skips_host_setup(tmp_path, _no_real_travel_host_setup):

    media_path = str(tmp_path / "media")

    with patch("installer.cli.detect_system", return_value=make_system_info()), patch(
        "installer.cli.detect_disk", return_value={"disk_free_gb": 900.0, "disk_path_checked": media_path}
    ), patch("installer.cli.write_stack", return_value=READY_WRITE_RESULT):

        result = runner.invoke(app, ["build", "--tier", "light", "--media-path", media_path,
                                     "--non-interactive", "--yes"])

    assert result.exit_code == 0, result.output
    _no_real_travel_host_setup.assert_not_called()


def test_travel_host_setup_reports_each_step():

    config = _config_from_previous_state(TRAVEL_STATE)
    rows = [{"step": "avahi (trip.local)", "ok": True, "error": None, "skipped": False},
            {"step": "kiosk (removed)", "ok": True, "error": None, "skipped": True}]

    with patch("installer.cli.host_setup", return_value=rows) as mock_host_setup, patch(
        "installer.cli.detect_os", return_value={"os_id": "debian"}
    ):
        assert REAL_TRAVEL_HOST_SETUP(config) is True

    assert mock_host_setup.call_args[0][1] == "trip"


def test_travel_setup_command_needs_a_travel_stack():

    with patch("installer.cli.load_previous_state", return_value=PREVIOUS_STATE):
        result = runner.invoke(app, ["travel", "setup"])

    assert result.exit_code == 1
    assert "No Travel stack" in result.output


def test_travel_setup_command_exits_1_when_a_step_fails(_no_real_travel_host_setup):

    _no_real_travel_host_setup.return_value = False

    with patch("installer.cli.load_previous_state", return_value=TRAVEL_STATE):
        result = runner.invoke(app, ["travel", "setup"])

    assert result.exit_code == 1


def test_doctor_without_a_stack():

    result = runner.invoke(app, ["doctor"])

    assert result.exit_code == 1
    assert "No Vulcan stack" in result.output


def test_doctor_on_a_home_tier_has_nothing_to_check():

    with patch("installer.cli.load_previous_state", return_value=PREVIOUS_STATE):
        result = runner.invoke(app, ["doctor"])

    assert result.exit_code == 0
    assert "Nothing to check" in result.output


def test_doctor_prints_fixes_and_exits_1_on_failure():

    checks = [{"name": "Avahi (avahi-daemon) running", "ok": True, "fix": ""},
              {"name": "trip.local resolves", "ok": False, "fix": "sudo apt install libnss-mdns"}]

    with patch("installer.cli.load_previous_state", return_value=TRAVEL_STATE), patch(
        "installer.cli.doctor_checks", return_value=checks
    ) as mock_checks:
        result = runner.invoke(app, ["doctor"])

    assert result.exit_code == 1
    assert "libnss-mdns" in result.output
    mock_checks.assert_called_once_with("trip")
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_travel.py tests/test_cli.py -q -k "avahi or apply_steps or host_setup or doctor or travel_setup"`
Expected: FAIL. `ImportError: cannot import name 'apply_steps' from 'installer.travel'`, and `AttributeError: module 'installer.cli' has no attribute '_travel_host_setup'`.

- [ ] **Step 3: Implement**

Replace `installer/travel.py` with:

```python
"""
Travel tier: the pieces that live on the box itself, outside the Docker
stack - Avahi so the box answers as <hostname>.local on any network, plus
the checks `vulcan doctor` runs. Plan builders are pure; apply_steps() is
the only thing that executes, always through run_privileged.
"""

import ipaddress
import os
import re
import socket
import subprocess
import tempfile

from installer.deps import _INSTALL_CMD, _family_for
from installer.shell import run_privileged

_HOSTNAME = re.compile(r"[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?")

# libnss-mdns/nss-mdns let this box itself resolve *.local (what doctor checks).
AVAHI_PACKAGES = {
    "debian": ["avahi-daemon", "libnss-mdns"],
    "fedora": ["avahi", "nss-mdns"],
    "arch": ["avahi", "nss-mdns"],
}


def valid_hostname(name: str) -> bool:
    """One DNS label (RFC 1123): what Avahi can publish as <name>.local."""

    return bool(_HOSTNAME.fullmatch(name))


def valid_ip(value: str) -> bool:

    try:
        ipaddress.ip_address(value)
    except ValueError:
        return False

    return True


def apply_steps(steps: list[list[str]], run=run_privileged) -> dict:
    """Run each argv in order; stop at the first failure and name it."""

    for argv in steps:

        result = run(argv)

        if not result["success"]:
            return {"ok": False, "error": f"{' '.join(argv)}: {result['error']}"}

    return {"ok": True, "error": None}


def write_root_file(path: str, content: str, run=run_privileged) -> dict:
    """Write a root-owned 0644 file (systemd units) via `install` through sudo."""

    with tempfile.NamedTemporaryFile("w", delete=False, suffix=".vulcan") as handle:
        handle.write(content)

    try:
        return run(["install", "-m", "0644", handle.name, path])
    finally:
        os.unlink(handle.name)


def avahi_steps(os_id: str | None, os_is_atomic: bool, hostname: str) -> list[list[str]] | None:
    """Install + enable Avahi and set the system hostname it publishes.
    None when Vulcan doesn't know this distro's package names."""

    tail = [["hostnamectl", "set-hostname", hostname], ["systemctl", "enable", "--now", "avahi-daemon"]]

    # Atomic desktops (Bazzite, Silverblue) ship Avahi in the base image.
    if os_is_atomic:
        return tail

    family = _family_for(os_id)

    if family is None:
        return None

    return [[*_INSTALL_CMD[family], *AVAHI_PACKAGES[family]], *tail]


def _row(step: str, result: dict) -> dict:

    return {"step": step, "ok": result["ok"], "error": result.get("error"), "skipped": result.get("skipped", False)}


def host_setup(
    services: set[str],
    hostname: str,
    kiosk: bool,
    os_info: dict,
    run=run_privileged,
    write=write_root_file,
    exists=os.path.exists,
    user_exists: bool | None = None,
    groups: list[str] | None = None,
) -> list[dict]:
    """Every host-side travel step, in order. Re-run safe: each step is
    idempotent. services/kiosk/write/exists/user_exists/groups are used by
    the timer and kiosk steps."""

    steps = avahi_steps(os_info.get("os_id"), os_info.get("os_is_atomic", False), hostname)

    if steps is None:
        avahi = {"ok": False, "error": "install avahi (avahi-daemon) by hand, then: sudo systemctl enable --now avahi-daemon"}
    else:
        avahi = apply_steps(steps, run)

    return [_row(f"avahi ({hostname}.local)", avahi)]


def doctor_checks(hostname: str, run_capture=subprocess.run, resolve=socket.getaddrinfo) -> list[dict]:

    try:
        active = run_capture(["systemctl", "is-active", "avahi-daemon"], capture_output=True, text=True).stdout.strip() == "active"
    except OSError:
        active = False

    try:
        resolve(f"{hostname}.local", None)
        resolves = True
    except OSError:
        resolves = False

    return [
        {
            "name": "Avahi (avahi-daemon) running",
            "ok": active,
            "fix": "sudo systemctl enable --now avahi-daemon   (or re-run: vulcan travel setup)",
        },
        {
            "name": f"{hostname}.local resolves",
            "ok": resolves,
            "fix": "install mDNS lookups - Debian/Ubuntu: sudo apt install libnss-mdns, Fedora: "
                   "sudo dnf install nss-mdns - and check the name with: hostnamectl",
        },
    ]
```

`installer/cli.py`:
1. Add `detect_os,` to the `from installer.detect import (...)` list. Replace the travel import with:

```python
from installer.travel import doctor_checks, host_setup, valid_hostname, valid_ip
```

2. After the `media_app` block (before `console = Console()`), add:

```python
travel_app = typer.Typer(
    help="Travel tier: host setup (Avahi, timers, Kodi kiosk) and sync from your home Vulcan."
)
app.add_typer(travel_app, name="travel")
```

3. In `run_install`, replace

```python
        build_result = _build(
            config, non_interactive, yes,
            on_phase=panel.advance, panel=panel
        )
```

with

```python
        build_result = _build(
            config, non_interactive, yes,
            on_phase=panel.advance, panel=panel
        )

        # Travel host pieces (Avahi, timers, kiosk) - after the files exist,
        # before start. Failures warn; `vulcan travel setup` re-applies.
        if config.tier.name == "travel" and not dry_run:
            _travel_host_setup(config, panel)
```

4. Add after `_report_stack_generated` (before `if __name__ == "__main__":`):

```python
def _travel_host_setup(config: GenerationConfig, panel: RunPanel | _NoOpPanel | None = None) -> bool:
    """Host pieces of a travel box, outside Docker and through sudo. A failure
    warns and never undoes the build - `vulcan travel setup` re-applies,
    `vulcan doctor` checks."""

    panel = panel if panel is not None else _NoOpPanel(console)
    results = host_setup(enabled_service_keys(config), config.hostname, config.kiosk, detect_os())

    for step in results:

        if step["skipped"]:
            continue

        if step["ok"]:
            panel.note(f"[green]✓[/green] {step['step']}")
        else:
            panel.note(f"[yellow]! {step['step']}: {step['error']}[/yellow]")

    ok = all(step["ok"] for step in results)

    if not ok:
        panel.note("Fix the above, then re-run: vulcan travel setup   (check with: vulcan doctor)")

    return ok


@travel_app.command(name="setup")
def travel_setup():
    """Apply (or re-apply) this travel box's host pieces from the saved stack: Avahi, timers, kiosk."""

    state = load_previous_state(STACK_DIR)

    if not state or state["tier"] != "travel":
        console.print("[red]No Travel stack here.[/red] Build one first: vulcan build --tier travel")
        raise typer.Exit(code=1)

    if not _travel_host_setup(_config_from_previous_state(state)):
        raise typer.Exit(code=1)


@app.command()
def doctor():
    """Check the host-side pieces this stack relies on, with a plain fix for each failure."""

    state = load_previous_state(STACK_DIR)

    if state is None:
        console.print("[red]No Vulcan stack found here.[/red] Run: vulcan build")
        raise typer.Exit(code=1)

    if state["tier"] != "travel":
        console.print(f"Nothing to check for the {state['tier']} tier yet.")
        return

    checks = doctor_checks(state.get("hostname") or "vulcan")

    for check in checks:
        if check["ok"]:
            console.print(f"[green]✓[/green] {check['name']}")
        else:
            console.print(f"[red]✗[/red] {check['name']}\n    Fix: {check['fix']}")

    if not all(check["ok"] for check in checks):
        raise typer.Exit(code=1)
```

- [ ] **Step 4: Run to verify they pass**

Run: `python -m pytest tests/test_travel.py tests/test_cli.py -q && python -m pytest tests/ -q && ruff check .`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git switch -c travel/3-avahi-doctor
git add installer/travel.py installer/cli.py tests/test_travel.py tests/test_cli.py
git commit -m "feat(travel): Avahi host setup, vulcan travel setup and vulcan doctor"
```

PR: `git push -u origin travel/3-avahi-doctor && gh pr create --title "Travel tier 3/9: find the box by name" --body "Installs/enables Avahi and sets the hostname so the box answers as <name>.local; vulcan travel setup re-applies host steps; vulcan doctor checks Avahi + .local resolution with plain fixes."`

---

### Task 4: Offline-tolerant self-download group, media-register timer, offline media probe

**Files:**
- Modify: `templates/docker-compose.yml.j2` (~10 lines), `installer/travel.py` (~55 lines), `installer/cli.py` (~15 lines), `installer/media/probe.py` (~4 lines)
- Test: `tests/test_generate.py`, `tests/test_travel.py`, `tests/test_media_cli.py`, `tests/test_media_probe.py`

**Interfaces:**
- Consumes: `render_compose(... travel=...)` (Task 2), `host_setup`, `apply_steps`, `write_root_file` (Task 3), `TRAVEL_IMAGES` (Task 2).
- Produces (in `installer.travel`): `SYSTEMD_DIR = "/etc/systemd/system"`, `MEDIA_REGISTER_UNIT = "vulcan-media-register"`, `invoking_user() -> str`, `timer_units(name: str, description: str, command: str, on_calendar: str, user: str, workdir: str) -> dict[str, str]`, `install_timer(name: str, description: str, command: str, on_calendar: str = "hourly", run=run_privileged, write=write_root_file, user: str | None = None, workdir: str | None = None) -> dict`, `remove_timer(name: str, run=run_privileged, exists=os.path.exists) -> dict`. `installer.media.probe.Prober(root, cache_path=None, run=subprocess.run, host_ffprobe=None, image=JELLYFIN_IMAGE)`. `vulcan media register` exits 0 with "Nothing queued" when the pending list is empty.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_generate.py`:

```python
def test_travel_gluetun_tolerates_no_internet():

    services = yaml.safe_load(render_compose(travel_config(enabled_optional=set(TRAVEL_SELF_DOWNLOAD))))["services"]

    assert "HEALTH_RESTART_VPN=off" in services["gluetun"]["environment"]
    assert services["qbittorrent"]["depends_on"]["gluetun"]["condition"] == "service_started"


def test_home_tier_gluetun_keeps_its_health_gate():

    services = yaml.safe_load(render_compose(make_config("light", enabled_optional={"gluetun"})))["services"]

    assert "HEALTH_RESTART_VPN=off" not in services["gluetun"]["environment"]
    assert services["qbittorrent"]["depends_on"]["gluetun"]["condition"] == "service_healthy"
```

Append to `tests/test_travel.py`:

```python
from installer.travel import MEDIA_REGISTER_UNIT, remove_timer, timer_units


def test_timer_units_content():

    units = timer_units("vulcan-media-register", "Vulcan: register imported media",
                        "/venv/bin/python -m installer media register", "hourly", "ron", "/home/ron/vulcan")
    service = units["/etc/systemd/system/vulcan-media-register.service"]
    timer = units["/etc/systemd/system/vulcan-media-register.timer"]

    assert "Type=oneshot" in service and "User=ron" in service
    assert "WorkingDirectory=/home/ron/vulcan" in service
    assert "ExecStart=/venv/bin/python -m installer media register" in service
    assert "OnCalendar=hourly" in timer and "Persistent=true" in timer and "WantedBy=timers.target" in timer


def test_host_setup_installs_the_register_timer_when_arrs_are_in_the_stack():

    calls, run = fake_runner()
    written = {}
    host_setup({"jellyfin", "sonarr", "radarr"}, "trip", False, DEBIAN,
               run=run, write=fake_write(written), exists=lambda p: False)

    assert f"/etc/systemd/system/{MEDIA_REGISTER_UNIT}.timer" in written
    assert ["systemctl", "enable", "--now", "vulcan-media-register.timer"] in calls


def test_host_setup_removes_the_register_timer_without_arrs():

    calls, run = fake_runner()
    results = host_setup({"jellyfin"}, "trip", False, DEBIAN, run=run, write=fake_write({}), exists=lambda p: True)

    assert ["systemctl", "disable", "--now", "vulcan-media-register.timer"] in calls
    assert any(r["step"] == "media-register timer (removed)" and r["ok"] for r in results)


def test_remove_timer_is_a_skipped_no_op_when_not_installed():

    calls, run = fake_runner()

    assert remove_timer("vulcan-media-register", run, exists=lambda p: False) == {"ok": True, "error": None, "skipped": True}
    assert calls == []
```

In `tests/test_media_cli.py`, add `from pathlib import Path` and `from installer.services import TRAVEL_IMAGES` to the imports. Replace `test_register_without_reachable_arrs_exits_1` with:

```python
def test_register_without_reachable_arrs_exits_1(tmp_path):
    pending = Path("stack/media-plans/pending-registration.json")
    pending.parent.mkdir(parents=True)
    pending.write_text(json.dumps([{"destination": "/lib/media/movies/A (2020)/a.mkv", "reason": "stack offline"}]))
    result = runner.invoke(app, ["media", "register"])
    assert result.exit_code == 1 and "Sonarr/Radarr" in result.output


def test_register_is_a_quiet_no_op_when_nothing_is_queued(tmp_path):
    result = runner.invoke(app, ["media", "register"])
    assert result.exit_code == 0 and "Nothing queued" in result.output


def test_scan_on_travel_uses_the_pinned_jellyfin_image(tmp_path):
    seen = {}

    class RecordingProber(NullProber):
        def __init__(self, *a, **k): seen.update(k)

    state = {"tier": "travel", "media_path": str(tmp_path / "lib")}
    with patch("installer.cli.load_previous_state", return_value=state), \
         patch("installer.cli.MediaProber", RecordingProber), \
         patch("installer.cli.media_scan_engine", return_value=fake_plan(tmp_path)):
        result = runner.invoke(app, ["media", "scan", str(tmp_path), "--offline", "--plan", str(tmp_path / "p.json")])
    assert result.exit_code == 0, result.output
    assert seen["image"] == TRAVEL_IMAGES["jellyfin"]
```

Append to `tests/test_media_probe.py`:

```python
def test_prober_starts_its_container_from_the_given_image(tmp_path):
    import subprocess as sp
    from installer.media.probe import Prober

    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        return sp.CompletedProcess(cmd, 0, "", "")

    with Prober(tmp_path, run=fake_run, host_ffprobe="", image="lscr.io/linuxserver/jellyfin:pinned"):
        pass

    assert "lscr.io/linuxserver/jellyfin:pinned" in calls[0]
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_generate.py tests/test_travel.py tests/test_media_cli.py tests/test_media_probe.py -q -k "gluetun or timer or register or pinned or given_image"`
Expected: FAIL. `ImportError: cannot import name 'MEDIA_REGISTER_UNIT'`, plus assertion failures: no `HEALTH_RESTART_VPN`, `Nothing queued` not printed, and `TypeError: ... unexpected keyword argument 'image'`.

- [ ] **Step 3: Implement**

`templates/docker-compose.yml.j2`, gluetun: replace

```
      - WIREGUARD_ADDRESSES=${WIREGUARD_ADDRESSES}
      - TZ=${TZ}
      # --- Port forwarding
```

with

```
      - WIREGUARD_ADDRESSES=${WIREGUARD_ADDRESSES}
      - TZ=${TZ}
{% if travel %}
      # Travel boxes are often offline: don't restart the tunnel every few
      # seconds when the internet is simply gone - WireGuard picks up again
      # on its own once a network is back. Stops the log flood.
      - HEALTH_RESTART_VPN=off
{% endif %}
      # --- Port forwarding
```

qBittorrent: replace

```
    depends_on:
      gluetun:
        condition: service_healthy
{% else %}
```

with

```
    # Travel: gluetun reports unhealthy with no internet, and a
    # service_healthy gate would then make `up -d` fail offline - start
    # once gluetun has started and let restart: unless-stopped absorb the
    # namespace race.
    depends_on:
      gluetun:
        condition: {{ 'service_started' if travel else 'service_healthy' }}
{% else %}
```

`installer/media/probe.py`: change the `Prober.__init__` signature to `def __init__(self, root, cache_path=None, run=subprocess.run, host_ffprobe=None, image=JELLYFIN_IMAGE):`, add `self.image = image` as its first line, and in `__enter__` replace `JELLYFIN_IMAGE, "infinity"` with `self.image, "infinity"`.

`installer/travel.py`: add `import getpass` and `import sys` to the imports. Add the constants after `AVAHI_PACKAGES`:

```python
SYSTEMD_DIR = "/etc/systemd/system"
MEDIA_REGISTER_UNIT = "vulcan-media-register"
```

Add before `_row`:

```python
def invoking_user() -> str:
    """The real user behind sudo - timers must run as them, not root."""

    return os.environ.get("SUDO_USER") or getpass.getuser()


def timer_units(name: str, description: str, command: str, on_calendar: str, user: str, workdir: str) -> dict[str, str]:

    service = (
        f"[Unit]\nDescription={description}\nAfter=network-online.target docker.service\n"
        "Wants=network-online.target\n\n"
        f"[Service]\nType=oneshot\nUser={user}\nWorkingDirectory={workdir}\nExecStart={command}\n"
    )
    timer = (
        f"[Unit]\nDescription={description} (timer)\n\n"
        f"[Timer]\nOnCalendar={on_calendar}\nPersistent=true\nRandomizedDelaySec=5m\n\n"
        "[Install]\nWantedBy=timers.target\n"
    )

    return {f"{SYSTEMD_DIR}/{name}.service": service, f"{SYSTEMD_DIR}/{name}.timer": timer}


def install_timer(
    name: str,
    description: str,
    command: str,
    on_calendar: str = "hourly",
    run=run_privileged,
    write=write_root_file,
    user: str | None = None,
    workdir: str | None = None,
) -> dict:

    units = timer_units(name, description, command, on_calendar, user or invoking_user(), workdir or os.getcwd())

    for path, content in units.items():

        written = write(path, content, run)

        if not written["success"]:
            return {"ok": False, "error": f"couldn't write {path}: {written['error']}"}

    return apply_steps([["systemctl", "daemon-reload"], ["systemctl", "enable", "--now", f"{name}.timer"]], run)


def remove_timer(name: str, run=run_privileged, exists=os.path.exists) -> dict:

    timer = f"{SYSTEMD_DIR}/{name}.timer"

    if not exists(timer):
        return {"ok": True, "error": None, "skipped": True}

    return apply_steps([
        ["systemctl", "disable", "--now", f"{name}.timer"],
        ["rm", "-f", timer, f"{SYSTEMD_DIR}/{name}.service"],
        ["systemctl", "daemon-reload"],
    ], run)
```

Replace `host_setup`'s body (keep its signature) with:

```python
    """Every host-side travel step, in order. Re-run safe: each step is
    idempotent. kiosk/user_exists/groups are used by the kiosk step."""

    steps = avahi_steps(os_info.get("os_id"), os_info.get("os_is_atomic", False), hostname)

    if steps is None:
        avahi = {"ok": False, "error": "install avahi (avahi-daemon) by hand, then: sudo systemctl enable --now avahi-daemon"}
    else:
        avahi = apply_steps(steps, run)

    results = [_row(f"avahi ({hostname}.local)", avahi)]

    # Hourly catch-up for imports queued while Sonarr/Radarr were offline -
    # only meaningful when the self-download group is in the stack.
    if services & {"sonarr", "radarr"}:
        results.append(_row("media-register timer", install_timer(
            MEDIA_REGISTER_UNIT, "Vulcan: register imported media with Sonarr/Radarr",
            f"{sys.executable} -m installer media register", run=run, write=write,
        )))
    else:
        results.append(_row("media-register timer (removed)", remove_timer(MEDIA_REGISTER_UNIT, run, exists)))

    return results
```

`installer/cli.py`:
1. Change the media imports:

```python
from installer.media.arr import PENDING_FILE, add_pending, connect_arrs, register_pending
from installer.media.probe import JELLYFIN_IMAGE
from installer.services import TRAVEL_IMAGES
```

2. In `media_scan`, replace `        with MediaProber(root, cache_path=PLANS_DIR / ".probe-cache.json") as prober:` with:

```python
        state = load_previous_state(STACK_DIR)
        # A travel box may be offline: probe with the Jellyfin image it already has.
        image = TRAVEL_IMAGES["jellyfin"] if state and state["tier"] == "travel" else JELLYFIN_IMAGE
        with MediaProber(root, cache_path=PLANS_DIR / ".probe-cache.json", image=image) as prober:
```

3. In `media_register`, insert at the top of the body (after the docstring):

```python
    # The hourly travel timer runs this - nothing queued is the normal case, not an error.
    if not (json.loads(PENDING_FILE.read_text() or "[]") if PENDING_FILE.exists() else []):
        console.print("Nothing queued - nothing to register.")
        return
```

- [ ] **Step 4: Run to verify they pass**

Run: `python -m pytest tests/ -q && ruff check .`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git switch -c travel/4-offline
git add templates/docker-compose.yml.j2 installer/travel.py installer/cli.py installer/media/probe.py \
        tests/test_generate.py tests/test_travel.py tests/test_media_cli.py tests/test_media_probe.py
git commit -m "feat(travel): offline-tolerant downloads and an hourly media-register timer"
```

PR: `git push -u origin travel/4-offline && gh pr create --title "Travel tier 4/9: offline behaviour" --body "gluetun stops restart-looping with no internet and qBittorrent no longer blocks up -d offline (travel only); vulcan-media-register.timer when Sonarr/Radarr are in the stack; media register is a quiet no-op with nothing queued; scans use the pinned Jellyfin image."`

---

### Task 5: Tailscale node name, `vulcan travel sync` (rsync over the tailnet, size cap, free-space floor, resume), optional sync timer

**Files:**
- Modify: `templates/docker-compose.yml.j2` (~4 lines), `templates/env.j2` (~12 lines), `installer/generate.py` (~25 lines), `installer/travel.py` (~95 lines), `installer/cli.py` (~75 lines)
- Test: `tests/test_generate.py`, `tests/test_travel.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: `install_timer`, `remove_timer`, `SYSTEMD_DIR` (Task 4). `_preserved_vpn_value` (existing).
- Produces (in `installer.travel`): `SYNC_UNIT = "vulcan-travel-sync"`, `SYNC_INBOX = Path("downloads") / "from-home"`, `SYNC_LEDGER = Path("stack") / "travel-sync-ledger.txt"`, `SSH_COMMAND = "ssh -o BatchMode=yes -o ConnectTimeout=10"`, `home_reachable(home: str, run=subprocess.run) -> bool`, `list_command(home: str, remote_path: str, inbox: Path) -> list[str]`, `transfer_command(home: str, remote_path: str, inbox: Path, files_from: str) -> list[str]`, `parse_listing(output: str) -> list[tuple[int, str]]`, `select_files(files: list[tuple[int, str]], max_bytes: int, free_bytes: int, min_free_bytes: int) -> tuple[list[tuple[int, str]], str | None]`, `sync_from_home(home: str, remote_path: str, media_path, max_bytes: int, min_free_bytes: int, ledger_path=SYNC_LEDGER, run=subprocess.run, free: int | None = None) -> dict` → `{"reachable", "files", "bytes", "limited_by", "error", "inbox"}`.
- Produces (cli): `vulcan travel sync [--from HOST] [--remote-path P] [--max-gb N] [--min-free-gb N] [--if-reachable] [--install-timer | --remove-timer]`. `.env` keys `TRAVEL_SYNC_FROM`, `TRAVEL_SYNC_PATH`, `TRAVEL_SYNC_MAX_GB`, `TRAVEL_SYNC_MIN_FREE_GB` (written when tier is travel and Tailscale is on, and kept across rebuilds).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_generate.py`:

```python
def test_travel_tailscale_gets_its_own_node_name():

    services = yaml.safe_load(render_compose(travel_config(enabled_optional={"tailscale"}, hostname="trip")))["services"]

    assert "TS_HOSTNAME=trip-travel" in services["tailscale"]["environment"]


def test_travel_env_has_sync_settings_only_with_home_sync():

    assert "TRAVEL_SYNC_FROM=" in render_env(travel_config(enabled_optional={"tailscale"}))
    assert "TRAVEL_SYNC_MAX_GB=200" in render_env(travel_config(enabled_optional={"tailscale"}))
    assert "TRAVEL_SYNC_FROM" not in render_env(travel_config())
    assert "TRAVEL_SYNC_FROM" not in render_env(make_config("heavy", enabled_optional={"tailscale"}))
```

Append to `tests/test_travel.py`:

```python
from pathlib import Path

from installer.travel import list_command, parse_listing, select_files, sync_from_home, transfer_command


def test_parse_listing_keeps_files_only():

    assert parse_listing("4096 movies/\n30 movies/New (2026)/new.mkv\n\nnoise\n") == [(30, "movies/New (2026)/new.mkv")]


def test_select_files_respects_cap_and_floor():

    files = [(30, "a"), (50, "b"), (5, "c")]

    assert select_files(files, 40, 10**6, 0) == ([(30, "a"), (5, "c")], "size cap")
    assert select_files(files, 10**6, 60, 20) == ([(30, "a"), (5, "c")], "free-space floor")
    assert select_files(files, 10**6, 10, 20) == ([], "free-space floor")
    assert select_files(files, 10**6, 10**6, 0) == (files, None)


def test_sync_commands_go_over_ssh_and_resume():

    inbox = Path("/m/downloads/from-home")
    listing = list_command("you@home", "/mnt/media/media/", inbox)
    transfer = transfer_command("you@home", "/mnt/media/media", inbox, "/tmp/list.txt")

    assert listing[:2] == ["rsync", "-a"] and "--dry-run" in listing and "--out-format=%l %n" in listing
    assert listing[-2:] == ["you@home:/mnt/media/media/", "/m/downloads/from-home/"]
    assert "--partial-dir=.vulcan-partial" in transfer and "--files-from=/tmp/list.txt" in transfer
    assert transfer[transfer.index("-e") + 1] == "ssh -o BatchMode=yes -o ConnectTimeout=10"


def test_sync_from_home_pulls_only_new_files_within_the_cap(tmp_path):

    media = tmp_path / "media"
    (media / "media" / "movies" / "Old (2020)").mkdir(parents=True)
    (media / "media" / "movies" / "Old (2020)" / "old.mkv").write_bytes(b"x" * 10)
    ledger = tmp_path / "ledger.txt"
    ledger.write_text("tv/Show/S01E01.mkv\n")
    listing = ("4096 movies/\n10 movies/Old (2020)/old.mkv\n10 tv/Show/S01E01.mkv\n"
               "30 movies/New (2026)/new.mkv\n50 movies/Big (2026)/big.mkv\n")

    def run(argv, **kw):
        if argv[0] == "ssh" or "--dry-run" in argv:
            return subprocess.CompletedProcess(argv, 0, listing, "")
        files_from = next(a for a in argv if a.startswith("--files-from=")).split("=", 1)[1]
        for name in Path(files_from).read_text().splitlines():
            target = media / "downloads" / "from-home" / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"x" * 30)
        return subprocess.CompletedProcess(argv, 0, "", "")

    result = sync_from_home("you@home", "/mnt/media/media", media, max_bytes=40, min_free_bytes=0,
                            ledger_path=ledger, run=run, free=10**12)

    assert result["files"] == ["movies/New (2026)/new.mkv"]
    assert result["bytes"] == 30 and result["limited_by"] == "size cap" and result["error"] is None
    assert "movies/New (2026)/new.mkv" in ledger.read_text().splitlines()


def test_sync_from_home_does_nothing_when_home_is_unreachable(tmp_path):

    calls = []

    def run(argv, **kw):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 255, "", "no route")

    result = sync_from_home("you@home", "/mnt/media/media", tmp_path, 10**9, 0, ledger_path=tmp_path / "l", run=run)

    assert result["reachable"] is False and result["files"] == []
    assert [argv[0] for argv in calls] == ["ssh"]
```

Append to `tests/test_cli.py`:

```python
SYNC_STATE = {**TRAVEL_STATE, "enabled_optional": ["tailscale"]}
NOT_REACHABLE = {"reachable": False, "files": [], "bytes": 0, "limited_by": None, "error": None,
                 "inbox": "/m/downloads/from-home"}


def test_travel_sync_needs_a_home_host():

    with patch("installer.cli.load_previous_state", return_value=SYNC_STATE):
        result = runner.invoke(app, ["travel", "sync"])

    assert result.exit_code == 1
    assert "TRAVEL_SYNC_FROM" in result.output


def test_travel_sync_if_reachable_exits_0_when_home_is_away():

    with patch("installer.cli.load_previous_state", return_value=SYNC_STATE), patch(
        "installer.cli.shutil.which", return_value="/usr/bin/rsync"
    ), patch("installer.cli.sync_from_home", return_value=NOT_REACHABLE):
        result = runner.invoke(app, ["travel", "sync", "--from", "you@home", "--if-reachable"])

    assert result.exit_code == 0
    assert "isn't reachable" in result.output


def test_travel_sync_reports_files_and_the_import_step():

    pulled = {**NOT_REACHABLE, "reachable": True, "files": ["movies/A/a.mkv", "tv/B/b.mkv"], "bytes": 3 * 10**9,
              "limited_by": "size cap"}

    with patch("installer.cli.load_previous_state", return_value=SYNC_STATE), patch(
        "installer.cli.shutil.which", return_value="/usr/bin/rsync"
    ), patch("installer.cli.sync_from_home", return_value=pulled) as mock_sync:
        result = runner.invoke(app, ["travel", "sync", "--from", "you@home", "--max-gb", "5"])

    assert result.exit_code == 0, result.output
    assert "Pulled 2 files" in result.output and "vulcan media scan" in result.output
    assert mock_sync.call_args[0][3] == 5 * 10**9


def test_travel_sync_install_timer():

    with patch("installer.cli.load_previous_state", return_value=SYNC_STATE), patch(
        "installer.cli.install_timer", return_value={"ok": True, "error": None}
    ) as mock_install:
        result = runner.invoke(app, ["travel", "sync", "--install-timer"])

    assert result.exit_code == 0, result.output
    assert mock_install.call_args[0][0] == "vulcan-travel-sync"
    assert mock_install.call_args[0][2].endswith("-m installer travel sync --if-reachable")
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_generate.py tests/test_travel.py tests/test_cli.py -q -k "sync or tailscale or listing or select_files"`
Expected: FAIL. `ImportError: cannot import name 'list_command'`, CLI exit code 2 (`No such command 'sync'`), and no `TS_HOSTNAME`.

- [ ] **Step 3: Implement**

`templates/docker-compose.yml.j2`, tailscale: replace

```
      - TS_AUTHKEY=${TS_AUTHKEY}
      - TS_STATE_DIR=/var/lib/tailscale
```

with

```
      - TS_AUTHKEY=${TS_AUTHKEY}
      - TS_STATE_DIR=/var/lib/tailscale
{% if travel %}
      # Its own tailnet name - the home box is usually already "vulcan".
      - TS_HOSTNAME={{ tailscale_hostname }}
{% endif %}
```

`templates/env.j2`, append at the end:

```
{% if travel_sync %}

# Travel - `vulcan travel sync` pulls new files from your home Vulcan over
# Tailscale into <media path>/downloads/from-home. TRAVEL_SYNC_FROM is the
# home box as ssh reaches it over the tailnet, e.g. you@vulcan.
TRAVEL_SYNC_FROM={{ travel_sync_from }}
# The home Vulcan's library folder: its media path + /media.
TRAVEL_SYNC_PATH={{ travel_sync_path }}
# Most to pull in one run, and free space always left on this box (GB).
TRAVEL_SYNC_MAX_GB={{ travel_sync_max_gb }}
TRAVEL_SYNC_MIN_FREE_GB={{ travel_sync_min_free_gb }}
{% endif %}
```

`installer/generate.py`:
1. In `render_compose`'s `template.render(...)`, after the `jellyfin_published_url=...` line add:

```python
        tailscale_hostname=f"{config.hostname}-travel",
```

2. `render_env` signature: replace `    atlas_scan_minutes: str = "15"\n) -> str:` with:

```python
    atlas_scan_minutes: str = "15",
    travel_sync_from: str = "",
    travel_sync_path: str = "/mnt/media/media",
    travel_sync_max_gb: str = "200",
    travel_sync_min_free_gb: str = "20"
) -> str:
```

In its `template.render(...)`, replace `        atlas_scan_minutes=atlas_scan_minutes\n    )` with:

```python
        atlas_scan_minutes=atlas_scan_minutes,
        travel_sync=config.tier.name == "travel" and "tailscale" in enabled,
        travel_sync_from=travel_sync_from,
        travel_sync_path=travel_sync_path,
        travel_sync_max_gb=travel_sync_max_gb,
        travel_sync_min_free_gb=travel_sync_min_free_gb
    )
```

3. `write_stack`'s `render_env(...)` call: replace

```python
            _preserved_vpn_value(output_dir, "ATLAS_REFRESH_MINUTES", "15")
        )
    )
```

with

```python
            _preserved_vpn_value(output_dir, "ATLAS_REFRESH_MINUTES", "15")
        ),
        # User-filled travel sync settings - must survive a rebuild.
        travel_sync_from=_preserved_vpn_value(output_dir, "TRAVEL_SYNC_FROM", ""),
        travel_sync_path=_preserved_vpn_value(output_dir, "TRAVEL_SYNC_PATH", "/mnt/media/media"),
        travel_sync_max_gb=_preserved_vpn_value(output_dir, "TRAVEL_SYNC_MAX_GB", "200"),
        travel_sync_min_free_gb=_preserved_vpn_value(output_dir, "TRAVEL_SYNC_MIN_FREE_GB", "20")
    )
```

`installer/travel.py`: add `import shutil` and `from pathlib import Path` to the imports. Add the constants after `MEDIA_REGISTER_UNIT`:

```python
SYNC_UNIT = "vulcan-travel-sync"
# Relative to the media path; the media assistant imports from here.
SYNC_INBOX = Path("downloads") / "from-home"
SYNC_LEDGER = Path("stack") / "travel-sync-ledger.txt"
SSH_COMMAND = "ssh -o BatchMode=yes -o ConnectTimeout=10"
```

Add at the end of the module:

```python
def home_reachable(home: str, run=subprocess.run) -> bool:

    try:
        return run([*SSH_COMMAND.split(), home, "true"], capture_output=True, text=True, timeout=30).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def list_command(home: str, remote_path: str, inbox: Path) -> list[str]:
    """Dry run: every file the inbox doesn't already have, as '<bytes> <path>' lines."""

    return ["rsync", "-a", "-s", "--dry-run", "--out-format=%l %n", "-e", SSH_COMMAND,
            f"{home}:{remote_path.rstrip('/')}/", f"{inbox}/"]


def transfer_command(home: str, remote_path: str, inbox: Path, files_from: str) -> list[str]:
    """--partial-dir keeps an interrupted file, so the next run resumes it."""

    return ["rsync", "-a", "-s", "--partial-dir=.vulcan-partial", "--info=progress2", f"--files-from={files_from}",
            "-e", SSH_COMMAND, f"{home}:{remote_path.rstrip('/')}/", f"{inbox}/"]


def parse_listing(output: str) -> list[tuple[int, str]]:

    files = []

    for line in output.splitlines():

        size, _, name = line.partition(" ")

        if size.isdigit() and name and not name.endswith("/"):
            files.append((int(size), name))

    return files


def select_files(
    files: list[tuple[int, str]], max_bytes: int, free_bytes: int, min_free_bytes: int
) -> tuple[list[tuple[int, str]], str | None]:
    """Files that fit both the per-run cap and the free-space floor, in listing
    order; a file too big for what's left is skipped, smaller ones still go."""

    budget = min(max_bytes, free_bytes - min_free_bytes)
    chosen, total, limited_by = [], 0, None

    for size, name in files:

        if total + size > budget:
            limited_by = "size cap" if max_bytes <= free_bytes - min_free_bytes else "free-space floor"
            continue

        chosen.append((size, name))
        total += size

    return chosen, limited_by


def sync_from_home(
    home: str,
    remote_path: str,
    media_path,
    max_bytes: int,
    min_free_bytes: int,
    ledger_path=SYNC_LEDGER,
    run=subprocess.run,
    free: int | None = None,
) -> dict:
    """Pull files the box doesn't have yet into <media>/downloads/from-home.
    The ledger remembers what arrived, so a file imported (and moved out of
    the inbox) by the media assistant is never pulled twice."""

    inbox = Path(media_path) / SYNC_INBOX
    library = Path(media_path) / "media"
    ledger = Path(ledger_path)
    result = {"reachable": False, "files": [], "bytes": 0, "limited_by": None, "error": None, "inbox": str(inbox)}

    if not home_reachable(home, run):
        return result

    result["reachable"] = True
    inbox.mkdir(parents=True, exist_ok=True)
    listed = run(list_command(home, remote_path, inbox), capture_output=True, text=True)

    if listed.returncode != 0:
        result["error"] = f"couldn't list {home}:{remote_path} ({(listed.stderr or '').strip()[:200]})"
        return result

    done = set(ledger.read_text().splitlines()) if ledger.exists() else set()
    new = [(size, name) for size, name in parse_listing(listed.stdout)
           if name not in done and not (library / name).exists()]
    chosen, result["limited_by"] = select_files(
        new, max_bytes, shutil.disk_usage(inbox).free if free is None else free, min_free_bytes
    )

    if not chosen:
        return result

    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as handle:
        handle.write("".join(f"{name}\n" for _, name in chosen))

    try:
        copied = run(transfer_command(home, remote_path, inbox, handle.name))
    finally:
        os.unlink(handle.name)

    arrived = [(size, name) for size, name in chosen
               if (inbox / name).is_file() and (inbox / name).stat().st_size == size]

    if arrived:
        ledger.parent.mkdir(parents=True, exist_ok=True)
        with ledger.open("a") as out:
            out.write("".join(f"{name}\n" for _, name in arrived))

    result["files"] = [name for _, name in arrived]
    result["bytes"] = sum(size for size, _ in arrived)

    if copied.returncode != 0:
        result["error"] = f"rsync stopped (exit {copied.returncode}) - run again to resume"

    return result
```

`installer/cli.py`: extend the travel import:

```python
from installer.travel import (
    SYNC_UNIT,
    doctor_checks,
    host_setup,
    install_timer,
    remove_timer,
    sync_from_home,
    valid_hostname,
    valid_ip,
)
```

Add after `travel_setup`:

```python
@travel_app.command(name="sync")
def travel_sync(
    home: str | None = typer.Option(
        None, "--from", help="Home Vulcan as ssh reaches it over Tailscale, e.g. you@vulcan (default: TRAVEL_SYNC_FROM)"
    ),
    remote_path: str | None = typer.Option(None, "--remote-path", help="Home library folder (default: TRAVEL_SYNC_PATH)"),
    max_gb: float | None = typer.Option(None, "--max-gb", help="Most to pull this run (default: TRAVEL_SYNC_MAX_GB)"),
    min_free_gb: float | None = typer.Option(
        None, "--min-free-gb", help="Free space to always leave here (default: TRAVEL_SYNC_MIN_FREE_GB)"
    ),
    if_reachable: bool = typer.Option(False, "--if-reachable", help="Exit 0 quietly when home can't be reached (the timer)"),
    install: bool = typer.Option(False, "--install-timer", help="Run this hourly whenever home is reachable"),
    remove: bool = typer.Option(False, "--remove-timer", help="Stop the hourly sync"),
):
    """Pull new files from your home Vulcan over Tailscale into downloads/from-home, ready for `vulcan media scan`."""

    state = load_previous_state(STACK_DIR)

    if not state or state["tier"] != "travel":
        console.print("[red]No Travel stack here.[/red] Build one first: vulcan build --tier travel --home-sync")
        raise typer.Exit(code=1)

    if install or remove:

        result = (
            install_timer(SYNC_UNIT, "Vulcan: sync new media from home", f"{sys.executable} -m installer travel sync --if-reachable")
            if install else remove_timer(SYNC_UNIT)
        )

        if not result["ok"]:
            console.print(f"[red]{result['error']}[/red]")
            raise typer.Exit(code=1)

        console.print(f"{SYNC_UNIT}.timer " + ("installed - runs hourly when home is reachable." if install else "removed."))
        return

    home = home or _preserved_vpn_value(STACK_DIR, "TRAVEL_SYNC_FROM", "")

    if not home:
        console.print("[red]Which home box?[/red] Set TRAVEL_SYNC_FROM in stack/.env (e.g. you@vulcan) or pass --from.")
        raise typer.Exit(code=1)

    if not shutil.which("rsync"):
        console.print("[red]rsync is required[/red] - e.g. `sudo apt install rsync`, then re-run.")
        raise typer.Exit(code=1)

    remote = remote_path or _preserved_vpn_value(STACK_DIR, "TRAVEL_SYNC_PATH", "/mnt/media/media")
    cap = max_gb if max_gb is not None else float(_preserved_vpn_value(STACK_DIR, "TRAVEL_SYNC_MAX_GB", "200"))
    floor = min_free_gb if min_free_gb is not None else float(_preserved_vpn_value(STACK_DIR, "TRAVEL_SYNC_MIN_FREE_GB", "20"))

    result = sync_from_home(home, remote, state["media_path"], int(cap * 1e9), int(floor * 1e9))

    if not result["reachable"]:
        console.print(f"Home Vulcan ({home}) isn't reachable over Tailscale - nothing to do.")
        raise typer.Exit(code=0 if if_reachable else 1)

    console.print(f"Pulled {len(result['files'])} files ({_gb(result['bytes'])}) into {result['inbox']}.")

    if result["limited_by"]:
        console.print(f"[yellow]Stopped short by the {result['limited_by']}[/yellow] - the rest comes next run.")

    if result["files"]:
        console.print(f"Next: vulcan media scan {result['inbox']}  then  vulcan media import <plan> --move")

    if result["error"]:
        console.print(f"[red]{result['error']}[/red]")
        raise typer.Exit(code=1)
```

- [ ] **Step 4: Run to verify they pass**

Run: `python -m pytest tests/ -q && ruff check .`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git switch -c travel/5-home-sync
git add templates/docker-compose.yml.j2 templates/env.j2 installer/generate.py installer/travel.py installer/cli.py \
        tests/test_generate.py tests/test_travel.py tests/test_cli.py
git commit -m "feat(travel): vulcan travel sync from the home Vulcan over Tailscale"
```

PR: `git push -u origin travel/5-home-sync && gh pr create --title "Travel tier 5/9: sync from home" --body "Tailscale joins as <name>-travel; vulcan travel sync pulls new files with rsync over ssh on the tailnet - per-run size cap, free-space floor, resumable partials, a ledger so imported files aren't pulled twice; optional hourly vulcan-travel-sync.timer."`

---

### Task 6: Kodi kiosk (host packages, unit, kiosk user, Jellyfin add-on login, CEC, removal, atomic refusal)

**Files:**
- Modify: `installer/travel.py` (~130 lines), `installer/cli.py` (~40 lines), `installer/generate.py` (~10 lines), `templates/env.j2` (~6 lines)
- Test: `tests/test_travel.py`, `tests/test_cli.py`, `tests/test_generate.py`

**Interfaces:**
- Consumes: `host_setup`, `apply_steps`, `write_root_file`, `_row`, `SYSTEMD_DIR` (Tasks 3–4). `installer.userdata.Jellyfin`. `installer.deps._family_for`. `JELLYFIN_API_KEY` in `.env` (existing).
- Produces (in `installer.travel`): `KIOSK_UNIT = "vulcan-kiosk"`, `KIOSK_USER = "vulcan-kiosk"`, `KIOSK_HOME = "/var/lib/vulcan-kiosk"`, `KIOSK_JELLYFIN_USER = "kiosk"`, `KIOSK_PACKAGES = ["kodi", "cec-utils"]`, `KIOSK_GROUPS = ("video", "render", "input", "audio", "dialout")`, `JELLYFIN_KODI_ZIPS: tuple[str, ...]`, `kiosk_unit() -> str`, `kiosk_refusal(os_info: dict) -> str | None`, `kiosk_install_steps(user_exists: bool, groups: list[str]) -> list[list[str]]`, `install_kiosk(run, write, user_exists, groups) -> dict`, `remove_kiosk(run, exists) -> dict`, `kodi_credentials(login: dict, port: int) -> str`, `kiosk_jellyfin_login(url: str, api_key: str, password: str, opener=urllib.request.urlopen) -> dict` → `{"server_id", "server_name", "user_id", "token"}`, `install_kodi_addon(login: dict | None, port: int, run=run_privileged, fetch=urllib.request.urlretrieve) -> dict`. `host_setup` gains the kiosk step (`"kiosk"` / `"kiosk (removed)"`). `.env` key `KIOSK_JELLYFIN_PASSWORD`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_travel.py`:

```python
import io
import json
import zipfile
from unittest.mock import patch

from installer.travel import (
    install_kodi_addon,
    kiosk_jellyfin_login,
    kiosk_refusal,
    kiosk_unit,
    kodi_credentials,
)

LOGIN = {"server_id": "srv1", "server_name": "trip", "user_id": "u1", "token": "tok"}


def test_kiosk_unit_takes_over_tty1_as_the_kiosk_user():

    unit = kiosk_unit()

    assert "User=vulcan-kiosk" in unit and "TTYPath=/dev/tty1" in unit
    assert "Conflicts=getty@tty1.service" in unit and "ExecStart=/usr/bin/kodi-standalone" in unit
    assert "WantedBy=multi-user.target" in unit


def test_kiosk_refusals():

    assert kiosk_refusal(DEBIAN) is None
    assert "atomic" in kiosk_refusal({"os_id": "fedora", "os_is_atomic": True, "architecture": "x86_64"})
    assert "Debian or Ubuntu" in kiosk_refusal({"os_id": "fedora", "os_is_atomic": False, "architecture": "x86_64"})
    assert "x86-64" in kiosk_refusal({"os_id": "debian", "os_is_atomic": False, "architecture": "aarch64"})


def test_host_setup_installs_the_kiosk():

    calls, run = fake_runner()
    written = {}
    results = host_setup({"jellyfin"}, "trip", True, DEBIAN, run=run, write=fake_write(written),
                         exists=lambda p: False, user_exists=False, groups=["video", "audio"])

    assert ["apt-get", "install", "-y", "kodi", "cec-utils"] in calls
    assert ["useradd", "--system", "--create-home", "--home-dir", "/var/lib/vulcan-kiosk",
            "--shell", "/usr/sbin/nologin", "--groups", "video,audio", "vulcan-kiosk"] in calls
    assert "/etc/systemd/system/vulcan-kiosk.service" in written
    assert ["systemctl", "enable", "--now", "vulcan-kiosk.service"] in calls
    assert any(r["step"] == "kiosk" and r["ok"] for r in results)


def test_host_setup_refuses_the_kiosk_on_an_atomic_os():

    calls, run = fake_runner()
    results = host_setup({"jellyfin"}, "trip", True, {"os_id": "fedora", "os_is_atomic": True, "architecture": "x86_64"},
                         run=run, write=fake_write({}), exists=lambda p: False, user_exists=True, groups=["video"])

    kiosk = next(r for r in results if r["step"] == "kiosk")
    assert kiosk["ok"] is False and "atomic" in kiosk["error"]
    assert not any(argv[:2] == ["apt-get", "install"] for argv in calls)


def test_no_kiosk_removes_the_unit_and_gives_tty1_back():

    calls, run = fake_runner()
    host_setup({"jellyfin"}, "trip", False, DEBIAN, run=run, write=fake_write({}), exists=lambda p: True)

    assert ["systemctl", "disable", "--now", "vulcan-kiosk.service"] in calls
    assert ["rm", "-f", "/etc/systemd/system/vulcan-kiosk.service"] in calls
    assert ["systemctl", "start", "getty@tty1.service"] in calls


def test_kodi_credentials_point_at_localhost():

    servers = json.loads(kodi_credentials(LOGIN, 8096))["Servers"]

    assert servers == [{"Id": "srv1", "Name": "trip", "address": "http://localhost:8096", "AccessToken": "tok",
                        "UserId": "u1", "DateLastAccessed": "1970-01-01T00:00:00Z"}]


def test_install_kodi_addon_stages_addons_and_login():

    def fetch(url, dest):
        top = "repository.jellyfin.kodi" if "repository" in url else "plugin.video.jellyfin"
        with zipfile.ZipFile(dest, "w") as archive:
            archive.writestr(f"{top}/addon.xml", "<addon/>")

    staged = {}

    def run(argv):
        if argv[0] == "cp":
            source = Path(argv[2][:-1])
            staged.update({str(p.relative_to(source)): p.read_text() for p in source.rglob("*") if p.is_file()})
        return {"success": True, "error": None}

    result = install_kodi_addon(LOGIN, 8096, run=run, fetch=fetch)

    assert result == {"ok": True, "error": None}
    assert {"addons/plugin.video.jellyfin/addon.xml", "addons/repository.jellyfin.kodi/addon.xml"} <= set(staged)
    data = json.loads(staged["userdata/addon_data/plugin.video.jellyfin/data.json"])
    assert data["Servers"][0]["address"] == "http://localhost:8096"


def test_install_kodi_addon_without_internet_says_so():

    def fetch(url, dest):
        raise OSError("Temporary failure in name resolution")

    result = install_kodi_addon(None, 8096, run=lambda argv: {"success": True, "error": None}, fetch=fetch)

    assert result["ok"] is False and "internet" in result["error"]


class FakeJellyfin:

    calls = []

    def __init__(self, url, key):
        self.url = url

    def __call__(self, path, method="GET", body=None):
        FakeJellyfin.calls.append((path, method, body))
        return {"/System/Info/Public": {"ServerName": "trip", "Id": "srv1"}, "/Users": [],
                "/Users/New": {"Id": "u1"}}[path]


def test_kiosk_login_creates_the_user_then_signs_in():

    def opener(req, timeout):
        assert req.full_url == "http://localhost:8096/Users/AuthenticateByName"
        assert json.loads(req.data) == {"Username": "kiosk", "Pw": "pw"}
        return io.BytesIO(json.dumps({"AccessToken": "tok", "ServerId": "srv1", "User": {"Id": "u1"}}).encode())

    with patch("installer.travel.Jellyfin", FakeJellyfin):
        login = kiosk_jellyfin_login("http://localhost:8096", "key", "pw", opener=opener)

    assert login == LOGIN
    assert ("/Users/New", "POST", {"Name": "kiosk", "Password": "pw"}) in FakeJellyfin.calls
```

Append to `tests/test_generate.py`:

```python
def test_travel_env_has_a_kiosk_password_only_with_the_kiosk():

    assert re.search(r"^KIOSK_JELLYFIN_PASSWORD=\S{20,}$", render_env(travel_config(kiosk=True)), re.M)
    assert "KIOSK_JELLYFIN_PASSWORD" not in render_env(travel_config())
```

Append to `tests/test_cli.py`:

```python
def test_build_travel_refuses_kiosk_on_atomic_os(tmp_path):

    result, mock_write_stack = _build_travel(tmp_path, "--kiosk", info=make_system_info(os_is_atomic=True))

    assert result.exit_code == 1
    assert "atomic" in result.output
    mock_write_stack.assert_not_called()


def test_travel_host_setup_wires_the_kodi_addon_after_the_kiosk_step():

    config = _config_from_previous_state({**TRAVEL_STATE, "kiosk": True})
    rows = [{"step": "kiosk", "ok": True, "error": None, "skipped": False}]

    with patch("installer.cli.host_setup", return_value=rows), patch(
        "installer.cli.detect_os", return_value={"os_id": "debian"}
    ), patch("installer.cli._preserved_vpn_value", side_effect=lambda d, k, default: {"JELLYFIN_API_KEY": "key", "KIOSK_JELLYFIN_PASSWORD": "pw"}.get(k, default)), patch(
        "installer.cli.kiosk_jellyfin_login", return_value={"server_id": "s", "server_name": "n", "user_id": "u", "token": "t"}
    ) as mock_login, patch("installer.cli.install_kodi_addon", return_value={"ok": True, "error": None}) as mock_addon:

        assert REAL_TRAVEL_HOST_SETUP(config) is True

    mock_login.assert_called_once_with("http://localhost:8096", "key", "pw")
    assert mock_addon.call_args[0][1] == 8096
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_travel.py tests/test_cli.py tests/test_generate.py -q -k "kiosk or kodi"`
Expected: FAIL. `ImportError: cannot import name 'install_kodi_addon' from 'installer.travel'`.

- [ ] **Step 3: Implement**

`templates/env.j2`, append at the end:

```
{% if kiosk %}

# Kodi kiosk - password of the "kiosk" Jellyfin user Vulcan creates for the
# TV's Jellyfin add-on. Generated; changing it logs the TV out.
KIOSK_JELLYFIN_PASSWORD={{ kiosk_jellyfin_password }}
{% endif %}
```

`installer/generate.py`:
1. `render_env` signature: replace `    travel_sync_min_free_gb: str = "20"\n) -> str:` with:

```python
    travel_sync_min_free_gb: str = "20",
    kiosk_jellyfin_password: str | None = None
) -> str:
```

In its `template.render(...)`, replace `        travel_sync_min_free_gb=travel_sync_min_free_gb\n    )` with:

```python
        travel_sync_min_free_gb=travel_sync_min_free_gb,
        kiosk=config.kiosk and config.tier.name == "travel",
        kiosk_jellyfin_password=kiosk_jellyfin_password or secrets.token_urlsafe(18)
    )
```

2. In `write_stack`'s `render_env(...)` call, replace `        travel_sync_min_free_gb=_preserved_vpn_value(output_dir, "TRAVEL_SYNC_MIN_FREE_GB", "20")\n    )` with:

```python
        travel_sync_min_free_gb=_preserved_vpn_value(output_dir, "TRAVEL_SYNC_MIN_FREE_GB", "20"),
        # The kiosk's Jellyfin user was created with it - keep it.
        kiosk_jellyfin_password=(
            _preserved_vpn_value(output_dir, "KIOSK_JELLYFIN_PASSWORD", "") or None
        )
    )
```

`installer/travel.py`: add `import grp`, `import json`, `import pwd`, `import urllib.request`, `import zipfile` and `from installer.userdata import Jellyfin` to the imports. Add the constants after `SSH_COMMAND`:

```python
KIOSK_UNIT = "vulcan-kiosk"
KIOSK_USER = "vulcan-kiosk"
KIOSK_HOME = "/var/lib/vulcan-kiosk"
KIOSK_JELLYFIN_USER = "kiosk"
# cec-utils: `cec-client -l` shows whether a CEC adapter is there at all.
KIOSK_PACKAGES = ["kodi", "cec-utils"]
# dialout: USB-CEC adapters (most x86 HDMI ports have no CEC of their own).
KIOSK_GROUPS = ("video", "render", "input", "audio", "dialout")
JELLYFIN_KODI_ZIPS = (
    "https://kodi.jellyfin.org/repository.jellyfin.kodi.zip",
    "https://kodi.jellyfin.org/py3/plugin.video.jellyfin/plugin.video.jellyfin-2.2.0%2Bpy3.zip",
)
```

Add before `_row`:

```python
def kiosk_unit() -> str:
    """Kodi full-screen on tty1 at boot. Conflicts= stops the login prompt
    there; remove_kiosk() starts it again."""

    return (
        "[Unit]\nDescription=Vulcan kiosk (Kodi full-screen on the TV)\n"
        "After=network-online.target docker.service systemd-user-sessions.service\n"
        "Wants=network-online.target\nConflicts=getty@tty1.service\n\n"
        f"[Service]\nUser={KIOSK_USER}\nEnvironment=HOME={KIOSK_HOME}\nPAMName=login\nTTYPath=/dev/tty1\n"
        "StandardInput=tty\nStandardOutput=journal\nExecStart=/usr/bin/kodi-standalone\n"
        "Restart=on-failure\nRestartSec=5\n\n"
        "[Install]\nWantedBy=multi-user.target\n"
    )


def kiosk_refusal(os_info: dict) -> str | None:

    if os_info.get("os_is_atomic"):
        return ("Kodi kiosk isn't supported on atomic/immutable systems (Bazzite, Silverblue, ...) - "
                "the stack still works; play from the TV's Jellyfin app instead")

    if _family_for(os_info.get("os_id")) != "debian":
        return "Kodi kiosk needs Debian or Ubuntu in this release - the stack still works"

    if os_info.get("architecture") not in ("x86_64", "amd64"):
        return "Kodi kiosk is x86-64 only in this release (Pi 5 is experimental) - the stack still works"

    return None


def kiosk_install_steps(user_exists: bool, groups: list[str]) -> list[list[str]]:

    member = ["usermod", "-aG", ",".join(groups), KIOSK_USER] if user_exists else [
        "useradd", "--system", "--create-home", "--home-dir", KIOSK_HOME,
        "--shell", "/usr/sbin/nologin", "--groups", ",".join(groups), KIOSK_USER,
    ]

    return [["apt-get", "install", "-y", *KIOSK_PACKAGES], member]


def _user_exists(name: str) -> bool:

    try:
        pwd.getpwnam(name)
    except KeyError:
        return False

    return True


def _existing_groups(names) -> list[str]:

    found = []

    for name in names:
        try:
            grp.getgrnam(name)
            found.append(name)
        except KeyError:
            pass

    return found


def install_kiosk(run, write, user_exists: bool, groups: list[str]) -> dict:

    result = apply_steps(kiosk_install_steps(user_exists, groups), run)

    if not result["ok"]:
        return result

    unit_path = f"{SYSTEMD_DIR}/{KIOSK_UNIT}.service"
    written = write(unit_path, kiosk_unit(), run)

    if not written["success"]:
        return {"ok": False, "error": f"couldn't write {unit_path}: {written['error']}"}

    return apply_steps([["systemctl", "daemon-reload"], ["systemctl", "enable", "--now", f"{KIOSK_UNIT}.service"]], run)


def remove_kiosk(run, exists) -> dict:
    """--no-kiosk: the unit goes, tty1 gets its login prompt back. Kodi and the
    kiosk user stay installed."""

    unit_path = f"{SYSTEMD_DIR}/{KIOSK_UNIT}.service"

    if not exists(unit_path):
        return {"ok": True, "error": None, "skipped": True}

    return apply_steps([
        ["systemctl", "disable", "--now", f"{KIOSK_UNIT}.service"],
        ["rm", "-f", unit_path],
        ["systemctl", "daemon-reload"],
        ["systemctl", "start", "getty@tty1.service"],
    ], run)


def kodi_credentials(login: dict, port: int) -> str:
    """The Jellyfin add-on's own saved-login file (addon_data/.../data.json)."""

    return json.dumps({"Servers": [{
        "Id": login["server_id"],
        "Name": login["server_name"],
        "address": f"http://localhost:{port}",
        "AccessToken": login["token"],
        "UserId": login["user_id"],
        "DateLastAccessed": "1970-01-01T00:00:00Z",
    }]}, indent=4, sort_keys=True)


def kiosk_jellyfin_login(url: str, api_key: str, password: str, opener=urllib.request.urlopen) -> dict:
    """Create the "kiosk" Jellyfin user if missing, then sign in as it."""

    jf = Jellyfin(url, api_key)
    info = jf("/System/Info/Public")

    if not any(user["Name"] == KIOSK_JELLYFIN_USER for user in jf("/Users")):
        jf("/Users/New", "POST", {"Name": KIOSK_JELLYFIN_USER, "Password": password})

    request = urllib.request.Request(
        url.rstrip("/") + "/Users/AuthenticateByName", method="POST",
        data=json.dumps({"Username": KIOSK_JELLYFIN_USER, "Pw": password}).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": 'MediaBrowser Client="Vulcan kiosk", Device="vulcan-kiosk", DeviceId="vulcan-kiosk", Version="1"',
        },
    )
    auth = json.loads(opener(request, timeout=30).read())

    return {"server_id": auth["ServerId"], "server_name": info["ServerName"],
            "user_id": auth["User"]["Id"], "token": auth["AccessToken"]}


def install_kodi_addon(login: dict | None, port: int, run=run_privileged, fetch=urllib.request.urlretrieve) -> dict:
    """Place the Jellyfin repo + add-on in the kiosk user's Kodi, plus its saved
    login when we have one. Needs the internet (the zips), hence 'set it up at
    home first'."""

    staging = Path(tempfile.mkdtemp(prefix="vulcan-kodi-"))

    try:

        addons = staging / "addons"
        addons.mkdir()

        for url in JELLYFIN_KODI_ZIPS:

            zip_path = staging / url.rsplit("/", 1)[1]
            fetch(url, zip_path)

            with zipfile.ZipFile(zip_path) as archive:
                archive.extractall(addons)

            zip_path.unlink()

        if login:
            data = staging / "userdata" / "addon_data" / "plugin.video.jellyfin" / "data.json"
            data.parent.mkdir(parents=True)
            data.write_text(kodi_credentials(login, port))

        kodi_dir = f"{KIOSK_HOME}/.kodi"

        return apply_steps([
            ["mkdir", "-p", kodi_dir],
            ["cp", "-a", f"{staging}/.", kodi_dir],
            ["chown", "-R", f"{KIOSK_USER}:{KIOSK_USER}", kodi_dir],
        ], run)

    except (OSError, zipfile.BadZipFile) as error:
        return {"ok": False, "error": f"couldn't fetch the Kodi Jellyfin add-on ({error}) - needs internet, run it at home"}

    finally:
        shutil.rmtree(staging, ignore_errors=True)
```

Replace `host_setup`'s body (keep its signature) with:

```python
    """Every host-side travel step, in order. Re-run safe: each step is idempotent."""

    steps = avahi_steps(os_info.get("os_id"), os_info.get("os_is_atomic", False), hostname)

    if steps is None:
        avahi = {"ok": False, "error": "install avahi (avahi-daemon) by hand, then: sudo systemctl enable --now avahi-daemon"}
    else:
        avahi = apply_steps(steps, run)

    results = [_row(f"avahi ({hostname}.local)", avahi)]

    # Hourly catch-up for imports queued while Sonarr/Radarr were offline -
    # only meaningful when the self-download group is in the stack.
    if services & {"sonarr", "radarr"}:
        results.append(_row("media-register timer", install_timer(
            MEDIA_REGISTER_UNIT, "Vulcan: register imported media with Sonarr/Radarr",
            f"{sys.executable} -m installer media register", run=run, write=write,
        )))
    else:
        results.append(_row("media-register timer (removed)", remove_timer(MEDIA_REGISTER_UNIT, run, exists)))

    if kiosk:

        refusal = kiosk_refusal(os_info)

        if refusal:
            results.append(_row("kiosk", {"ok": False, "error": refusal}))
        else:
            results.append(_row("kiosk", install_kiosk(
                run, write,
                _user_exists(KIOSK_USER) if user_exists is None else user_exists,
                _existing_groups(KIOSK_GROUPS) if groups is None else groups,
            )))

    else:
        results.append(_row("kiosk (removed)", remove_kiosk(run, exists)))

    return results
```

`installer/cli.py`:
1. Add `install_kodi_addon,` and `kiosk_jellyfin_login,` to the `from installer.travel import (...)` list.

2. In the travel block of `_gather_generation_config`, after the `kiosk_value` if/elif/else, add:

```python
        if kiosk_value and info.os_is_atomic:
            console.print("[red]Kodi kiosk isn't supported on atomic/immutable systems.[/red] Re-run with --no-kiosk.")
            raise typer.Exit(code=1)
```

3. Replace `_travel_host_setup` with:

```python
def _travel_host_setup(config: GenerationConfig, panel: RunPanel | _NoOpPanel | None = None) -> bool:
    """Host pieces of a travel box, outside Docker and through sudo. A failure
    warns and never undoes the build - `vulcan travel setup` re-applies,
    `vulcan doctor` checks."""

    panel = panel if panel is not None else _NoOpPanel(console)
    results = host_setup(enabled_service_keys(config), config.hostname, config.kiosk, detect_os())

    for step in results:

        if step["skipped"]:
            continue

        if step["ok"]:
            panel.note(f"[green]✓[/green] {step['step']}")
        else:
            panel.note(f"[yellow]! {step['step']}: {step['error']}[/yellow]")

    ok = all(step["ok"] for step in results)

    if any(step["step"] == "kiosk" and step["ok"] for step in results):
        ok = _kiosk_addon(config, panel) and ok

    if not ok:
        panel.note("Fix the above, then re-run: vulcan travel setup   (check with: vulcan doctor)")

    return ok


def _kiosk_addon(config: GenerationConfig, panel: RunPanel | _NoOpPanel) -> bool:
    """Kodi's Jellyfin add-on + its saved login. The login needs a running
    Jellyfin and an API key, so a first build places the add-on only and says
    how to finish."""

    port = resolve_ports(config)["jellyfin"]
    key = _preserved_vpn_value(STACK_DIR, "JELLYFIN_API_KEY", "")
    password = _preserved_vpn_value(STACK_DIR, "KIOSK_JELLYFIN_PASSWORD", "")
    login = None

    if key and password:
        try:
            login = kiosk_jellyfin_login(f"http://localhost:{port}", key, password)
        except (OSError, ValueError, KeyError) as error:
            panel.note(f"[yellow]! Kodi login: Jellyfin didn't answer ({error}) - start the stack, then re-run "
                       "vulcan travel setup[/yellow]")
    else:
        panel.note("Kodi login: finish Jellyfin's first-run wizard, add JELLYFIN_API_KEY to stack/.env "
                   "(Dashboard > API Keys), then run: vulcan travel setup")

    result = install_kodi_addon(login, port)

    if result["ok"]:
        panel.note("[green]✓[/green] Kodi Jellyfin add-on" + (" (signed in)" if login else ""))
    else:
        panel.note(f"[yellow]! Kodi Jellyfin add-on: {result['error']}[/yellow]")

    return result["ok"]
```

- [ ] **Step 4: Run to verify they pass**

Run: `python -m pytest tests/ -q && ruff check .`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git switch -c travel/6-kiosk
git add installer/travel.py installer/cli.py installer/generate.py templates/env.j2 \
        tests/test_travel.py tests/test_cli.py tests/test_generate.py
git commit -m "feat(travel): optional Kodi kiosk with a pre-signed-in Jellyfin add-on"
```

PR: `git push -u origin travel/6-kiosk && gh pr create --title "Travel tier 6/9: Kodi kiosk" --body "--kiosk installs Kodi + cec-utils, a vulcan-kiosk user and vulcan-kiosk.service on tty1, places the Jellyfin add-on with a saved login for a 'kiosk' Jellyfin user (localhost:8096); --no-kiosk removes the unit; atomic and non-Debian/x86-64 hosts get a clear refusal."`

---

### Task 7: TUI: Travel in both tier menus + the Travel checklist

**Files:**
- Modify: `installer/menu.sh` (~55 lines), `installer/cli.py` (1 line, `PREVIOUS_KIOSK`)
- Test: `tests/test_menu.bats`, `tests/test_cli.py`

**Interfaces:**
- Consumes: the `vulcan build` flags from Task 1. `vulcan detect`'s new field `PREVIOUS_KIOSK` (`'true'|'false'`).
- Produces: `_guided_setup_travel_options` (fills `TOGGLE_FLAGS` with `--self-download|--no-self-download`, `--home-sync|--no-home-sync`, `--kiosk|--no-kiosk`, and `--gpu|--no-gpu` when a GPU was detected).

- [ ] **Step 1: Write the failing tests**

In `tests/test_menu.bats`, add `PREVIOUS_KIOSK='false'` to the `_detect` heredoc (after `PREVIOUS_DASHY_PRIVATE='true'`), add `PREVIOUS_KIOSK` to the variable list in the "every field menu.sh references from 'vulcan detect'" test, then append:

```bash
@test "travel options map the checklist to real build flags" {

    whiptail() {
        case "$*" in
            *"Travel Options"*) echo -n '"download" "kiosk"' >&3; return 0 ;;
            *"GPU Passthrough"*) return 0 ;;
            *) return 0 ;;
        esac
    }
    export -f whiptail

    run bash -c "
        source '$MENU_SH'
        PREVIOUS_ENABLED_OPTIONAL=''
        PREVIOUS_KIOSK='false'
        GPU_VENDOR='intel'
        TOGGLE_FLAGS=()
        _guided_setup_travel_options
        echo \"\${TOGGLE_FLAGS[*]}\"
    "

    [ "$status" -eq 0 ]
    [[ "$output" == *"--self-download"* ]]
    [[ "$output" == *"--no-home-sync"* ]]
    [[ "$output" == *"--kiosk"* ]]
    [[ "$output" == *"--gpu"* ]]
    [[ "$output" != *"--no-self-download"* ]]
}

@test "travel options pre-check what the previous travel build had" {

    whiptail() {
        case "$*" in
            *"Travel Options"*) echo "ARGS: $*" >&2; return 1 ;;
            *) return 0 ;;
        esac
    }
    export -f whiptail

    run bash -c "
        source '$MENU_SH'
        PREVIOUS_ENABLED_OPTIONAL='tailscale'
        PREVIOUS_KIOSK='true'
        GPU_VENDOR=''
        TOGGLE_FLAGS=()
        _guided_setup_travel_options
    "

    [[ "$output" == *"Sync from home Vulcan over Tailscale ON"* ]]
    [[ "$output" == *"Kodi full-screen on the TV at boot ON"* ]]
    [[ "$output" == *"behind a VPN OFF"* ]]
}

@test "both guided setups offer Travel and use its checklist instead of the home-tier toggles" {

    export VULCAN_CALLS="$BATS_TMPDIR/vcalls-travel-$$"
    export SETUP_LOG="$BATS_TMPDIR/setup-travel-$$.log"

    fake_vulcan() {
        case "$1" in
            detect) _detect "GPU_VENDOR=''" ;;
            *) printf '%s\n' "$*" >> "$VULCAN_CALLS"; return 0 ;;
        esac
    }
    export -f fake_vulcan

    whiptail() {
        case "$*" in
            *"Media Library"*) echo -n "${@: -1}" >&3; return 0 ;;
            *"Choose a Tier"*)
                [[ "$*" == *'"travel"'* || "$*" == *" travel "* ]] || echo "NO TRAVEL ITEM" >&2
                echo -n "travel" >&3; return 0 ;;
            *"Travel Options"*) echo -n '"download" "kiosk"' >&3; return 0 ;;
            *"Customize the full service list"*) echo "CUSTOMIZE ASKED" >&2; return 1 ;;
            *"Optional Services"*) echo "HOME TOGGLES ASKED" >&2; return 1 ;;
            *) return 0 ;;
        esac
    }
    export -f whiptail

    for flow in guided_setup guided_setup_no_start; do

        : > "$VULCAN_CALLS"
        run bash -c "source '$MENU_SH'; VULCAN_BIN=fake_vulcan; $flow <<< \$'\n\n\n'"

        [ "$status" -eq 0 ]
        grep -q -- '--tier travel' "$VULCAN_CALLS"
        grep -q -- '--self-download' "$VULCAN_CALLS"
        grep -q -- '--no-home-sync' "$VULCAN_CALLS"
        grep -q -- ' --kiosk' "$VULCAN_CALLS"
        [[ "$output" != *"NO TRAVEL ITEM"* ]]
        [[ "$output" != *"CUSTOMIZE ASKED"* ]]
        [[ "$output" != *"HOME TOGGLES ASKED"* ]]
    done
}
```

Append to `tests/test_cli.py`:

```python
def test_detect_shell_emits_previous_kiosk(tmp_path):

    with patch("installer.cli.detect_system", return_value=make_system_info()), patch(
        "installer.cli.STACK_DIR", tmp_path / "stack"
    ), patch("installer.cli.load_previous_state", return_value={**TRAVEL_STATE, "kiosk": True}):
        result = runner.invoke(app, ["detect"])

    assert "PREVIOUS_KIOSK='true'" in result.output.splitlines()
```

- [ ] **Step 2: Run to verify they fail**

Run: `bats tests/test_menu.bats -f "travel|vulcan detect" && python -m pytest tests/test_cli.py -q -k previous_kiosk`
Expected: FAIL. bats fails with `_guided_setup_travel_options: command not found` and "NO TRAVEL ITEM" / "CUSTOMIZE ASKED" in the output. The field test fails with `menu.sh references $PREVIOUS_KIOSK but detect_shell() never emits it`. pytest fails because `PREVIOUS_KIOSK` is missing.

- [ ] **Step 3: Implement**

`installer/cli.py`, `detect_shell()` fields: after `"PREVIOUS_DASHY_PRIVATE": (...)` add:

```python
        "PREVIOUS_KIOSK": "true" if (previous and previous.get("kiosk")) else "false",
```

`installer/menu.sh` (each of the first three edits occurs identically in both `guided_setup_no_start` and `guided_setup`, so apply each with replace-all):

1. Replace

```bash
    local light_on medium_on heavy_on
    light_on="OFF"; medium_on="OFF"; heavy_on="OFF"
    case "$default_tier" in
        light) light_on="ON" ;;
        medium) medium_on="ON" ;;
        heavy) heavy_on="ON" ;;
    esac
```

with

```bash
    local light_on medium_on heavy_on travel_on
    light_on="OFF"; medium_on="OFF"; heavy_on="OFF"; travel_on="OFF"
    case "$default_tier" in
        light) light_on="ON" ;;
        medium) medium_on="ON" ;;
        heavy) heavy_on="ON" ;;
        travel) travel_on="ON" ;;
    esac
```

2. Replace

```bash
        "heavy"  "Heavy - full stack, GPU transcoding, more services" "$heavy_on" \
```

with

```bash
        "heavy"  "Heavy - full stack, GPU transcoding, more services" "$heavy_on" \
        "travel" "Travel - a small box you carry; plays with no internet" "$travel_on" \
```

3. Replace

```bash
    local customize=false

    if whiptail --backtitle "$BACKTITLE" --title "Services" \
        --yesno "Customize the full service list? (adds Traefik/Authelia domain routing, CrowdSec, Tailscale, Decluttarr, Maintainerr, and more)\n\nChoose No for the common case - just the tier's usual services plus the toggles on the next screen." \
        "$DLG_ROWS" "$DLG_COLS" --defaultno; then
        customize=true
    fi

    SERVICES_FLAG=()
    DOMAIN_FLAGS=()
    TOGGLE_FLAGS=()

    if [ "$customize" = true ]; then
        _guided_setup_customize_services
    else
        _guided_setup_quick_toggles
    fi
```

with

```bash
    local customize=false

    SERVICES_FLAG=()
    DOMAIN_FLAGS=()
    TOGGLE_FLAGS=()

    if [ "$TIER" = "travel" ]; then
        _guided_setup_travel_options
    else
        if whiptail --backtitle "$BACKTITLE" --title "Services" \
            --yesno "Customize the full service list? (adds Traefik/Authelia domain routing, CrowdSec, Tailscale, Decluttarr, Maintainerr, and more)\n\nChoose No for the common case - just the tier's usual services plus the toggles on the next screen." \
            "$DLG_ROWS" "$DLG_COLS" --defaultno; then
            customize=true
        fi

        if [ "$customize" = true ]; then
            _guided_setup_customize_services
        else
            _guided_setup_quick_toggles
        fi
    fi
```

4. Add just above the `# Quick path: tier's own default services` comment block:

```bash
# Travel tier: its own short checklist instead of the home-tier toggles.
# Every item maps to a real `vulcan build` flag; the engine owns the rest
# (installer/tiers.py's TRAVEL_SELF_DOWNLOAD / TRAVEL_HOME_SYNC groups).
_guided_setup_travel_options() {

    local prev_optional=",${PREVIOUS_ENABLED_OPTIONAL},"
    local download_on="OFF" sync_on="OFF" kiosk_on="OFF" chosen

    [[ "$prev_optional" == *",gluetun,"* ]] && download_on="ON"
    [[ "$prev_optional" == *",tailscale,"* ]] && sync_on="ON"
    [ "${PREVIOUS_KIOSK:-false}" = "true" ] && kiosk_on="ON"

    chosen=$(whiptail --backtitle "$BACKTITLE" --title "Travel Options" \
        --checklist "Plays from this box's own drives, no internet needed. Add any of these:" \
        "$DLG_ROWS" "$DLG_COLS" "$DLG_ITEMS" \
        "download" "Self-download: Sonarr, Radarr, Prowlarr, qBittorrent behind a VPN" "$download_on" \
        "sync"     "Sync from home Vulcan over Tailscale" "$sync_on" \
        "kiosk"    "Kodi kiosk: Kodi full-screen on the TV at boot" "$kiosk_on" \
        3>&1 1>&2 2>&3) || chosen=""

    if [[ "$chosen" == *'"download"'* ]]; then TOGGLE_FLAGS+=(--self-download); else TOGGLE_FLAGS+=(--no-self-download); fi
    if [[ "$chosen" == *'"sync"'* ]]; then TOGGLE_FLAGS+=(--home-sync); else TOGGLE_FLAGS+=(--no-home-sync); fi
    if [[ "$chosen" == *'"kiosk"'* ]]; then TOGGLE_FLAGS+=(--kiosk); else TOGGLE_FLAGS+=(--no-kiosk); fi

    if [ -n "$GPU_VENDOR" ]; then
        if whiptail --backtitle "$BACKTITLE" --title "GPU Passthrough" \
            --yesno "Use the $GPU_VENDOR GPU for Jellyfin hardware transcoding (Intel Quick Sync on most mini PCs)?" "$DLG_ROWS" "$DLG_COLS"; then
            TOGGLE_FLAGS+=(--gpu)
        else
            TOGGLE_FLAGS+=(--no-gpu)
        fi
    fi
}
```

- [ ] **Step 4: Run to verify they pass**

Run: `shellcheck -S warning installer/menu.sh && bats tests/test_menu.bats tests/test_install.bats && bats tests/test_menu_pty.bats && python -m pytest tests/ -q && ruff check .`
Expected: all PASS, shellcheck clean.

- [ ] **Step 5: Commit**

```bash
git switch -c travel/7-tui
git add installer/menu.sh installer/cli.py tests/test_menu.bats tests/test_cli.py
git commit -m "feat(travel): Travel in the guided setup menus with its own checklist"
```

PR: `git push -u origin travel/7-tui && gh pr create --title "Travel tier 7/9: TUI" --body "Travel in both tier menus; picking it shows a three-item checklist (self-download, sync from home, Kodi kiosk) plus the GPU question, instead of the home-tier toggles. vulcan detect emits PREVIOUS_KIOSK."`

---

### Task 8: Docs: travel guide, tiers table, services catalog, README, ROADMAP, CHANGELOG, CLAUDE.md, mkdocs nav

**Files:**
- Create: `docs/guides/travel.md` (~150 lines)
- Modify: `mkdocs.yml` (1 line), `docs/tiers.md` (~8 lines), `docs/services-catalog.md` (~15 lines), `README.md` (~6 lines), `ROADMAP.md` (~3 lines), `CHANGELOG.md` (~3 lines), `CLAUDE.md` (~3 lines)

**Interfaces:** none new. The docs name only what Tasks 1–7 ship: flags, `vulcan travel setup|sync`, `vulcan doctor`, timer names, `.env` keys.

- [ ] **Step 1: Write the failing check**

```bash
grep -q "guides/travel.md" mkdocs.yml && test -f docs/guides/travel.md && grep -q "| Travel |" docs/tiers.md
```
Expected: exit 1 (nothing there yet).

- [ ] **Step 2: Write `docs/guides/travel.md`**

```markdown
# Travel: a Vulcan you carry

A small box (an N100 mini PC or an old laptop) that plays your movies and shows from its own drives with no internet, can be reached by name on any network, can run the TV, and catches up on new media whenever it gets online.

**Supported:** x86-64 boxes on Debian or Ubuntu (Kodi kiosk) or any distro Vulcan supports (the stack itself). **Raspberry Pi 5:** experimental. It has no hardware video encoder, so set Jellyfin's clients to direct play and bring files that play everywhere (the media assistant flags the ones that may need converting).

## What you need

- The box: at least 2 cores, 4 GB RAM and 64 GB free. An Intel N100 is ideal, because Quick Sync transcodes for free.
- A drive with your media (internal or USB).
- A travel router (a GL.iNet, for example) if you want the same network everywhere. Optional, but it makes "by IP" links stable.
- For the kiosk: an HDMI TV. TV remote control over HDMI (CEC) needs a USB-CEC adapter on most PCs.

## 1. Set it up at home first

Do the whole setup at home, with internet. That's when images download, posters and metadata fill in, and the Kodi add-on installs. Once it's done, the box needs nothing from the internet.

    ./install            # pick Travel in the tier menu

or without the menu:

    ./install --plain --tier travel --media-path /mnt/media --hostname vulcan \
        --self-download --home-sync --kiosk --non-interactive --yes --start

Travel asks about three extras:

| Extra | What it does | Flag |
|---|---|---|
| Self-download | Sonarr, Radarr, Prowlarr and qBittorrent behind the gluetun VPN. Downloads new episodes when online; idles quietly when not. | `--self-download` |
| Sync from home | Tailscale + `vulcan travel sync`: pulls new files from your home Vulcan. | `--home-sync` |
| Kodi kiosk | Kodi full-screen on the TV at boot, already signed in to Jellyfin. | `--kiosk` |

Then:

1. Open Jellyfin (`http://vulcan.local:8096`), finish its first-run wizard, add your libraries.
2. If you picked self-download: fill in your VPN in `stack/.env` (`vulcan configure` walks you through it).
3. If you picked the kiosk: in Jellyfin go to Dashboard → API Keys → + and paste the key after `JELLYFIN_API_KEY=` in `stack/.env`. Then run `vulcan travel setup`. That creates a `kiosk` Jellyfin user and signs Kodi in.
4. Run `vulcan doctor`. It should show two green ticks.

## 2. Finding the box on any network

The box answers as **`<hostname>.local`** (default `vulcan.local`) through Avahi (mDNS). Every Homepage tile and the setup summary use that name, never an IP that the next network won't have.

- Homepage: `http://vulcan.local:3000`
- Jellyfin: `http://vulcan.local:8096`. Jellyfin also tells its apps this address.

Some devices (many Android phones, some smart TVs) can't resolve `.local`. For those, reserve an IP on your travel router and give it to Vulcan:

1. GL.iNet admin panel (`http://192.168.8.1`) → **Network → LAN → Address Reservation** → add the Vulcan box and keep the IP it shows.
2. Rebuild with `--travel-ip 192.168.8.50` (your IP). Homepage gains a **By IP** tab with the same tiles at that address, and the summary shows both links.

`.local` not working? Run `vulcan doctor`. It checks that Avahi is running and that the name resolves, and prints the fix if not.

## 3. Three ways to catch up

**By hand: the media assistant.** Plug in a drive and run *Media → Scan & import* in the menu, or `vulcan media scan /mnt/usb` then `vulcan media import <plan>`. Works fully offline. Anything Sonarr/Radarr couldn't see yet is queued, and `vulcan-media-register.timer` registers it hourly once they're back.

**Self-download.** With self-download on, Sonarr/Radarr grab new episodes and movies whenever the box is online. Offline, gluetun stops trying to reconnect every few seconds and qBittorrent simply waits.

**Sync from home.** Your home Vulcan has everything already. Pull what this box doesn't have:

1. Put both boxes on the same tailnet. On this box, set `TS_AUTHKEY` in `stack/.env` (from https://login.tailscale.com/admin/settings/keys) and start the stack. It joins as `<hostname>-travel`.
2. Let this box log in to the home box over the tailnet. Either run `ssh-copy-id you@<home box>` (the home box's normal SSH), or install Tailscale on the home host itself and run `sudo tailscale set --ssh`. The home Vulcan's own Tailscale container can't do this, because SSH would land inside the container.
3. In `stack/.env` set `TRAVEL_SYNC_FROM=you@<home box>` and `TRAVEL_SYNC_PATH=` the home media path + `/media` (default `/mnt/media/media`).
4. Run `vulcan travel sync`. New files land in `<media path>/downloads/from-home`. Import them with `vulcan media scan <that folder>` then `vulcan media import <plan> --move`.

It never pulls more than `TRAVEL_SYNC_MAX_GB` (default 200) per run and always leaves `TRAVEL_SYNC_MIN_FREE_GB` (default 20) free. An interrupted run resumes where it stopped, and a file you've already imported is never pulled again. `vulcan travel sync --install-timer` runs it hourly, and the timer only does anything when the home box is reachable. `--remove-timer` stops it.

Watch history sync between the two boxes comes later, with `vulcan media pack`.

## 4. The Kodi kiosk

With `--kiosk`, the box boots straight into Kodi full-screen on the TV (`vulcan-kiosk.service`, running as a dedicated `vulcan-kiosk` user on tty1). Kodi's Jellyfin add-on is already installed and pointed at `http://localhost:8096`.

- If Kodi lists the Jellyfin add-on as disabled the first time: Add-ons → My add-ons → Video add-ons → Jellyfin → **Enable**. This is a one-time step, done at home, because it fetches the add-on's helpers.
- TV remote (CEC): Kodi turns it on by itself when it finds a CEC adapter. `cec-client -l` lists adapters. Most PCs need a USB-CEC adapter (Pulse-Eight) between the box and the TV.
- Turn it off: rebuild with `--no-kiosk`. The unit is removed and the normal login prompt comes back. Kodi stays installed.
- Atomic/immutable systems (Bazzite, Silverblue) can't run the kiosk. Use the TV's own Jellyfin app instead.

## 5. Offline: what to expect

- Everything starts with no internet: the images are pinned and already on the box, and there's no Watchtower.
- Jellyfin plays everything already on the drive. Posters fetched at home stay.
- Homepage tile icons load from the internet the first time a browser opens Homepage, so open it once at home.
- Updates are deliberate: `vulcan update` at home, with internet.

## Commands

| Command | What it does |
|---|---|
| `vulcan travel setup` | Re-applies the host pieces: Avahi + hostname, timers, kiosk (and its Jellyfin sign-in) |
| `vulcan travel sync [--from you@home] [--max-gb N] [--min-free-gb N]` | Pulls new files from the home Vulcan |
| `vulcan travel sync --install-timer` / `--remove-timer` | Hourly sync whenever home is reachable |
| `vulcan doctor` | Checks Avahi and `<hostname>.local`, with fixes |
```

- [ ] **Step 3: Update the other docs**

`mkdocs.yml` nav, after the Media Assistant line:

```yaml
  - "Guide: Travel": guides/travel.md
```

`docs/tiers.md`: add a table row and a paragraph under the table:

```markdown
| Travel | ≥ 2 cores, ≥ 4 GB RAM, ≥ 64 GB free (x86-64; Pi 5 experimental) | Jellyfin, Homepage, FileBrowser (+ optional self-download, sync from home, Kodi kiosk) |

**Travel** is a separate shape, not a step above Heavy: a small box you carry that plays with no internet. You choose it yourself (`--tier travel` or *Travel* in the menu). Vulcan never recommends it. It never includes a domain, Traefik, Authelia, CrowdSec, Cloudflare Tunnel or Watchtower, and its container limits are sized from the box itself. See [Guide: Travel](guides/travel.md).
```

`docs/services-catalog.md`, a new section before the first category:

```markdown
## Travel tier

The Travel tier uses its own short list (not Light + extras). Every image is pinned so it starts offline.

| Service | Travel | What it's for there |
|---|---|---|
| Jellyfin | core | Plays from the box's own drives, `http://<hostname>.local:8096` |
| Homepage | core | Start page, `.local` links (+ a By IP tab with `--travel-ip`) |
| FileBrowser | core | Manage files on the box from a phone |
| Sonarr, Radarr, Prowlarr, qBittorrent, Gluetun | optional, together (`--self-download`) | Downloads when online, idles offline |
| Tailscale | optional (`--home-sync`) | Reaches the home Vulcan for `vulcan travel sync` |
```

`README.md`: add a Tiers table row identical to the `docs/tiers.md` row above. In the command table (next to the `vulcan media` rows), add:

```markdown
| `vulcan travel setup` / `vulcan travel sync` | Travel tier: re-apply host setup (Avahi, timers, kiosk); pull new media from your home Vulcan over Tailscale |
| `vulcan doctor` | Checks the host pieces a stack relies on (Travel: Avahi + `<hostname>.local`) |
```

`CHANGELOG.md`, under `## Unreleased` → `### Added`:

```markdown
- **Travel tier** (`--tier travel`, *Travel* in the menu) - a small box you carry: plays from local drives with no internet (pinned images, `pull_policy: missing`, no Watchtower), answers as `<hostname>.local` on any network (Avahi; optional `--travel-ip` by-IP links), optional self-download behind gluetun that idles offline, optional `vulcan travel sync` from your home Vulcan over Tailscale (size cap, free-space floor, resumable), optional Kodi kiosk on the TV (`--kiosk`). Plus `vulcan doctor` and an hourly `vulcan-media-register.timer`. x86-64; Raspberry Pi 5 experimental. See [docs/guides/travel.md](docs/guides/travel.md).
```

`ROADMAP.md`, under `## Next`:

```markdown
- [ ] **Travel tier - real-hardware verification** - code, tests and docs are merged (Tasks 1-8 of `specs/2026-11-19-travel-tier-plan.md`); still owed before release: an online and an offline run, `.local` from another device, a real `vulcan travel sync` from the home Vulcan over Tailscale, the Kodi kiosk on a real x86 box with a screen.
```

`CLAUDE.md`, `## Tiers` list, add after Heavy:

```markdown
- **Travel** — ≥ 2 cores, ≥ 4 GB RAM, ≥ 64 GB free; chosen explicitly, never recommended. Jellyfin + Homepage + FileBrowser, optional self-download / home sync / Kodi kiosk; host pieces in `installer/travel.py`.
```

- [ ] **Step 4: Run the check + CI**

Run: `grep -q "guides/travel.md" mkdocs.yml && test -f docs/guides/travel.md && grep -q "| Travel |" docs/tiers.md && python -m pytest tests/ -q && ruff check .`
Expected: exit 0. If the docs extra is installed (`pip install -e ".[docs]"`), `mkdocs build --strict` also passes.

- [ ] **Step 5: Commit**

```bash
git switch -c travel/8-docs
git add docs/guides/travel.md mkdocs.yml docs/tiers.md docs/services-catalog.md README.md ROADMAP.md CHANGELOG.md CLAUDE.md
git commit -m "docs(travel): travel guide, tier table, catalog, changelog and roadmap"
```

PR: `git push -u origin travel/8-docs && gh pr create --title "Travel tier 8/9: docs" --body "Beginner travel guide (set up at home first, finding the box, three ways to catch up, kiosk, Pi experimental) + tiers/catalog/README/CHANGELOG/ROADMAP."`

---

### Task 9: Real-infrastructure verification (required before release)

Mocked tests are necessary but not sufficient (AGENTS.md). Every step below runs against real containers, a real network and real hardware. **[OWNER]** marks steps that need the owner's hardware, accounts or hands. Record each result (command output or a photo/screenshot) in the PR. Any bug found gets its own failing test, fix and commit on this branch before the ROADMAP entry moves to Shipped.

**Files:**
- Modify: `ROADMAP.md` (move the Travel entry from Next to Shipped with the evidence), `CHANGELOG.md` (only if a fix landed). Plus fix commits as needed.

**Interfaces:** none new.

- [ ] **Step 1: Pinned images exist.** On any Docker host:

```bash
python -c "from installer.services import TRAVEL_IMAGES; print('\n'.join(TRAVEL_IMAGES.values()))" | xargs -n1 docker pull
```
Expected: every pull succeeds. A missing tag means: pick the current one, update `TRAVEL_IMAGES`, re-run.

- [ ] **Step 2: [OWNER] Online run on the real x86 travel box** (Debian/Ubuntu, screen attached, at home):

```bash
git clone https://github.com/Cyb3rRon1n/vulcan && cd vulcan
./install --plain --tier travel --media-path /mnt/media --self-download --home-sync --kiosk \
    --travel-ip <reserved IP> --non-interactive --yes --start
docker compose -f stack/docker-compose.yml ps     # every container "running"
grep -c "pull_policy: missing" stack/docker-compose.yml; grep ":latest" stack/docker-compose.yml   # N services; no output
vulcan doctor                                    # two ✓
systemctl list-timers | grep vulcan-media-register
```
Then finish the Jellyfin wizard, set `JELLYFIN_API_KEY`, run `vulcan travel setup`, and confirm "Kodi Jellyfin add-on (signed in)".

- [ ] **Step 3: [OWNER] Offline run.** Unplug the network (or `sudo nmcli networking off`) and reboot the box. After 10 minutes:

```bash
docker compose -f stack/docker-compose.yml ps                      # all running, none "Restarting"
docker inspect -f '{{.Name}} {{.RestartCount}}' $(docker ps -q)    # no restart counts climbing
docker logs --since 10m gluetun | wc -l                            # low, not a flood (record the number)
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8096/health   # 200
```
Play a movie in Jellyfin from a phone or laptop on the box's LAN (the travel router, no WAN) and confirm it plays. `docker compose -f stack/docker-compose.yml up -d` must also exit 0 while offline.

- [ ] **Step 4: [OWNER] `.local` from another device.** On the travel router's LAN, from a laptop, run `ping vulcan.local` and open `http://vulcan.local:3000` and `http://vulcan.local:8096`. From an Android phone, open the By IP tab's Jellyfin link. Record which devices resolved `.local` (this feeds the guide).

- [ ] **Step 5: [OWNER] Real sync from the home Vulcan over Tailscale.** Set `TS_AUTHKEY`, start the stack, and confirm the node appears as `vulcan-travel` in the tailnet admin. Set up the SSH key (or host `tailscale set --ssh`) on the home box, set `TRAVEL_SYNC_FROM`/`TRAVEL_SYNC_PATH`, then:

```bash
vulcan travel sync --max-gb 5          # pulls ≤ 5 GB into /mnt/media/downloads/from-home
# interrupt a second run with Ctrl-C mid-file, run again -> resumes (no restart from 0, .vulcan-partial gone after)
vulcan media scan /mnt/media/downloads/from-home --plan /tmp/p.json && vulcan media import /tmp/p.json --move
vulcan travel sync --max-gb 5          # already-imported files are not pulled again
vulcan travel sync --install-timer && systemctl list-timers | grep vulcan-travel-sync
```
Then take the home box off the tailnet and run `vulcan travel sync --if-reachable; echo $?`. Expected: `0`, "isn't reachable".

- [ ] **Step 6: [OWNER] Kodi kiosk on the real x86 box with a screen.** Reboot. Expected: Kodi comes up full-screen on the TV with no login prompt. Open the Jellyfin add-on and confirm it's signed in as `kiosk` against `localhost:8096` and plays a file. Record whether the "Enable add-on" step was needed (update the guide if it wasn't). With a USB-CEC adapter attached, check that the TV remote moves through Kodi (`cec-client -l` lists the adapter). Then:

```bash
./install --plain --tier travel --no-kiosk --non-interactive --yes    # unit removed
systemctl status vulcan-kiosk.service    # not found; tty1 shows a login prompt again
```

- [ ] **Step 7: Atomic refusal (any atomic VM or Bazzite box).** `vulcan build --tier travel --media-path /tmp/m --kiosk --non-interactive --yes`. Expected: exit 1, "isn't supported on atomic/immutable systems".

- [ ] **Step 8: Record and commit.** Move the ROADMAP item from Next to Shipped with the real results from Steps 1–7 (numbers, device list, any bug and its fix commit), matching the media assistant entry's style. Then:

```bash
git switch -c travel/9-verified
git add ROADMAP.md CHANGELOG.md
git commit -m "docs(travel): real-hardware verification results"
```

PR: `git push -u origin travel/9-verified && gh pr create --title "Travel tier 9/9: real verification" --body "Results of the online/offline/.local/sync/kiosk runs on real hardware; see ROADMAP."`

---

## Self-review against the spec

| Spec requirement | Task |
|---|---|
| Fourth tier `travel`, chosen explicitly (`--tier travel`, both TUI tier menus) | 1 (CLI), 7 (both radiolists) |
| Never auto-recommended; excluded from `recommend_tier()` / `_next_tier_up` | 1 (`test_travel_is_never_recommended`, `test_next_tier_up_skips_travel`) |
| Limits sized from detected CPU/RAM; `RESOURCE_LIMITS["travel"]` so `resource_limits_for` never raises | 1 (`_travel_limits`, `ram_gb` on `GenerationConfig`) |
| Own service list, not cumulative; minimums 2/4/64 | 1 |
| Core: Jellyfin (Quick Sync/VA-API via `/dev/dri`), media assistant, Homepage, File Browser | 1 (list; GPU question on travel), 4 (assistant works offline: pinned probe image, register timer) |
| Optional off by default: self-download behind gluetun; home sync; Kodi kiosk; readers stay ordinary optional | 1 (flags default off), 5, 6; Ruling 4 |
| Excluded: domain, Traefik, Authelia, CrowdSec, Cloudflared, Watchtower | 1 (CLI refusal), 2 (`enabled_service_keys` choke point) |
| x86-64 supported; Pi 5 experimental, direct-play guidance | 6 (kiosk refusal on non-x86), 8 (guide), 9 (x86 verified) |
| `--kiosk/--no-kiosk`, `--travel-ip`, `--hostname` (default `vulcan`) | 1 |
| `_SERVICE_DEPS` qBittorrent → gluetun for self-download | 1 (group always includes gluetun; Ruling 2) |
| TUI: "Travel" in both tier menus + checklist (Self-download, Sync from home, Kodi kiosk) | 7 |
| State records tier `travel` + options; re-runs rebuild the same | 1 (`hostname`/`travel_ip`/`kiosk` + `enabled_optional`; rerun test) |
| Avahi installed + enabled; `--hostname` sets it | 3 (`hostnamectl` + `avahi-daemon`) |
| Homepage tiles + setup summary link `http://<hostname>.local:<port>` | 2 (`link_host` in `write_stack` and all 7 CLI call sites) |
| Optional `--travel-ip` second link; guide shows GL.iNet reservation | 2 (By IP group/tab + summary), 8 |
| Jellyfin published URL = `http://<hostname>.local:8096` | 2 |
| Kodi talks to `localhost:8096` | 6 (`kodi_credentials`) |
| `vulcan doctor`: Avahi running + `.local` resolves, plain fix | 3 |
| Pinned tags, `pull_policy: missing`, no Watchtower | 2 |
| `vulcan-media-register.timer` hourly, no-op when nothing queued | 4 |
| gluetun health tolerant of no internet; dependents idle, no crash loop / log flood | 4 (`HEALTH_RESTART_VPN=off`, `service_started`), 9 (offline run) |
| Tailscale joins with `TS_AUTHKEY`; `vulcan travel sync` rsync over Tailscale SSH, size cap, free-space floor, resumable, into the import path; by hand or optional timer that only acts when home is reachable | 5; Rulings 5–7 |
| Watch-history sync deferred | 8 (guide says so); not built |
| Guide leads with "set it up at home first" | 8 |
| Kodi + Jellyfin add-on (Debian/Ubuntu x86-64); `vulcan-kiosk` unit on a dedicated user; add-on pre-configured with a Vulcan-created Jellyfin user; CEC | 6; Rulings 11–13 |
| `--no-kiosk` removes the unit; atomic OSes get a clear refusal | 6 (`remove_kiosk`, CLI + `host_setup` refusal) |
| Docs: `docs/guides/travel.md` + nav, `docs/tiers.md`, `docs/services-catalog.md`, README, ROADMAP, CHANGELOG | 8 |
| pytest coverage list (tier/exclusion, sizing, compose, Homepage links, gluetun offline, sync flags, kiosk unit, state round-trip) | 1, 1, 2, 2, 4, 5, 6, 1 |
| bats: TUI travel entries + checklist | 7 |
| Real checks before release (online, offline, `.local`, real sync, kiosk on real x86) | 9 |
| Out of scope: 2b kit, `media pack`, Pi full support, tiers-by-purpose refresh | not planned |

**Consistency checks (fixed inline while writing).**
- Names used across tasks:
  - `TRAVEL_SELF_DOWNLOAD`, `TRAVEL_HOME_SYNC`, `TRAVEL_EXCLUDED`, `tier_shortfalls`.
  - `GenerationConfig.ram_gb/hostname/travel_ip/kiosk`, `link_host(config, detected_ip)`, `pin_travel_images`, `TRAVEL_IMAGES`.
  - `apply_steps`, `write_root_file(path, content, run)`, `host_setup(services, hostname, kiosk, os_info, run, write, exists, user_exists, groups)`. Its signature is fixed in Task 3 and its body grows in Tasks 4 and 6.
  - `install_timer`/`remove_timer`, `MEDIA_REGISTER_UNIT`, `SYNC_UNIT`, `sync_from_home(home, remote_path, media_path, max_bytes, min_free_bytes, ...)`.
  - `install_kodi_addon(login, port, run, fetch)`, `kiosk_jellyfin_login(url, api_key, password, opener)`.
  - `_travel_host_setup(config, panel)`. It is patched by the autouse fixture in `tests/test_cli.py` from Task 3 on, and tested through `REAL_TRAVEL_HOST_SETUP`.
- `render_env` keyword chain: Task 5 appends `travel_sync_*` after `atlas_scan_minutes`. Task 6 anchors on Task 5's `travel_sync_min_free_gb` lines and appends `kiosk_jellyfin_password`. `write_stack` follows the same order.
- Task 1's `_build_travel` helper passes `info=` (used by Task 6's atomic test). Task 3's autouse fixture keeps Task 1's travel build tests from reaching sudo.
- `media register`'s new no-op changes the old "no Arrs → exit 1" test. Task 4 rewrites that test to queue a row first.
