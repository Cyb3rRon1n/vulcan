# Post-install walkthrough

Vulcan generates and starts your stack, but every app still needs its own
one-time setup - accounts, API keys, connecting apps to each other. This is
the order to do that in. Later steps depend on earlier ones being done
first, so working top to bottom avoids a lot of "why isn't this working"
detours (e.g. Radarr can't do anything useful until Prowlarr has indexers,
and qBittorrent needs a real login before anything else should touch it).

Skip any section for a service you didn't enable - your guided-menu/CLI run
also printed a copy of this same order, trimmed to just what you actually
enabled, right after the stack came up.

!!! note "Representative mockups, not literal captures"
    The screenshots below are hand-built to show the shape of each screen,
    not pixel-accurate captures of the real apps - the real UI you'll see
    will differ in layout and styling.

## 1. Vaultwarden - do this first

If you enabled it: visit it and create your account before touching
anything else below. Every login, password, and API key you create for the
rest of this walkthrough goes here as you create it - it's much easier to
save each one in the moment than to try to gather them all after the fact.

<p align="center">
  <img src="images/screenshots/vaultwarden-signup.svg" alt="Vaultwarden account creation example" style="max-width: 100%; width: 820px;">
</p>

**Browser extension** (so it can save/fill credentials as you go through the
rest of this walkthrough) - official store listings, confirmed current via
`bitwarden.com/download`'s own outbound links:

- **Chrome / Brave / Vivaldi**: https://chromewebstore.google.com/detail/bitwarden-free-password-m/nngceckbapebfimnlniiiahkandclblb
- **Firefox**: https://addons.mozilla.org/en-US/firefox/addon/bitwarden-password-manager/
- **Edge**: https://microsoftedge.microsoft.com/addons/detail/jbkfoedolllekgbhcbcoahefnbanhhlh
- **Opera**: https://addons.opera.com/extensions/details/bitwarden-free-password-manager/
- **Safari**: no standalone extension listing - install the Bitwarden desktop app (Mac App Store, or `bitwarden.com/download`), which bundles the Safari extension and lets you enable it from Safari's own Extensions settings

After installing: Settings → gear icon → Self-hosted → set the Server URL to
`http://<your-ip>:8222` **before** logging in, then log in with the account
you just created.

Once you've created every account you need, set `VAULTWARDEN_SIGNUPS_ALLOWED=false`
in `stack/.env` and restart the container to stop accepting new signups.

Vaultwarden is deliberately **not** routed through Authelia even if you
enabled Authelia too - see "A note on Authelia" below for why. Its own
master password (and its own optional two-factor authentication, worth
turning on) is the real protection layer for this one service.

## 2. Authelia

If you enabled it: your admin login was already created during install -
you set the username/password yourself when Vulcan asked. Save that login
in Vaultwarden now.

Authelia protects every other Traefik-routed service in this stack with a
real login and brute-force lockout - you shouldn't need to touch its own
configuration again unless you want to add more user accounts
(`stack/config/authelia/users_database.yml`).

## 3. Prowlarr

If you enabled it: add your indexers first. Radarr, Sonarr, Lidarr, and
Readarr all search *through* Prowlarr, not on their own, so nothing else in
this stack can find anything until this step is done.

Settings > Indexers > Add Indexer, for each tracker/indexer you use.

## 4. Radarr / Sonarr / Lidarr / Readarr

For each one you enabled:

