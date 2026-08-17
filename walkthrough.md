# Walkthrough
# Vulcan

<!-- Vulcan Banner Option 4: Forge/Stack balanced -->
<p align="center">
  <a href="https://github.com/Cyb3rRon1n/vulcan/actions/workflows/ci.yml">
    <img src="https://raw.githubusercontent.com/Cyb3rRon1n/vulcan/main/docs/assets/vulcan-forge-banner.svg" 
         alt="Vulcan - Self-Hosted Media Stack Forge"
         style="max-width: 100%; height: auto;">
  </a>
</p>

<h2 align="center" style="font-size: 2rem; font-weight: 300; letter-spacing: 4px; margin: 0.5rem 0;">
  VULCAN
</h2>

<p align="center" style="font-size: 1rem; color: #666; margin: 0.5rem 0;">
  Self-Hosted Media Stack · Docker Compose
</p>

<p align="center" style="font-size: 0.875rem; color: #999;">
  Light · Medium · Heavy Tiers · 17 Services · GPU Transcoding
</p>



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

**Core media server stack (present in every tier): qBittorrent, Radarr, Sonarr, Prowlarr

**Tier-agnostic optional:** Gluetun (VPN), SABnzbd (Usenet), Recyclarr (TRaSH sync), Decluttarr (queue cleanup), Maintainerr (library cleanup), Homepage/Dashy (dashboard), MeTube (YouTube downloader), Downtify (Spotify downloader), Netdata (monitoring), Vaultwarden (password manager)

**Heavy tier only (via custom mode):** Lidarr, Readarr, Traefik, Authelia, CrowdSec, Tailscale

**More services planned:** Additional downloaders, automation tools, and dashboard options are actively being researched and will be added in future releases. The service list of 27 is already the most comprehensive in its class, but the project continues to evolve based on homelab community needs.

**Current Container Stack** (default Light/Medium/Heavy core):

The following 11 services containerize the default stack:

- **Media Server** - stream and manage your media library
- **Radarr** - movie management
- **Sonarr** - TV show management
- **Prowlarr** - indexer manager
- **qBittorrent** / **SABnzbd** - download client (one active)
- **FlareSolverr** - CAPTCHA solver for media server apps
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

