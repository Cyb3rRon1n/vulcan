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

## Stream analytics (Tracearr)

Real-time stream analytics for Jellyfin/Plex/Emby — a modern replacement for Tautulli and Jellystat. The `supervised` image bundles its own PostgreSQL and Redis, so no extra database containers are needed. Point it at your media server's URL on first access (`http://<host>:3000`) and it begins tracking views, sessions, and bandwidth immediately.

## DNS ad-blocker (Pi-hole + Unbound)

Pi-hole provides DNS-level ad blocking across your entire network, with Unbound as a recursive resolver so you don't depend on any upstream DNS provider. Pi-hole's web UI is exposed on port 8053 (not 80, to avoid conflicting with Traefik if both are enabled).

**To use Pi-hole as your network's DNS server:**

1. Set your router's DHCP DNS option to point at this host's IP (e.g. `192.168.1.100#53` or just the IP if Pi-hole listens on port 53)
2. Or configure each device manually to use this host's IP as its DNS server
3. Access the Pi-hole admin panel at `http://<host>:8053/admin`

When Traefik is also enabled with a domain, Pi-hole is routed at `pihole.<domain>`.

## Sports automation (Sportarr)

A PVR for sports — monitors leagues and events, automatically downloads match replays and highlights via your existing download clients (qBittorrent/SABnzbd + Prowlarr). Exposed on port 1867.

## IPTV live TV (Threadfin)

An M3U/IPTV proxy that emulates an HDHomeRun tuner, giving Jellyfin/Plex/Emby live TV support without physical tuner hardware. Point it at your M3U playlist URL and it handles buffering, channel mapping, and EPG integration. Exposed on port 34400.