1. Settings > Indexers > Sync with Prowlarr (or add Prowlarr as an
   indexer source directly - Prowlarr's own docs cover both).
2. Settings > Media Management, confirm the root folder points at your
   media library (already mounted correctly by Vulcan, just confirm it).
3. Settings > General, copy the API key - save it in Vaultwarden. You'll
   need it again for Recyclarr, Decluttarr, or Jellyseerr if you enabled
   those.

## 5. qBittorrent / SABnzbd

Set a real login on first visit (not the container image's documented
default) - save it in Vaultwarden. Then connect each *arr app above to it:
Settings > Download Clients > Add.

If Gluetun is enabled, qBittorrent shares its network namespace - the
connection settings work the same either way, just confirm step 6 below is
actually connected first.

SABnzbd additionally needs your Usenet provider's server details entered
through its own setup wizard before it can download anything.

## 6. Gluetun

If you enabled it, `stack/.env` has three placeholder values that need your
real VPN credentials before Gluetun can connect at all -
`VPN_SERVICE_PROVIDER`, `VPN_TYPE` (defaults to `wireguard`), and
`WIREGUARD_PRIVATE_KEY`. A fourth, `WIREGUARD_ADDRESSES`, is only required
by some providers (noted below) - leave it blank otherwise.

These two work with just `WIREGUARD_PRIVATE_KEY` (no `WIREGUARD_ADDRESSES`
needed):

- **ProtonVPN** - `VPN_SERVICE_PROVIDER=protonvpn`. Generate a config at
  [account.proton.me/u/0/vpn/WireGuard](https://account.proton.me/u/0/vpn/WireGuard)
  and copy the `PrivateKey` value shown - it works for all ProtonVPN
  servers, not just the one you generated it for.
- **NordVPN** - `VPN_SERVICE_PROVIDER=nordvpn`. Get your WireGuard private
  key from [my.nordaccount.com](https://my.nordaccount.com/dashboard/nordvpn/manual-configuration/service-credentials/)
  (NordVPN's manual/service credentials, not your regular account
  login).

These two also need `WIREGUARD_ADDRESSES` set (the IPv4 address from your
generated config's `Address` line, e.g. `10.64.222.21/32`):

- **Mullvad** - `VPN_SERVICE_PROVIDER=mullvad`. Generate a config at
  [mullvad.net/en/account/wireguard-config](https://mullvad.net/en/account/wireguard-config),
  download it, and pull `PrivateKey` and `Address` from the file - not the
  "Wireguard Key" shown on the Devices page, that's a different value.
- **Surfshark** - `VPN_SERVICE_PROVIDER=surfshark`. In your account:
  VPN → Manual Setup → Desktop or mobile → WireGuard → "I don't have a
  keypair" → generate one, then download the config for the `Address` value.

Other providers Gluetun supports (OpenVPN-only ones, or ones needing extra
env vars this stack doesn't wire up yet): see
[gluetun-wiki's provider list](https://github.com/qdm12/gluetun-wiki/tree/main/setup/providers) -
each page has the exact env vars and where to get them.

Once `stack/.env` is filled in, restart the stack (`sudo vulcan update`, or
`docker compose -f stack/docker-compose.yml up -d --force-recreate gluetun`
for just this container) and confirm the tunnel actually connected before
trusting qBittorrent's traffic -

```
docker compose -f stack/docker-compose.yml logs gluetun
```

qBittorrent has no network access at all if Gluetun can't connect (that's
the point - it fails closed, not open), so a stalled download queue here
usually means check this first.

<p align="center">
  <img src="images/screenshots/gluetun-log.svg" alt="Gluetun connection log example" style="max-width: 100%; width: 820px;">
</p>

## 7. Bazarr

If you enabled it: connect it to Radarr and/or Sonarr (Settings >
Radarr/Sonarr) once they have some content in their libraries - Bazarr
searches for subtitles against what's already tracked there.

## 8. Jellyfin

Create your library folders (Dashboard > Libraries > Add Media Library) -
one per content type, pointed at the matching folder under
`/data/media` inside the container.

Then, **enable Jellyfin's own two-factor authentication**
(Dashboard > My Profile). This matters more here than for any other
service in this stack: even with Authelia enabled, Jellyfin is
deliberately excluded from it (see "A note on Authelia" below), so its own
login is the real, only protection in front of it.

## 9. Jellyseerr

If you enabled it: connect it to Jellyfin (for your library) and to
Radarr/Sonarr (so requests actually get fulfilled) through its own setup
wizard.

## 10. Recyclarr / Decluttarr / Maintainerr

Configure these last, once Radarr/Sonarr are already connected to Prowlarr
and downloading successfully - all three sit on top of a working *arr
setup rather than replacing any part of it.

### Recyclarr

Needs each app's real API key and base URL added to
`stack/config/recyclarr/recyclarr.yml`.

### Decluttarr

Decluttarr watches Radarr/Sonarr's download queue and automatically removes
stalled downloads, failed downloads, and bad files, then triggers a fresh
search for each one it removes. It sits on top of your existing *arr setup -
it doesn't replace any part of it, just keeps the queue clean so you don't
have to babysit failed grabs manually.

Vulcan pre-seeded a config at `stack/config/decluttarr/config.yaml` with the
correct base URLs for every *arr app you enabled. Each `api_key` is still a
`CHANGEME` placeholder - you need to fill those in before Decluttarr can
connect.

**Step 1: Get the API keys.** For each *arr app (Radarr, Sonarr, Lidarr,
Readarr) that you enabled, visit its web UI, go to Settings > General, and
copy the API key listed there. Save each one in Vaultwarden as you go.

**Step 2: Edit the config file.**

```
nano stack/config/decluttarr/config.yaml
```

The file looks like this (Radarr and Sonarr shown - Lidarr and Readarr follow
the same pattern if enabled):

```yaml
general:
  log_level: INFO
  test_run: true
  timer: 10

job_defaults:
  max_strikes: 3
  min_days_between_searches: 7
  max_concurrent_searches: 3

jobs:
  remove_bad_files:
  remove_failed_downloads:
  remove_stalled:

instances:
  radarr:
    - base_url: "http://radarr:7878"
      api_key: "CHANGEME"
  sonarr:
    - base_url: "http://sonarr:8989"
      api_key: "CHANGEME"

download_clients:
  qbittorrent:
    - base_url: "http://qbittorrent:8080"
      name: "qBittorrent"
```

Replace each `CHANGEME` with the real API key from that app's Settings >
General page. The `base_url` values are already correct (they use Docker's
internal hostnames, not your LAN IP) - leave them as-is.

If your qBittorrent WebUI has auth configured (it should, per section 5),
you can optionally add an `api_key` or `username`/`password` to the
`qbittorrent` entry under `download_clients` - Decluttarr will use it to
check download status. Without auth credentials there, Decluttarr can still
clean up stalled items at the *arr level but won't be able to verify status
directly with qBittorrent.

**Step 3: Understand what each option does.**

- `test_run: true` - dry run mode. Decluttarr logs what it *would* remove
  but doesn't actually remove anything. This is the safe default while you're
  confirming the config is right.
- `timer: 10` - how often (in minutes) Decluttarr checks the queue.
- `max_strikes: 3` - an item must fail this many times before Decluttarr
  removes it and searches again. Prevents removing items on a single flaky
  timeout.
- `min_days_between_searches: 7` - after Decluttarr removes an item and
  re-searches, it won't re-search the same title again for this many days.
  Prevents search loops on titles that genuinely have no available release.
- `max_concurrent_searches: 3` - limits how many re-searches run at once to
  avoid hammering your indexers.
- `jobs` - which cleanup jobs are active. All three are enabled by default:
  `remove_bad_files` (incomplete/missing files), `remove_failed_downloads`
  (download client reported failure), `remove_stalled` (no progress for a
  prolonged period).

**Step 4: Test it.** Restart the Decluttarr container to pick up the config
changes:

```
docker compose -f stack/docker-compose.yml restart decluttarr
```

Check the logs to confirm it connected successfully:

```
docker compose -f stack/docker-compose.yml logs decluttarr
```

Look for lines showing it found your Radarr/Sonarr instances and started
scanning the queue. Errors about invalid API keys mean you need to
double-check what you pasted in step 2.

**Step 5: Flip to live mode.** Once the logs confirm Decluttarr is connecting
to all your *arr apps and the logged removals look correct, edit the config
one more time and change `test_run: true` to `test_run: false`, then restart
the container again. Decluttarr will now actually remove items and trigger
re-searches.

### Maintainerr

Maintainerr cleans up media from your Jellyfin (or Plex/Emby) libraries
based on rules you define - for example, remove anything unwatched after 30
days, or remove an entire show once you've finished watching it. It works at
the *library* level (what's on your server and who has watched it), whereas
Decluttarr works at the *download queue* level (stalled or failed grabs).
They're complementary: Decluttarr keeps your download queue clean, Maintainerr
keeps your library clean.

Vulcan doesn't pre-seed any config for Maintainerr - it's entirely configured
through its own web UI.

**Step 1: Connect to Jellyfin.** Visit Maintainerr's web UI (the URL Vulcan
printed when the stack started - typically `http://<your-ip>:6246`, or
`maintainerr.<your-domain>` if Traefik is enabled). Walk through the setup
wizard:

1. Select **Jellyfin** as your media server (or Plex/Emby if that's what
   you're running instead).
2. Enter the Jellyfin server URL. From inside Docker, this is
   `http://jellyfin:8096` - the wizard may detect it automatically, or it may
   ask for your host's LAN IP (e.g. `http://192.168.1.100:8096`). Either
   works; the internal Docker address avoids routing issues.
3. Enter your Jellyfin username and password (or an API key from Jellyfin's
   Dashboard > API Keys).

**Step 2: Connect Radarr/Sonarr.** Still in the setup wizard:

1. Add a **Radarr** instance: URL `http://radarr:7878`, API key from
   Radarr's Settings > General page.
2. Add a **Sonarr** instance: URL `http://sonarr:8989`, API key from
   Sonarr's Settings > General page.
3. Add Lidarr/Readarr the same way if you enabled them.

These connections let Maintainerr delete media files through Radarr/Sonarr
(which handles removal from disk) rather than deleting them directly.

**Step 3: Create rules.** Once the wizard is complete, go to Rules and
create your first rule set. Each rule set targets a specific Jellyfin library
and defines conditions for what gets removed. Common patterns:

- **Unwatched movies**: Jellyfin library = Movies, condition = "last played
  more than 30 days ago" (or never played), action = remove.
- **Finished TV shows**: Jellyfin library = TV Shows, condition = "all
  episodes watched" and "last played more than 14 days ago", action =
  remove.
- **Storage-based**: condition = "library size exceeds X GB", action = remove
  oldest unwatched first.

Save each rule set, then enable it. Maintainerr runs its rules on a schedule
(configurable in Settings) and shows pending actions before executing them, so
you can review what it plans to remove before anything actually gets deleted.

## 11. MeTube / Downtify

If you enabled either: paste a URL to start a download, then add a
Jellyfin library pointed at their output folder so the result shows up
there automatically.

### MeTube

MeTube downloads YouTube videos and playlists. Downloads land in
`stack/media/youtube` on the host. To see them in Jellyfin, add a library
there (Dashboard > Libraries > Add Media Library, any content type works)
pointed at `/data/media/youtube`.

### Downtify

Downtify downloads tracks, albums, and playlists from Spotify and saves them
as local audio files. No Spotify Premium account is needed, and no API key -
just paste a Spotify track, album, or playlist URL into its web UI and it
downloads everything.

Downloads land in `stack/media/music/downtify` on the host, which sits
inside your existing Music library path - Jellyfin picks up the files
automatically with no new library needed. If Lidarr is also enabled, it may
flag this subfolder as unmapped files on its own library scans; that's
cosmetic, not destructive, since Lidarr never auto-imports or deletes
anything without confirmation.

Downtify's own image has no documented PUID/PGID support, so downloaded
files may land owned by root rather than your configured PUID/PGID like
every other service - Jellyfin's read-only mount is unaffected, but you may
need `sudo` to move or delete them directly on the host.

Paste a track, album, or playlist URL at Downtify's web UI (the URL Vulcan
printed when the stack started - typically `http://<your-ip>:8000`, or
`downtify.<your-domain>` if Traefik is enabled) to start a download.

## 12. Homepage / Dashy / Uptime Kuma / Netdata / Traefik dashboard

Check these last - they only have something to show once the services
above are actually running.

- **Homepage** and **Dashy** were both pre-seeded with tiles for
  everything you enabled, including a link back to this page (under
  "Guides") - Dashy is a second, more visually customizable dashboard
  option alongside Homepage, not a replacement; enable one or both. Dashy
  runs as a fixed container uid/gid (1000:1000, no PUID/PGID support) -
  if your own PUID/PGID differ, you may need `sudo` to edit
  `stack/config/dashy/conf.yml` directly on the host.
- **Uptime Kuma** needs a one-time account, then a monitor added per
  service you want to track.
- **Netdata** and the **Traefik dashboard** need no setup at all - both
  are ready to view as soon as their containers start.

<p align="center">
  <img src="images/screenshots/homepage-dashboard.svg" alt="Homepage dashboard example" style="max-width: 100%; width: 820px;">
</p>

## A note on Authelia

Authelia puts a real login in front of almost every routed service in this
stack - but not Jellyfin or Vaultwarden. Both are deliberately excluded,
for the same reason: Authelia's forward-auth login works by redirecting
your browser to a login page, and native apps (Jellyfin on a phone or
smart TV, the Bitwarden/Vaultwarden apps and browser extension) can't
complete that redirect - they expect to log in directly against the app's
own API instead. Putting Authelia in front of either one would just break
their native apps outright.

Everything else Vulcan routes (the *arr apps, download clients,
Jellyseerr, Homepage, dashboards) is a plain browser-only web UI with no
native-app login of its own, so Authelia protects all of those cleanly.

## Reaching everything remotely

- **Tailscale**, if enabled, puts every host-published port in this stack
  on your private tailnet - reachable from any of your own devices with no
  further setup, and nothing exposed publicly at all.
- **Traefik + a domain + Cloudflare DNS**, if enabled, is what makes
  `jellyfin.yourdomain.com` (or any other `*.yourdomain.com`) work from
  anywhere - a phone on cellular data, a smart TV app, a browser at a
  friend's house. Three things Vulcan doesn't do for you:

  1. **Get a scoped Cloudflare API token.** [dash.cloudflare.com/profile/api-tokens](https://dash.cloudflare.com/profile/api-tokens/)
     → Create Token → "Edit zone DNS" template → restrict it to your one
     domain → Create Token, then copy it (shown once) into `stack/.env`'s
     `CF_DNS_API_TOKEN`. This is what lets Traefik prove domain ownership
     to Let's Encrypt without opening any port for the challenge itself.
  2. **Add a DNS record for each subdomain you're routing** (Jellyfin,
     Jellyseerr, whatever else was in your `--services` list) - Cloudflare
     dashboard → your domain → DNS → Add record → type `A` → name
     `jellyfin` (etc.) → content = this host's public IP.
  3. **Decide proxy status per record** - this is the actual "hide my
     public IP" switch, not a DNS server choice: orange cloud (Proxied)
     routes through Cloudflare's edge, so your real IP never appears in a
     public DNS lookup; grey cloud (DNS only) publishes it directly.
     Either way, ports 80/443 still need to reach this host from your
     router (port forward, or your ISP already routes them) - Cloudflare's
     proxy hides *who* traffic came from publicly, it doesn't tunnel
     traffic in without a real path to the host. That's what Cloudflare
     Tunnel (below) is for.
- **Cloudflare Tunnel** (`cloudflared`, alongside `traefik`), if enabled, skips
  port-forwarding entirely - an outbound-only connection to Cloudflare's edge,
  no inbound port needed on your router at all.

  1. **Create the tunnel.** Zero Trust dashboard → Networks → Tunnels →
     Create a tunnel → name it → Docker environment → copy the token from
     the run command shown (just the token, not the whole command) into
     `stack/.env`'s `TUNNEL_TOKEN`.
  2. **Add a Public Hostname**, same screen: subdomain + your domain →
     Service type `HTTP` → URL `traefik:8081` (Vulcan's internal
     tunnel-only entrypoint - plain HTTP is correct here, Cloudflare's edge
     already terminated public TLS by the time traffic reaches it). One
     wildcard hostname (`*.yourdomain.com`) covers every routed service at
     once; per-subdomain hostnames work too if you'd rather be explicit.
  3. **No DNS record step needed** - unlike the direct port-forward path
     above, adding a Public Hostname creates its own DNS record
     automatically.
  4. Restart the stack (`sudo vulcan update`) once `TUNNEL_TOKEN` is filled
     in, then `docker compose -f stack/docker-compose.yml logs cloudflared`
     to confirm it connected.

  Traefik's `80`/`443` ports stay published either way - this adds a
  second, port-forward-free path to the same Traefik, it doesn't replace
  the direct one.

Both can be enabled together - Tailscale for your own admin access
(Homepage, Traefik's dashboard, anything you'd rather keep off the public
internet entirely), Traefik+domain for the one or two services (Jellyfin,
Jellyseerr) you actually want reachable by other people.
