# Media Assistant Implementation Plan

**Goal:** Add `vulcan media scan / import / register` (+ a whiptail menu entry) that identifies existing media files on any drive, plans and safely copies them into the library, and registers them with Sonarr/Radarr when online.

**Architecture:** A new engine package `installer/media/` of pure functions returning plain dicts (never prompting), split by responsibility: `parse.py` (offline name parser), `probe.py` (ffprobe + sidecar subtitles), `classify.py` (language rule + direct play), `plan.py` (scan → plan JSON), `transfer.py` (rsync copy + verify), `arr.py` (Sonarr/Radarr confirm + register + pending list). `installer/cli.py` gets a thin `media_app` Typer group; `installer/menu.sh` gets a `media_flow`.

**Tech Stack:** Python 3.11+ stdlib (urllib, hashlib, subprocess, json, re), Typer + Rich (already deps), rsync (host), ffprobe (host or the stack's `lscr.io/linuxserver/jellyfin` image), pytest, bats.

**Spec:** `specs/2026-10-11-media-assistant-design.md`

**Ruling (plan vs spec):** the spec names a single `installer/media.py`; this plan splits it into an `installer/media/` package so each file has one job. The public function names in the spec (`parse_name`, `probe_file`→`Prober.probe`, `scan`, `plan_destination`, `import_plan`, `register_pending`) are kept. Cost if wrong: a file move.

## Global Constraints

- No new Python dependencies (pyproject `dependencies` stays typer, rich, psutil, jinja2, pyyaml).
- Engine modules never prompt, never print, never call `sys.exit`; they return plain dicts/lists. All console output lives in `installer/cli.py`.
- Scan never writes anything except its plan file and the probe cache under `stack/media-plans/`.
- Import never overwrites or deletes anything already in the library; `--move` deletes a source only after its copy verified.
- Copies land as `<dest>.vulcan-partial` and are renamed into place only after verification.
- Language rule: `ok` if any audio is English, or original-language audio + an English subtitle (embedded or sidecar). Extra dub tracks don't matter. Unknown original language reports `ok` with a note, never a false `breaks`.
- Direct play = H.264 8-bit video + AAC/AC3/EAC3/MP3 audio + only text subtitles.
- Inside the stack, Sonarr/Radarr see `${MEDIA_PATH}` as `/data` (compose: `${MEDIA_PATH}:/data`).
- Code style: match the surrounding file; ruff is pyflakes-only (`ruff check .` must pass).
- Tests run from an isolated empty cwd (autouse fixture in `tests/conftest.py`) — always use `tmp_path`, never the repo's `stack/`.

## File structure

| File | Responsibility |
|---|---|
| `installer/media/__init__.py` | package marker + re-exports |
| `installer/media/parse.py` | `parse_name(path) -> dict`, `VIDEO_EXTENSIONS` |
| `installer/media/probe.py` | `summarize()`, `sidecar_subtitles()`, `english_text()`, `norm_lang()`, `Prober` |
| `installer/media/classify.py` | `rule_status()`, `direct_play()` |
| `installer/media/plan.py` | `PLANS_DIR`, `library_roots()`, `plan_destination()`, `scan()`, `write_plan()`, `load_plan()` |
| `installer/media/transfer.py` | `verify_copy()`, `import_plan()` |
| `installer/media/arr.py` | `Arr`, `ArrClients`, `connect_arrs()`, `add_pending()`, `register_pending()`, `PENDING_FILE` |
| `installer/cli.py` | `media_app`: `scan`, `import`, `register` |
| `installer/menu.sh` | `media_flow`, main-menu item |
| `tests/test_media_parse.py` … `tests/test_media_cli.py` | unit tests per module |
| `tests/test_menu.bats` | media_flow tests |
| `docs/guides/media-assistant.md`, `mkdocs.yml`, `ROADMAP.md`, `CHANGELOG.md`, `README.md` | user docs |

---

### Task 1: Offline name parser

**Files:**
- Create: `installer/media/__init__.py`, `installer/media/parse.py`
- Test: `tests/test_media_parse.py`

**Interfaces:**
- Produces: `parse_name(path: str) -> dict` with keys `kind` (`"episode"|"movie"|"unknown"`), `title` (str|None), `year` (int|None), `season` (int|None), `episodes` (list[int]), `absolute` (int|None), `anime` (bool), `confidence` (`"high"|"low"|"unknown"`). `VIDEO_EXTENSIONS: set[str]`.

- [ ] **Step 1: Write the failing tests** (real cyberpac file names)

```python
# tests/test_media_parse.py
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
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_media_parse.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'installer.media'`

- [ ] **Step 3: Implement**

```python
# installer/media/__init__.py
"""Media assistant: scan existing media, plan, import into the library, register with Sonarr/Radarr."""
```

```python
# installer/media/parse.py
"""
Offline media-name parser for `vulcan media scan`. Turns a file path into a
movie/episode identity plus a confidence level; when the stack is online,
installer/media/arr.py confirms or corrects it with Sonarr/Radarr's own parser.
"""

import re
from pathlib import PurePath

VIDEO_EXTENSIONS = {".mkv", ".mp4", ".m4v", ".avi", ".ts", ".webm"}

_SE = re.compile(r"(?<![a-z0-9])s(\d{1,2})[ ._-]?e(\d{1,3})((?:[ ._-]?-?[ ._-]?e\d{1,3})*)", re.I)
_NX = re.compile(r"(?<![0-9])(\d{1,2})x(\d{2,3})(?![0-9])")
_ABS = re.compile(r" - (\d{1,4})(?:v\d)?(?= |\[|\(|$)")
_YEAR = re.compile(r"(?:^|[ .(\[_-])((?:19|20)\d{2})(?=$|[ .)\]_-])")
_TRAILING_YEAR = re.compile(r"\(?((?:19|20)\d{2})\)?\s*-?\s*$")
_BRACKETS = re.compile(r"\[[^\]]*\]|\{[^}]*\}")
_SEASON_DIR = re.compile(r"(?:season[ ._]?|s)(\d{1,2})", re.I)


def _clean(text):
    """Title text before an anchor -> (title or None, year or None)."""

    s = _BRACKETS.sub(" ", text)
    s = re.sub(r"[._]", " ", s)
    year = None
    m = _TRAILING_YEAR.search(s)
    if m and m.start() > 0:
        year, s = int(m.group(1)), s[:m.start()]
    s = re.sub(r"\s+", " ", s).strip(" -")
    return (s or None), year


def _identity(kind, title=None, year=None, season=None, episodes=None, absolute=None, anime=False, confidence="unknown"):

    return {"kind": kind, "title": title, "year": year, "season": season, "episodes": episodes or [],
            "absolute": absolute, "anime": anime, "confidence": confidence}


def parse_name(path):
    p = PurePath(path)
    stem = p.stem
    parents = list(p.parts[:-1])
    season_match = _SEASON_DIR.fullmatch(parents[-1]) if parents else None
    season_dir = int(season_match.group(1)) if season_match else None
    show_dir = parents[-2] if season_match and len(parents) >= 2 else (parents[-1] if parents else "")
    anime = bool(re.match(r"\s*\[[^\]]+\]", stem))

    m = _SE.search(stem)
    if m:
        first = int(m.group(2))
        extra = [int(x) for x in re.findall(r"e(\d{1,3})", m.group(3), re.I)]
        episodes = [first] + extra
        if len(episodes) == 2 and "-" in m.group(3) and episodes[1] > first + 1:
            episodes = list(range(first, episodes[1] + 1))
        title, year = _clean(stem[:m.start()])
        if not title:
            title, year = _clean(show_dir)
            return _identity("episode", title, year, int(m.group(1)), episodes, None, anime, "low" if title else "unknown")
        return _identity("episode", title, year, int(m.group(1)), episodes, None, anime, "high")

    m = _NX.search(stem)
    if m:
        title, year = _clean(stem[:m.start()])
        return _identity("episode", title, year, int(m.group(1)), [int(m.group(2))], None, anime,
                         "high" if title else "unknown")

    spaced = stem.replace("_", " ")
    matches = [x for x in _ABS.finditer(spaced) if not re.fullmatch(r"(?:19|20)\d{2}", x.group(1))]
    if matches:
        m = matches[-1]
        title, year = _clean(spaced[:m.start()])
        if not title:
            title, year = _clean(show_dir)
        return _identity("episode", title, year, season_dir, [], int(m.group(1)), True,
                         "high" if title else "unknown")

    years = [x for x in _YEAR.finditer(stem) if x.start() > 0]
    if years:
        m = years[-1]
        title, _ = _clean(stem[:m.start()])          # start of the whole match drops the "(" / "." too
        if title:
            return _identity("movie", title, int(m.group(1)), confidence="high")

    if season_dir is not None and re.fullmatch(r"\d{1,3}", stem.strip()):
        title, year = _clean(show_dir)
        return _identity("episode", title, year, season_dir, [int(stem)], None, anime, "low" if title else "unknown")

    if parents:
        title, year = _clean(parents[-1])
        if title and year:
            return _identity("movie", title, year, confidence="low")

    return _identity("unknown")
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_media_parse.py -q && ruff check installer/media`
Expected: all PASS, ruff clean. If a case fails, fix the regex, not the expectation — the cases are real file names from a live library.

- [ ] **Step 5: Commit**

```bash
git add installer/media/__init__.py installer/media/parse.py tests/test_media_parse.py
git commit -m "feat(media): offline media-name parser"
```

---

### Task 2: Probing — ffprobe summary, sidecar subtitles, Prober

**Files:**
- Create: `installer/media/probe.py`
- Test: `tests/test_media_probe.py`

**Interfaces:**
- Produces:
  - `norm_lang(code: str|None) -> str` (3-letter, `"und"` when missing)
  - `summarize(ffprobe_json: dict) -> dict` with `width, height, vcodec, bit_depth, audio: [{"lang","codec"}], subs: [{"lang","codec"}], duration`
  - `english_text(path: Path) -> bool`
  - `sidecar_subtitles(video: Path) -> list[{"path": str, "lang": str}]`
  - `class Prober(root, cache_path=None, run=subprocess.run, host_ffprobe=None)`: context manager; `.probe(path) -> dict|None` (summarize() output; None on failure)
  - constants `JELLYFIN_IMAGE = "lscr.io/linuxserver/jellyfin:latest"`, `CONTAINER_FFPROBE = "/usr/lib/jellyfin-ffmpeg/ffprobe"`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_media_probe.py
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


def test_prober_returns_none_on_ffprobe_failure(tmp_path):
    video = tmp_path / "a.mkv"
    video.write_bytes(b"x")
    run = lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, stdout="", stderr="bad")
    with Prober(tmp_path, run=run, host_ffprobe="/usr/bin/ffprobe") as p:
        assert p.probe(video) is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_media_probe.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'installer.media.probe'`

- [ ] **Step 3: Implement**

```python
# installer/media/probe.py
"""
Reads what is inside a video for `vulcan media scan`: resolution, codecs,
audio/subtitle languages, plus sidecar subtitle files and their language.
ffprobe comes from the host when installed, else from the stack's own
Jellyfin image (one long-lived container per scan, `docker exec` per file),
so nothing new is installed.
"""

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

