import socket
import subprocess

from installer.travel import MEDIA_REGISTER_UNIT, apply_steps, avahi_steps, doctor_checks, host_setup, remove_timer, timer_units

HOSTS = "127.0.0.1 localhost\n"
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
