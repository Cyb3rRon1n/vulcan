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
        if f.suffix.lower() not in SUB_EXTENSIONS or not f.name.startswith(video.stem + "."):
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
            try:
                in_container = path.relative_to(self.root)
            except ValueError:
                # A symlink resolving outside root can't be mapped into the container.
                return None
            cmd = ["docker", "exec", self.container, CONTAINER_FFPROBE, *FFPROBE_ARGS, "/in/" + str(in_container)]

        result = self.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            return None
        try:
            info = summarize(json.loads(result.stdout))
        except ValueError:
            return None

        self.cache[key] = info
        return info
