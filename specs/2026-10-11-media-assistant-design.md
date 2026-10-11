# Media assistant (`vulcan media scan` / `vulcan media import`) — design

**Status:** approved in brainstorming 2026-10-11, awaiting spec review.
**Part of:** the travel ("Vulcan Mobile") effort, sub-project 1 of 3. Order: 1 media assistant → 2 Travel tier → 3 `vulcan media pack`. The public-facing Vulcan refresh is a separate, later project.

## Why

People arrive with media already on drives: messy names, mixed quality, foreign dubs, duplicates. Today Vulcan builds the stack but leaves "get my existing files into it" to the user. The media assistant scans any folder or drive, says exactly what is there and where it would go, then imports it safely — and, when online, registers it with Sonarr/Radarr so it is tracked from then on. It is useful to every Vulcan user and is the foundation for trip packing (sub-project 3).

## User-facing behaviour

### `vulcan media scan <path> [--plan FILE]`
Read-only. Walks `<path>` for video files (`.mkv .mp4 .m4v .avi .ts .webm`) and writes a plan (default `stack/media-plans/<timestamp>.json`) plus an on-screen report. Per file:

| Field | Meaning |
|---|---|
| identity | movie or episode; title, year, season/episode(s); confidence `high` / `low` / `unknown` |
| quality | resolution, video codec, bit depth |
| languages | audio languages; subtitle languages (embedded + sidecar files) |
| rule | `ok` / `breaks` against the language rule: English audio, or original-language audio + English subtitles. Extra dub tracks don't matter. |
| direct play | `universal` (H.264 8-bit + AAC/AC3/EAC3 + text subs) or `may convert`, with the reason (HEVC/10-bit, DTS/TrueHD, PGS/VobSub subs) |
| duplicate | same movie/episode seen more than once; the better copy is marked (higher resolution, then English audio, then larger) |
| destination | target path in the library |
| action | `import` / `skip:duplicate` / `skip:conflict` (destination exists) / `review` (low or unknown confidence) |

Report summary: counts by action, total size vs free space at the destination (refuse to plan an import that cannot fit), files breaking the language rule, files that may need conversion, unknowns listed for review.

### `vulcan media import <plan> [--move] [--verify quick|full] [--include-review]`
Executes a plan. Copies by default (source untouched). Imports only `action: import` rows (plus `review` rows with `--include-review`); duplicates, conflicts and unknowns are never imported implicitly. The user may edit the plan JSON (e.g. flip an action) before importing.

- Never overwrites or deletes anything already in the library; a destination that appeared since the scan becomes `skip:conflict`.
- `--move` deletes a source file only after its copy verified.
- Resumable: re-running the same plan skips rows already done and resumes partial copies.
- Online (Sonarr/Radarr reachable): registers imported titles (see Registration). Offline: appends them to `stack/media-plans/pending-registration.json`, processed automatically the next time `vulcan media import` or `vulcan media register` runs with the stack online.

### `vulcan media register`
Processes the pending-registration list. Exposed so it can also be run by hand or from a timer once the travel tier exists.

### TUI
`menu.sh` gains a "Media assistant" entry: pick source path → scan → summary screen (counts, space, rule breakers, unknowns) → confirm import (copy or move). Same engine calls as the CLI; no logic in the menu.

## Internals

### Module layout
- `installer/media.py` — new pure engine module, plain result dicts, never prompts (same contract as the rest of the engine): `parse_name()`, `probe_file()`, `scan()`, `plan_destination()`, `import_plan()`, `register_pending()`.
- `installer/cli.py` — thin `media_app` Typer group (`scan`, `import`, `register`), mounted like `storage_app`/`plan_app`.
- `installer/menu.sh` — the menu entry.
- No new Python dependencies.

### Identification
1. **Built-in parser (always, offline-capable):** `SxxEyy`, `SxxEyy-Ezz`/`SxxEyyEzz` multi-episode, `NxNN`, anime absolute numbering (`Show - 12`, `[Group] Show - 12 (1080p)`), movie `Title (Year)` / `Title.Year.`, release clutter stripped (resolution, codec, source, group, bracketed tags). Parent folders are hints: `Show/Season 2/02.mkv`, `Movie (1995)/file.mkv`. Confidence `high` when title + episode/year are both found, `low` when one is inferred from folders, `unknown` otherwise.
2. **Sonarr/Radarr (when the stack is up and reachable):** `GET /api/v3/parse?title=` and `/series/lookup` / `/movie/lookup` confirm or correct the built-in result and supply canonical title + year. Their answer wins when it disagrees.

