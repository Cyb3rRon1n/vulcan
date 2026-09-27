"""
Jellyfin user-data export/restore - the part of a media server a config backup can't bring back.

Favorites, 👍/👎, watched status (date + play count) and resume positions live in Jellyfin's
database keyed by Jellyfin's own item ids, which a rebuilt or re-scanned library changes. This
exports them per user keyed by TMDb/TVDb/IMDb ids (episodes: the show's ids + season/episode),
plus Seerr's requests and a library list, so they can be written back onto a fresh Jellyfin.

    vulcan userdata export                     -> exports/userdata/<date>/
    vulcan userdata restore <snapshot> [--user NAME] [--apply]   (dry run by default)

Needs a Jellyfin API key (Dashboard > API Keys) as JELLYFIN_API_KEY in stack/.env.
"""

import datetime as dt
import json
import shutil
import urllib.parse
import urllib.request
from pathlib import Path

USERDATA_DIR = Path("exports") / "userdata"
KEEP_SNAPSHOTS = 30
FIELDS = "ProviderIds,DateCreated,ProductionYear,SeriesName,SeriesId,ParentIndexNumber,IndexNumber"


class Jellyfin:

    def __init__(self, url: str, key: str):

        self.url, self.key = url.rstrip("/"), key

    def __call__(self, path: str, method: str = "GET", body: dict | None = None):

        # Jellyfin 10.11+/12 rejects X-Emby-Token for API keys - this header form works everywhere.
        req = urllib.request.Request(
            self.url + path, method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Authorization": f'MediaBrowser Token="{self.key}"', "Content-Type": "application/json"},
        )
        raw = urllib.request.urlopen(req, timeout=300).read()

        return json.loads(raw) if raw else None


def _ids(item: dict) -> dict:

    return {k.lower(): v for k, v in (item.get("ProviderIds") or {}).items() if k in ("Tmdb", "Tvdb", "Imdb") and v}


def _entry(item: dict, series_ids: dict) -> dict:

    ud = item.get("UserData") or {}
    e = {
        "type": item["Type"], "title": item.get("Name"), "year": item.get("ProductionYear"), "ids": _ids(item),
        "favorite": bool(ud.get("IsFavorite")), "likes": ud.get("Likes"),   # True 👍 / False 👎 / None
        "played": bool(ud.get("Played")), "play_count": ud.get("PlayCount", 0),
        "last_played": ud.get("LastPlayedDate"), "position_ticks": ud.get("PlaybackPositionTicks", 0),
    }

    if item["Type"] == "Episode":

        e.update(series=item.get("SeriesName"), series_ids=series_ids.get(item.get("SeriesId"), {}),
                 season=item.get("ParentIndexNumber"), episode=item.get("IndexNumber"))

    return e


def _user_items(jf: Jellyfin, uid: str) -> list[dict]:
    """Items with any user data worth keeping. Jellyfin's "Dislikes" filter also returns
    never-rated items, so the union is post-filtered on the real UserData."""

    seen = {}

    for f in ("IsFavorite", "IsPlayed", "IsResumable", "Likes", "Dislikes"):

        r = jf(f"/Items?userId={uid}&Recursive=true&IncludeItemTypes=Movie,Series,Episode&Filters={f}&Fields={FIELDS}")

        for it in r["Items"]:

            seen[it["Id"]] = it

    return [it for it in seen.values()
            if (ud := it.get("UserData") or {}) and (ud.get("IsFavorite") or ud.get("Played")
                                                     or ud.get("PlaybackPositionTicks") or ud.get("Likes") is not None)]


def _seerr_requests(url: str, key: str) -> list[dict]:

    reqs, skip = [], 0

    while True:

        req = urllib.request.Request(f"{url.rstrip('/')}/api/v1/request?take=100&skip={skip}&sort=added",
                                     headers={"X-Api-Key": key})
        page = json.load(urllib.request.urlopen(req, timeout=120))

        for r in page["results"]:

            m, by = r.get("media") or {}, r.get("requestedBy") or {}
            reqs.append({"type": r.get("type"), "status": r.get("status"), "created": r.get("createdAt"),
                         "by": by.get("jellyfinUsername") or by.get("displayName"), "tmdb": m.get("tmdbId"),
                         "tvdb": m.get("tvdbId"), "seasons": [s.get("seasonNumber") for s in r.get("seasons") or []]})

        skip += 100

        if skip >= page["pageInfo"]["results"]:

            return reqs


