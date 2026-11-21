import socket
import subprocess
from unittest.mock import patch

import pytest

from installer.travel import MEDIA_REGISTER_UNIT, apply_steps, avahi_steps, doctor_checks, host_setup, remove_timer, timer_units, home_host_problem, sync_from_home, travel_teardown

HOSTS = "127.0.0.1 localhost\n"
DEBIAN = {"os_id": "debian", "os_is_atomic": False, "architecture": "x86_64"}


@pytest.fixture(autouse=True)
def _avahi_not_installed():
    """Keep tests independent of whether the dev box has Avahi."""

    with patch("installer.travel._avahi_installed", return_value=False):
        yield


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
    results = host_setup({"jellyfin"}, "trip", False, DEBIAN, run=run, write=fake_write({}), exists=lambda p: False, read_hosts=lambda: HOSTS)

    assert results[0] == {"step": "avahi (trip.local)", "ok": True, "error": None, "skipped": False}
    assert ["hostnamectl", "set-hostname", "trip"] in calls


def test_host_setup_reports_an_unsupported_distro():

    calls, run = fake_runner()
    results = host_setup({"jellyfin"}, "trip", False, {"os_id": "gentoo", "os_is_atomic": False},
                         run=run, write=fake_write({}), exists=lambda p: False, read_hosts=lambda: HOSTS)

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


def test_host_setup_rejects_a_bad_hostname_before_running_anything():

    calls, run = fake_runner()
    written = {}

    for bad in ("Bad Name", "-x", "a.b", ""):
        results = host_setup({"jellyfin"}, bad, False, DEBIAN, run=run, write=fake_write(written), exists=lambda p: False, read_hosts=lambda: HOSTS)

        assert results[0]["ok"] is False and "not a valid hostname" in results[0]["error"]

    assert calls == [] and written == {}


def _hosts_for(text):

    written = {}
    calls, run = fake_runner()
    rows = host_setup({"jellyfin"}, "trip", False, DEBIAN, run=run, write=fake_write(written),
                      exists=lambda p: False, read_hosts=lambda: text)

    return rows, written


def test_hosts_replaces_the_old_127_0_1_1_line_only():

    rows, written = _hosts_for("127.0.0.1 localhost\n127.0.1.1 oldname oldname.lan\n::1 ip6-localhost\n")

    assert written["/etc/hosts"] == "127.0.0.1 localhost\n127.0.1.1 trip\n::1 ip6-localhost\n"
    assert rows[1]["ok"] is True


def test_hosts_adds_the_line_when_missing():

    _, written = _hosts_for("127.0.0.1 localhost\n")

    assert written["/etc/hosts"] == "127.0.0.1 localhost\n127.0.1.1 trip\n"


def test_hosts_is_untouched_when_already_correct():

    rows, written = _hosts_for("127.0.0.1 localhost\n127.0.1.1 trip\n")

    assert written == {}
    assert rows[1]["skipped"] is True


def test_atomic_failure_and_unknown_distro_mention_rpm_ostree():

    calls, run = fake_runner(fail_on=["systemctl", "enable", "--now", "avahi-daemon"])
    atomic = {"os_id": "fedora", "os_is_atomic": True}
    rows = host_setup({"jellyfin"}, "trip", False, atomic, run=run, write=fake_write({}), exists=lambda p: False, read_hosts=lambda: HOSTS)

    assert "rpm-ostree install avahi nss-mdns" in rows[0]["error"] and "reboot" in rows[0]["error"]

    rows = host_setup({"jellyfin"}, "trip", False, {"os_id": "gentoo"}, run=run, write=fake_write({}), exists=lambda p: False, read_hosts=lambda: HOSTS)

    assert "rpm-ostree install avahi nss-mdns" in rows[0]["error"]


def test_doctor_fix_covers_arch_and_atomic():

    def no_resolve(host, port):
        raise socket.gaierror("x")

    fix = doctor_checks("trip", run_capture=lambda *a, **k: subprocess.CompletedProcess(a, 0, "active\n", ""),
                        resolve=no_resolve)[1]["fix"]

    assert "pacman -S avahi nss-mdns" in fix and "rpm-ostree install avahi nss-mdns" in fix


def test_hosts_write_is_followed_by_restorecon_only_when_installed():

    for present in (True, False):
        calls, run = fake_runner()

        def write(path, content, run):
            calls.append(["write", path])
            return {"success": True, "error": None}

        host_setup({"jellyfin"}, "trip", False, DEBIAN, run=run, write=write, exists=lambda p: False,
                   read_hosts=lambda: "127.0.0.1 localhost\n",
                   which=lambda name: "/usr/sbin/restorecon" if present else None)

        assert (["restorecon", "/etc/hosts"] in calls) is present
        if present:
            assert calls.index(["restorecon", "/etc/hosts"]) == calls.index(["write", "/etc/hosts"]) + 1