JELLYFIN_IMAGE = "lscr.io/linuxserver/jellyfin:latest"
CONTAINER_FFPROBE = "/usr/lib/jellyfin-ffmpeg/ffprobe"
FFPROBE_ARGS = ["-v", "error", "-show_streams", "-show_format", "-of", "json"]
SUB_EXTENSIONS = {".srt", ".ass", ".ssa", ".vtt", ".sub"}

_LANG = {"en": "eng", "ja": "jpn", "fr": "fre", "fra": "fre", "de": "ger", "deu": "ger", "es": "spa",
         "it": "ita", "pt": "por", "ru": "rus", "zh": "chi", "zho": "chi", "ko": "kor", "hi": "hin",
         "ar": "ara", "nl": "dut", "nld": "dut", "pl": "pol", "sv": "swe", "th": "tha", "vi": "vie"}
_ENGLISH_TAGS = {"en", "eng", "english", "sdh"}
_STOPWORDS = re.compile(r"\b(the|you|and|what|this|is|it|to)\b", re.I)


def norm_lang(code):
    c = (code or "und").strip().lower()
    return _LANG.get(c, c)


def summarize(ff):
    streams = ff.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"
                  and not (s.get("disposition") or {}).get("attached_pic")), {})
    lang = lambda s: norm_lang((s.get("tags") or {}).get("language"))
    pix = video.get("pix_fmt") or ""

    return {
        "width": video.get("width"),
        "height": video.get("height"),
        "vcodec": video.get("codec_name"),
        "bit_depth": 10 if ("10" in pix or "12" in pix) else 8,
        "audio": [{"lang": lang(s), "codec": s.get("codec_name")} for s in streams if s.get("codec_type") == "audio"],
        "subs": [{"lang": lang(s), "codec": s.get("codec_name")} for s in streams if s.get("codec_type") == "subtitle"],
        "duration": float((ff.get("format") or {}).get("duration") or 0),
    }


def english_text(path):
    """An untagged or ambiguous (.hi) subtitle file is English if its text reads as English."""

    try:
        text = Path(path).read_text(encoding="utf-8", errors="ignore")[:40000]
    except OSError:
        return False
    return len(_STOPWORDS.findall(text)) > 40


def sidecar_subtitles(video):
    video = Path(video)
    try:
        siblings = list(video.parent.iterdir())
    except OSError:
        return []

    found = []
    for f in siblings:
        if f.suffix.lower() not in SUB_EXTENSIONS or not f.name.startswith(video.stem):
            continue
        tags = [t.lower() for t in f.name[len(video.stem):-len(f.suffix)].split(".") if t]
        if any(t in _ENGLISH_TAGS for t in tags):
            lang = "eng"
        else:
            # "hi" is Hindi in ISO 639-1 but Bazarr's hearing-impaired suffix - decide by reading it
            known = [norm_lang(t) for t in tags if len(t) in (2, 3) and t != "hi"]
            lang = known[0] if known else ("eng" if english_text(f) else "und")
        found.append({"path": str(f), "lang": lang})

    return sorted(found, key=lambda s: s["path"])