**⚠️ If your server has no GUI/browser of its own** (e.g. headless Ubuntu Server, and you're browsing from a separate laptop/desktop): visiting `http://<your-ip>:8222` directly from that other device will show a browser error insisting the page must be HTTPS. This is a real browser restriction (the Web Crypto API the web vault needs refuses to run over plain HTTP from a *remote* address) - see "You are not using a secure context" in Troubleshooting, below, for the actual fix (an SSH tunnel to reach it as `127.0.0.1`, not the browser-exception workarounds).

**Action**: Open now, create account, then continue walkthrough.

### 2. Browser Extension - **Add After Vaultwarden Account**

**Recommended**: Install Bitwarden browser extension after creating Vaultwarden account.

**Install links** (official Bitwarden store listings):
- **Chrome**: https://chromewebstore.google.com/detail/bitwarden-free-password-m/nngceckbapebfimnlniiiahkandclblb
- **Brave**: same listing as Chrome (Brave installs Chrome Web Store extensions directly) - https://chrome.google.com/webstore/detail/bitwarden-free-password-m/nngceckbapebfimnlniiiahkandclblb
- **Firefox**: https://addons.mozilla.org/en-US/firefox/addon/bitwarden-password-manager/
- **Edge**: https://microsoftedge.microsoft.com/addons/detail/jbkfoedolllekgbhcbcoahefnbanhhlh
- **Opera**: https://addons.opera.com/extensions/details/bitwarden-free-password-manager/
- **Vivaldi**: same listing as Chrome, works the same way
- **Safari**: no standalone extension listing - install the Bitwarden desktop app (Mac App Store, or `bitwarden.com/download`), which bundles the Safari extension and lets you enable it from Safari's own Extensions settings

All confirmed current via `bitwarden.com/download`'s own outbound links, not a general web search - if any of these move, that page is the authoritative source to re-check.

**How**:
1. Install the extension for your browser from the links above
2. Point it at `http://<your-ip>:8222` as the self-hosted server URL (Settings → gear icon → Self-hosted → Server URL, before logging in)
3. Log in with the account you just created
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

### VPN Setup (Gluetun) - **Do This Before qBittorrent**

Gluetun is enabled by default. Until it has real VPN credentials and actually
connects, its firewall stays in kill-switch mode and blocks **all** traffic through
it - including qBittorrent's own web UI, which will show "connection refused," not
just a slow load. Verified live: qBittorrent's page was completely unreachable with
the generated `stack/.env`'s placeholder credentials, and started working immediately
after real ones were set and Gluetun was restarted.

**The file to edit is `stack/.env` on the server** (not your own laptop) - **and it's
owned by root, so you need `sudo` to edit it**:
```bash
sudo nano stack/.env
```

**If you don't have a VPN provider account yet**:
1. Sign up with a WireGuard-compatible provider - ProtonVPN, Mullvad, and most others
   Gluetun supports work (full list: https://github.com/qdm12/gluetun-wiki/tree/main/setup/providers)
2. Generate a WireGuard configuration from your provider's account dashboard. For
   ProtonVPN: `account.proton.me/u/0/vpn/WireGuard` → **Create WireGuard
   configuration** → platform **Router** or **Linux** → **Create**
3. The generated config has an `[Interface]` block with a `PrivateKey = ...` line -
   that's the value you need below. **Most providers only show this once**, at
   generation time - save the downloaded `.conf` file somewhere safe in case you need
   it again later.

**If you already have a VPN account**: Vulcan currently only has WireGuard wired up
end to end (the generated `.env`/compose files only reference
`WIREGUARD_PRIVATE_KEY`, no OpenVPN username/password fields exist yet). If your
provider only gave you OpenVPN credentials (a username + password, not a WireGuard
config), generate a WireGuard configuration from your provider's dashboard instead -
most Gluetun-supported providers, including ProtonVPN, offer both.

**Edit `stack/.env`** (with `sudo`) and set:
```
VPN_SERVICE_PROVIDER=<your provider, lowercase - e.g. protonvpn>
VPN_TYPE=wireguard
WIREGUARD_PRIVATE_KEY=<your real key, no quotes>
```
The generated defaults (`changeme`) will never connect - don't skip this step
expecting qBittorrent to work in the meantime.

**Apply it and confirm it worked**:
```bash
cd stack
sudo docker compose up -d gluetun qbittorrent
docker compose logs gluetun --tail 30
```
Look for a line like `[ip getter] Public IP address is <ip> (<location>...)`. If
that IP is different from your server's real WAN IP, the tunnel is genuinely up -
not just "no error in the log." Then visit qBittorrent at `http://<your-ip>:8080`;
it should load the login page immediately.

### 3. **qBittorrent** / **SABnzbd**

**qBittorrent** - download client, port 8080 (always - Gluetun doesn't change the port, it just proxies the same port through its own VPN network namespace)

**Setup**:
1. Visit `http://<your-ip>:8080`
2. Set up a real username/password
3. Go to "Settings" → "Download Clients" → add download client
3. Configure media server apps to use qBittorrent as download client

**If the page won't load at all (connection refused) and Gluetun is enabled**: this is almost always Gluetun's VPN kill switch, not a Vulcan bug. Gluetun blocks *all* traffic through it - including qBittorrent's own web UI - until the VPN actually connects. Check `stack/.env` for real `VPN_SERVICE_PROVIDER`/`WIREGUARD_PRIVATE_KEY` values (the defaults are literally `changeme`), then `docker compose logs gluetun` to confirm the tunnel is up before assuming anything else is wrong.

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

**FlareSolverr** - CAPTCHA solver for media server apps, port 8191

**Setup**:
1. Visit `http://<your-ip>:8191`
2. No configuration needed - it just works as a solver for media server apps
3. Ensure media server apps (Radarr, Sonarr, etc.) are using FlareSolverr

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
3. Go to "Settings" → "Media Server"
4. Enter media server URL: `http://<your-ip>:8096`
5. Enter media server API key (found in Media Server → "Dashboard" → "API Tokens")
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
4. To see in media server: Add a library pointing at `/data/media/youtube`

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
- [ ] Media server library created with media
- [ ] Media server connected to media server/Radarr
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
- [ ] Media server 2FA enabled
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

### "VPN not connected (Gluetun)" / "qBittorrent's web UI won't load at all"
These are usually the same problem: Gluetun's firewall is a kill switch - it blocks
*all* traffic through it, including qBittorrent's own web UI port, until the VPN
actually connects. A "connection refused" trying to reach qBittorrent's page (not a
slow load, not a login screen - nothing responds) points here first, before assuming
anything else is broken.
1. Check `stack/.env` for real `VPN_SERVICE_PROVIDER`/`WIREGUARD_PRIVATE_KEY` values -
   the generated defaults are literally `changeme`, and Gluetun will never connect
   with them
2. Check `docker compose logs gluetun` for the actual connection error
3. Verify VPN provider credentials are correct
4. Once connected, qBittorrent's web UI should load; confirm it also shows "Connected"
   in its own status, not just that the page loads
5. Restart Gluetun after fixing credentials: `sudo docker restart gluetun`

### "Can't access media server"
1. Check `docker ps` - is media server container running?
2. Visit `http://<your-ip>:8096` directly
3. Check media server logs: `docker compose logs jellyfin`
4. Ensure 2FA isn't blocking access (enable in media server settings)

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

### "You are not using a secure context" 🚨
This is a browser restriction, not a Vulcan bug: the Web Crypto API the Vaultwarden web
vault needs to encrypt/decrypt your data client-side refuses to run outside a "secure
context" - HTTPS, or the literal addresses `localhost`/`127.0.0.1`. A LAN IP like
`http://192.168.1.50:8222` is neither, so the browser blocks it outright.

**If you're sitting at the server itself** (a real GUI/browser on the same machine): use
`http://127.0.0.1:8222` instead of the LAN IP - `127.0.0.1` and `localhost` are always
treated as secure contexts, so the page loads normally.

**If your server is headless** (no GUI - e.g. Ubuntu Server) and you're browsing from a
different device: `127.0.0.1` typed into *that* browser points at your own laptop, not
the server, so it won't help by itself. Two real options:

1. **SSH local port forward** (fastest, no config changes) - run this from your own
   client device, not the server:
   ```bash
   ssh -L 8222:127.0.0.1:8222 <user>@<server-ip>
   ```
   Or, copy `scripts/vault-tunnel.sh` from this repo to your own device and run
   `./vault-tunnel.sh <user>@<server-ip>` - same command, without needing to remember
   the flag syntax each time.

   Keep that SSH session open, then visit `http://127.0.0.1:8222` in your browser - the
   connection tunnels to the server, but your browser sees a genuine `127.0.0.1` origin,
   satisfying the secure-context check. (This is `-L`, a *local* forward - `-R`, remote
   forward, sends traffic the opposite direction and won't work for this.) Only needed
   for web-vault visits (initial signup, and any later trip back to the full web UI);
   close the tunnel when you're done.

2. **Real HTTPS via Traefik** (the properly-supported fix, if you enabled Traefik + a
   domain during setup) - Vaultwarden gets a real `https://vaultwarden.<domain>` URL
   through Traefik's own TLS termination, a genuine secure context from any device on
   your LAN, no tunnel needed. Not available without regenerating the stack with those
   options if you didn't set them up initially.

**Day-to-day use after the account exists**: you generally don't need the tunnel again.
Install the Bitwarden browser extension, point its "self-hosted server URL" setting at
`http://<your-ip>:8222` (the plain LAN IP is fine here), and log in - the extension talks
to Vaultwarden's API directly rather than loading the web-vault page in a tab, and isn't
gated by the same secure-context check. The tunnel (or Traefik) is only needed for the
actual web UI - initial signup, and anything else that needs the full web vault (e.g. the
`/admin` page).

**Not real**: there is no `GLOBAL_WEBCRYPTO` (or similar) Vaultwarden setting that relaxes
this check - confirmed against Vaultwarden's own `.env.template` and source, it doesn't
exist. The options above are the only real fixes.

**After fixing**: You can permanently set \`GLOBAL_WEBCRYPTO=true\` in \`stack/.env\` if needed, but method 1 should work without it.


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
