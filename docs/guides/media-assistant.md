# Media assistant

You've got movies and shows already sitting on a drive — messy names, mixed
quality, foreign dubs, the odd duplicate. `vulcan media scan` / `vulcan media
import` / `vulcan media register` get that existing pile into your library
safely: it tells you exactly what's there and where it would go, copies it in
(never moves unless you ask), and — when Sonarr/Radarr are up — registers it
so it's tracked from then on, the same as anything downloaded normally.

## The three commands

### `vulcan media scan <path> [--plan FILE] [--media-path PATH] [--offline]`

Read-only. Walks `<path>` for video files and writes a plan — a JSON file you
can review or hand-edit — plus an on-screen summary. `--media-path` overrides
the library root (defaults to the running stack's own); `--offline` skips
asking Sonarr/Radarr and uses only the built-in name parser, even if the
stack is up.

```
$ vulcan media scan /mnt/old-drive
Sonarr/Radarr: online - names checked against TVDB/TMDB
  Media plan - 5 video files
┏━━━━━━━━━━━━━━━━┳━━━━━━━┓
┃ Action         ┃ Files ┃
┡━━━━━━━━━━━━━━━━╇━━━━━━━┩
│ import         │     3 │
│ review         │     1 │
│ skip:duplicate │     1 │
└────────────────┴───────┘
To import: 4.1 GB - free at destination: 67.2 GB
1 files may need converting to play on every device (reported only).
! 1 files need review (not recognised, or couldn't be read):
  - random_clip.mkv

Plan saved: stack/media-plans/20261011-174812.json
```

Nothing on `<path>` is ever touched by `scan`. For each file it works out:

- **identity** — movie or episode, title/year/season/episode, and a
  confidence (`high`/`low`/`unknown`). If Sonarr/Radarr are reachable, their
  own TVDB/TMDB lookup confirms or corrects the built-in guess; offline, only
  the filename and folder structure are used.
- **the language rule** — `ok` if any audio track is English, or if the
  original-language audio is present together with an English subtitle
  (embedded or a sidecar `.srt`/`.ass`/etc.); otherwise `breaks`. An extra dub
  track never counts against a file that's already fine. An untagged
  (`und`) audio track and an unknown original language (no Sonarr/Radarr
  lookup to confirm it against) both report as `ok` with a note instead of
  a false `breaks` — there's nothing to contradict the rule, so the benefit
  of the doubt goes to the file, not an alarm you'd have to double-check by
  hand.
- **direct play** — `universal` (plays on anything: H.264 8-bit, AAC/AC3/EAC3
  audio, text subtitles) or **"may convert"**, naming the reason (HEVC,
  10-bit, DTS/TrueHD audio, PGS/VobSub subtitles). This is reported only —
  the assistant never transcodes anything itself; that's a separate,
  not-yet-built tool (`vulcan media pack`).
- **duplicate** — the same movie or episode seen more than once; the better
  copy (higher resolution, then English audio, then larger file) is kept and
  the other is skipped.
- **action** — `import`, `skip:duplicate`, `skip:conflict` (something's
  already at that destination), or `review` (low/unknown confidence — you
  decide).

Only `import` rows are imported by default. Edit the plan JSON by hand if you
want to flip a `review` row to `import`, or an `import` row to `skip`.

### `vulcan media import <plan> [--move] [--verify quick|full] [--include-review] [--offline]`

```
$ vulcan media import stack/media-plans/20261011-174812.json
  imported         Heat.1995.1080p.mkv
  imported         Blade Runner (1982).mkv
  imported         spy.x.family.s01e11.mkv
Imported 3, skipped 0, failed 0.
Registered 3 with Sonarr/Radarr; 0 queued for `vulcan media register`.
```

Copies every `import` row into the library (plus `review` rows too, if you
pass `--include-review`). What "import" means:

- Each file is copied to `<dest>.vulcan-partial`, verified, then renamed into
  place — a crash or a `Ctrl-C` mid-copy never leaves a half-written file in
  your library. Re-running the same plan resumes the interrupted file instead
  of starting over, and skips every row already done.
- `--verify quick` (the default) checks size plus a SHA-256 of the first and
  last 8 MiB; `--verify full` hashes the whole file both sides.
- `--move` deletes the source only after its copy is verified — never before,
  and never for a row that failed or was skipped. Refused outright if the
  plan's source folder is inside the stack's own media path — moving it
  there could delete files Sonarr/Radarr still track or that are seeding.
- Progress is reported per file, as each one finishes (`imported`,
  `skip:conflict`, `failed: ...`); there's no live byte-level progress bar
  yet for the file currently copying.
- A destination that already exists is never overwritten; it's reported as
  `skip:conflict` instead, even if it appeared after the scan.
- If Sonarr/Radarr are reachable, imported titles are registered automatically
  (added with your usual quality profile, then rescanned in place — no second
  copy). If they're not, the import still finishes; see below.
- `--offline` skips registering with Sonarr/Radarr even if they're reachable
  — the import is queued for `vulcan media register` instead, same as if the
  stack were actually down.

### `vulcan media register`

Processes anything still waiting from an import that ran while Sonarr/Radarr
were offline (or that they hadn't picked up yet).

```
$ vulcan media register
Registered 1; 0 still pending.
```

## Offline imports

Importing doesn't require the stack to be running. If Sonarr/Radarr aren't
reachable, the copy still happens — nothing is lost — and the file is queued
in `stack/media-plans/pending-registration.json` with a reason (e.g. `stack
offline`). Once the stack is back up, run `vulcan media register` (or just
`vulcan media import` again — it flushes the backlog first) and those files
get registered without re-copying anything.

## The TUI

The whiptail Main Menu has a **Media** entry: pick a folder, see the scan
summary (counts, free space, language-rule breaks, unknowns), then a yes/no
"Delete the originals after each verified copy?" (default No — copy and
keep them; Yes passes `--move` through) before confirming the import. It's a
thin front end over the exact same `vulcan media scan`/`import` calls
described above — no separate logic.

## Safety guarantees

- **Read-only until you say import.** `scan` never changes anything on the
  source or in your library.
- **The source is never touched** unless you pass `--move`, and even then
  only after that file's copy has verified.
- **Nothing in your library is ever overwritten.** A destination that already
  has a file there is skipped, not replaced.
- **No half-written files.** Copies land at `<dest>.vulcan-partial` and are
  only renamed into place after verification.
- **Resumable.** An interrupted import (crash, `Ctrl-C`, network drop) can
  always be re-run against the same plan — finished rows are skipped, a
  partial copy picks up where it left off.
