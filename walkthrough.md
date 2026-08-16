# Walkthrough

A suggested order to configure every service after install - real sequencing advice, not hardcoded "1./2./3." so skipping a disabled service's step never leaves a gap in the sequence.

## Suggested Setup Order

1. **Vaultwarden** - create your account first - save every login below here as you create it, so nothing gets lost.

2. **Prowlarr** - add your indexers first - Radarr/Sonarr/Lidarr/Readarr all query through it, so nothing else can search until this is done.

3. **Radarr** and **Sonarr** - connect each to Prowlarr (Settings > Indexers) and set root folders, then save each app's own API key (Settings > General) into Vaultwarden.

4. **qBittorrent** / **SABnzbd** - set a real login (not the image's default) and connect it to each *arr app above (Settings > Download Clients).

5. **Gluetun** - confirm the VPN actually connected (docker compose logs gluetun) before trusting qBittorrent's traffic - it stays offline if Gluetun can't connect.

6. **Bazarr** - connect it to Radarr/Sonarr for subtitles once they have content to work with.

7. **Jellyfin** - create libraries pointed at your media folders, then enable its own built-in two-factor authentication (Dashboard > My Profile).

8. **Jellyseerr** - connect it to Jellyfin and Radarr/Sonarr so requests can actually be fulfilled.

9. **Homepage/Dashy/Uptime Kuma/Netdata** - check these last - they only have something to show once the services above are actually running.

## Full Walkthrough

For a real, detailed walkthrough with step-by-step instructions, real infrastructure verification, and screenshots, visit the [full documentation site](https://cyb3rron1n.github.io/vulcan/) or see the [Getting Started docs](docs/getting-started/index.md).

---

## Dependencies Between Services

- **Prowlarr** must be configured before any *arr app that queries it
- **A working download client** (qBittorrent or SABnzbd) must be connected before anything expects downloads
- **Jellyfin libraries** must be created before Jellyseerr can request content into them
- **Dashboards** (Homepage/Dashy) should be checked last since they have nothing to show until everything above is running

---

## Post-Install Checklist

- [ ] Visit each service URL and confirm it's responding
- [ ] Save all service logins in Vaultwarden
- [ ] Configure Prowlarr indexers
- [ ] Set up download client credentials
- [ ] Verify VPN connection (if Gluetun enabled)
- [ ] Set up parity/checksums for your RAID array (if using mdadm)
