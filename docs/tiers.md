# Tiers & Custom Mode

Both the guided menu and the plain CLI show what each tier actually contains before you pick one — not just its name.

| Tier | Target Hardware | Core Services |
|---|---|---|
| Light | ≥ 2 cores, ≥ 4 GB RAM, ≥ 100 GB free | Jellyfin, Radarr, Sonarr, Prowlarr, qBittorrent |
| Medium | ≥ 4 cores, ≥ 8 GB RAM, ≥ 500 GB free | Light + Jellyseerr, Bazarr, FlareSolverr |
| Heavy | ≥ 6–8 cores, ≥ 16 GB RAM, ≥ 1 TB free | Medium + Uptime Kuma, Watchtower |

Every tier also offers the same tier-agnostic optional extras: Gluetun (VPN, on by default), SABnzbd (Usenet), Recyclarr (TRaSH sync), Decluttarr (queue cleanup), Maintainerr (library cleanup), Homepage or Dashy (dashboard), MeTube/Downtify (downloaders), Netdata (monitoring), and Vaultwarden (password manager). Heavy tier adds GPU transcoding when a GPU is detected, plus Lidarr, Readarr, Traefik, Authelia, CrowdSec, and Tailscale via custom mode.

All tiers share the same directory layout and volume naming, so re-running the installer later to move up a tier shouldn't lose data.

## Custom mode

Pick exactly which services to include, from all 28 known services regardless of tier, pre-checked based on what your hardware qualifies for:

```bash
./install --plain --tier medium --services jellyfin,radarr,homepage,watchtower --non-interactive --yes --media-path /mnt/media
```

Resource limits still scale using whichever tier you choose (`--tier` here, or the detected recommendation if omitted) — picking Homepage or Watchtower alongside a Medium selection doesn't pull in Heavy-tier resource limits.

- In the interactive `--plain` flow, answer "y" to "Customize which services are included?" after picking a tier.
- In the guided `whiptail` menu, answer "Yes" to "Customize the full service list?" right after picking a tier to get the same free-pick checklist.

This is also the only path (menu or `--plain`) that can reach Traefik/Authelia/CrowdSec/Tailscale/Decluttarr/Maintainerr/Lidarr/Readarr, since domain-based routing only activates when an explicit service list includes `traefik` — see [Optional Integrations](integrations.md) for what each of those actually does.