class Prober:

    def __init__(self, root, cache_path=None, run=subprocess.run, host_ffprobe=None):
        self.root = Path(root).resolve()
        self.run = run
        self.host = shutil.which("ffprobe") if host_ffprobe is None else host_ffprobe
        self.container = None
        self.cache_path = Path(cache_path) if cache_path else None
        self.cache = {}
        if self.cache_path and self.cache_path.exists():
            try:
                self.cache = json.loads(self.cache_path.read_text())
            except ValueError:
                self.cache = {}

    def __enter__(self):
        if not self.host:
            self.container = f"vulcan-media-probe-{os.getpid()}"
            self.run(["docker", "run", "-d", "--rm", "--name", self.container, "-v", f"{self.root}:/in:ro",
                      "--entrypoint", "sleep", JELLYFIN_IMAGE, "infinity"],
                     capture_output=True, text=True, check=True)
        return self

    def __exit__(self, *exc):
        if self.container:
            self.run(["docker", "rm", "-f", self.container], capture_output=True, text=True)
        if self.cache_path:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(json.dumps(self.cache))

    def probe(self, path):
        path = Path(path).resolve()
        st = path.stat()
        key = f"{path}|{st.st_size}|{st.st_mtime_ns}"
        if key in self.cache:
            return self.cache[key]

        if self.host:
            cmd = [self.host, *FFPROBE_ARGS, str(path)]
        else:
            cmd = ["docker", "exec", self.container, CONTAINER_FFPROBE, *FFPROBE_ARGS,
                   "/in/" + str(path.relative_to(self.root))]

        result = self.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            return None
        try:
            info = summarize(json.loads(result.stdout))
        except ValueError:
            return None

        self.cache[key] = info
        return info
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_media_probe.py -q && ruff check installer/media`
Expected: PASS, ruff clean.

- [ ] **Step 5: Commit**

```bash
git add installer/media/probe.py tests/test_media_probe.py
git commit -m "feat(media): ffprobe summary, sidecar subtitle languages, Prober"
```

---

### Task 3: Classification — language rule and direct play

**Files:**
- Create: `installer/media/classify.py`
- Test: `tests/test_media_classify.py`

**Interfaces:**
- Consumes: `summarize()` output (Task 2), `sidecar_subtitles()` output (Task 2).
- Produces: `rule_status(info: dict, sidecars: list[dict], original_language: str|None) -> tuple[str, str]` (`("ok"|"breaks", note)`); `direct_play(info: dict) -> tuple[bool, list[str]]`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_media_classify.py
from installer.media.classify import direct_play, rule_status


def info(audio, subs=(), vcodec="h264", bit_depth=8):
    return {"vcodec": vcodec, "bit_depth": bit_depth,
            "audio": [{"lang": a, "codec": c} for a, c in audio],
            "subs": [{"lang": s, "codec": c} for s, c in subs]}


def test_english_audio_is_always_ok():
    assert rule_status(info([("eng", "aac")]), [], "jpn")[0] == "ok"


def test_original_audio_plus_sidecar_english_is_ok_even_with_extra_dub():
    i = info([("fre", "aac"), ("jpn", "aac")], [("fre", "subrip")])
    assert rule_status(i, [{"path": "x.en.srt", "lang": "eng"}], "jpn")[0] == "ok"


def test_original_audio_without_english_subs_breaks():
    status, note = rule_status(info([("jpn", "aac")], [("spa", "subrip")]), [], "jpn")
    assert status == "breaks" and "no English subtitles" in note


def test_foreign_dub_only_breaks():
    assert rule_status(info([("ita", "aac")], [("eng", "subrip")]), [], "jpn")[0] == "breaks"


def test_unknown_original_language_is_ok_with_note():
    status, note = rule_status(info([("kor", "aac")]), [], None)
    assert status == "ok" and "unknown" in note


def test_direct_play_universal():
    assert direct_play(info([("eng", "aac")], [("eng", "subrip")])) == (True, [])


def test_direct_play_reasons():
    ok, reasons = direct_play(info([("eng", "truehd"), ("jpn", None)], [("eng", "hdmv_pgs_subtitle")],
                                   vcodec="hevc", bit_depth=10))
    assert not ok
    assert reasons == ["video hevc", "audio truehd/unknown", "picture subtitles hdmv_pgs_subtitle"]


def test_direct_play_flags_10bit_h264():
    assert direct_play(info([("eng", "aac")], bit_depth=10)) == (False, ["10-bit video"])
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_media_classify.py -q`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement**

```python
# installer/media/classify.py
"""
Per-file verdicts for `vulcan media scan`:
- language rule: English audio, else original-language audio + English subtitles
  (embedded or sidecar). Extra dub tracks don't matter.
- direct play: will most devices play it without the server converting it?
"""

DIRECT_VIDEO = {"h264"}
DIRECT_AUDIO = {"aac", "ac3", "eac3", "mp3"}
TEXT_SUBS = {"subrip", "ass", "ssa", "mov_text", "webvtt", "text"}


def rule_status(info, sidecars, original_language):
    audio = {a["lang"] for a in info["audio"]}
    if "eng" in audio:
        return "ok", "English audio"
    if not original_language:
        return "ok", "original language unknown - not checked"
    subs = {s["lang"] for s in info["subs"]} | {s["lang"] for s in sidecars}
    if original_language not in audio:
        return "breaks", f"no English or original ({original_language}) audio"
    if "eng" not in subs:
        return "breaks", "original audio but no English subtitles"
    return "ok", "original audio + English subtitles"


def direct_play(info):
    reasons = []
    if info["vcodec"] not in DIRECT_VIDEO:
        reasons.append(f"video {info['vcodec']}")
    elif info["bit_depth"] != 8:
        reasons.append(f"{info['bit_depth']}-bit video")
    bad_audio = sorted({a["codec"] or "unknown" for a in info["audio"]} - DIRECT_AUDIO)
    if bad_audio:
        reasons.append("audio " + "/".join(bad_audio))
    bad_subs = sorted({s["codec"] or "unknown" for s in info["subs"]} - TEXT_SUBS)
    if bad_subs:
        reasons.append("picture subtitles " + "/".join(bad_subs))
    return not reasons, reasons
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_media_classify.py -q && ruff check installer/media`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add installer/media/classify.py tests/test_media_classify.py
git commit -m "feat(media): language-rule and direct-play classification"
```

---

### Task 4: Scan → plan

**Files:**
- Create: `installer/media/plan.py`
- Test: `tests/test_media_plan.py`

**Interfaces:**
- Consumes: `parse_name`, `VIDEO_EXTENSIONS` (Task 1); `Prober.probe`, `sidecar_subtitles` (Task 2); `rule_status`, `direct_play` (Task 3). An optional `arr` object with `.roots() -> dict[str, Path]` and `.confirm(identity: dict, filename: str) -> dict` (implemented in Task 6 as `ArrClients`).
- Produces:
  - `PLANS_DIR: Path` (= `STACK_DIR / "media-plans"`)
  - `library_roots(media_path: Path, arr_roots: dict|None) -> dict` with keys `tv`, `movies`, optional `anime`
  - `plan_destination(identity: dict, source: Path, roots: dict) -> Path|None`
  - `scan(source: Path, media_path: Path, prober, arr=None, free_bytes: int|None=None) -> dict` plan:
    `{"version": 1, "created", "source", "media_path", "rows": [...], "summary": {...}}`; each row:
    `source, size, identity, sidecars (list[str]), probe (dict|"failed"), rule, rule_note, direct_play ("universal"|"may convert"), direct_play_reasons, destination (str|None), action, duplicate_of (only on duplicates)`;
    summary: `files, actions (dict action->count), import_bytes, free_bytes, fits (bool), rule_breaks, may_convert, review`
  - `write_plan(plan: dict, path: Path) -> None`, `load_plan(path: Path) -> dict`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_media_plan.py
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
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_media_plan.py -q`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement**

