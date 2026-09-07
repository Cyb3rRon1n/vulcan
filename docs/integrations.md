# Optional Integrations

All of these require [custom mode](tiers.md#custom-mode) (an explicit `--services` list) rather than a plain tier pick — see that page for why.

## Domain-based routing (Traefik)

If `traefik` is part of your custom selection, pass `--domain` to get real `<service>.<domain>` routing (e.g. `jellyfin.media.example.com`) for every included web-facing service, instead of Traefik's default do-nothing skeleton:

```bash
./install --plain --tier heavy --services jellyfin,radarr,sonarr,traefik --domain media.example.com --non-interactive --yes --media-path /mnt/media
```

HTTPS uses Traefik's own auto-generated self-signed certificate by default — real routing and encryption with zero external setup, at the cost of a browser trust warning on first visit. Vulcan doesn't create DNS records for you; point each subdomain at this host yourself. qBittorrent isn't routed when Gluetun is also enabled, since it shares Gluetun's network namespace in a way Traefik can't discover. Traefik's own routing dashboard is also enabled at `https://traefik.<domain>` — protected by Authelia automatically if it's also active, otherwise Vulcan warns that it's reachable with no login in front of it.

## Real Let's Encrypt certificates via Cloudflare DNS

If your domain's DNS is managed by Cloudflare, add `--cloudflare-dns` (with `--cloudflare-email`) to get real, trusted certificates instead of Traefik's self-signed default — no browser warning, no port-forwarding required (DNS-01 challenges don't need one):

```bash
./install --plain --tier heavy --services jellyfin,radarr,sonarr,traefik --domain media.example.com --cloudflare-dns --cloudflare-email you@example.com --non-interactive --yes --media-path /mnt/media
```

You'll need a scoped Cloudflare API token (`Zone:DNS:Edit` on your domain's zone) filled into `stack/.env` (`CF_DNS_API_TOKEN`) before this actually issues anything — Vulcan reminds you after generating, the same "never invent a secret, always tell you what's needed" pattern every other credential in this project follows. For the actual token-creation and DNS-record steps (Vulcan doesn't create either for you), see [the walkthrough's "Reaching everything remotely" section](walkthrough.md#reaching-everything-remotely).

## No forwarded ports at all (Cloudflare Tunnel)

Add `cloudflared` alongside `traefik` in a custom selection to reach your stack from the internet without forwarding ports 80/443 from your router at all — an outbound-only connection from your host to Cloudflare's edge, instead of the router accepting inbound connections. It points at Traefik as its single upstream, so every existing router/TLS/middleware decision (Authelia, CrowdSec, per-service routing) keeps working unchanged; nothing is duplicated or bypassed.

```bash
./install --plain --tier heavy --services jellyfin,radarr,sonarr,traefik,cloudflared --domain media.example.com --non-interactive --yes --media-path /mnt/media
```

Needs a real Tunnel token (`TUNNEL_TOKEN` in `stack/.env`) from the Zero Trust dashboard's Networks → Tunnels → Create a tunnel → Docker tab, and a Public Hostname added there: Service type `HTTPS`, URL `traefik:8081` (an internal tunnel-only entrypoint), with **No TLS Verify** turned on under the hostname's TLS settings (Traefik serves a self-signed cert there and every router requires TLS — a plain `HTTP` service URL 404s). Cloudflare's edge still terminates the *public* TLS; this is only the internal hop. Unlike the direct port-forward path above, DNS is dashboard-managed: adding a Public Hostname creates its own DNS record, no manual A record needed. Additive, not a replacement — Traefik's `80`/`443` host ports stay published for LAN access either way. Full steps: [the walkthrough's "Reaching everything remotely" section](walkthrough.md#reaching-everything-remotely).

!!! warning "Not yet run against a real tunnel"
    This is a real, tested compose/env change (`stack/docker-compose.yml` generation, `.env` credential handling), but has never been verified end-to-end against a live Cloudflare account and domain — the same real-infrastructure-verification gap the [Roadmap](roadmap.md) tracks project-wide. If something doesn't match what's documented here, that's the likely reason.

### Cloudflare Access (Zero Trust) setup for family

With a Cloudflare Tunnel running, you can protect every service behind Cloudflare Access (Zero Trust) so no one on the internet can reach them — not even your Traefik-routed ports — until they authenticate through your Cloudflare team's identity provider. This is the recommended way to give family members remote access: no VPN apps on their phones, no port-forwarding from your router, and every login logged in your Zero Trust dashboard.

**What to do in Cloudflare (after your tunnel is running):**

1. Go to **Zero Trust Dashboard > Access > Applications > Add an application**
2. Choose **Self-hosted**, name it (e.g. `Jellyfin`)
3. Set the application domain to the service's subdomain (e.g. `jellyfin.yourdomain.com`)
4. Under **Policy**, add a rule: Emails → your family member's email address (or any `@yourfamilydomain.com` pattern)
5. Repeat for each service you want family to reach (Seerr, Jellyfin are typical; Radarr/Sonarr you probably only want yourself accessing)

Family members will see a Cloudflare login page before reaching the actual app — the same zero-trust principle you see at your employer. No VPN apps needed, no phones need configuration, and every access is logged.

!!! note "Traefik's own login vs Cloudflare Access"
    These are complementary, not alternatives. Cloudflare Access authenticates at the edge (before traffic ever reaches your server). Traefik/Authelia authenticates at the server level. For family access to Jellyfin/Seerr, Cloudflare Access alone is sufficient — you can skip Authelia's own login for those specific services if the UX of two login screens back-to-back is too much.

## Private remote access (Tailscale)

Add `tailscale` to your custom selection for access to every host-published port in your stack from anywhere, with zero public exposure and no port-forwarding — a real alternative to Traefik+domain routing when you'd rather not expose anything to the public internet at all, or a complement to it for services you'd rather keep private. Needs a real auth key (`TS_AUTHKEY` in `stack/.env`, generated at [login.tailscale.com/admin/settings/keys](https://login.tailscale.com/admin/settings/keys)) before it connects. Runs with host networking, so once it's authenticated, every service's existing host-published port (Jellyfin at `:8096`, Radarr at `:7878`, etc.) is reachable from any device on your tailnet at this host's Tailscale address — no per-service setup needed.

Tailscale and **Gluetun can run together**: Gluetun is container-scoped (only qBittorrent routes through the VPN, the host routing table is untouched), Tailscale is host-level for inbound access. When Pi-hole or AdGuard Home is also enabled, Vulcan sets `TS_ACCEPT_DNS=false` so Tailscale's MagicDNS doesn't replace the host resolver you just set up.

## Auth (Authelia)

Add `authelia` alongside `traefik` in a custom selection to put a real login in front of every routed service — no LDAP, Postgres, or Redis required, and no external identity provider. You'll be prompted for an admin username/password (once — a regenerate never re-asks if it's already configured), and Vulcan handles hashing it and generating the random secrets Authelia needs itself. Without Traefik+`--domain` also active, Authelia has nothing to protect and its own login portal isn't reachable — Vulcan warns outright rather than pretending it did something.

### RBAC (admin vs. media-only users)

When `--domain` is active, Authelia enforces role-based access control: the admin user (the one you created during install) has full access to every service, while additional users in the `media` group can only reach Jellyfin and Seerr — Radarr, Sonarr, Traefik dashboard, Uptime Kuma, and every other management service are blocked.

Vulcan doesn't create management accounts on every service individually (each service has its own auth model); Authelia's RBAC is the single layer that decides who sees what. The admin group (`group:admin`) can reach everything; the media group (`group:media`) is scoped to exactly Jellyfin + Seerr.

!!! note "Why Jellyfin and Seerr are outside Authelia"
    Jellyfin's native apps (mobile, TV, smart-TV) can't complete a browser-redirect login flow, so Jellyfin and Seerr are deliberately excluded from Authelia's forwardAuth middleware — their own login is the real protection layer. RBAC only governs the management services that *are* routed through Authelia.

### Multi-user setup

Pass `--auth-users` to add additional Authelia users at install time:

```bash
./install --plain --tier heavy --services traefik,authelia,cloudflared,jellyfin,seerr,radarr,sonarr --domain media.example.com --auth-username admin --auth-password 'yourpassword' --auth-users 'friend:friendpass:media' --non-interactive --yes
```

Format: `username:password:group` (comma-separated for multiple users). The `group` is either `admin` (full access to all services) or `media` (Jellyfin + Seerr only). Passwords are hashed automatically — you never see plaintext storage of them.

To add users after install, either re-run with `--auth-users` or edit `stack/config/authelia/users_database.yml` directly — both are identical YAML, and a re-run never overwrites the admin account.

See also: [Cloudflare Access](#cloudflare-access-zero-trust-setup) for giving family members zero-trust remote access without VPN apps.

## Intrusion protection (CrowdSec)

Add `crowdsec` alongside `traefik` in a custom selection to block malicious IPs at the edge, before they ever reach a login page — Authelia protects the door once someone's inside, CrowdSec protects the door itself. It watches Traefik's own access log and uses [CrowdSec's](https://www.crowdsec.net/) community-sourced blocklist (via the official [Traefik bouncer plugin](https://github.com/maxlerebourg/crowdsec-bouncer-traefik-plugin)) to block requests from IPs with a bad reputation, on every routed service — including Jellyfin and Vaultwarden, which deliberately skip Authelia (their native apps can't complete a browser-redirect login) but aren't exempt from this, since IP-reputation blocking doesn't share that conflict. No credential to fill in: Vulcan generates a real, random shared key between Traefik and CrowdSec itself. Without Traefik+`--domain` also active, there's no routed traffic for it to protect yet.

!!! warning "A real, known gotcha, not hidden"
    Traefik downloads the bouncer plugin from its own plugin catalog on first start — a separate step from CrowdSec's own container, which starts and works independently of it. This has been observed to fail (even for Traefik's own official demo plugin, confirmed by testing it directly) when Traefik's plugin catalog service itself is having problems — check `docker compose logs traefik` for a "Plugins are disabled" error if requests aren't being filtered; this is an external service issue, not something CrowdSec or Vulcan controls.

## Password manager (Vaultwarden)

A lightweight, Bitwarden-compatible server for every credential this stack generates, with the official Bitwarden apps working against it unmodified. Not routed through Authelia even if enabled, same reason as Jellyfin (native apps can't complete a browser-redirect login).

## Pre-seeded dashboard (Homepage / Dashy)

If Homepage or Dashy is included, it boots with real tiles for every other web-facing service already in your stack — correct icon, correct link (routed through Traefik if you've set up domain-based routing, otherwise your host's real LAN address), grouped by category (Media, Media Management, Downloads, Monitoring, Security, Infrastructure), and a brief one-line description under each tile so a service is identifiable at a glance, not just an icon and a name — instead of a blank dashboard you'd have to configure by hand. Only written once: if you've since customized the dashboard's config yourself, a later regenerate never touches it.

## Media automation (Decluttarr / Maintainerr / MeTube / Downtify)

- **Decluttarr** removes stalled or failed downloads from Radarr/Sonarr's queue and triggers a fresh search.
- **Maintainerr** cleans up unwatched media on your media server's own rules — complementary to Decluttarr, not overlapping.
- **MeTube** and **Downtify** (Spotify-sourced audio, no Premium account needed) handle on-demand grabs outside the `*arr` automation pipeline.

## Real-time monitoring (Netdata)

Live CPU/RAM/disk/network/temperature and per-container awareness, matched to its own official recommended configuration.

## Lightweight system monitor + dashboard widgets (Glances)

A single small container (`nicolargo/glances`, port 61208) exposing a REST API. Unlike Netdata it has a normal Docker-network identity, so it routes through Traefik/Authelia like any other service. Its real value is powering Homepage's per-metric `glances` widgets (CPU, RAM, disk I/O, top processes, temperature) — see the [Dashboard Widgets Guide](guides/homepage-widgets.md) for exact widget configs and what does/doesn't work in the default routed setup.

## Music streaming (Navidrome)

A lightweight, Subsonic-API-compatible music server (`deluan/navidrome`, port 4533) pointed read-only at `stack/media/music`. Any Subsonic-compatible client works against it unmodified (DSub, Substreamer, play:Sub, and others). Deliberately not routed through Authelia even if enabled, same reason as Jellyfin: every Subsonic client authenticates directly against `/rest/*` with its own query-string token, not a browser login, and Navidrome's own docs call out excluding that path from forward-auth for exactly this reason — its own login (created on first visit) is the real protection layer here instead. `crowdsec@docker` still applies since IP-reputation blocking isn't an auth challenge.

## Reading — comics, manga, ebooks (Komga, Kavita, Suwayomi, Mylar3, LazyLibrarian)

Five services under the **Reading** category, all optional, all sharing one tree under `stack/media/books` — `comics/` (Mylar3), `manga/` (Suwayomi + hand-added), `ebooks/` (LazyLibrarian). Komga reads all three; Jellyfin's book library sees the lot. The generator creates the three subfolders when any reading service is enabled.

**Komga** (`gotson/komga`, port 25600) pointed read-only at `stack/media` — a comic/manga/ebook library server with a strong web reader and an OPDS feed for mobile apps (Mihon/Tachiyomi, Paperback, Panels). It runs as `PUID:PGID` directly (no s6-overlay) so it needs **zero** added capabilities under `cap_drop: ALL`. Deliberately **not** routed through Authelia, same reasoning as Navidrome: the OPDS clients authenticate directly against Komga with their own credentials, not a browser forward-auth redirect, and Komga has real multi-user auth of its own. `crowdsec@docker` still applies.

**Kavita** (`lscr.io/linuxserver/kavita`, port 5000) pointed read-only at `stack/media/books` — a reader server with broader format support and a native ebook reader with reading progress. Like Komga it has its own mandatory multi-user auth plus an OPDS feed, so it's also kept out of `authelia@docker` (crowdsec only). Komga vs Kavita is a preference call — both can run at once.

**Suwayomi** (`ghcr.io/suwayomi/suwayomi-server:stable`, port 4567) — a self-hosted Tachiyomi/Mihon server: browse online manga sources through community extensions, read in the browser, favourite, and download chapters to disk as CBZ (into `media/books/manga`, so Komga serves the kept library). Non-root JVM run as `PUID:PGID`, **zero** caps under `cap_drop: ALL`. It has **no sources out of the box** — add an extension repo under Settings → Browse → Extension Repos (e.g. `https://raw.githubusercontent.com/keiyoushi/extensions/repo/index.min.json`), then install sources under Browse → Extensions. Its own login is optional and **off by default**, so unlike Komga/Kavita it keeps `authelia@docker` in front. To run it as a public reader instead: set `server.authMode = "UI_LOGIN"` (plus a username/password) in `stack/config/suwayomi/server.conf`, then drop `authelia@docker` with a `docker-compose.override.yml` stanza:

```yaml
services:
  suwayomi:
    labels:
      traefik.http.routers.suwayomi.middlewares: "crowdsec@docker"
```

If Suwayomi is in the stack alongside FlareSolverr, the generator wires `FLARESOLVERR_URL` automatically so Cloudflare-guarded sources work.

**Mylar3** (`lscr.io/linuxserver/mylar3`, port 8090) with a read-write mount of the whole media path — the "Sonarr for comics": tracks series and auto-downloads new issues through Prowlarr and your torrent client, writing ComicInfo.xml into each `.cbz`. It's a management tool (admin-only under Authelia RBAC), not a reader. The LSIO image writes `http_host = localhost` on first run (loopback only — published port unreachable), so the generator pre-seeds `config/mylar3/mylar/config.ini` with `http_host = 0.0.0.0` before first start. Wire it up: Prowlarr → Settings → Apps → Mylar; then Mylar → Configuration → Download Settings → point at qBittorrent/SABnzbd; set Comic Location to `/data/media/books/comics`. GetComics DDL (Configuration → Download Settings) is Mylar's best free source and needs no indexer. Same 5-cap linuxserver.io pattern as the *arr apps.

**LazyLibrarian** (`lscr.io/linuxserver/lazylibrarian`, port 5299, read-write media mount) — ebook/audiobook/magazine PVR, the maintained stand-in for Readarr (which is abandoned upstream and breaks against qBittorrent 5.x). Tracks authors and series, pulls metadata from GoodReads/OpenLibrary/Google Books, and auto-downloads through Prowlarr + your download client. Admin-only under Authelia RBAC, same 5-cap linuxserver.io pattern. Wire it up: enable its API (Config → Interface), add it in Prowlarr (Settings → Apps → LazyLibrarian), set the download client under Config → Downloaders, and set the book API to OpenLibrary (its default GoodReads key is dead). Optional linuxserver `DOCKER_MODS` add Calibre for format conversion.

## Music via Soulseek (slskd + Lidarr plugin)

Public music torrents are effectively dead, so **slskd** (`slskd/slskd`, port 5030) brings in Soulseek. It runs standalone as a browse-and-download web UI, and Lidarr can search/grab through it via a plugin. Admin download tool → behind Authelia, same as the *arrs. Runs as `PUID:PGID`, **zero** caps under `cap_drop: ALL`.

The generator pre-seeds `stack/config/slskd/slskd.yml` with a generated web password (`admin` / see the file), a generated API key for the Lidarr plugin, a read-only share of `media/music`, and `CHANGEME` Soulseek credentials — **open the file and set `soulseek.username` / `soulseek.password`** (any unused username auto-registers on first connect). Downloads land in `media/downloads/slskd/complete`.

To let **Lidarr** search Soulseek:

1. Pin Lidarr to the plugins branch — `lscr.io/linuxserver/lidarr:nightly` (or `ghcr.io/hotio/lidarr:nightly`). **This is a one-way DB migration** — back up `stack/config/lidarr` first; you can't return to `latest`/`master` without that backup.
2. System → Plugins → install `https://github.com/allquiet-hub/Lidarr.Plugin.Slskd`, restart.
3. Add **slskd** as a download client (Settings → Download Clients) *and* an indexer (Settings → Indexers) — host `slskd`, port `5030`, API key = the `api_keys` value from `slskd.yml`.

LazyLibrarian also has a Soulseek provider that can point at the same slskd, but Soulseek is weak for prose ebooks — it's mainly useful there for audiobooks.

## Tougher Cloudflare solving (Byparr)

**FlareSolverr** (`flaresolverr`, port 8191) is the built-in indexer proxy: add it in Prowlarr under Settings → Indexers → Indexer Proxy, tag the indexers that need it. It's only lightly maintained now and can't get past some current Cloudflare/Turnstile challenges.

**Byparr** is a drop-in replacement — same `/v1` API, Camoufox-based. It isn't a first-class Vulcan service because its headless browser needs a relaxed container sandbox (it won't run under `cap_drop: ALL` + `no-new-privileges`, which every generated service uses). Add it via `docker-compose.override.yml`:

```yaml
services:
  byparr:
    image: ghcr.io/thephaseless/byparr:latest
    container_name: byparr
    environment:
      - TZ=${TZ}
    shm_size: 2gb          # Camoufox crashes mid-solve with the 64M default
    restart: unless-stopped
```

Then point Prowlarr's FlareSolverr indexer proxy at `http://byparr:8191/` (the proxy attaches to indexers by tag — make sure each Cloudflare-guarded indexer carries that tag). Update `FLARESOLVERR_URL` for Suwayomi and `flaresolverr_url` in Mylar's config the same way. You can leave the `flaresolverr` container running or untick it — nothing else depends on it.

## Web file manager (FileBrowser)

Browser-based file manager for the media library, mounted at `/srv`. When Homepage is also enabled, `stack/config/homepage/` is additionally mounted read-write at `homepage-config/` — the easiest way to edit Homepage's YAML (tiles, widgets, layout) without SSH. Never mounts the rest of `stack/config/` (Authelia secrets, VPN keys live there).

## Container management (Portainer)

A web UI for the containers themselves — start/stop/restart, read logs, exec into a shell, redeploy from an edited compose file. Complements, not replaces, Vulcan's own lifecycle commands: `docker-compose.yml` is regenerated by `vulcan build` every time, so an edit made through Portainer's own stack editor is overwritten on the next build. Use Portainer for day-to-day container operations; use `vulcan build --services ...` to add or remove services. **First login locks after ~5 minutes if no admin account is created** — if you see a setup screen after that window, `docker restart portainer` to reset the timer.

## Stream analytics (Tracearr)

Real-time stream analytics for Jellyfin/Plex/Emby — a modern replacement for Tautulli and Jellystat. The `supervised` image bundles its own PostgreSQL and Redis, so no extra database containers are needed. Point it at your media server's URL on first access (`http://<host>:3000`) and it begins tracking views, sessions, and bandwidth immediately.

## DNS ad-blocker (Pi-hole + Unbound)

Pi-hole (v6) provides DNS-level ad blocking across your entire network, with Unbound as a recursive resolver so you don't depend on any upstream DNS provider. Pi-hole's web UI is exposed on port 8053 (not 80, to avoid conflicting with Traefik if both are enabled); Pi-hole shares Unbound's container network namespace, so from inside the Docker network it's reachable at `http://unbound` (not `http://pihole`).

**To use Pi-hole as your network's DNS server:**

1. Set your router's DHCP DNS option to point at this host's IP (e.g. `192.168.1.100#53` or just the IP if Pi-hole listens on port 53)
2. Or configure each device manually to use this host's IP as its DNS server
3. Access the Pi-hole admin panel at `http://<host>:8053`, log in with `PIHOLE_WEBPASSWORD` from `stack/.env`

When Traefik is also enabled with a domain, Pi-hole is routed at `pihole.<domain>`.

## Alternative DNS ad-blocker (AdGuard Home)

A DNS-level ad blocker like Pi-hole, with a different UI and built-in per-client stats — pick one or the other, not both (they'd fight over port 53). Also binds `:53` directly (no separate resolver container the way Pi-hole+Unbound does).

## Sports automation (Sportarr)

A PVR for sports — monitors leagues and events, automatically downloads match replays and highlights via your existing download clients (qBittorrent/SABnzbd + Prowlarr). Exposed on port 1867.

## IPTV live TV (Threadfin)

An M3U/IPTV proxy that emulates an HDHomeRun tuner, giving Jellyfin/Plex/Emby live TV support without physical tuner hardware. Point it at your M3U playlist URL and it handles buffering, channel mapping, and EPG integration. Exposed on port 34400.
