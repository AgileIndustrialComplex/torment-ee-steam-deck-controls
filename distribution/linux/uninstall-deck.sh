#!/usr/bin/env bash
# Revert the controller mod and restore the original game files.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$HERE/install.py" uninstall "$@"