```python
# installer/media/plan.py
"""
`vulcan media scan`: walk a folder or drive, identify and inspect every video,
and write a plan - what each file is, where it would go, and whether it will
be imported, skipped (duplicate / already in the library) or needs review.
Read-only apart from the plan file itself.
"""

import datetime as dt
import json
import re
import shutil
from collections import Counter
from pathlib import Path

from installer.generate import STACK_DIR
from installer.media.classify import direct_play, rule_status
from installer.media.parse import VIDEO_EXTENSIONS, parse_name
from installer.media.probe import sidecar_subtitles

PLANS_DIR = STACK_DIR / "media-plans"


def library_roots(media_path, arr_roots=None):
    roots = {"tv": Path(media_path) / "media" / "tv", "movies": Path(media_path) / "media" / "movies"}
    roots.update(arr_roots or {})
    return roots


def _safe(name):
    return re.sub(r'[<>:"/\\|?*]', "", name).strip()


def plan_destination(identity, source, roots):
    if identity.get("kind") not in ("movie", "episode") or not identity.get("title"):
        return None
    folder = _safe(f"{identity['title']} ({identity['year']})" if identity.get("year") else identity["title"])
    if identity["kind"] == "movie":
        return roots["movies"] / folder / source.name
    base = roots["anime"] if identity.get("anime") and "anime" in roots else roots["tv"]
    if identity.get("season") is not None:
        return base / folder / f"Season {identity['season']:02d}" / source.name
    return base / folder / source.name


def _dup_key(identity):
    return (identity["kind"], (identity["title"] or "").lower(), identity["year"] if identity["kind"] == "movie" else None,
            identity.get("season"), tuple(identity.get("episodes") or []), identity.get("absolute"))


def _rank(row):
    probe = row["probe"]
    return (probe.get("height") or 0, any(a["lang"] == "eng" for a in probe["audio"]), row["size"])


def _existing(path):
    path = Path(path)
    while not path.exists() and path != path.parent:
        path = path.parent
    return path


def scan(source, media_path, prober, arr=None, free_bytes=None):
    source = Path(source).resolve()
    if source.is_file():
        files = [source]
    else:
        files = sorted(p for p in source.rglob("*") if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS)
    roots = library_roots(media_path, arr.roots() if arr else None)

    rows = []
    for f in files:
        identity = parse_name(str(f))
        if arr:
            identity = arr.confirm(identity, f.name)
        info = prober.probe(f)
        sidecars = sidecar_subtitles(f)
        original = identity.get("original_language") or ("jpn" if identity.get("anime") else None)
        row = {"source": str(f), "size": f.stat().st_size, "identity": identity,
               "sidecars": [s["path"] for s in sidecars], "probe": info or "failed"}
        if info:
            row["rule"], row["rule_note"] = rule_status(info, sidecars, original)
            ok, reasons = direct_play(info)
            row["direct_play"], row["direct_play_reasons"] = ("universal" if ok else "may convert"), reasons
        dest = plan_destination(identity, f, roots)
        row["destination"] = str(dest) if dest else None
        if dest and dest.exists():
            row["action"] = "skip:conflict"
        elif info and dest and identity["confidence"] == "high":
            row["action"] = "import"
        else:
            row["action"] = "review"
        rows.append(row)

    groups = {}
    for r in rows:
        if r["identity"]["kind"] != "unknown" and r["probe"] != "failed":
            groups.setdefault(_dup_key(r["identity"]), []).append(r)
    for group in groups.values():
        if len(group) > 1:
            best = max(group, key=_rank)
            for r in group:
                if r is not best and r["action"] in ("import", "review"):
                    r["action"], r["duplicate_of"] = "skip:duplicate", best["source"]

    import_bytes = sum(r["size"] for r in rows if r["action"] == "import")
    free = free_bytes if free_bytes is not None else shutil.disk_usage(_existing(media_path)).free
    summary = {
        "files": len(rows),
        "actions": dict(Counter(r["action"] for r in rows)),
        "import_bytes": import_bytes,
        "free_bytes": free,
        "fits": import_bytes <= free,
        "rule_breaks": sum(r.get("rule") == "breaks" for r in rows),
        "may_convert": sum(r.get("direct_play") == "may convert" for r in rows),
        "review": sum(r["action"] == "review" for r in rows),
    }
    return {"version": 1, "created": dt.datetime.now().isoformat(timespec="seconds"), "source": str(source),
            "media_path": str(media_path), "rows": rows, "summary": summary}


def write_plan(plan, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(plan, indent=1))
    tmp.replace(path)


def load_plan(path):
    return json.loads(Path(path).read_text())
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_media_plan.py -q && ruff check installer/media`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add installer/media/plan.py tests/test_media_plan.py
git commit -m "feat(media): scan a source into an import plan"
```

---

### Task 5: Import — copy, verify, resume, move

**Files:**
- Create: `installer/media/transfer.py`
- Test: `tests/test_media_transfer.py`

**Interfaces:**
- Consumes: plan dict from Task 4 (rows with `source`, `size`, `sidecars`, `destination`, `action`).
- Produces:
  - `verify_copy(src: Path, dst: Path, mode: str = "quick") -> bool`
  - `import_plan(plan: dict, *, move=False, verify="quick", include_review=False, save=None, on_row=None, run=subprocess.run) -> dict` → `{"imported": [row], "failed": [row], "skipped": [row], "stopped": str|None}`; mutates rows: `done: True`, `result: "imported" | "skip:conflict" | "failed: <why>"`. `save(plan)` is called after every row (resume); `on_row(row)` for progress.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_media_transfer.py
import shutil
import subprocess
from pathlib import Path

from installer.media.transfer import import_plan, verify_copy


def fake_rsync(cmd, **kw):
    """Stand-in for `rsync ... SRC DST`: plain copy (tests don't depend on rsync being installed)."""
    shutil.copyfile(cmd[-2], cmd[-1])
    return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")


def row(src, dest, action="import", sidecars=()):
    return {"source": str(src), "size": src.stat().st_size, "sidecars": [str(s) for s in sidecars],
            "destination": str(dest), "action": action}


def setup(tmp_path, data=b"video-bytes"):
    src = tmp_path / "drive" / "Heat.1995.mkv"
    src.parent.mkdir(parents=True)
    src.write_bytes(data)
    sub = tmp_path / "drive" / "Heat.1995.en.srt"
    sub.write_text("subs")
    dest = tmp_path / "lib" / "media" / "movies" / "Heat (1995)" / "Heat.1995.mkv"
    return src, sub, dest


def test_verify_copy_quick_and_full(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.write_bytes(b"x" * (20 * 1024 * 1024))
    b.write_bytes(b"x" * (20 * 1024 * 1024))
    assert verify_copy(a, b) and verify_copy(a, b, "full")
    b.write_bytes(b"x" * (10 * 1024 * 1024) + b"y" + b"x" * (10 * 1024 * 1024 - 1))   # middle differs
    assert verify_copy(a, b, "quick") and not verify_copy(a, b, "full")
    b.write_bytes(b"short")
    assert not verify_copy(a, b)


def test_import_copies_video_and_sidecar_and_keeps_source(tmp_path):
    src, sub, dest = setup(tmp_path)
    plan = {"rows": [row(src, dest, sidecars=[sub])]}
    saved = []
    result = import_plan(plan, run=fake_rsync, save=lambda p: saved.append(True))
    assert dest.read_bytes() == b"video-bytes" and (dest.parent / "Heat.1995.en.srt").read_text() == "subs"
    assert src.exists() and not list(dest.parent.glob("*.vulcan-partial"))
    assert plan["rows"][0]["done"] and plan["rows"][0]["result"] == "imported"
    assert len(result["imported"]) == 1 and saved


def test_import_skips_non_import_rows_unless_review_included(tmp_path):
    src, _, dest = setup(tmp_path)
    plan = {"rows": [row(src, dest, action="review")]}
    assert import_plan(plan, run=fake_rsync)["imported"] == []
    assert len(import_plan(plan, run=fake_rsync, include_review=True)["imported"]) == 1


def test_import_never_overwrites_existing(tmp_path):
    src, _, dest = setup(tmp_path)
    dest.parent.mkdir(parents=True)
    dest.write_bytes(b"keep me")
    plan = {"rows": [row(src, dest)]}
    result = import_plan(plan, run=fake_rsync)
    assert dest.read_bytes() == b"keep me" and plan["rows"][0]["result"] == "skip:conflict" and result["skipped"]


def test_move_deletes_source_only_after_verify(tmp_path):
    src, sub, dest = setup(tmp_path)

    def corrupting_rsync(cmd, **kw):
        Path(cmd[-1]).write_bytes(b"corrupt")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    plan = {"rows": [row(src, dest, sidecars=[sub])]}
    result = import_plan(plan, move=True, run=corrupting_rsync)
    assert src.exists() and not dest.exists() and result["failed"]
    assert not list(dest.parent.glob("*.vulcan-partial"))
    plan = {"rows": [row(src, dest, sidecars=[sub])]}
    import_plan(plan, move=True, run=fake_rsync)
    assert dest.exists() and not src.exists() and not sub.exists()


def test_resume_skips_done_rows_and_missing_source_fails_softly(tmp_path):
    src, _, dest = setup(tmp_path)
    gone = row(src, tmp_path / "lib" / "x.mkv")
    gone["source"] = str(tmp_path / "drive" / "vanished.mkv")
    plan = {"rows": [dict(row(src, dest), done=True, result="imported"), gone]}
    result = import_plan(plan, run=fake_rsync)
    assert not dest.exists()                                         # done row not redone
    assert plan["rows"][1]["result"].startswith("failed: source missing") and result["failed"]


def test_rsync_failure_is_a_failed_row(tmp_path):
    src, _, dest = setup(tmp_path)
    plan = {"rows": [row(src, dest)]}
    bad = lambda cmd, **kw: subprocess.CompletedProcess(cmd, 23, stdout="", stderr="rsync error")
    result = import_plan(plan, run=bad)
    assert plan["rows"][0]["result"].startswith("failed: rsync") and result["failed"] and not dest.exists()
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_media_transfer.py -q`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement**