def test_unreadable_hosts_is_left_alone():

    written = {}
    calls, run = fake_runner()
    rows = host_setup({"jellyfin"}, "trip", False, DEBIAN, run=run, write=fake_write(written),
                      exists=lambda p: False, read_hosts=lambda: None, which=lambda n: "/x/restorecon")

    assert written == {} and ["restorecon", "/etc/hosts"] not in calls
    assert rows[1]["ok"] is False and "could not read /etc/hosts" in rows[1]["error"] and "127.0.1.1 trip" in rows[1]["error"]


def test_every_127_0_1_1_line_is_rewritten_and_restorecon_failure_is_labelled():

    _, written = _hosts_for("127.0.1.1 a\n127.0.0.1 localhost\n127.0.1.1 b\n")

    assert written["/etc/hosts"] == "127.0.1.1 trip\n127.0.0.1 localhost\n127.0.1.1 trip\n"

    calls, run = fake_runner(fail_on=["restorecon", "/etc/hosts"])
    rows = host_setup({"jellyfin"}, "trip", False, DEBIAN, run=run, write=fake_write({}), exists=lambda p: False,
                      read_hosts=lambda: HOSTS, which=lambda n: "/x")

    assert rows[1]["ok"] is False and rows[1]["error"].startswith("written; restorecon failed")


def test_timer_units_content():

    units = timer_units("vulcan-media-register", "Vulcan: register imported media",
                        ["/venv/bin/python", "-m", "installer", "media", "register"], "hourly", "ron", "/home/ron/vulcan")
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


from pathlib import Path

from installer.travel import list_command, parse_listing, select_files, transfer_command


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

    assert listing[:2] == ["rsync", "-a"] and "-8" in listing and "--dry-run" in listing and "--out-format=%l %n" in listing
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


def _ssh_says(code, stderr):

    return lambda argv, **kw: subprocess.CompletedProcess(argv, code, "", stderr)


def test_sync_from_home_reports_ssh_refusals_as_errors_not_unreachable(tmp_path):

    for stderr in ("Host key verification failed.", "you@home: Permission denied (publickey)."):

        result = sync_from_home("you@home", "/m/media", tmp_path, 10**9, 0, ledger_path=tmp_path / "l",
                                run=_ssh_says(255, stderr))

        assert result["reachable"] is True and result["error"] and result["files"] == []


def test_sync_from_home_refuses_root_path_and_option_like_hosts(tmp_path):

    def run(argv, **kw):
        raise AssertionError("must not run anything")

    root = sync_from_home("you@home", "/", tmp_path, 10**9, 0, ledger_path=tmp_path / "l", run=run)
    option = sync_from_home("-oProxyCommand=x", "/m/media", tmp_path, 10**9, 0, ledger_path=tmp_path / "l", run=run)

    assert "can't be /" in root["error"]
    assert "option" in option["error"]


import io
import json
import zipfile

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
    assert ["systemctl", "enable", "vulcan-kiosk.service"] in calls
    assert ["systemctl", "enable", "--now", "vulcan-kiosk.service"] not in calls
    assert not any(argv[:2] == ["systemctl", "start"] for argv in calls)
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

    result = install_kodi_addon(LOGIN, 8096, run=run, fetch=fetch, exists=lambda p: False)

    assert result == {"ok": True, "error": None}
    assert {"addons/plugin.video.jellyfin/addon.xml", "addons/repository.jellyfin.kodi/addon.xml"} <= set(staged)
    data = json.loads(staged["userdata/addon_data/plugin.video.jellyfin/data.json"])
    assert data["Servers"][0]["address"] == "http://localhost:8096"


def test_install_kodi_addon_without_internet_says_so():

    def fetch(url, dest):
        raise OSError("Temporary failure in name resolution")

    result = install_kodi_addon(None, 8096, run=lambda argv: {"success": True, "error": None}, fetch=fetch,
                                exists=lambda p: False)

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


def test_install_kodi_addon_already_installed_offline_still_writes_the_login():

    def fetch(url, dest):
        raise AssertionError("must not download once the add-on is in place")

    staged = {}

    def run(argv):
        if argv[0] == "cp":
            source = Path(argv[2][:-1])
            staged.update({str(p.relative_to(source)): p.read_text() for p in source.rglob("*") if p.is_file()})
        return {"success": True, "error": None}

    result = install_kodi_addon(LOGIN, 8096, run=run, fetch=fetch, exists=lambda p: p.endswith("addons/plugin.video.jellyfin"))

    assert result == {"ok": True, "error": None}
    assert list(staged) == ["userdata/addon_data/plugin.video.jellyfin/data.json"]


