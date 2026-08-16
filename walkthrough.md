# Walkthrough

A suggested order to configure every service after install - real sequencing advice, not hardcoded "1./2./3." so skipping a disabled service's step never leaves a gap in the sequence.

## Quick Start

```bash
git clone https://github.com/Cyb3rRon1n/vulcan.git
cd vulcan
sudo ./install
```

`sudo ./install` bootstraps a local virtual environment, then opens a persistent **Main Menu** — Guided Setup (whiptail-driven), plus Update/Pull/Backup/Restore/Uninstall for an already-generated stack. Every item is always listed; picking a task before a stack exists gives a real "no stack found" message. **Guided Setup** walks you through:

1. Detects your system
2. Gets Docker ready if needed
3. Recommends a tier
4. Asks only what matters (media path, optional VPN/SABnzbd/Recyclarr/Homepage, PUID/PGID/timezone)
5. Generates a ready-to-run stack, with an option to start it

Before starting, Vulcan checks that every needed port is free and refuses cleanly (naming the conflict) rather than letting Docker fail partway through. Once up, it prints the real URL for every service you enabled.

Scripted use is also supported:

```bash
sudo ./install --tier medium --media-path /mnt/media --non-interactive --yes --start
```

`--non-interactive` requires `--yes` and an explicit `--tier`/`--media-path`. `--start` is opt-in on every path: generating a stack never launches it without being asked or told. Use `--plain` for the plain-prompt flow (no whiptail). Use `--offline` to skip the Docker install attempt when there's no connection (CLI-only; a real gap tracked in ROADMAP.md).

---

## Tiers

Each tier's actual services are shown before you pick — not just the name.

| Tier | Target Hardware | Core Services |
|------|-----------------|---------------|
| Light | ≥ 2 cores, ≥ 4 GB RAM, ≥ 100 GB | qBittorrent, Radarr, Sonarr, Prowlarr |
| Medium | ≥ 4 cores, ≥ 8 GB RAM, ≥ 500 GB | Light + Jellyseerr, Bazarr, FlareSolverr |
| Heavy | ≥ 6–8 cores, ≥ 16 GB RAM, ≥ 1 TB | Medium + Uptime Kuma, Watchtower |

Every tier also offers the same tier-agnostic optional extras: Gluetun (VPN, on by default), SABnzbd (Usenet), Recyclarr (TRaSH sync), Decluttarr (queue cleanup), Maintainerr (library cleanup), Homepage/Dashy (dashboard), MeTube/Downtify (downloaders), Netdata (monitoring), Vaultwarden (password manager). Heavy adds GPU transcoding (when a GPU is detected), plus Lidarr, Readarr, Traefik, Authelia, CrowdSec, and Tailscale via custom mode.

All tiers share the same directory layout and volume naming, so re-running later to move up a tier shouldn't lose data.

### Custom mode

Pick exactly which services to include, from all 27 known services regardless of tier, pre-checked based on your hardware:

```bash
sudo ./install --plain --tier medium --services qbittorrent,radarr,homepage,watchtower --non-interactive --yes --media-path /mnt/media
```

Resource limits scale using whichever tier you choose — picking Homepage alongside Medium doesn't pull in Heavy-tier limits. In `--plain`, answer "y" to "Customize which services are included?" after picking a tier. In the whiptail menu, answer "Yes" to "Customize the full service list?" right after picking a tier. This is also the only path that can reach Traefik/Authelia/CrowdSec/Tailscale/Decluttarr/Maintainerr/Lidarr/Readarr, since domain-based routing only activates when an explicit service list includes `traefik`.

---

## Storage Planning & RAID

For a fresh machine with drives that aren't set up yet, Vulcan can detect what's really there and compute the exact `mdadm`/`mkfs`/`mount` commands a RAID + mount setup would need — **plan-only, nothing is ever executed**:

```bash
vulcan storage report                                    # list real block devices, flag which are protected
vulcan storage plan --devices /dev/sdb,/dev/sdc           # compute a plan (mdadm RAID + format + mount)
```

A device backing `/`/`/boot`/`/boot/efi` can never be selected as a target — no override flag. **Software RAID (mdadm) is the recommended approach for homelab media stacks** — it provides redundancy (RAID1/5/10) while keeping all drives in a single filesystem pool, enabling the hardlink-safe volume layout that `write_stack()` relies on (downloads and media on the same filesystem = instant hardlinks, not copies). ZFS and btrfs are also supported for advanced users, but mdadm is the default since it's available in every distro's repos.

