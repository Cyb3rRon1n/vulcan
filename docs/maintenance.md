# Maintaining a Stack

Every command below is also reachable from the guided menu's own **Main Menu** (Update Stack / Pull Images / Backup Stack / Restore Stack / Uninstall Stack) — not CLI-only. The menu versions confirm before running (a real `whiptail --yesno`, mirroring the same wording as the CLI's own prompts) and show real live output while running, rather than a spinner.

| Command | What it does |
|---|---|
| `vulcan update` | Pulls the latest images and recreates containers |
| `vulcan pull` | Pulls images without starting anything |
| `vulcan backup` | Archives `stack/config/` + `docker-compose.yml`/`.env` to `backups/` |
| `vulcan restore [file]` | Restores `config/`, `docker-compose.yml`, and `.env` from a backup archive |
| `vulcan uninstall` | Stops the stack and deletes `stack/` entirely — back to a clean slate |

`vulcan update` is the on-demand alternative to Heavy tier's Watchtower (which updates continuously on its own) — useful for every other tier, for a cron job, or to force an update right now instead of waiting for the next poll. It confirms before touching anything running (`--non-interactive --yes` for scripted use).

`vulcan pull` is `vulcan update`'s pull step on its own, with nothing recreated or restarted — run it (or select "Pull Images" from the guided menu's Main Menu) while you have a connection to prepare a stack you'll start later somewhere offline. Needs no confirmation, since it touches nothing running.

`vulcan backup` needs no confirmation either — it only ever adds a new timestamped archive under `backups/` (gitignored, like `stack/`), and it's safe to run while your stack is up: any live SQLite database (Radarr/Sonarr/Jellyfin/etc.) is snapshotted consistently rather than archived mid-write. The archive includes `stack/.env`, which may hold real credentials, so store it securely.

`vulcan restore` reverses a backup: it defaults to the most recent archive in `backups/` if you don't pass a specific file, stops the currently running stack first (if there is one) so extraction can't race with a container actively using its own config directory, then extracts over what's there now — genuinely destructive, so it confirms before touching anything, same as every other mutating command.

`vulcan uninstall` is the reverse of a plain install: it stops the running stack and deletes `stack/` (containers, network, and all app config/data) so you can run `./install` again as if nothing was ever there — handy for testing, or for tearing a stack down for good. It never touches your media library, and leaves `backups/`/`exports/` alone unless you also pass `--purge-artifacts`. Pass `--prune-docker` to also run `docker system prune -a` afterward and reclaim disk space — this is opt-in and asked separately (its own confirmation, defaulting to No) because it affects the *whole* Docker host's stopped containers, unused networks, dangling images, and build cache, not just vulcan's own.

## Sharing a stack's shape (plans)

```bash
vulcan plan export my-plan.json
vulcan build --from-plan my-plan.json --non-interactive --yes
```

`vulcan plan export` writes the current stack's tier, enabled services, domain/routing settings, and PUID/PGID/timezone to a plain JSON file — **never credentials**, those stay in `stack/.env`, generated separately by `vulcan configure`. Safe to commit to a repo or hand to someone else.

`vulcan build --from-plan <file>` uses that file exactly the way a re-run on the same machine already uses `.vulcan-state.json`: every field in the plan is a *default*, and any explicit flag on the command (`--tier`, `--media-path`, `--services`, `--domain`, …) overrides the plan's value for that one field. On a fresh machine you'll usually still pass `--media-path` — the plan's own path is just what it was on the machine it was exported from.

## Updating Vulcan itself

```bash
vulcan update-self
```

Different from every command above — this updates *Vulcan's own checkout*, not a generated stack. A plain fast-forward `git pull` against `origin/main`, never a force or reset: if your local checkout has diverged (uncommitted changes, local commits), it refuses cleanly and tells you why rather than discarding anything. Reinstalls dependencies afterward the same way `./install` does on first run. Also reachable from the guided menu's Main Menu ("Update Vulcan").

## Airgap / Offline Installs

Vulcan assumes internet access by default, but moving a stack to a machine that has none is covered:

| Command | What it does |
|---|---|
| `vulcan export [--output PATH]` | Bundles already-pulled images into a tarball (`exports/`) |
| `vulcan import [FILE]` | Loads images from that tarball on another machine |

Install Docker ahead of time on a machine with no connection (Vulcan's automatic install needs one); Phase 0 detects an already-installed Docker and skips the install step regardless.

`vulcan export` packages a stack's already-pulled images (run `vulcan pull` first) into a single tarball under `exports/`; `vulcan import` loads that tarball's images on a different machine — one that's never been online at all, unlike `vulcan pull`, which still needs a live connection on the same machine it's run on. Neither needs confirmation, and `import` defaults to the most recent file in `exports/` if you don't pass one, the same convenience `restore` already offers for backups.
