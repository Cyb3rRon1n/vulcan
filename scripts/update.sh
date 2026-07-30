#!/usr/bin/env bash
set -euo pipefail

# Pull the latest images for the generated stack and recreate containers.
# Thin wrapper - the real logic lives in installer/post_install.py,
# reached the same way ./install reaches installer/cli.py.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$SCRIPT_DIR/../.venv/bin/python" -m installer update "$@"
