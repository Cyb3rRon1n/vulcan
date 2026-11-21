# Travel: a Vulcan you carry

Travel is a small box (an N100 mini PC or an old laptop) that you take with you. It plays your movies and shows from its own drives with no internet. You can reach it by name on any network. It can run a TV by itself. And it catches up on new media whenever it gets online.

**Supported:** x86-64 boxes. The stack runs on any distro Vulcan supports. The Kodi kiosk needs Debian or Ubuntu. On other systems the build refuses `--kiosk`. **Raspberry Pi 5:** experimental. It has no hardware video encoder. Set your Jellyfin apps to direct play, and bring files that play everywhere (the media assistant flags files that may need converting).

## What you need

- The box: at least 2 cores, 4 GB RAM and 64 GB free. An Intel N100 is ideal, because Quick Sync transcodes for free.
- A drive with your media (internal or USB).
- A travel router (a GL.iNet, for example) if you want the same network everywhere. It is optional, but it keeps "by IP" links stable.
- For the kiosk: an HDMI TV. To control Kodi with the TV remote (HDMI-CEC), most PCs need a USB-CEC adapter.

## 1. Set it up at home first

Do the whole setup at home, with internet. That is when the images download, posters and metadata fill in, and the Kodi add-on installs. After that, the box needs nothing from the internet.

    ./install            # pick Travel in the tier menu

Or without the menu:

    ./install --plain --tier travel --media-path /mnt/media --hostname vulcan \
        --self-download --home-sync --kiosk --non-interactive --yes --start

Travel is never recommended for you. You choose it yourself. It never includes a domain, Traefik, Authelia, CrowdSec, Cloudflare Tunnel or Watchtower, and it refuses `--domain`.

In the menu, Travel shows a checklist with three extras. Your last choices are ticked again on a re-run, and Cancel stops the setup.

| Extra | What it does | Flag |
|---|---|---|
| Self-download | Sonarr, Radarr, Prowlarr and qBittorrent. Downloads new episodes when online and waits quietly when not. It always runs behind the gluetun VPN, so the menu asks for your VPN details. | `--self-download` / `--no-self-download` |
| Sync from home Vulcan | Tailscale plus `vulcan travel sync`: pulls new files from your home Vulcan. | `--home-sync` / `--no-home-sync` |
| Kodi kiosk | Kodi full-screen on the TV at boot, already signed in to Jellyfin. | `--kiosk` / `--no-kiosk` |

You can also pick the name with `--hostname NAME` (default `vulcan`).

Then:

1. Open Jellyfin (`http://vulcan.local:8096`), finish its first-run wizard and add your libraries.
2. If you picked self-download: give it your VPN details. The build asks for them. If you skipped that, run `vulcan configure` (it fills in `stack/.env` for you).
3. If you picked the kiosk: in Jellyfin go to Dashboard, then API Keys, then **+**. Paste the key after `JELLYFIN_API_KEY=` in `stack/.env`. Then run `vulcan travel setup`. It creates a Jellyfin user called `kiosk` and signs Kodi in. Kodi starts on the TV after a reboot (or run `sudo systemctl start vulcan-kiosk`).
4. Run `vulcan doctor`. It should show two green ticks.

## 2. Finding the box on any network

The box answers as **`<hostname>.local`** (default `vulcan.local`). This works through Avahi (also called mDNS), a small service that announces the name on the local network. The setup summary and Homepage use this name. A `.local` name works on any network, which an IP address does not.

- Homepage: `http://vulcan.local:3000`
- Jellyfin: `http://vulcan.local:8096`

Some devices (many Android phones, some smart TVs) can't find `.local` names. For those, reserve an IP on your travel router and give it to Vulcan:

1. Open your router's admin page (on a GL.iNet it is `http://192.168.8.1`). Go to **Network, LAN, Address Reservation**. Add the Vulcan box and keep the IP it shows.
2. Rebuild with `--travel-ip 192.168.8.50` (use your IP). Homepage gets a **By IP** tab with the same tiles at that address. The summary shows both links.

If `.local` does not work, run `vulcan doctor`. It checks that Avahi is running and that the name resolves, and prints the fix if not.

## 3. Three ways to catch up

**By hand: the media assistant.** Plug in a drive. Run *Media, Scan & import* in the menu, or run `vulcan media scan /mnt/usb` and then `vulcan media import <plan>`. This works fully offline. Anything Sonarr or Radarr could not see yet is queued. With self-download on, `vulcan-media-register.timer` registers the queue every hour once they are back. Without self-download there is no Sonarr or Radarr to register with. See the [media assistant guide](media-assistant.md).

**Self-download.** With self-download on, Sonarr and Radarr grab new episodes and movies whenever the box is online. Offline, they just wait.

**Sync from home.** Your home Vulcan already has everything. Pull what this box does not have:

