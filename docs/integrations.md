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

## Private remote access (Tailscale)

Add `tailscale` to your custom selection for access to every host-published port in your stack from anywhere, with zero public exposure and no port-forwarding — a real alternative to Traefik+domain routing when you'd rather not expose anything to the public internet at all, or a complement to it for services you'd rather keep private. Needs a real auth key (`TS_AUTHKEY` in `stack/.env`, generated at [login.tailscale.com/admin/settings/keys](https://login.tailscale.com/admin/settings/keys)) before it connects. Runs with host networking, so once it's authenticated, every service's existing host-published port (Jellyfin at `:8096`, Radarr at `:7878`, etc.) is reachable from any device on your tailnet at this host's Tailscale address — no per-service setup needed.

## Auth (Authelia)

Add `authelia` alongside `traefik` in a custom selection to put a real login in front of every routed service — no LDAP, Postgres, or Redis required, and no external identity provider. You'll be prompted for an admin username/password (once — a regenerate never re-asks if it's already configured), and Vulcan handles hashing it and generating the random secrets Authelia needs itself. Without Traefik+`--domain` also active, Authelia has nothing to protect and its own login portal isn't reachable — Vulcan warns outright rather than pretending it did something.

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
