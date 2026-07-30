#!/usr/bin/env bash
set -euo pipefail

# Basic backup of the generated stack's config volumes.
# Thin wrapper - the real logic lives in installer/post_install.py,
# reached the same way ./install reaches installer/cli.py.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$SCRIPT_DIR/../.venv/bin/python" -m installer backup "$@"