```python
# installer/media/transfer.py
"""
`vulcan media import`: carry out a plan. Each video is rsync'd to
<dest>.vulcan-partial (resumable), verified, then renamed into place, so the
library never holds a half-written file. Existing library files are never
overwritten; --move deletes a source only after its copy verified.
"""

import hashlib
import shutil
import subprocess
from pathlib import Path

CHUNK = 8 * 1024 * 1024


def _digest(path, full):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        if full:
            for block in iter(lambda: f.read(1024 * 1024), b""):
                h.update(block)
        else:
            h.update(f.read(CHUNK))
            size = Path(path).stat().st_size
            if size > CHUNK:
                f.seek(max(CHUNK, size - CHUNK))
                h.update(f.read(CHUNK))
    return h.hexdigest()


def verify_copy(src, dst, mode="quick"):
    src, dst = Path(src), Path(dst)
    if not dst.exists() or src.stat().st_size != dst.stat().st_size:
        return False
    return _digest(src, mode == "full") == _digest(dst, mode == "full")


def _free(path):
    path = Path(path)
    while not path.exists():
        path = path.parent
    return shutil.disk_usage(path).free


def import_plan(plan, *, move=False, verify="quick", include_review=False, save=None, on_row=None, run=subprocess.run):
    result = {"imported": [], "failed": [], "skipped": [], "stopped": None}
    wanted = {"import", "review"} if include_review else {"import"}

    for row in plan["rows"]:
        if row.get("action") not in wanted or row.get("done") or not row.get("destination"):
            continue
        src, dest = Path(row["source"]), Path(row["destination"])

        if dest.exists():
            row["result"] = "skip:conflict"
            result["skipped"].append(row)
        elif not src.exists():
            row["result"] = "failed: source missing"
            result["failed"].append(row)
        elif _free(dest.parent) < row["size"]:
            result["stopped"] = f"destination full before {src.name}"
            break
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            partial = dest.with_name(dest.name + ".vulcan-partial")
            copied = run(["rsync", "--partial", "--append-verify", "--preallocate", str(src), str(partial)],
                         capture_output=True, text=True)
            if copied.returncode != 0:
                row["result"] = f"failed: rsync exit {copied.returncode}: {(copied.stderr or '').strip()[:120]}"
                result["failed"].append(row)
            elif not verify_copy(src, partial, verify):
                partial.unlink(missing_ok=True)
                row["result"] = "failed: copy did not verify"
                result["failed"].append(row)
            else:
                partial.rename(dest)
                for sidecar in row.get("sidecars", []):
                    target = dest.parent / Path(sidecar).name
                    if Path(sidecar).exists() and not target.exists():
                        shutil.copy2(sidecar, target)
                if move:
                    src.unlink()
                    for sidecar in row.get("sidecars", []):
                        Path(sidecar).unlink(missing_ok=True)
                row["done"], row["result"] = True, "imported"
                result["imported"].append(row)

        if save:
            save(plan)
        if on_row:
            on_row(row)

    return result
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_media_transfer.py -q && ruff check installer/media`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add installer/media/transfer.py tests/test_media_transfer.py
git commit -m "feat(media): verified, resumable import of a plan"
```

---

### Task 6: Sonarr/Radarr — confirm, register, pending list

**Files:**
- Create: `installer/media/arr.py`
- Test: `tests/test_media_arr.py`

**Interfaces:**
- Consumes: plan rows (Task 4/5) with `identity`, `destination`.
- Produces:
  - `class Arr(base: str, key: str, opener=urllib.request.urlopen)` with `.call(path, method="GET", body=None)` (prefixes `/api/v3`)
  - `class ArrClients(sonarr: Arr|None, radarr: Arr|None, media_path: Path, sleep=time.sleep)` with `.to_host(container_path) -> Path`, `.to_container(host_path) -> str`, `.roots() -> dict`, `.confirm(identity, filename) -> dict`, `.register(rows) -> {"registered": [row], "pending": [row-with-"reason"]}`
  - `connect_arrs(stack_dir: Path, media_path: Path, ports: dict) -> ArrClients|None`
  - `PENDING_FILE: Path`, `add_pending(rows, path=PENDING_FILE) -> None`, `register_pending(clients, path=PENDING_FILE) -> dict` (same shape as `register`)
  - `ISO: dict[str, str]` (Arr language name → 3-letter code)
  - identity keys added by `confirm`: `tvdb_id` / `tmdb_id`, `original_language`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_media_arr.py
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
    assert c.confirm(other, "02.mkv")["confidence"] == "low"


def test_confirm_survives_unreachable_arr(tmp_path):
    c = ArrClients(FakeArr({}), FakeArr({}), tmp_path)
    ident = {"kind": "movie", "title": "Heat", "year": 1995, "confidence": "high"}
    assert c.confirm(ident, "Heat.1995.mkv") == ident


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
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_media_arr.py -q`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement**

