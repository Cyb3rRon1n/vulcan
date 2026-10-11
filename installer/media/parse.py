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


def _clean(text, strip_year=True):
    """Title text before an anchor -> (title or None, year or None)."""

    s = _BRACKETS.sub(" ", text)
    s = re.sub(r"[._]", " ", s)
    year = None
    if strip_year:
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
        title, _ = _clean(stem[:m.start()], strip_year=False)          # start of the whole match drops the "(" / "." too
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