def test_timer_units_quote_arguments_with_spaces():

    units = timer_units("t", "d", ["/my venv/bin/python", "-m", "installer"], "hourly", "ron", "/home/ron/my vulcan")

    assert "ExecStart='/my venv/bin/python' -m installer\n" in units["/etc/systemd/system/t.service"]


def test_host_setup_removes_the_sync_timer_without_tailscale():

    calls, run = fake_runner()
    exists = lambda p: p.endswith("vulcan-travel-sync.timer")
    host_setup({"jellyfin"}, "trip", False, DEBIAN, run=run, write=fake_write({}), exists=exists, read_hosts=lambda: HOSTS)

    assert ["systemctl", "disable", "--now", "vulcan-travel-sync.timer"] in calls

    calls.clear()
    host_setup({"jellyfin", "tailscale"}, "trip", False, DEBIAN, run=run, write=fake_write({}), exists=exists, read_hosts=lambda: HOSTS)

    assert ["systemctl", "disable", "--now", "vulcan-travel-sync.timer"] not in calls


def test_travel_teardown_removes_what_is_installed_and_does_nothing_otherwise():

    calls, run = fake_runner()
    rows = travel_teardown(run, exists=lambda p: False)

    assert calls == [] and all(row["skipped"] for row in rows)

    rows = travel_teardown(run, exists=lambda p: True)
    flat = [" ".join(argv) for argv in calls]

    assert "systemctl disable --now vulcan-kiosk.service" in flat
    assert "systemctl disable --now vulcan-media-register.timer" in flat
    assert "systemctl disable --now vulcan-travel-sync.timer" in flat
    assert all(row["ok"] for row in rows)


def test_avahi_install_is_skipped_when_already_installed():

    assert avahi_steps("fedora", False, "trip", installed=True) == [
        ["hostnamectl", "set-hostname", "trip"],
        ["systemctl", "enable", "--now", "avahi-daemon"],
    ]

    calls, run = fake_runner()
    host_setup({"jellyfin"}, "trip", False, {"os_id": "fedora", "os_is_atomic": False}, run=run, write=fake_write({}),
               exists=lambda p: False, read_hosts=lambda: HOSTS, avahi_installed=lambda: True)

    assert not any(argv[0] == "dnf" for argv in calls)
    assert ["systemctl", "enable", "--now", "avahi-daemon"] in calls


def test_home_host_problem_refuses_this_box_and_loopback():

    def loopback(host, port):
        return [(2, 1, 6, "", ("127.0.1.1", 0))]

    def remote(host, port):
        return [(2, 1, 6, "", ("100.64.0.9", 0))]

    def nothing(host, port):
        raise socket.gaierror("x")

    assert home_host_problem("you@vulcan", ["vulcan"], remote)
    assert home_host_problem("you@Vulcan.local", ["vulcan"], remote)
    assert home_host_problem("you@home-vulcan", ["trip"], loopback)
    assert home_host_problem("you@home-vulcan", ["trip"], remote) is None
    assert home_host_problem("you@home-vulcan", ["trip"], nothing) is None


def test_sync_from_home_refuses_this_box_itself(tmp_path):

    def run(argv, **kw):
        raise AssertionError("must not run anything")

    result = sync_from_home("you@vulcan", "/m/media", tmp_path, 10**9, 0, ledger_path=tmp_path / "l", run=run,
                            own_names=("vulcan",), resolve=lambda h, p: [])

    assert "this box itself" in result["error"]


def test_sync_ledger_skips_a_file_whose_size_does_not_match(tmp_path):

    media = tmp_path / "media"
    ledger = tmp_path / "ledger.txt"
    listing = "30 movies/Cut (2026)/cut.mkv\n"

    def run(argv, **kw):
        if argv[0] == "ssh" or "--dry-run" in argv:
            return subprocess.CompletedProcess(argv, 0, listing, "")
        target = media / "downloads" / "from-home" / "movies/Cut (2026)/cut.mkv"
        target.parent.mkdir(parents=True)
        target.write_bytes(b"x" * 12)  # truncated
        return subprocess.CompletedProcess(argv, 0, "", "")

    result = sync_from_home("you@home", "/m/media", media, 10**9, 0, ledger_path=ledger, run=run, free=10**12)

    assert result["files"] == [] and not ledger.exists()