```python
# installer/media/arr.py
"""
Sonarr/Radarr side of the media assistant: confirm identities with their own
parser + TVDB/TMDB lookups, and register imported files (add the series/movie
with the user's usual quality profile, rescan in place, verify each file was
picked up). Anything that can't be registered now - stack offline, not
identified, not picked up - goes on a pending list retried by
`vulcan media register`. Inside the stack ${MEDIA_PATH} is /data.
"""

import json
import re
import time
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

from installer.media.plan import PLANS_DIR

PENDING_FILE = PLANS_DIR / "pending-registration.json"
ISO = {"English": "eng", "Japanese": "jpn", "Chinese": "chi", "Korean": "kor", "French": "fre", "German": "ger",
       "Spanish": "spa", "Italian": "ita", "Portuguese": "por", "Russian": "rus", "Hindi": "hin", "Thai": "tha"}


class Arr:

    def __init__(self, base, key, opener=urllib.request.urlopen):
        self.base, self.key, self.opener = base.rstrip("/"), key, opener

    def call(self, path, method="GET", body=None):
        req = urllib.request.Request(self.base + "/api/v3" + path, method=method,
                                     data=json.dumps(body).encode() if body is not None else None,
                                     headers={"X-Api-Key": self.key, "Content-Type": "application/json"})
        with self.opener(req, timeout=60) as resp:
            text = resp.read()
        return json.loads(text) if text else None


def _norm(name):
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def _try(arr, path):
    try:
        return arr.call(path)
    except (OSError, ValueError):
        return None


class ArrClients:

    def __init__(self, sonarr, radarr, media_path, sleep=time.sleep):
        self.sonarr, self.radarr, self.media_path, self.sleep = sonarr, radarr, Path(media_path), sleep

    def to_host(self, container_path):
        p = str(container_path)
        return self.media_path / p[len("/data/"):] if p.startswith("/data/") else Path(p)

    def to_container(self, host_path):
        return "/data/" + str(Path(host_path).relative_to(self.media_path))

    def roots(self):
        roots = {}
        for arr, kind in ((self.sonarr, "tv"), (self.radarr, "movies")):
            folders = (_try(arr, "/rootfolder") or []) if arr else []
            for f in folders:
                key = "anime" if kind == "tv" and "anime" in f["path"].lower() else kind
                roots.setdefault(key, self.to_host(f["path"]))
        return roots

    def confirm(self, identity, filename):
        out = dict(identity)
        kind = identity.get("kind")
        arr = self.sonarr if kind == "episode" else self.radarr if kind == "movie" else None
        if arr is None:
            return out

        hit = (_try(arr, "/parse?title=" + urllib.parse.quote(filename)) or {}).get("series" if kind == "episode" else "movie")
        exact = bool(hit)
        if not hit and identity.get("title"):
            term = identity["title"] + (f" {identity['year']}" if kind == "movie" and identity.get("year") else "")
            found = _try(arr, ("/series/lookup?term=" if kind == "episode" else "/movie/lookup?term=")
                         + urllib.parse.quote(term)) or []
            hit = found[0] if found else None
            exact = bool(hit) and _norm(hit.get("title")) == _norm(identity["title"])
        if not hit:
            return out

        out.update(title=hit["title"], year=hit.get("year") or out.get("year"),
                   original_language=ISO.get((hit.get("originalLanguage") or {}).get("name")))
        if kind == "episode":
            out.update(tvdb_id=hit.get("tvdbId"), anime=out.get("anime") or hit.get("seriesType") == "anime")
        else:
            out["tmdb_id"] = hit.get("tmdbId")
        if exact:
            out["confidence"] = "high"
        return out

    def _profile(self, arr, items_path):
        used = Counter(i.get("qualityProfileId") for i in (arr.call(items_path) or []))
        if used:
            return used.most_common(1)[0][0]
        return arr.call("/qualityprofile")[0]["id"]

    def _wait(self, arr, body):
        cmd = arr.call("/command", "POST", body)
        for _ in range(300):
            if arr.call(f"/command/{cmd['id']}").get("status") in ("completed", "failed", "aborted"):
                return
            self.sleep(1)

    def _series_id(self, row):
        ident, dest = row["identity"], Path(row["destination"])
        existing = self.sonarr.call(f"/series?tvdbId={ident['tvdb_id']}") or []
        if existing:
            return existing[0]["id"]
        lookup = self.sonarr.call(f"/series/lookup?term=tvdb:{ident['tvdb_id']}")[0]
        folder = dest.parent.parent if dest.parent.name.startswith("Season ") else dest.parent
        roots = [r["path"] for r in self.sonarr.call("/rootfolder")]
        root = next((r for r in roots if ident.get("anime") and "anime" in r.lower()), roots[0])
        body = dict(lookup, qualityProfileId=self._profile(self.sonarr, "/series"), rootFolderPath=root,
                    path=self.to_container(folder), monitored=True, seasonFolder=True,
                    seriesType="anime" if ident.get("anime") else "standard",
                    addOptions={"searchForMissingEpisodes": False, "monitor": "all"})
        body.pop("id", None)
        return self.sonarr.call("/series", "POST", body)["id"]

    def _movie_id(self, row):
        ident, dest = row["identity"], Path(row["destination"])
        existing = self.radarr.call(f"/movie?tmdbId={ident['tmdb_id']}") or []
        if existing:
            return existing[0]["id"]
        lookup = self.radarr.call(f"/movie/lookup/tmdb?tmdbId={ident['tmdb_id']}")
        body = dict(lookup, qualityProfileId=self._profile(self.radarr, "/movie"),
                    rootFolderPath=self.radarr.call("/rootfolder")[0]["path"], path=self.to_container(dest.parent),
                    monitored=True, addOptions={"searchForMovie": False})
        body.pop("id", None)
        return self.radarr.call("/movie", "POST", body)["id"]

    def register(self, rows):
        registered, pending, groups = [], [], {}
        for row in rows:
            ident = row["identity"]
            if ident.get("kind") == "episode" and ident.get("tvdb_id") and self.sonarr:
                groups.setdefault(("series", ident["tvdb_id"]), []).append(row)
            elif ident.get("kind") == "movie" and ident.get("tmdb_id") and self.radarr:
                groups.setdefault(("movie", ident["tmdb_id"]), []).append(row)
            else:
                pending.append(dict(row, reason="not identified online"))

        for (kind, _), group in groups.items():
            try:
                if kind == "series":
                    sid = self._series_id(group[0])
                    self._wait(self.sonarr, {"name": "RescanSeries", "seriesId": sid})
                    have = {self.to_host(f["path"]) for f in self.sonarr.call(f"/episodefile?seriesId={sid}") or []}
                    app = "Sonarr"
                else:
                    mid = self._movie_id(group[0])
                    self._wait(self.radarr, {"name": "RescanMovie", "movieId": mid})
                    have = {self.to_host(f["path"]) for f in self.radarr.call(f"/moviefile?movieId={mid}") or []}
                    app = "Radarr"
            except (OSError, ValueError, KeyError, IndexError, TypeError) as error:
                pending += [dict(r, reason=f"registration error: {error}") for r in group]
                continue
            for r in group:
                if Path(r["destination"]) in have:
                    registered.append(r)
                else:
                    pending.append(dict(r, reason=f"not picked up by {app} rescan"))

        return {"registered": registered, "pending": pending}


def _api_key(stack_dir, app):
    try:
        m = re.search(r"<ApiKey>([^<]+)</ApiKey>", (Path(stack_dir) / "config" / app / "config.xml").read_text())
    except OSError:
        return None
    return m.group(1) if m else None


def connect_arrs(stack_dir, media_path, ports, opener=urllib.request.urlopen):
    found = {}
    for app in ("sonarr", "radarr"):
        key = _api_key(stack_dir, app)
        arr = Arr(f"http://localhost:{ports.get(app, 8989 if app == 'sonarr' else 7878)}", key, opener) if key else None
        found[app] = arr if arr and _try(arr, "/system/status") else None
    if not found["sonarr"] and not found["radarr"]:
        return None
    return ArrClients(found["sonarr"], found["radarr"], media_path)


def add_pending(rows, path=PENDING_FILE):
    path = Path(path)
    existing = json.loads(path.read_text()) if path.exists() else []
    by_dest = {r["destination"]: r for r in existing}
    by_dest.update({r["destination"]: r for r in rows})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(list(by_dest.values()), indent=1))


def register_pending(clients, path=PENDING_FILE):
    path = Path(path)
    rows = json.loads(path.read_text()) if path.exists() else []
    if not rows:
        return {"registered": [], "pending": []}
    result = clients.register(rows)
    path.write_text(json.dumps(result["pending"], indent=1))
    return result
```

Note for the `FakeArr` routes: `"GET /series?tvdbId"` must be checked before `"GET /series"` — dicts keep insertion order, and the tests list the more specific prefix first.

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_media_arr.py -q && ruff check installer/media`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add installer/media/arr.py tests/test_media_arr.py
git commit -m "feat(media): Sonarr/Radarr confirm, register and pending list"
```

---

### Task 7: CLI — `vulcan media scan | import | register`

**Files:**
- Modify: `installer/cli.py` (add imports near the other `installer.*` imports; add `media_app` right after `userdata_app` is mounted, ~line 130; add commands after the `userdata` commands, ~line 1220)
- Test: `tests/test_media_cli.py`

**Interfaces:**
- Consumes: `Prober` (T2), `scan`, `write_plan`, `load_plan`, `PLANS_DIR` (T4), `import_plan` (T5), `connect_arrs`, `add_pending`, `register_pending` (T6); existing `load_previous_state`, `STACK_DIR`, `resolve_ports`, `_config_from_previous_state`, `console`.
- Produces: CLI commands; exit code 1 on: no stack and no `--media-path`, probe tool unavailable, plan doesn't fit, any failed/stopped import row, `register` with Arrs unreachable.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_media_cli.py
import json
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from installer.cli import app

runner = CliRunner()


def fake_plan(tmp_path, fits=True):
    return {"version": 1, "source": str(tmp_path), "media_path": str(tmp_path / "lib"), "rows": [],
            "summary": {"files": 0, "actions": {}, "import_bytes": 0, "free_bytes": 1, "fits": fits,
                        "rule_breaks": 0, "may_convert": 0, "review": 0}}


class NullProber:
    def __init__(self, *a, **k): pass
    def __enter__(self): return self
    def __exit__(self, *a): return False


def test_scan_needs_a_stack_or_media_path(tmp_path):
    result = runner.invoke(app, ["media", "scan", str(tmp_path)])
    assert result.exit_code == 1 and "--media-path" in result.output


def test_scan_writes_plan_and_fails_when_it_does_not_fit(tmp_path):
    out = tmp_path / "p.json"
    with patch("installer.cli.MediaProber", NullProber), \
         patch("installer.cli.media_scan_engine", return_value=fake_plan(tmp_path, fits=False)):
        result = runner.invoke(app, ["media", "scan", str(tmp_path), "--media-path", str(tmp_path / "lib"),
                                     "--offline", "--plan", str(out)])
    assert result.exit_code == 1 and out.exists() and "won't fit" in result.output.lower()


def test_import_requires_rsync(tmp_path):
    plan = tmp_path / "p.json"
    plan.write_text(json.dumps(fake_plan(tmp_path)))
    with patch("installer.cli.shutil.which", return_value=None):
        result = runner.invoke(app, ["media", "import", str(plan)])
    assert result.exit_code == 1 and "rsync" in result.output


def test_import_offline_queues_imported_rows_for_registration(tmp_path):
    plan = tmp_path / "p.json"
    plan.write_text(json.dumps(fake_plan(tmp_path)))
    imported = [{"destination": "/lib/a.mkv", "identity": {}}]
    pending = []
    with patch("installer.cli.shutil.which", return_value="/usr/bin/rsync"), \
         patch("installer.cli.import_plan", return_value={"imported": imported, "failed": [], "skipped": [], "stopped": None}), \
         patch("installer.cli.add_pending", side_effect=lambda rows, *a: pending.extend(rows)):
        result = runner.invoke(app, ["media", "import", str(plan), "--offline"])
    assert result.exit_code == 0, result.output
    assert pending and pending[0]["reason"] == "stack offline" and "vulcan media register" in result.output


