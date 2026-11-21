from pathlib import Path

from installer.media.plan import library_roots, load_plan, plan_destination, scan, write_plan


class FakeProber:
    def __init__(self, by_name):
        self.by_name = by_name

    def probe(self, path):
        return self.by_name.get(Path(path).name)


def media(audio=("eng",), height=1080, vcodec="h264"):
    return {"width": 1920, "height": height, "vcodec": vcodec, "bit_depth": 8, "duration": 1.0,
            "audio": [{"lang": a, "codec": "aac"} for a in audio], "subs": []}


def make(root, rel, size=10):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"x" * size)
    return p


def test_plan_destination_layout(tmp_path):
    roots = library_roots(tmp_path)
    ep = {"kind": "episode", "title": "Reborn Rich", "year": 2022, "season": 1, "episodes": [1], "anime": False}
    mv = {"kind": "movie", "title": "Heat", "year": 1995}
    ab = {"kind": "episode", "title": "Spy x Family", "year": None, "season": None, "episodes": [], "anime": True}
    assert plan_destination(ep, Path("/x/e.mkv"), roots) == tmp_path / "media/tv/Reborn Rich (2022)/Season 01/e.mkv"
    assert plan_destination(mv, Path("/x/m.mkv"), roots) == tmp_path / "media/movies/Heat (1995)/m.mkv"
    assert plan_destination(ab, Path("/x/a.mkv"), roots) == tmp_path / "media/tv/Spy x Family/a.mkv"
    assert plan_destination({"kind": "unknown"}, Path("/x/u.mkv"), roots) is None
    assert plan_destination(dict(mv, title='AC/DC: "Live"'), Path("/x/m.mkv"), roots).parent.name == "ACDC Live (1995)"


def test_plan_destination_does_not_double_the_year_suffix(tmp_path):
    roots = library_roots(tmp_path)
    mv = {"kind": "movie", "title": "Heat (1995)", "year": 1995}
    assert plan_destination(mv, Path("/x/m.mkv"), roots) == tmp_path / "media/movies/Heat (1995)/m.mkv"


def test_plan_destination_uses_arr_host_path_when_present(tmp_path):
    roots = library_roots(tmp_path)
    series_folder = tmp_path / "arr-tv" / "Reborn Rich (2022)"
    ep = {"kind": "episode", "title": "Reborn Rich", "year": 2022, "season": 1, "episodes": [1],
          "host_path": str(series_folder)}
    assert plan_destination(ep, Path("/x/e.mkv"), roots) == series_folder / "Season 01" / "e.mkv"

    movie_folder = tmp_path / "arr-movies" / "Heat (1995)"
    mv = {"kind": "movie", "title": "Heat", "year": 1995, "host_path": str(movie_folder)}
    assert plan_destination(mv, Path("/x/m.mkv"), roots) == movie_folder / "m.mkv"


def test_scan_actions_duplicates_conflicts_and_summary(tmp_path):
    src, lib = tmp_path / "drive", tmp_path / "lib"
    make(src, "Heat (1995) 720p.mkv")
    make(src, "Heat.1995.1080p.mkv", size=20)
    make(src, "random_clip.mkv")
    make(src, "Show.S01E01.mkv")
    make(src, "Broken.S01E02.mkv")
    make(src, "notes.txt")
    make(lib, "media/tv/Show/Season 01/Show.S01E01.mkv")             # already in the library
    prober = FakeProber({
        "Heat (1995) 720p.mkv": media(height=720), "Heat.1995.1080p.mkv": media(height=1080),
        "random_clip.mkv": media(), "Show.S01E01.mkv": media(), "Broken.S01E02.mkv": None,
    })
    plan = scan(src, lib, prober, free_bytes=10**9)
    by = {Path(r["source"]).name: r for r in plan["rows"]}
    assert "notes.txt" not in by
    assert by["Heat.1995.1080p.mkv"]["action"] == "import"
    assert by["Heat (1995) 720p.mkv"]["action"] == "skip:duplicate"
    assert by["Heat (1995) 720p.mkv"]["duplicate_of"].endswith("Heat.1995.1080p.mkv")
    assert by["random_clip.mkv"]["action"] == "review"
    assert by["Show.S01E01.mkv"]["action"] == "skip:conflict"
    assert by["Broken.S01E02.mkv"]["probe"] == "failed" and by["Broken.S01E02.mkv"]["action"] == "review"
    assert by["Heat.1995.1080p.mkv"]["rule"] == "ok" and by["Heat.1995.1080p.mkv"]["direct_play"] == "universal"
    s = plan["summary"]
    assert s["files"] == 5 and s["actions"]["import"] == 1 and s["import_bytes"] == 20 and s["fits"]


def test_scan_reports_not_fitting(tmp_path):
    src = tmp_path / "drive"
    make(src, "Heat.1995.mkv", size=100)
    plan = scan(src, tmp_path / "lib", FakeProber({"Heat.1995.mkv": media()}), free_bytes=50)
    assert plan["summary"]["fits"] is False


