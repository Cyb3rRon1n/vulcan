import json
from pathlib import Path

from installer.media.arr import Arr, ArrClients, add_pending, connect_arrs, register_pending


class FakeArr(Arr):
    """Routes calls to a dict of path-prefix -> response (callable or value); records every call."""

    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def call(self, path, method="GET", body=None):
        self.calls.append((method, path, body))
        for prefix, resp in self.routes.items():
            if (method + " " + path).startswith(prefix):
                return resp(path, body) if callable(resp) else resp
        raise OSError(f"no route for {method} {path}")


SERIES = {"id": 7, "title": "SPY x FAMILY", "year": 2022, "tvdbId": 405920, "seriesType": "anime",
          "originalLanguage": {"name": "Japanese"}}


def test_confirm_episode_from_parse_hit(tmp_path):
    sonarr = FakeArr({"GET /parse": {"series": SERIES}})
    c = ArrClients(sonarr, None, tmp_path)
    got = c.confirm({"kind": "episode", "title": "spy x family", "year": None, "anime": False,
                     "confidence": "high"}, "spy.x.family.s01e11.mkv")
    assert got["title"] == "SPY x FAMILY" and got["tvdb_id"] == 405920
    assert got["original_language"] == "jpn" and got["anime"] is True


def test_confirm_lookup_only_raises_confidence_on_matching_name(tmp_path):
    sonarr = FakeArr({"GET /parse": {}, "GET /series/lookup": [dict(SERIES, id=None)]})
    c = ArrClients(sonarr, None, tmp_path)
    low = {"kind": "episode", "title": "Spy x Family", "year": None, "anime": False, "confidence": "low"}
    assert c.confirm(low, "02.mkv")["confidence"] == "high"
    other = dict(low, title="Something Else")
    assert c.confirm(other, "02.mkv") == other


def test_confirm_lookup_rejects_wrong_year(tmp_path):
    """"Doctor Who" (2005) must not be confirmed against the 1963 series of the same name."""
    sonarr = FakeArr({"GET /parse": {}, "GET /series/lookup": [{"title": "Doctor Who", "year": 1963,
                                                                 "originalLanguage": {"name": "English"}}]})
    c = ArrClients(sonarr, None, tmp_path)
    ident = {"kind": "episode", "title": "Doctor Who", "year": 2005, "anime": False, "confidence": "low"}
    assert c.confirm(ident, "doctor.who.s01e01.mkv") == ident


def test_confirm_lookup_accepts_movie_year_off_by_one(tmp_path):
    """Radarr/TMDB sometimes lists a movie a year off from a release-date guess; allow +/-1 for movies."""
    radarr = FakeArr({"GET /parse": {}, "GET /movie/lookup": [{"title": "Heat", "year": 1996,
                                                                "originalLanguage": {"name": "English"}}]})
    c = ArrClients(None, radarr, tmp_path)
    ident = {"kind": "movie", "title": "Heat", "year": 1995, "confidence": "low"}
    assert c.confirm(ident, "Heat.1995.mkv")["confidence"] == "high"


def test_confirm_clears_wrong_offline_anime_guess(tmp_path):
    """Arr is authoritative on seriesType - an exact hit must be able to clear a wrong offline guess."""
    sonarr = FakeArr({"GET /parse": {"series": dict(SERIES, seriesType="standard")}})
    c = ArrClients(sonarr, None, tmp_path)
    got = c.confirm({"kind": "episode", "title": "spy x family", "year": None, "anime": True,
                     "confidence": "high"}, "spy.x.family.s01e11.mkv")
    assert got["anime"] is False


def test_confirm_survives_unreachable_arr(tmp_path):
    c = ArrClients(FakeArr({}), FakeArr({}), tmp_path)
    ident = {"kind": "movie", "title": "Heat", "year": 1995, "confidence": "high"}
    assert c.confirm(ident, "Heat.1995.mkv") == ident


def test_confirm_carries_arr_container_path_as_host_path(tmp_path):
    sonarr = FakeArr({"GET /parse": {"series": dict(SERIES, path="/data/media/anime/SPY x FAMILY (2022)")}})
    c = ArrClients(sonarr, None, tmp_path)
    got = c.confirm({"kind": "episode", "title": "spy x family", "year": None, "anime": False,
                     "confidence": "high"}, "spy.x.family.s01e11.mkv")
    assert got["host_path"] == str(tmp_path / "media/anime/SPY x FAMILY (2022)")


def test_paths_map_between_host_and_container(tmp_path):
    c = ArrClients(None, None, tmp_path)
    assert c.to_host("/data/media/tv") == tmp_path / "media/tv"
    assert c.to_container(tmp_path / "media/tv/Show") == "/data/media/tv/Show"


def test_roots_from_root_folders(tmp_path):
    sonarr = FakeArr({"GET /rootfolder": [{"path": "/data/media/tv"}, {"path": "/data/media/anime"}]})
    radarr = FakeArr({"GET /rootfolder": [{"path": "/data/media/movies"}]})
    roots = ArrClients(sonarr, radarr, tmp_path).roots()
    assert roots == {"tv": tmp_path / "media/tv", "anime": tmp_path / "media/anime", "movies": tmp_path / "media/movies"}


