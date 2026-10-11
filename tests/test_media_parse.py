import pytest

from installer.media.parse import parse_name

CASES = [
    ("anime/Daemons of the Shadow Realm (2026)/Season 01/Daemons of the Shadow Realm (2026) - S01E02 - Right and Left "
     "[WEBDL-1080p Proper][x264][AAC 2.0]-Tsundere-Raws.mkv",
     dict(kind="episode", title="Daemons of the Shadow Realm", year=2026, season=1, episodes=[2], confidence="high")),
    ("spy.x.family.s01e11.dubbed.1080p.web.h264-skyanime.mkv",
     dict(kind="episode", title="spy x family", season=1, episodes=[11], confidence="high")),
    ("The.Rising.of.the.Shield.Hero.S02E011.1080p.Multi.Subs.AAC.x265-DLKING.mkv",
     dict(kind="episode", title="The Rising of the Shield Hero", season=2, episodes=[11])),
    ("Overlord S03E03 Enris Upheaval and Hectic Days 1080p CR WEB-DL DUAL DDP2 0 H 264-Kitsune.mkv",
     dict(kind="episode", title="Overlord", season=3, episodes=[3])),
    ("Reborn Rich (2022) - S01E01 - Soonyangs Loyal Servant [WEBDL-1080p][h264][AAC 2.0].mkv",
     dict(kind="episode", title="Reborn Rich", year=2022, season=1, episodes=[1])),
    ("Show.S01E01-E02.1080p.mkv", dict(kind="episode", title="Show", season=1, episodes=[1, 2])),
    ("Show.S01E01E02.mkv", dict(kind="episode", title="Show", season=1, episodes=[1, 2])),
    ("Show 2x05 Title.mkv", dict(kind="episode", title="Show", season=2, episodes=[5])),
    ("[SubsPlease] Spy x Family - 09 (1080p) [ABCD1234].mkv",
     dict(kind="episode", title="Spy x Family", absolute=9, season=None, anime=True, confidence="high")),
    ("DanMachi IV꞉ Shin Shou - Meikyuu-hen - 01 [BD 1080p x265 OPUS][Anipakku].mkv",
     dict(kind="episode", title="DanMachi IV꞉ Shin Shou - Meikyuu-hen", absolute=1, anime=True)),
    ("movies/Heat (1995)/Heat (1995) [imdbid-tt0113277] - Bluray-1080p [x264][AC3 2.0].mkv",
     dict(kind="movie", title="Heat", year=1995, confidence="high")),
    ("Heat.1995.1080p.BluRay.x264-GRP.mkv", dict(kind="movie", title="Heat", year=1995)),
    ("Blade Runner 2049 (2017).mkv", dict(kind="movie", title="Blade Runner 2049", year=2017)),
    ("tv/Some Show/Season 2/02.mkv", dict(kind="episode", title="Some Show", season=2, episodes=[2], confidence="low")),
    ("movies/Alien (1979)/movie.mkv", dict(kind="movie", title="Alien", year=1979, confidence="low")),
    ("Show.2019.S01E01.1080p.mkv", dict(kind="episode", title="Show", year=2019, season=1, episodes=[1], confidence="high")),
    ("Show (2019) - S01E01.mkv", dict(kind="episode", title="Show", year=2019, season=1, episodes=[1])),
    ("random_clip.mkv", dict(kind="unknown", confidence="unknown")),
]


@pytest.mark.parametrize("path,expected", CASES)
def test_parse_name_real_world_names(path, expected):
    result = parse_name(path)
    for key, value in expected.items():
        assert result[key] == value, (key, result)


def test_parse_name_always_returns_every_key():
    assert set(parse_name("random_clip.mkv")) == {
        "kind", "title", "year", "season", "episodes", "absolute", "anime", "confidence"}
