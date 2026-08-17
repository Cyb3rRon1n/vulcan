#!/usr/bin/env bash
set -euo pipefail

# Run this ON YOUR OWN DEVICE (laptop/desktop), NOT on the Vulcan server -
# unlike backup.sh/restore.sh/update.sh in this directory, this one wraps a
# client-side SSH tunnel, not a server-side vulcan command. It opens a local
# port forward so your browser can reach Vaultwarden's web vault as a
# genuine 127.0.0.1 origin, satisfying the Web Crypto "secure context"
# requirement a plain LAN IP can never pass. See walkthrough.md's "You are
# not using a secure context" section for the full explanation.
#
# Only needed for the web vault itself (initial account signup, and any
# later trip back to the full web UI/admin page) - day-to-day use goes
# through the Bitwarden browser extension instead, which isn't gated by
# the same restriction.

if [ $# -lt 1 ]; then
    echo "Usage: $0 <user>@<server-ip-or-host> [vaultwarden-port]" >&2
    echo "Example: $0 sentinel@192.168.1.129" >&2
    exit 1
fi

TARGET="$1"
PORT="${2:-8222}"

echo "Opening a tunnel to $TARGET:$PORT ..."
echo "Once connected, visit: http://127.0.0.1:$PORT"
echo "Press Ctrl+C here to close the tunnel when you're done."
echo

exec ssh -L "$PORT:127.0.0.1:$PORT" -N "$TARGET"