def export_userdata(jf: Jellyfin, out_root: Path = USERDATA_DIR, seerr: tuple[str, str] | None = None,
                    today: dt.date | None = None, keep: int = KEEP_SNAPSHOTS) -> dict:

    today = today or dt.date.today()
    out = out_root / today.isoformat()
    (out / "users").mkdir(parents=True, exist_ok=True)
    series_ids = {s["Id"]: _ids(s) for s in jf("/Items?Recursive=true&IncludeItemTypes=Series&Fields=ProviderIds")["Items"]}
    library = [{"type": i["Type"], "title": i["Name"], "year": i.get("ProductionYear"), "ids": _ids(i),
                "added": i.get("DateCreated")}
               for i in jf(f"/Items?Recursive=true&IncludeItemTypes=Movie,Series&Fields={FIELDS}")["Items"]]
    (out / "library.json").write_text(json.dumps(library, indent=1, ensure_ascii=False))
    counts = {}

    for u in jf("/Users"):

        items = [_entry(it, series_ids) for it in _user_items(jf, u["Id"])]
        counts[u["Name"]] = len(items)
        (out / "users" / f"{u['Name']}.json").write_text(json.dumps(
            {"user": u["Name"], "exported": dt.datetime.now(dt.timezone.utc).isoformat(), "items": items},
            indent=1, ensure_ascii=False))

    requests = _seerr_requests(*seerr) if seerr else []

    if seerr:

        (out / "seerr-requests.json").write_text(json.dumps(requests, indent=1, ensure_ascii=False))

    for old in sorted(d.name for d in out_root.iterdir() if d.is_dir() and d.name[:4].isdigit())[:-keep]:

        shutil.rmtree(out_root / old)

    return {"path": out, "users": counts, "titles": len(library), "requests": len(requests)}


def _index(jf: Jellyfin) -> tuple[dict, dict]:
    """provider id -> Jellyfin id for movies/series; (show id key, season, episode) -> id for episodes."""

    by_id, series_keys, eps = {}, {}, {}

    for it in jf("/Items?Recursive=true&IncludeItemTypes=Movie,Series&Fields=ProviderIds")["Items"]:

        for k, v in _ids(it).items():

            by_id[(it["Type"], k, v)] = it["Id"]

            if it["Type"] == "Series":

                series_keys.setdefault(it["Id"], []).append((k, v))

    for it in jf("/Items?Recursive=true&IncludeItemTypes=Episode&Fields=SeriesId")["Items"]:

        for key in series_keys.get(it.get("SeriesId"), []):

            eps[(key, it.get("ParentIndexNumber"), it.get("IndexNumber"))] = it["Id"]

    return by_id, eps


def _find(e: dict, by_id: dict, eps: dict) -> str | None:

    if e["type"] == "Episode":

        return next((eps[k] for k in ((tuple(p), e.get("season"), e.get("episode"))
                                      for p in (e.get("series_ids") or {}).items()) if k in eps), None)

    return next((by_id[(e["type"], k, e["ids"][k])] for k in ("tmdb", "tvdb", "imdb")
                 if e["ids"].get(k) and (e["type"], k, e["ids"][k]) in by_id), None)


def _write(jf: Jellyfin, uid: str, jid: str, e: dict) -> None:

    q = f"?userId={uid}"

    if e["favorite"]:

        jf(f"/UserFavoriteItems/{jid}{q}", "POST")

    if e["likes"] is not None:

        jf(f"/UserItems/{jid}/Rating{q}&likes={'true' if e['likes'] else 'false'}", "POST")

    if e["played"]:

        date = f"&datePlayed={urllib.parse.quote(e['last_played'])}" if e["last_played"] else ""
        jf(f"/UserPlayedItems/{jid}{q}{date}", "POST")

    if e["position_ticks"] or e["play_count"]:

        jf(f"/UserItems/{jid}/UserData{q}", "POST", {"PlaybackPositionTicks": e["position_ticks"],
                                                     "PlayCount": e["play_count"],
                                                     "LastPlayedDate": e["last_played"], "Played": e["played"]})


def restore_userdata(jf: Jellyfin, snapshot: Path, user: str | None = None, apply: bool = False) -> list[dict]:
    """Match each exported item to the current library by provider ids and (with apply) write it
    back. Users are matched by name - recreate them in Jellyfin first."""

    users = {u["Name"].lower(): u["Id"] for u in jf("/Users")}
    by_id, eps = _index(jf)
    results = []

    for f in sorted((snapshot / "users").glob("*.json")):

        data = json.loads(f.read_text())

        if user and data["user"].lower() != user.lower():

            continue

        uid = users.get(data["user"].lower())

        if not uid:

            results.append({"user": data["user"], "error": "no such Jellyfin user - create it, then re-run"})
            continue

        matched, missing = 0, []

        for e in data["items"]:

            jid = _find(e, by_id, eps)

            if not jid:

                missing.append(e.get("series") or e["title"])
                continue

            matched += 1

            if apply:

                _write(jf, uid, jid, e)

        results.append({"user": data["user"], "matched": matched, "missing": sorted(set(missing))})

    return results