**Device safety rule**: A physical device backing `/`, `/boot`, or `/boot/efi` can never be selected as a target — no override flag exists. Full detail: [Storage Planning →](https://cyb3rron1n.github.io/vulcan/storage/) (or [docs/storage.md](docs/storage.md)).

---

## Maintaining an Existing Stack

Commands reachable from the Main Menu (not CLI-only):

| Command | What it does |
|---|---|
| `sudo vulcan update` | Pulls latest images and recreates containers |
| `sudo vulcan pull` | Pulls images without starting anything |
| `sudo vulcan backup` | Archives `stack/config/` + `docker-compose.yml`/`.env` to `backups/` |
| `sudo vulcan restore [file]` | Restores `config/`, `docker-compose.yml`, and `.env` from a backup |
| `sudo vulcan uninstall` | Stops the stack and deletes `stack/` entirely — back to a clean slate |
| `sudo vulcan update-self` | Updates this Vulcan checkout — plain fast-forward `git pull` |

Airgap/offline: `--offline` skips the Docker install attempt; `vulcan export`/`import` move a stack's images to a machine never online at all.

Full detail, destructive vs. safe, and airgap installs: [Maintaining a Stack →](https://cyb3rron1n.github.io/vulcan/maintenance/) (or [docs/maintenance.md](docs/maintenance.md)).

---

## Currently Implemented Services (27 total, more coming)

**Core `*arr` stack (present in every tier):** Jellyfin, Radarr, Sonarr, Prowlarr, qBittorrent

**Tier-agnostic optional:** Gluetun (VPN), SABnzbd (Usenet), Recyclarr (TRaSH sync), Decluttarr (queue cleanup), Maintainerr (library cleanup), Homepage/Dashy (dashboard), MeTube (YouTube downloader), Downtify (Spotify downloader), Netdata (monitoring), Vaultwarden (password manager)

**Heavy tier only (via custom mode):** Lidarr, Readarr, Traefik, Authelia, CrowdSec, Tailscale

**More services planned:** Additional downloaders, automation tools, and dashboard options are actively being researched and will be added in future releases. The service list of 27 is already the most comprehensive in its class, but the project continues to evolve based on homelab community needs.

**Current Container Stack** (default Light/Medium/Heavy core):

The following 11 services containerize the default stack:

- **Jellyfin** - media streaming server
- **Radarr** - movie management
- **Sonarr** - TV show management
- **Prowlarr** - indexer manager
- **qBittorrent** / **SABnzbd** - download client (one active)
- **FlareSolverr** - CAPTCHA solver for *arr apps
- **Jellyseerr** - request manager
- **Bazarr** - subtitle manager
- **Netdata** - system monitoring
- **Vaultwarden** - password manager

**Additional services (opt-in via custom mode):**

- **Lidarr** - music management
- **Readarr** - book management
- **Traefik** - reverse proxy with routing
- **Authelia** - login authentication
- **CrowdSec** - intrusion protection
- **Tailscale** - private remote access
- **Homepage** / **Dashy** - dashboards
- **MeTube** / **Downtify** - video/audio downloaders
- **Decluttarr** / **Maintainerr** - queue/library cleanup

*More services are actively being researched and added based on homelab community needs.*

---

## 🔐 Onboarding & Credential Management

### 1. Vaultwarden Account - **Must Do First**

**URL**: `http://<your-ip>:8222`

**⚠️ Critical**: Create your Vaultwarden account **before** configuring any other services.

**Why**: Every credential created below has nowhere to go immediately. Vaultwarden is the "landing pad" for all passwords.

**Action**: Open now, create account, then continue walkthrough.

### 2. Browser Extension - **Add After Vaultwarden Account**

**Recommended**: Install Bitwarden browser extension after creating Vaultwarden account.

**How**:
1. Go to `bitwarden.com/download` in your browser
2. Install the official Bitwarden extension
3. Point it at `http://<your-ip>:8222`
4. It will immediately start auto-saving credentials

**Why this pattern works**: Users see immediate value - they're saving credentials *as* they configure services, not "later."

### 3. Save Credentials After Each Service

**Pattern** (repeat for each service configured):

**After configuring [Service X]**:

1. Click the Bitwarden extension icon
2. Click "+" to add new entry
3. **URL**: service URL (e.g., `http://<your-ip>:<port>`)
4. **Username**: your service login
5. **Password**: your service password
6. **Notes**: e.g., "Radarr - movie management, port 7878"

**Why**: Prevents credential loss, builds habit, makes Vaultwarden immediately useful.

---

## Service-Specific Configuration

### 1. **Radarr**

**Radarr** - movie management, port 7877 (configurable)

**Setup**:
1. Visit `http://<your-ip>:7878`
2. Go to "Settings" → "Indexers" → add Prowlarr indexer
3. Go to "Movies" → add movie library, set root folder
4. Set quality profiles and download client (qBittorrent/SABnzbd)
5. Go to "Add Movie" → add movies manually or via search

### 💾 Save Credential to Vaultwarden

After configuring Radarr, immediately save the login to Vaultwarden:

1. Click the Bitwarden extension icon
2. Click "+" to add new entry
3. **URL**: `http://<your-ip>:7878`
4. **Username**: your Radarr API key or login
5. **Password**: your Radarr password
6. **Notes**: "Radarr - movie management, port 7878"

**Why**: Prevents credential loss, makes Vaultwarden immediately useful.

### 2. **Sonarr**

**Sonarr** - TV show management, port 8988 (configurable)

**Setup**:
1. Visit `http://<your-ip>:8989`
2. Go to "Settings" → "Indexers" → add Prowlarr indexer
3. Go to "TV Shows" → add TV library, set root folder
4. Set quality profiles and download client (qBittorrent/SABnzbd)
5. Go to "Add Episode" → add episode manually or via search

### 💾 Save Credential to Vaultwarden

After configuring Sonarr, immediately save the login to Vaultwarden:

1. Click the Bitwarden extension icon
2. Click "+" to add new entry
3. **URL**: `http://<your-ip>:8989`
4. **Username**: your Sonarr API key or login
5. **Password**: your Sonarr password
6. **Notes**: "Sonarr - TV show management, port 8989"

**Why**: Prevents credential loss, makes Vaultwarden immediately useful.

### 3. **qBittorrent** / **SABnzbd**

**qBittorrent** - download client, port 8080 (or `8081` if using Gluetun)

**Setup**:
1. Visit `http://<your-ip>:8080`
2. Set up a real username/password
3. Go to "Settings" → "Download Clients" → add download client
3. Configure each *arr app to use qBittorrent as download client

**SABnzbd** - Usenet downloader, port 8081

**Setup**:
1. Visit `http://<your-ip>:8081`
2. Complete the first-run wizard
3. Enter your Usenet provider's server details
4. Set your retention settings

### 💾 Save Credential to Vaultwarden

**For qBittorrent**:
1. Click the Bitwarden extension icon
2. Click "+" to add new entry
3. **URL**: `http://<your-ip>:8080`
4. **Username**: your qBittorrent username
5. **Password**: your qBittorrent password
6. **Notes**: "qBittorrent - download client, port 8080"

**For SABnzbd**:
1. Click the Bitwarden extension icon
2. Click "+" to add new entry
3. **URL**: `http://<your-ip>:8081`
4. **Username**: your SABnzbd username
5. **Password**: your SABnzbd password
6. **Notes**: "SABnzbd - Usenet downloader, port 8081"

**Why**: Prevents credential loss, makes Vaultwarden immediately useful.

### 4. **FlareSolverr**

**FlareSolverr** - CAPTCHA solver for *arr apps, port 8191

**Setup**:
1. Visit `http://<your-ip>:8191`
2. No configuration needed - it just works as a solver for *arr apps
3. Ensure *arr apps (Radarr, Sonarr, etc.) are using FlareSolverr

### 💾 Save Credential to Vaultwarden

After configuring FlareSolverr, immediately save the login to Vaultwarden:

1. Click the Bitwarden extension icon
2. Click "+" to add new entry
3. **URL**: `http://<your-ip>:8191`
4. **Username**: FlareSolverr username (if applicable)
5. **Password**: FlareSolverr password (if applicable)
6. **Notes**: "FlareSolverr - CAPTCHA solver, port 8191"

**Why**: Prevents credential loss, makes Vaultwarden immediately useful.

### 5. **Jellyseerr**

**Jellyseerr** - request manager, port 5055

**Setup**:
1. Visit `http://<your-ip>:5055`
2. Complete initial setup (create account if prompted)
3. Go to "Settings" → "Jellyfin"
4. Enter Jellyfin URL: `http://<your-ip>:8096`
5. Enter Jellyfin API key (found in Jellyfin → "Dashboard" → "API Tokens")
6. Save

### 💾 Save Credential to Vaultwarden

After configuring Jellyseerr, immediately save the login to Vaultwarden:

1. Click the Bitwarden extension icon
2. Click "+" to add new entry
3. **URL**: `http://<your-ip>:5055`
4. **Username**: your Jellyseerr username
5. **Password**: your Jellyseerr password
6. **Notes**: "Jellyseerr - request manager, port 5055"

**Why**: Prevents credential loss, makes Vaultwarden immediately useful.

### 6. **Bazarr**

**Bazarr** - subtitle manager, port 6767

**Setup**:
1. Visit `http://<your-ip>:6767`
2. Complete initial setup
3. Go to "Settings" → "Radarr/Sonarr"
4. Enter Radarr URL: `http://<your-ip>:7878`
5. Enter Sonarr URL: `http://<your-ip>:8989`
6. Enter your API keys (found in Radarr/Sonarr → "API Keys")
7. Save

### 💾 Save Credential to Vaultwarden

After configuring Bazarr, immediately save the login to Vaultwarden:

1. Click the Bitwarden extension icon
2. Click "+" to add new entry
3. **URL**: `http://<your-ip>:6767`
4. **Username**: your Bazarr settings username
5. **Password**: your Bazarr settings password
6. **Notes**: "Bazarr - subtitle management, port 6767"

**Why**: Prevents credential loss, makes Vaultwarden immediately useful.

### 7. **Homepage**

**Homepage** - dashboard, port 3000

**Setup**:
1. Visit `http://<your-ip>:3000`
2. Dashboard is pre-seeded with tiles for your actual stack
3. Edit `stack/config/homepage/services.yaml` to customize tiles
4. Each tile links to the corresponding service URL

### 💾 Save Credential to Vaultwarden

After configuring Homepage, immediately save the login to Vaultwarden:

1. Click the Bitwarden extension icon
2. Click "+" to add new entry
3. **URL**: `http://<your-ip>:3000`
4. **Username**: your Vaultwarden master password (or leave blank if just dashboard)
5. **Password**: your Vaultwarden master password
6. **Notes**: "Homepage - dashboard, port 3000"

**Why**: Prevents credential loss, makes Vaultwarden immediately useful.

### 8. **Dashy**

**Dashy** - dashboard, port 4000

**Setup**:
1. Visit `http://<your-ip>:4000`
2. Configuration at `stack/config/dashy/conf.yml`
3. Tiles auto-detect services via their URLs

### 💾 Save Credential to Vaultwarden

After configuring Dashy, immediately save the login to Vaultwarden:

1. Click the Bitwarden extension icon
2. Click "+" to add new entry
3. **URL**: `http://<your-ip>:4000`
4. **Username**: your Vaultwarden master password
5. **Password**: your Vaultwarden master password
6. **Notes**: "Dashy - dashboard, port 4000"

**Why**: Prevents credential loss, makes Vaultwarden immediately useful.

### 8. **MeTube**

**MeTube** - YouTube downloader, port 8081

**Setup**:
1. Visit `http://<your-ip>:8081`
2. Paste a YouTube playlist URL to start download
3. Downloads land in `stack/media/youtube` on the host
4. To see in Jellyfin: Add a library pointing at `/data/media/youtube`

### 💾 Save Credential to Vaultwarden

After configuring MeTube, immediately save the login to Vaultwarden:

1. Click the Bitwarden extension icon
2. Click "+" to add new entry
3. **URL**: `http://<your-ip>:8081`
4. **Username**: not typically required (public access)
5. **Password**: not typically required
6. **Notes**: "MeTube - YouTube downloader, port 8081"

**Why**: Prevents credential loss, makes Vaultwarden immediately useful.

### 8. **Downtify**

**Downtify** - Spotify downloader, port 8000

**Setup**:
1. Visit `http://<your-ip>:8000`
2. Paste a Spotify playlist/track URL
3. Downloads land in `stack/media/music/downtify` on the host
4. No Spotify account needed - it scrapes public pages

### 💾 Save Credential to Vaultwarden

After configuring Downtify, immediately save the login to Vaultwarden:

1. Click the Bitwarden extension icon
2. Click "+" to add new entry
3. **URL**: `http://<your-ip>:8000`
4. **Username**: not typically required
5. **Password**: not typically required
6. **Notes**: "Downtify - Spotify downloader, port 8000"

**Why**: Prevents credential loss, makes Vaultwarden immediately useful.

### 8. **Netdata**

**Netdata** - system monitoring, port 19999

**Setup**:
1. Visit `http://<your-ip>:19999`
2. First view may show health status
3. For detailed monitoring: Click "Systems" → "Add system" → follow setup wizard
4. Netdata will detect your CPU, RAM, disk, and network stats

### 💾 Save Credential to Vaultwarden

After configuring Netdata, immediately save the login to Vaultwarden:

1. Click the Bitwarden extension icon
2. Click "+" to add new entry
3. **URL**: `http://<your-ip>:19999`
4. **Username**: netdata admin (typically `admin`)
5. **Password**: netdata's system password (set during install)
6. **Notes**: "Netdata - system monitoring, port 19999"

**Why**: Prevents credential loss, makes Vaultwarden immediately useful.

### 9. **Vaultwarden**

**Vaultwarden** - password manager, port 8222

**Setup**:
1. Visit `http://<your-ip>:8222`
2. Create account (must do this first - see Onboarding section)
3. Configure settings (SIGNUPS_ALLOWED, etc.)
4. Configure Vaultwarden settings as needed

### 💾 Save Credential to Vaultwarden (Circular - but important)

After configuring Vaultwarden itself, save the master password to... Vaultwarden.

**Circular, but important**: The Vaultwarden master password is the one credential you MUST remember. Write it down in a password manager or secure location.

1. Click the Bitwarden extension icon
2. Click "+" to add new entry
3. **URL**: `http://<your-ip>:8222/admin`
4. **Username**: your Vaultwarden email
5. **Password**: your Vaultwarden master password **(must remember this one!)**
6. **Notes**: "Vaultwarden - password manager, port 8222. **MASTER PASSWORD - MUST REMEMBER**"

**Why**: The master password is the one credential you cannot reset or recover. Store it securely.

### 10. **Tailscale**

**Tailscale** - private remote access, port omitted (uses NAT)

**Setup**:
1. Visit `https://login.tailscale.com/admin/settings/keys` to obtain auth key
2. Run `tailscale up --auth-key=<key>`
3. All host-published ports become reachable over your tailnet

### 💾 Save Credential to Vaultwarden

After configuring Tailscale, immediately save the login to Vaultwarden:

1. Click the Bitwarden extension icon
2. Click "+" to add new entry
3. **URL**: Tailscale's admin console URL
4. **Username**: your Tailscale email
5. **Password**: your Tailscale auth key
6. **Notes**: "Tailscale - private remote access"

**Why**: Prevents credential loss, makes Vaultwarden immediately useful.

### 10. **Decluttarr**

**Decluttarr** - queue/library cleanup

**Setup**:
1. Visit its configured URL (varies)
2. Set up rules for removing stalled/failed downloads
3. Configure in its web UI

### 💾 Save Credential to Vaultwarden

After configuring Decluttarr, immediately save the login to Vaultwarden:

1. Click the Bitwarden extension icon
2. Click "+" to add new entry
3. **URL**: Declutter's configured URL
4. **Username**: Declutter username
5. **Password**: Declutter password
6. **Notes**: "Declutter - queue/library cleanup"

**Why**: Prevents credential loss, makes Vaultwarden immediately useful.

### 11. **Maintainerr**

**Maintainerr** - library cleanup

**Setup**:
1. Visit its configured URL (varies)
2. Set up rules for removing unwatched media
3. Configure in its web UI

### 💾 Save Credential to Vaultwarden

After configuring Maintainerr, immediately save the login to Vaultwarden:

1. Click the Bitwarden extension icon
2. Click "+" to add new entry
3. **URL**: Maintainerr's configured URL
4. **Username**: Maintainerr username
5. **Password**: Maintainerr password
6. **Notes**: "Maintainerr - library cleanup"

**Why**: Prevents credential loss, makes Vaultwarden immediately useful.

---

## 4. Verify & Explore

- Visit each service URL and confirm login
- Test the Bitwarden extension auto-save
- Bookmark important pages
- Check `docker ps` confirms all containers running
- Verify VPN status (if Gluetun enabled)

---

## 📋 Post-Install Checklist

### ✅ Completed
- [ ] Vaultwarden account created (first stop)
- [ ] Prowlarr indexers added
- [ ] Radarr/Sonarr configured with Prowlarr
- [ ] qBittorrent/SABnzbd login set up
- [ ] Gluetun VPN confirmed connected
- [ ] Jellyfin library created with media
- [ ] Jellyseerr connected to Jellyfin/Radarr
- [ ] Bazarr subtitles configured
- [ ] Homepage/Dashy dashboard verified
- [ ] Netdata monitoring confirmed
- [ ] Vaultwarden credentials saved
- [ ] MeTube/Downtify test downloads verified
- [ ] Decluttarr/Maintainerr configured (optional)

### ⚠️ Verify These
- [ ] VPN status confirmed (qBittorrent traffic protected)
- [ ] API keys stored in Vaultwarden
- [ ] Media library paths correct
- [ ] Subtitle download working (Bazarr)
- [ ] VPN connection status (if Gluetun enabled)

### 🛡️ Security Checklist
- [ ] Vaultwarden `SIGNUPS_ALLOWED=false` set (after onboarding)
- [ ] Jellyfin 2FA enabled
- [ ] All default passwords changed
- [ ] No services exposed to public internet without VPN/Tailscale
- [ ] Router not needed for internal access (Tailscale handles remote access)

---

## 📋 Troubleshooting Common Issues

### "Can't connect to service X"
1. Check `docker ps` - is the container running?
2. Check `docker compose logs <service>` - any errors?
3. Check firewall/port (though Whiptail/NAT handles this)
4. Ping the service URL from another device on the network

### "Subtitles not downloading (Bazarr)"
1. Verify Radarr/Sonarr API keys are correct
2. Check that Bazarr can reach Radarr/Sonarr URLs
3. Ensure Radarr/Sonarr are running and have content

### "VPN not connected (Gluetun)"
1. Check `docker compose logs gluetun`
2. Verify VPN provider credentials are correct
3. Check that qBittorrent shows "Connected" in its status
4. Restart Gluetun: `sudo docker restart gluetun`

### "Can't access Jellyfin"
1. Check `docker ps` - is Jellyfin container running?
2. Visit `http://<your-ip>:8096` directly
3. Check Jellyfin logs: `docker compose logs jellyfin`
4. Ensure 2FA isn't blocking access (enable in Jellyfin settings)

### "Subtitles not found (Bazarr)"
1. Verify Radarr/Sonarr have content in their libraries
2. Check API keys are correct
3. Ensure Radarr/Sonarr have network access
4. Try manual subtitle search in Bazarr UI

---


## "Host validation failed"
1. Ensure \`HOMEPAGE_ALLOWED_HOSTS\` is properly set in the generated configuration.
2. Restart the Homepage container: \`sudo docker compose restart homepage\`
3. Verify access at \`http://<your-ip>:3000\`.

### "You are not using a secure context"
1. This is a browser restriction for the Web Crypto API.
2. Use \`http://127.0.0.1\` instead of \`http://localhost\` in your browser.
2. Or configure Vaultwarden with \`GLOBAL_WEBCRYPTO=true\` env var.
3. Or add a browser exception for the HTTPS warning.

## 📋 Resources & Further Reading

- **Full Documentation**: https://cyb3rron1n.github.io/vulcan/
- **Vulcan ROADMAP**: https://cyb3rron1n.github.io/vulcan/ROADMAP.md
- **Service Docs**: Each service's official docs linked in the walkthrough
- **Community**: Vulcan Discord/Forum (check the docs site)

---

## 📋 Quick Commands Reference

```bash
# View running containers
docker ps

# View container logs
docker compose logs <service>

# Restart a service
sudo docker restart <service>

# Check VPN status
docker compose logs gluetun

# See service URLs after install
# (printed at the end of successful install)
```

---

## 📜 License

Vulcan is released under the [MIT License](LICENSE).