1. Put both boxes on the same tailnet (your private Tailscale network). On this box, set `TS_AUTHKEY` in `stack/.env` (make a key at <https://login.tailscale.com/admin/settings/keys>). This step needs a build with `--home-sync`. Then start the stack. It joins as `<hostname>-travel`.
2. Let this box log in to the home box over the tailnet. Either run `ssh-copy-id you@<home-tailnet-name>`, or install Tailscale on the home host itself and run `sudo tailscale set --ssh`. The home Vulcan's own Tailscale container can't do this, because SSH would land inside the container.
3. Connect once by hand: run `ssh you@<home-tailnet-name>` and answer `yes` to accept the host key. The sync never asks questions, so it fails until you have done this once.
4. In `stack/.env` set `TRAVEL_SYNC_FROM=you@<home-tailnet-name>` (for example `you@home-vulcan`; see `tailscale status` for the name). Do not use `vulcan`: this travel box answers to that name itself, so the sync would look at itself. Vulcan refuses a home name that is this box or points back at it. Set `TRAVEL_SYNC_PATH=` to the home media path plus `/media` (default `/mnt/media/media`). It can't be `/`.
5. Run `vulcan travel sync`. New files land in `<media path>/downloads/from-home`. Import them with `vulcan media scan <that folder>`, then `vulcan media import <plan> --move`.

It never pulls more than `TRAVEL_SYNC_MAX_GB` (default 200) per run. It always leaves `TRAVEL_SYNC_MIN_FREE_GB` (default 20) free. An interrupted run picks up where it stopped. A file you already imported is not pulled again.

To run it every hour, use `vulcan travel sync --install-timer`. It needs the home box set first (`--from` or `TRAVEL_SYNC_FROM`). The timer reads only `stack/.env`, so `--install-timer` saves any `--from`, `--remote-path`, `--max-gb` and `--min-free-gb` you give into `stack/.env`, after checking them. The timer is called `vulcan-travel-sync.timer` and runs `vulcan travel sync --if-reachable`. If the home box is away, it quietly does nothing. If ssh answers but refuses you (unknown host key, wrong key), it reports an error with a hint, even with `--if-reachable`. `--remove-timer` stops it.

## 4. The Kodi kiosk

With `--kiosk`, the box boots straight into Kodi full-screen on the TV. The build only sets this up. Kodi starts after a reboot, or when you run `sudo systemctl start vulcan-kiosk`. This is `vulcan-kiosk.service`, running as its own `vulcan-kiosk` user. Kodi's Jellyfin add-on is installed and points at `http://localhost:8096`.

- The add-on download needs internet, so do the first setup at home. After the add-on is installed, `vulcan travel setup` works offline.
- If Kodi shows the Jellyfin add-on as disabled the first time: Add-ons, My add-ons, Video add-ons, Jellyfin, then **Enable**.
- If setup says Jellyfin refused the kiosk login: a Jellyfin user named `kiosk` already exists with a different password. Delete that user in Jellyfin (Dashboard, Users) and run `vulcan travel setup` again.
- TV remote (CEC): Kodi uses it when it finds a CEC adapter. `cec-client -l` lists adapters.
- Turn it off: rebuild with `--no-kiosk`. The normal login prompt comes back. Kodi stays installed. The kiosk password stays in `stack/.env`, so turning the kiosk on again keeps the TV signed in.
- Only Debian and Ubuntu can run the kiosk. Atomic or immutable systems (Bazzite, Silverblue) and other distros are refused when you build. Use the TV's own Jellyfin app instead.
- Leaving Travel (a rebuild as another tier, or `vulcan uninstall`) removes the kiosk unit and both timers.

## 5. Offline: what to expect

- Everything starts with no internet. The images are pinned and already on the box. There is no Watchtower.
- Jellyfin plays everything already on the drive. Posters fetched at home stay.
- Open Homepage once at home. Its tile icons load from the internet the first time, and your browser keeps them (the box does not). A phone that never opened Homepage at home will not have them.
- Updates are a choice. The image versions are pinned, so they do not change on their own. At home, with internet, run `vulcan update-self` to get a newer Vulcan, then rebuild to move to its pinned versions.

Setup has not yet been tested on real travel hardware for every case. If something does not work as written, please open an issue.

## Commands

| Command | What it does |
|---|---|
| `vulcan travel setup` | Applies the host pieces again: Avahi and hostname, timers, kiosk (and its Jellyfin sign-in) |
| `vulcan travel sync [--from you@<home-tailnet-name>] [--remote-path PATH] [--max-gb N] [--min-free-gb N] [--if-reachable]` | Pulls new files from your home Vulcan |
| `vulcan travel sync --install-timer` / `--remove-timer` | Hourly sync whenever home is reachable (`--install-timer` saves the given settings into `stack/.env`) |
| `vulcan doctor` | Checks Avahi and `<hostname>.local`, with fixes |