guessit was considered and rejected: three extra dependencies, and the Arrs already cover the hard cases when online.

### Probing
`ffprobe -show_streams -show_format -of json`, run from the stack's Jellyfin image (`docker run --rm --entrypoint /usr/lib/jellyfin-ffmpeg/ffprobe -v <dir>:/in:ro jellyfin/jellyfin ...`) — no new image or host package. A host `ffprobe` on `PATH` is preferred when present. Sidecar subtitles (`<stem>*.srt|ass|ssa|vtt|sub`) are counted; their language comes from the filename tag (`.en`, `.eng`, `.english`, `.sdh` = English) and, when untagged or ambiguous (`.hi` is Hindi in ISO 639-1 but Bazarr's hearing-impaired suffix), from a text sample (English stopword ratio) — real cyberpac case: a `.hi.srt` that was Russian, and dramas whose English subs are untagged.

Cache: `stack/media-plans/.probe-cache.json` keyed by absolute path + size + mtime, so a re-scan of an unchanged drive does not re-probe.

### Language rule
`ok` if any audio track is English, or the series/movie original-language audio is present **and** an English subtitle exists (embedded or sidecar). Original language comes from Sonarr/Radarr lookup when online; offline it defaults to Japanese for anime-style names (absolute numbering / fansub group brackets) and is otherwise `unknown`, which reports as `ok` with a note rather than a false `breaks`.

### Destination
Sonarr/Radarr root folders when available (by type; anime root if the Sonarr series type is anime), else `${MEDIA_PATH}/media/tv` and `${MEDIA_PATH}/media/movies`. Path: `Show (Year)/Season NN/<original filename>` or `Movie (Year)/<original filename>`. Sidecar subtitles travel with their video. No renaming — Sonarr/Radarr apply the user's naming on registration.

### Copy and verify
`rsync --partial --append-verify --preallocate` per file (present on all supported distros; checked in preflight). `--verify quick` (default): size match + SHA-256 of the first and last 8 MiB. `--verify full`: SHA-256 of the whole file on both sides. Progress per file and overall via Rich. Copies are written to `<dest>.vulcan-partial` and renamed into place only after verification, so a library never contains a half-written file.

### Registration
Online: add missing series/movies via `/series` / `/movie` POST with the user's default quality profile (which carries the language custom formats) and `monitored` per the profile default, `addOptions.searchForMissingEpisodes=false`; then a `RescanSeries` / `RescanMovie` command picks up the files in place (no second copy). Verify via `/episodefile` / `/moviefile` that every imported file is registered; anything that is not stays in pending-registration with the reason.

## Error handling
- Unreadable file / ffprobe failure → row with `probe: failed` and `action: review`; scan continues.
- Source vanishes mid-import → row marked failed, partial removed, import continues; summary lists failures; re-run resumes.
- Destination full → stop before the next file, keep completed rows, explain.
- Arr unreachable during import → treated as offline (pending list), never a hard failure.

## Testing
- Parser: table tests built from real cyberpac file names (TV, anime absolute numbering, multi-episode, movies with years, fansub brackets, Tsundere-Raws/VARYG/ToonsHub releases, C-drama names).
- Rule + direct-play classification: fixture ffprobe JSON (English dub, jpn+eng subs sidecar, fre/jpn + en.srt, PGS-only subs, HEVC 10-bit).
- Import: temp dirs — copy, resume after interrupt, `--move` deletes only after verify, conflict never overwrites, partial-file rename.
- Real infrastructure (required before merge): a throwaway vulcan-generated stack with Sonarr + Radarr + Jellyfin; scan a test drive of real files, import, confirm registration via the API and playback in Jellyfin; repeat offline (network-less container) and confirm pending registration completes when brought online.

## Out of scope (later sub-projects)
- Converting files (`may convert` is reported only) → `vulcan media pack`.
- Music, books, comics → later; this covers movies and TV/anime.
- Moving Jellyfin metadata/watch history → `vulcan media pack`.
