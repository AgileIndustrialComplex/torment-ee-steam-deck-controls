#!/usr/bin/env python3
"""Assemble a native Linux payload directory for installer tests and packaging.

Copies the built bridge and the UI Lua next to the generated radial BAM
assets, so `PSTEE_NATIVE_PAYLOAD_DIR=<dir>` gives test_install.py real
payload files without a release download.

Usage:
    python3 make_native_payload.py --out-dir <dir> [--lab-dir <controller-lab>]
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

LAB = Path(__file__).resolve().parent


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--lab-dir", type=Path, default=LAB)
    args = parser.parse_args()

    lab = args.lab_dir
    bridge = lab / "native" / "libpstcontroller.so"
    lua = lab / "M_PSTPAD.lua"
    if not bridge.is_file():
        raise SystemExit(f"missing {bridge}; run build_plugin_linux.py first")
    if not lua.is_file():
        raise SystemExit(f"missing {lua}")

    import sys

    sys.path.insert(0, str(lab))
    from radial_asset import build_ui_assets

    out = args.out_dir
    out.mkdir(parents=True, exist_ok=True)
    shutil.copy2(bridge, out / "libpstcontroller.so")
    shutil.copy2(lua, out / "M_PSTPAD.lua")
    shutil.copy2(lab / "steam_input_manifest.vdf", out / "steam_input_manifest.vdf")
    for name, data in build_ui_assets().items():
        (out / name).write_bytes(data)

    print(f"native payload in {out}:")
    for member in sorted(out.iterdir()):
        print(f"  {member.name:24s} {member.stat().st_size}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