def test_register_without_reachable_arrs_exits_1(tmp_path):
    result = runner.invoke(app, ["media", "register"])
    assert result.exit_code == 1 and "Sonarr/Radarr" in result.output
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_media_cli.py -q`
Expected: FAIL — `No such command 'media'`

- [ ] **Step 3: Implement**

Imports (with the other `installer.*` imports at the top of `installer/cli.py`; add `import shutil` and `import datetime as dt` only if not already imported):

```python
from installer.media.arr import add_pending, connect_arrs, register_pending
from installer.media.plan import PLANS_DIR, load_plan, write_plan
from installer.media.plan import scan as media_scan_engine
from installer.media.probe import Prober as MediaProber
from installer.media.transfer import import_plan
```

Sub-app (after `app.add_typer(userdata_app, name="userdata")`):

```python
media_app = typer.Typer(
    help="Scan a drive or folder of existing movies/shows, import it into the library, register it with Sonarr/Radarr."
)
app.add_typer(media_app, name="media")
```

Commands (after the userdata commands):

```python
def _media_context(media_path: Path | None, offline: bool):
    """(media path, ArrClients or None). The stack's saved state supplies both unless overridden."""

    state = load_previous_state(STACK_DIR)
    if media_path is None and state:
        media_path = Path(state["media_path"])
    if media_path is None:
        console.print("[red]No Vulcan stack found here.[/red] Pass --media-path /path/to/your/media to plan without one.")
        raise typer.Exit(code=1)
    clients = None
    if not offline and state:
        clients = connect_arrs(STACK_DIR, media_path, resolve_ports(_config_from_previous_state(state)))
    return media_path, clients


def _gb(n: int) -> str:
    return f"{n / 1e9:.1f} GB"


def _print_media_plan(plan: dict) -> None:
    s = plan["summary"]
    table = Table(title=f"Media plan - {s['files']} video files")
    table.add_column("Action")
    table.add_column("Files", justify="right")
    for action, count in sorted(s["actions"].items()):
        table.add_row(action, str(count))
    console.print(table)
    console.print(f"To import: {_gb(s['import_bytes'])} - free at destination: {_gb(s['free_bytes'])}")
    if s["rule_breaks"]:
        console.print(f"[yellow]! {s['rule_breaks']} files break the language rule (no English audio, and no "
                      "original audio + English subtitles):[/yellow]")
        for row in [r for r in plan["rows"] if r.get("rule") == "breaks"][:10]:
            console.print(f"  - {Path(row['source']).name}: {row['rule_note']}")
    if s["may_convert"]:
        console.print(f"{s['may_convert']} files may need converting to play on every device (reported only).")
    if s["review"]:
        console.print(f"[yellow]! {s['review']} files need review (not recognised, or couldn't be read):[/yellow]")
        for row in [r for r in plan["rows"] if r["action"] == "review"][:10]:
            console.print(f"  - {Path(row['source']).name}")


@media_app.command(name="scan")
def media_scan(
    source: Path = typer.Argument(..., exists=True, help="Folder or drive to scan (only read, never changed)"),
    plan_file: Path | None = typer.Option(None, "--plan", help="Where to write the plan (default: stack/media-plans/<time>.json)"),
    media_path: Path | None = typer.Option(None, "--media-path", help="Library root (default: this stack's media path)"),
    offline: bool = typer.Option(False, "--offline", help="Don't ask Sonarr/Radarr - built-in name parser only"),
):
    """Identify every video under SOURCE and write an import plan. Nothing is copied."""

    media_path, clients = _media_context(media_path, offline)
    console.print("Sonarr/Radarr: " + ("online - names checked against TVDB/TMDB" if clients
                                        else "not used - built-in name parser only"))
    root = source if source.is_dir() else source.parent
    try:
        with MediaProber(root, cache_path=PLANS_DIR / ".probe-cache.json") as prober:
            plan = media_scan_engine(source, media_path, prober, clients)
    except (OSError, subprocess.CalledProcessError) as error:
        console.print(f"[red]Couldn't start ffprobe ({error}).[/red] Install ffmpeg on this machine, or make sure "
                      "Docker is running so the stack's Jellyfin image can be used.")
        raise typer.Exit(code=1)

    out = plan_file or PLANS_DIR / f"{dt.datetime.now():%Y%m%d-%H%M%S}.json"
    write_plan(plan, out)
    _print_media_plan(plan)
    console.print(f"\nPlan saved: {out}\nReview or edit it, then run: vulcan media import {out}")
    if not plan["summary"]["fits"]:
        console.print("[red]The planned import won't fit in the free space at the destination.[/red] "
                      "Free some space or change some rows' action to \"skip\" in the plan.")
        raise typer.Exit(code=1)


@media_app.command(name="import")
def media_import(
    plan_path: Path = typer.Argument(..., exists=True, help="A plan written by `vulcan media scan`"),
    move: bool = typer.Option(False, "--move", help="Delete each source file after its copy verified"),
    verify: str = typer.Option("quick", "--verify", help="quick (size + first/last 8 MiB) or full (whole-file hash)"),
    include_review: bool = typer.Option(False, "--include-review", help="Also import rows marked review"),
    offline: bool = typer.Option(False, "--offline", help="Don't register with Sonarr/Radarr now - queue it"),
):
    """Copy (or move) the plan's files into the library, then register them with Sonarr/Radarr."""

    if verify not in ("quick", "full"):
        raise typer.BadParameter("--verify must be quick or full")
    if not shutil.which("rsync"):
        console.print("[red]rsync is required for imports[/red] (resumable copies). Install it, e.g. "
                      "`sudo apt install rsync` / `sudo dnf install rsync`, and re-run.")
        raise typer.Exit(code=1)

    plan = load_plan(plan_path)

    def report(row):
        console.print(f"  {row.get('result', '?'):<16} {Path(row['source']).name}")

    result = import_plan(plan, move=move, verify=verify, include_review=include_review,
                         save=lambda p: write_plan(p, plan_path), on_row=report)
    console.print(f"Imported {len(result['imported'])}, skipped {len(result['skipped'])}, failed {len(result['failed'])}.")
    if result["stopped"]:
        console.print(f"[red]Stopped: {result['stopped']}.[/red] Free space and re-run - finished files are kept.")

    if result["imported"]:
        _, clients = _media_context(Path(plan["media_path"]), offline)
        if clients:
            reg = clients.register(result["imported"])
            add_pending(reg["pending"])
            console.print(f"Registered {len(reg['registered'])} with Sonarr/Radarr; {len(reg['pending'])} queued "
                          "for `vulcan media register`.")
            register_pending(clients)
        else:
            add_pending([dict(r, reason="stack offline") for r in result["imported"]])
            console.print("Sonarr/Radarr not reachable - queued for registration. Run `vulcan media register` "
                          "once the stack is online.")

    if result["failed"] or result["stopped"]:
        raise typer.Exit(code=1)


@media_app.command(name="register")
def media_register():
    """Register files imported while offline (or not picked up yet) with Sonarr/Radarr."""

    _, clients = _media_context(None, False) if load_previous_state(STACK_DIR) else (None, None)
    if not clients:
        console.print("[red]Sonarr/Radarr aren't reachable[/red] - start the stack and re-run.")
        raise typer.Exit(code=1)
    result = register_pending(clients)
    console.print(f"Registered {len(result['registered'])}; {len(result['pending'])} still pending.")
    for row in result["pending"][:10]:
        console.print(f"  - {Path(row['destination']).name}: {row['reason']}")
```

If `Table`, `subprocess` or `shutil` are not already imported in `cli.py`, add `from rich.table import Table`, `import subprocess`, `import shutil` at the top (check first with `grep -n "^import\|^from rich" installer/cli.py`).

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_media_cli.py -q && python -m pytest tests/ -q -x && ruff check .`
Expected: PASS, whole suite green, ruff clean.

- [ ] **Step 5: Commit**

```bash
git add installer/cli.py tests/test_media_cli.py
git commit -m "feat(media): vulcan media scan/import/register commands"
```

