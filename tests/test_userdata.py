import datetime as dt
import json
from unittest.mock import MagicMock, patch

from installer.generate import render_env, write_stack
from installer.post_install import push_offsite
from installer.userdata import export_userdata, restore_userdata
from tests.test_generate import make_config


class FakeJellyfin:
    """Two libraries' worth of Jellyfin: `old` ids for the export, `new` ids after a rebuild."""

    def __init__(self, ids):

        m, s, e = ids
        self.movie = {"Id": m, "Type": "Movie", "Name": "Heat", "ProductionYear": 1995,
                      "ProviderIds": {"Tmdb": "949", "Imdb": "tt0113277"}, "DateCreated": "2020-01-01"}
        self.show = {"Id": s, "Type": "Series", "Name": "Andor", "ProviderIds": {"Tvdb": "393189"}}
        self.ep = {"Id": e, "Type": "Episode", "Name": "Rix Road", "SeriesId": s, "SeriesName": "Andor",
                   "ParentIndexNumber": 1, "IndexNumber": 12}
        self.calls = []

    def __call__(self, path, method="GET", body=None):

        self.calls.append((method, path, body))

        if path == "/Users":
            return [{"Name": "alice", "Id": "u1"}]
        if "IncludeItemTypes=Series&Fields=ProviderIds" in path:
            return {"Items": [self.show]}
        if "IncludeItemTypes=Episode&Fields=SeriesId" in path:
            return {"Items": [self.ep]}
        if "IncludeItemTypes=Movie,Series&" in path and "userId" not in path:
            return {"Items": [self.movie, self.show]}
        if "userId=u1" in path and "Filters=" in path:
            movie = dict(self.movie, UserData={"IsFavorite": True, "Likes": True, "Played": True,
                                               "PlayCount": 2, "LastPlayedDate": "2026-09-01T20:00:00Z"})
            ep = dict(self.ep, UserData={"PlaybackPositionTicks": 12345, "Likes": False})
            never_rated = dict(self.show, UserData={})     # Jellyfin's Dislikes filter returns these too
            return {"Items": [movie, ep, never_rated]}
        return None


def test_export_then_restore_onto_a_rebuilt_jellyfin(tmp_path):

    old = FakeJellyfin(("m-old", "s-old", "e-old"))
    result = export_userdata(old, out_root=tmp_path, today=dt.date(2026, 9, 27))

    snap = tmp_path / "2026-09-27"
    assert result["users"] == {"alice": 2}          # the never-rated show was dropped
    items = json.loads((snap / "users" / "alice.json").read_text())["items"]
    movie = next(i for i in items if i["type"] == "Movie")
    assert movie["ids"] == {"tmdb": "949", "imdb": "tt0113277"} and movie["favorite"] and movie["likes"] is True
    ep = next(i for i in items if i["type"] == "Episode")
    assert ep["series_ids"] == {"tvdb": "393189"} and (ep["season"], ep["episode"]) == (1, 12)

    new = FakeJellyfin(("m-new", "s-new", "e-new"))  # rebuild: every Jellyfin id changed
    dry = restore_userdata(new, snap)
    assert dry == [{"user": "alice", "matched": 2, "missing": []}]
    assert not [c for c in new.calls if c[0] == "POST"]

    restore_userdata(new, snap, apply=True)
    posts = {(p.split("?")[0]) for m, p, _ in new.calls if m == "POST"}
    assert posts == {"/UserFavoriteItems/m-new", "/UserItems/m-new/Rating", "/UserPlayedItems/m-new",
                     "/UserItems/m-new/UserData", "/UserItems/e-new/Rating", "/UserItems/e-new/UserData"}


def test_restore_reports_missing_user(tmp_path):

    export_userdata(FakeJellyfin(("a", "b", "c")), out_root=tmp_path, today=dt.date(2026, 9, 27))
    other = FakeJellyfin(("a", "b", "c"))
    other_users = lambda path, method="GET", body=None: [] if path == "/Users" else other(path, method, body)  # noqa: E731

    [r] = restore_userdata(other_users, tmp_path / "2026-09-27")
    assert r["user"] == "alice" and "create it" in r["error"]


def test_export_keeps_newest_snapshots_only(tmp_path):

    for d in ("2026-09-01", "2026-09-02", "2026-09-03"):
        (tmp_path / d).mkdir()

    export_userdata(FakeJellyfin(("a", "b", "c")), out_root=tmp_path, today=dt.date(2026, 9, 27), keep=2)

    assert sorted(p.name for p in tmp_path.iterdir()) == ["2026-09-03", "2026-09-27"]


def test_push_offsite_rsyncs_each_existing_source(tmp_path):

    (tmp_path / "backups").mkdir()
    ok = MagicMock(returncode=0)

    with patch("installer.post_install.subprocess.run", return_value=ok) as run:
        result = push_offsite("nas:/vulcan", [tmp_path / "backups", tmp_path / "missing"], ssh_key="/k")

    assert result == {"success": True, "pushed": [str(tmp_path / "backups")], "errors": []}
    args = run.call_args[0][0]
    assert args[:4] == ["rsync", "-a", "--delete", "-e"] and "-i /k" in args[4]
    assert args[-2:] == [f"{tmp_path / 'backups'}/", "nas:/vulcan/backups/"]


def test_push_offsite_reports_failure_without_raising(tmp_path):

    (tmp_path / "backups").mkdir()

    with patch("installer.post_install.subprocess.run", return_value=MagicMock(returncode=255)):
        result = push_offsite("nas:/vulcan", [tmp_path / "backups"])

    assert result["success"] is False and result["errors"] == [str(tmp_path / "backups")]


def test_userdata_and_offsite_env_keys_survive_a_rebuild(tmp_path):

    config = make_config("heavy")
    config.media_path = str(tmp_path / "media-root")
    assert "JELLYFIN_API_KEY=\n" in render_env(config)

    write_stack(config, output_dir=tmp_path / "stack")
    env = tmp_path / "stack" / ".env"
    text = env.read_text().replace("JELLYFIN_API_KEY=\n", "JELLYFIN_API_KEY=abc123\n").replace(
        "BACKUP_OFFSITE_TARGET=\n", "BACKUP_OFFSITE_TARGET=backup@nas:/v\n")
    env.write_text(text)

    write_stack(config, output_dir=tmp_path / "stack")

    rebuilt = env.read_text()
    assert "JELLYFIN_API_KEY=abc123\n" in rebuilt and "BACKUP_OFFSITE_TARGET=backup@nas:/v\n" in rebuilt
