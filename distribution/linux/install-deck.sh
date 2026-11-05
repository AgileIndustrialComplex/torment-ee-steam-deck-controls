#!/usr/bin/env bash
# One-command install of the PST:EE controller mod for Steam Deck / Linux.
#
# Run this in Konsole (Desktop Mode) or over SSH:
#     bash install-deck.sh          # auto-detect the game
#     bash install-deck.sh --game-dir "/path/to/Planescape Torment Enhanced Edition"
#     bash install-deck.sh --import-saves
#
# Everything is stdlib Python; nothing is installed system-wide and no root
# password is needed. Use uninstall-deck.sh to revert.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if ! command -v python3 >/dev/null 2>&1; then
    echo "python3 not found. On SteamOS it ships with the system; check your PATH." >&2
    exit 1
fi
PY="$(command -v python3)"
echo "Using $("$PY" -V 2>&1)"

echo
echo "== Looking for Planescape: Torment Enhanced Edition =="
if ! "$PY" "$HERE/install.py" detect; then
    echo
    echo "No usable game folder found."
    echo "If the game is installed: Steam > the game > Properties > Compatibility >"
    echo "force Proton 9.0+ (the native Linux build has no Torment.exe), let it"
    echo "finish downloading, then re-run this script."
    exit 1
fi

echo
exec "$PY" "$HERE/install.py" install "$@"
