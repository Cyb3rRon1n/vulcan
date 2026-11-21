import json
import subprocess
from pathlib import Path

from installer.media.probe import Prober, english_text, norm_lang, sidecar_subtitles, summarize

FF = {
    "streams": [
        {"codec_type": "video", "codec_name": "hevc", "width": 1920, "height": 1080, "pix_fmt": "yuv420p10le"},
        {"codec_type": "video", "codec_name": "mjpeg", "disposition": {"attached_pic": 1}},
        {"codec_type": "audio", "codec_name": "eac3", "tags": {"language": "fre"}},
        {"codec_type": "audio", "codec_name": "aac", "tags": {"language": "ja"}},
        {"codec_type": "subtitle", "codec_name": "hdmv_pgs_subtitle", "tags": {"language": "fre"}},
        {"codec_type": "subtitle", "codec_name": "subrip"},
    ],
    "format": {"duration": "1420.5"},
}

ENGLISH = "\n".join(["1", "00:00:01,000 --> 00:00:02,000", "What is this? You and the others, it is time to go."] * 20)
RUSSIAN = "\n".join(["1", "00:00:01,000 --> 00:00:02,000", "В 20XX году я уже служила Проповеднику."] * 20)


def test_norm_lang():
    assert norm_lang("ja") == "jpn"
    assert norm_lang("ENG") == "eng"
    assert norm_lang(None) == "und"
    assert norm_lang("fra") == "fre"


def test_summarize_reads_tracks_and_skips_cover_art():
    s = summarize(FF)
    assert (s["width"], s["height"], s["vcodec"], s["bit_depth"]) == (1920, 1080, "hevc", 10)
    assert s["audio"] == [{"lang": "fre", "codec": "eac3"}, {"lang": "jpn", "codec": "aac"}]
    assert s["subs"] == [{"lang": "fre", "codec": "hdmv_pgs_subtitle"}, {"lang": "und", "codec": "subrip"}]
    assert s["duration"] == 1420.5


def test_sidecar_languages_from_tags_and_text(tmp_path):
    video = tmp_path / "Show - S01E01.mkv"
    video.write_bytes(b"")
    (tmp_path / "Show - S01E01.en.srt").write_text("x")
    (tmp_path / "Show - S01E01.es.srt").write_text("x")
    (tmp_path / "Show - S01E01.hi.srt").write_text(RUSSIAN)          # .hi that is not English
    (tmp_path / "Show - S01E01.ass").write_text(ENGLISH)             # untagged drama-style sidecar
    (tmp_path / "Show - S01E010.en.srt").write_text("x")             # different episode, must not match
    (tmp_path / "Other.en.srt").write_text("x")                      # different video
    langs = {Path(s["path"]).name: s["lang"] for s in sidecar_subtitles(video)}
    assert langs == {"Show - S01E01.en.srt": "eng", "Show - S01E01.es.srt": "spa",
                     "Show - S01E01.hi.srt": "und", "Show - S01E01.ass": "eng"}


def test_english_text(tmp_path):
    e, r = tmp_path / "e.srt", tmp_path / "r.srt"
    e.write_text(ENGLISH)
    r.write_text(RUSSIAN)
    assert english_text(e) and not english_text(r)


def test_prober_host_ffprobe_and_cache(tmp_path):
    video = tmp_path / "a.mkv"
    video.write_bytes(b"x")
    calls = []

    def run(cmd, **kw):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(FF), stderr="")

    cache = tmp_path / "cache.json"
    with Prober(tmp_path, cache_path=cache, run=run, host_ffprobe="/usr/bin/ffprobe") as p:
        assert p.probe(video)["vcodec"] == "hevc"
        p.probe(video)
    assert len(calls) == 1 and calls[0][0] == "/usr/bin/ffprobe"
    with Prober(tmp_path, cache_path=cache, run=run, host_ffprobe="/usr/bin/ffprobe") as p:
        p.probe(video)
    assert len(calls) == 1                                           # served from the saved cache


def test_prober_uses_one_jellyfin_container_without_host_ffprobe(tmp_path):
    (tmp_path / "sub").mkdir()
    video = tmp_path / "sub" / "a.mkv"
    video.write_bytes(b"x")
    calls = []

    def run(cmd, **kw):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(FF) if "exec" in cmd else "", stderr="")

    with Prober(tmp_path, run=run, host_ffprobe="") as p:
        p.probe(video)
    assert calls[0][:3] == ["docker", "run", "-d"] and f"{tmp_path.resolve()}:/in:ro" in calls[0]
    assert calls[1][:2] == ["docker", "exec"] and calls[1][-1] == "/in/sub/a.mkv"
    assert calls[2][:3] == ["docker", "rm", "-f"]


def test_prober_returns_none_for_symlink_resolving_outside_root(tmp_path):
    """Docker mode maps a path inside root to the container; a symlink that resolves outside
    root can't be mapped (relative_to raises ValueError) - that's a probe failure, not a crash."""
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "elsewhere.mkv"
    outside.write_bytes(b"x")
    link = root / "a.mkv"
    link.symlink_to(outside)

    run = lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(FF), stderr="")
    with Prober(root, run=run, host_ffprobe="") as p:
        assert p.probe(link) is None


def test_prober_returns_none_on_ffprobe_failure(tmp_path):
    video = tmp_path / "a.mkv"
    video.write_bytes(b"x")
    run = lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, stdout="", stderr="bad")
    with Prober(tmp_path, run=run, host_ffprobe="/usr/bin/ffprobe") as p:
        assert p.probe(video) is None


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