---

### Task 8: Whiptail menu entry

**Files:**
- Modify: `installer/menu.sh` (add `media_flow` before `main_menu`; add the `media` item + case to `main_menu`)
- Test: `tests/test_menu.bats`

**Interfaces:**
- Consumes: `confirm_and_run` (existing), `$VULCAN_BIN media scan SRC --plan stack/media-plans/menu-latest.json`, `$VULCAN_BIN media import stack/media-plans/menu-latest.json`.

- [ ] **Step 1: Write the failing bats tests** (append to `tests/test_menu.bats`)

```bash
@test "media_flow scans the chosen folder, then imports the same plan" {

    fake_vulcan() { echo "VULCAN $*"; }
    export -f fake_vulcan
    whiptail() {
        case "$*" in
            *--inputbox*) echo -n "/mnt/old drive" >&3 ;;
        esac
        return 0
    }
    export -f whiptail

    run bash -c "VULCAN_BIN=fake_vulcan; export VULCAN_BIN; source '$MENU_SH'; media_flow <<< \$'\n\n'"

    [ "$status" -eq 0 ]
    [[ "$output" == *"VULCAN media scan /mnt/old drive --plan stack/media-plans/menu-latest.json"* ]]
    [[ "$output" == *"VULCAN media import stack/media-plans/menu-latest.json"* ]]
}

@test "media_flow does nothing when the folder prompt is cancelled" {

    fake_vulcan() { echo "VULCAN $*"; }
    export -f fake_vulcan
    whiptail() { return 1; }
    export -f whiptail

    run bash -c "VULCAN_BIN=fake_vulcan; export VULCAN_BIN; source '$MENU_SH'; media_flow"

    [ "$status" -eq 0 ]
    [[ "$output" != *"VULCAN media"* ]]
}

@test "media_flow does not import when the scan fails" {

    fake_vulcan() { echo "VULCAN $*"; [ "$2" = "scan" ] && return 1; return 0; }
    export -f fake_vulcan
    whiptail() { case "$*" in *--inputbox*) echo -n "/mnt/old" >&3 ;; esac; return 0; }
    export -f whiptail

    run bash -c "VULCAN_BIN=fake_vulcan; export VULCAN_BIN; source '$MENU_SH'; media_flow <<< \$'\n\n'"

    [[ "$output" == *"VULCAN media scan"* ]]
    [[ "$output" != *"VULCAN media import"* ]]
}
```

- [ ] **Step 2: Run to verify it fails**

Run: `bats tests/test_menu.bats -f media_flow`
Expected: FAIL — `media_flow: command not found`

- [ ] **Step 3: Implement** (in `installer/menu.sh`, just above `# --- Main Menu ---`)

```bash
# --- Media assistant -----------------------------------------------------
#
# Front end for `vulcan media scan` / `vulcan media import` - the engine
# (installer/media/) does everything; this only asks for the folder and
# confirms each step. One fixed plan path so scan and import always agree.
media_flow() {
    local source plan="stack/media-plans/menu-latest.json"

    source=$(whiptail --backtitle "$BACKTITLE" --title "Media assistant" \
        --inputbox "Folder or drive with your existing movies and shows.\n\nIt is only read - nothing on it is changed." \
        "$DLG_ROWS" "$DLG_COLS" "" 3>&1 1>&2 2>&3) || return 0
    [ -n "$source" ] || return 0

    confirm_and_run "Scan media" \
        "Scan $source and write an import plan?\n\nNothing is copied yet - you'll see a summary first." \
        "$VULCAN_BIN" media scan "$source" --plan "$plan" || return 0

    confirm_and_run "Import media" \
        "Copy the planned files into your library and register them with Sonarr/Radarr?\n\nThe source stays untouched. Duplicates, files already in the library and unrecognised files are skipped." \
        "$VULCAN_BIN" media import "$plan" || return 0
}
```

And in `main_menu()`, add the item after `"stack"` and the case:

```bash
            "media"       "Media → Scan & import existing movies and shows" \
```

```bash
            media)      media_flow ;;
```

- [ ] **Step 4: Run to verify it passes**

Run: `bats tests/test_menu.bats && shellcheck -S warning installer/menu.sh`
Expected: all PASS (including the existing main_menu tests), shellcheck clean.

- [ ] **Step 5: Commit**

```bash
git add installer/menu.sh tests/test_menu.bats
git commit -m "feat(media): media assistant in the whiptail main menu"
```

---

### Task 9: Real-infrastructure verification + docs

**Files:**
- Create: `docs/guides/media-assistant.md`
- Modify: `mkdocs.yml` (nav entry under guides), `README.md` (one line in "Maintaining an Existing Stack" command table), `ROADMAP.md` (Shipped entry with the verification evidence), `CHANGELOG.md`

**Interfaces:** none new.

- [ ] **Step 1: Throwaway stack**

```bash
mkdir -p /tmp/vulcan-media-e2e/media && cd /tmp/vulcan-media-e2e
git clone ~/projects/github/repos/vulcan v && cd v && git checkout <branch>
./install --plain --tier light --media-path /tmp/vulcan-media-e2e/media --non-interactive --yes --start
```
Light includes Sonarr, Radarr and Jellyfin. Wait for `vulcan status` healthy; add root folders `/data/media/tv` and `/data/media/movies` in Sonarr/Radarr (UI or API).

- [ ] **Step 2: Test drive**

Build `/tmp/vulcan-media-e2e/drive/` with real small files made by ffmpeg (from the Jellyfin image: `docker run --rm -v $PWD:/o --entrypoint /usr/lib/jellyfin-ffmpeg/ffmpeg lscr.io/linuxserver/jellyfin -f lavfi -i testsrc=d=5 -f lavfi -i sine=d=5 -metadata:s:a:0 language=eng -c:v libx264 -c:a aac /o/<name>`), named like the Task 1 cases: `Heat.1995.1080p.mkv`, `Heat (1995) 720p.mkv` (duplicate), `spy.x.family.s01e11.mkv` (audio language `jpn`, plus a `.en.srt` sidecar), `random_clip.mkv`, an HEVC file (`-c:v libx265`) for "may convert".

- [ ] **Step 3: Scan / import / register for real**

```bash
vulcan media scan /tmp/vulcan-media-e2e/drive --plan /tmp/p.json
vulcan media import /tmp/p.json
```
Confirm: duplicate skipped, clip in review, HEVC flagged "may convert", Spy x Family `rule: ok` via sidecar. Files exist under `media/movies/Heat (1995)/` and `media/tv/SPY x FAMILY (2022)/Season 01/` with no `.vulcan-partial` left. `curl -s -H "X-Api-Key: $KEY" localhost:<sonarr>/api/v3/episodefile?seriesId=<id>` lists the file; same for Radarr. Library scan in Jellyfin shows both and plays.

- [ ] **Step 4: Offline path**

`docker compose stop sonarr radarr`; import a second plan → rows land in `stack/media-plans/pending-registration.json` with reason `stack offline`; `docker compose start sonarr radarr`; `vulcan media register` → registered, pending file empty.

- [ ] **Step 5: Interrupt/resume + move**

Interrupt an import of a large (≥2 GB) file with Ctrl-C mid-copy; re-run → resumes, verifies, no duplicate. Run once with `--move` on a scratch copy → sources removed only for verified rows.

- [ ] **Step 6: Docs**

`docs/guides/media-assistant.md`: what it does, the three commands with one example each, what each action means, the language rule and "may convert", offline → `vulcan media register`, and the safety guarantees (source read-only by default, never overwrites, `--move` after verify). Add to `mkdocs.yml` nav next to the other guides; one row in README's command table; ROADMAP Shipped entry listing the real-infra results from Steps 3–5; CHANGELOG entry.

- [ ] **Step 7: Tear down and commit**

```bash
cd /tmp/vulcan-media-e2e/v && docker compose -f stack/docker-compose.yml down -v && cd / && rm -rf /tmp/vulcan-media-e2e
cd ~/projects/github/repos/vulcan
git add docs/guides/media-assistant.md mkdocs.yml README.md ROADMAP.md CHANGELOG.md
git commit -m "docs(media): media assistant guide, roadmap and changelog"
```