def test_scan_anime_defaults_original_language_to_japanese(tmp_path):
    src = tmp_path / "drive"
    make(src, "[SubsPlease] Show - 01 (1080p).mkv")
    plan = scan(src, tmp_path / "lib", FakeProber({"[SubsPlease] Show - 01 (1080p).mkv": media(audio=("jpn",))}),
                free_bytes=10**9)
    assert plan["rows"][0]["rule"] == "breaks"                      # jpn audio, no English subs


def test_scan_uses_arr_confirm_and_roots(tmp_path):
    src = tmp_path / "drive"
    make(src, "spy.x.family.s01e11.mkv")

    class Arr:
        def roots(self):
            return {"tv": tmp_path / "arr-tv", "movies": tmp_path / "arr-movies"}

        def confirm(self, identity, filename):
            return dict(identity, title="SPY x FAMILY", year=2022, original_language="jpn", confidence="high")

    plan = scan(src, tmp_path / "lib", FakeProber({"spy.x.family.s01e11.mkv": media(audio=("jpn",))}),
                arr=Arr(), free_bytes=10**9)
    assert plan["rows"][0]["destination"] == str(tmp_path / "arr-tv/SPY x FAMILY (2022)/Season 01/spy.x.family.s01e11.mkv")


def test_plan_round_trip(tmp_path):
    p = tmp_path / "plans" / "a.json"
    write_plan({"version": 1, "rows": []}, p)
    assert load_plan(p) == {"version": 1, "rows": []}


def test_scan_arr_confirm_returns_partial_dict(tmp_path):
    src = tmp_path / "drive"
    make(src, "spy.x.family.s01e11.mkv")

    class PartialArr:
        def roots(self):
            return {"tv": tmp_path / "arr-tv", "movies": tmp_path / "arr-movies"}

        def confirm(self, identity, filename):
            return {"title": "SPY x FAMILY", "year": 2022}

    plan = scan(src, tmp_path / "lib", FakeProber({"spy.x.family.s01e11.mkv": media(audio=("jpn",))}),
                arr=PartialArr(), free_bytes=10**9)
    row = plan["rows"][0]
    assert row["identity"]["title"] == "SPY x FAMILY"
    assert row["identity"]["year"] == 2022
    assert row["destination"] is not None
    assert "arr-tv/SPY x FAMILY (2022)/Season 01/" in row["destination"]


def test_scan_skip_conflict_not_best_for_duplicates(tmp_path):
    """A conflict row (already in the library) beats ranking: every other row
    in its group is a duplicate of the library file, not of whichever
    source copy ranks best."""
    src, lib = tmp_path / "drive", tmp_path / "lib"
    make(src, "Show.S01E01.mkv", size=20)
    make(src, "Show.S01E01.720p.mkv", size=10)
    make(lib, "media/tv/Show/Season 01/Show.S01E01.mkv")
    prober = FakeProber({
        "Show.S01E01.mkv": media(height=1080),
        "Show.S01E01.720p.mkv": media(height=720),
    })
    plan = scan(src, lib, prober, free_bytes=10**9)
    by = {Path(r["source"]).name: r for r in plan["rows"]}
    assert by["Show.S01E01.mkv"]["action"] == "skip:conflict"
    assert by["Show.S01E01.720p.mkv"]["action"] == "skip:duplicate"
    assert by["Show.S01E01.720p.mkv"]["duplicate_of"] == by["Show.S01E01.mkv"]["destination"]


def test_scan_import_marked_duplicate_of_library_conflict(tmp_path):
    src, lib = tmp_path / "drive", tmp_path / "lib"
    make(src, "Heat.1995.1080p.mkv", size=20)                 # same name as library file -> conflict
    make(src, "Heat (1995) 720p.mkv", size=10)                 # different name -> would import
    make(lib, "media/movies/Heat (1995)/Heat.1995.1080p.mkv")
    prober = FakeProber({
        "Heat.1995.1080p.mkv": media(height=1080),
        "Heat (1995) 720p.mkv": media(height=720),
    })
    plan = scan(src, lib, prober, free_bytes=10**9)
    by = {Path(r["source"]).name: r for r in plan["rows"]}
    assert by["Heat.1995.1080p.mkv"]["action"] == "skip:conflict"
    assert by["Heat (1995) 720p.mkv"]["action"] == "skip:duplicate"
    assert by["Heat (1995) 720p.mkv"]["duplicate_of"] == by["Heat.1995.1080p.mkv"]["destination"]


def test_scan_skips_rsync_partial_files_and_hidden_paths(tmp_path):
    src = tmp_path / "from-home"
    make(src, "Heat.1995.1080p.mkv")
    make(src, "movies/.vulcan-partial/Big.Film.2020.mkv")
    make(src, ".hidden/Other.Film.2021.mkv")
    prober = FakeProber({"Heat.1995.1080p.mkv": media(), "Big.Film.2020.mkv": media(), "Other.Film.2021.mkv": media()})

    plan = scan(src, tmp_path / "lib", prober)

    assert [Path(r["source"]).name for r in plan["rows"]] == ["Heat.1995.1080p.mkv"]
