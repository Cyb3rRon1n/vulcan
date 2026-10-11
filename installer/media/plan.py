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
            identity = {**identity, **(arr.confirm(identity, f.name) or {})}
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
        if r["identity"]["kind"] != "unknown" and r["probe"] != "failed" and r["action"] in ("import", "review"):
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