def test_register_adds_series_rescans_and_verifies(tmp_path):
    dest = tmp_path / "media/anime/SPY x FAMILY (2022)/Season 01/spy.x.family.s01e11.mkv"
    added = {}

    def add(path, body):
        added.update(body)
        return {"id": 9}

    sonarr = FakeArr({
        "GET /series?tvdbId": [],
        "GET /series/lookup": [dict(SERIES, id=None)],
        "GET /qualityprofile": [{"id": 4}],
        "GET /series": [],
        "GET /rootfolder": [{"path": "/data/media/anime"}],
        "POST /series": add,
        "POST /command": {"id": 1},
        "GET /command/1": {"status": "completed"},
        "GET /episodefile": [{"path": "/data/media/anime/SPY x FAMILY (2022)/Season 01/spy.x.family.s01e11.mkv"}],
    })
    c = ArrClients(sonarr, None, tmp_path, sleep=lambda s: None)
    row = {"identity": {"kind": "episode", "tvdb_id": 405920, "anime": True}, "destination": str(dest)}
    result = c.register([row])
    assert result["registered"] == [row] and result["pending"] == []
    assert added["path"] == "/data/media/anime/SPY x FAMILY (2022)" and added["qualityProfileId"] == 4
    assert added["seriesType"] == "anime" and added["addOptions"]["searchForMissingEpisodes"] is False
    assert ("POST", "/command", {"name": "RescanSeries", "seriesId": 9}) in sonarr.calls


def test_register_confirms_rows_identified_while_offline(tmp_path):
    """
    A row imported while the stack was offline was identified by the
    built-in parser only - no tmdb_id. Once an Arr is reachable again,
    register() must confirm it (the same lookup scan() uses) instead of
    leaving it pending forever.
    """
    dest = tmp_path / "media/movies/Alien (1979)/Alien (1979).mkv"
    MOVIE = {"id": 55, "title": "Alien", "year": 1979, "tmdbId": 348, "originalLanguage": {"name": "English"}}
    added = {}

    def add(path, body):
        added.update(body)
        return {"id": 9}

    radarr = FakeArr({
        "GET /parse": {},
        "GET /movie/lookup/tmdb": MOVIE,
        "GET /movie/lookup": [dict(MOVIE, id=None)],
        "GET /movie?tmdbId": [],
        "GET /qualityprofile": [{"id": 4}],
        "GET /moviefile": [{"path": "/data/media/movies/Alien (1979)/Alien (1979).mkv"}],
        "GET /movie": [],
        "GET /rootfolder": [{"path": "/data/media/movies"}],
        "POST /movie": add,
        "POST /command": {"id": 1},
        "GET /command/1": {"status": "completed"},
    })
    c = ArrClients(None, radarr, tmp_path, sleep=lambda s: None)
    row = {"source": "/drive/Alien (1979).mkv",
           "identity": {"kind": "movie", "title": "Alien", "year": 1979, "confidence": "high"},
           "destination": str(dest)}
    result = c.register([row])
    assert result["registered"] == [row] and result["pending"] == []
    assert row["identity"]["tmdb_id"] == 348


def test_register_keeps_unpicked_and_unidentified_rows_pending(tmp_path):
    sonarr = FakeArr({"GET /series?tvdbId": [{"id": 3}], "POST /command": {"id": 1},
                      "GET /command/1": {"status": "completed"}, "GET /episodefile": []})
    c = ArrClients(sonarr, None, tmp_path, sleep=lambda s: None)
    rows = [{"identity": {"kind": "episode", "tvdb_id": 1}, "destination": str(tmp_path / "media/tv/A/a.mkv")},
            {"identity": {"kind": "episode"}, "destination": str(tmp_path / "media/tv/B/b.mkv")}]
    result = c.register(rows)
    reasons = sorted(r["reason"] for r in result["pending"])
    assert reasons == ["not identified online", "not picked up by Sonarr rescan"]


def test_pending_file_round_trip(tmp_path):
    pending = tmp_path / "pending.json"
    add_pending([{"destination": "/a", "reason": "offline"}, {"destination": "/a", "reason": "offline"}], pending)
    assert len(json.loads(pending.read_text())) == 1                 # de-duplicated by destination

    class Clients:
        def register(self, rows):
            return {"registered": rows[:0], "pending": [dict(rows[0], reason="still offline")]}

    result = register_pending(Clients(), pending)
    assert result["pending"][0]["reason"] == "still offline"
    assert json.loads(pending.read_text())[0]["reason"] == "still offline"


def test_connect_arrs_reads_keys_and_checks_reachability(tmp_path):
    for app in ("sonarr", "radarr"):
        d = tmp_path / "config" / app
        d.mkdir(parents=True)
        (d / "config.xml").write_text(f"<Config><ApiKey>{app}key</ApiKey></Config>")

    class Resp:
        def __init__(self, data): self.data = data
        def read(self): return self.data
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def opener(req, timeout=0):
        if ":7878" in req.full_url:
            raise OSError("radarr down")
        assert req.headers["X-api-key"] == "sonarrkey"
        return Resp(b'{"version": "4"}')

    clients = connect_arrs(tmp_path, Path("/m"), {"sonarr": 8989, "radarr": 7878}, opener=opener)
    assert clients.sonarr is not None and clients.radarr is None
    assert connect_arrs(tmp_path / "nothing", Path("/m"), {"sonarr": 8989, "radarr": 7878}, opener=opener) is None
