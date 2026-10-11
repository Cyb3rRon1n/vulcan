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
