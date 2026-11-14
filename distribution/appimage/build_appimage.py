#!/usr/bin/env python3
"""Build the PST:EE Steam Deck installer AppImage.

Assembles the AppDir from this repository's Linux installer, the GTK front
end and the native release payload, then packs it with appimagetool (which
is downloaded on demand and run extracted, so no FUSE is needed to build).

Usage:
    python3 build_appimage.py [--payload /path/PSTEE-Native-Controller-...zip] [--out-dir dist]
"""

from __future__ import annotations

import argparse
import os
import struct
import subprocess
import sys
import urllib.request
import zlib
from pathlib import Path

LAB = Path(__file__).resolve().parent
LINUX = LAB.parent / "linux"
ROOT = LAB.parents[1]
APP_NAME = "pstee-deck-installer"
APPIMAGETOOL_URL = (
    "https://github.com/AppImage/appimagetool/releases/download/continuous/"
    "appimagetool-x86_64.AppImage"
)
VERSION = "0.2.1"


def png_chunk(kind: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + kind
        + data
        + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    )


def build_icon(path: Path, size: int = 256) -> None:
    """A radial-menu emblem: dark disc, warm ring, eight sector spokes."""
    import math

    center = (size - 1) / 2.0
    ring_outer = size * 0.46
    ring_inner = size * 0.34
    hub = size * 0.10
    rows = []
    for y in range(size):
        row = bytearray()
        for x in range(size):
            dx, dy = x - center, y - center
            distance = math.hypot(dx, dy)
            if distance > center + 1.5:
                r = g = b = 0
                a = 0
            else:
                r, g, b = 34, 28, 24
                a = 255
            if ring_inner <= distance <= ring_outer:
                r, g, b = 224, 176, 68
            elif distance < hub:
                r, g, b = 224, 176, 68
            elif hub < distance < ring_inner:
                angle = math.atan2(-dy, dx)
                sector = int((angle + math.pi) / (math.pi / 4)) % 8
                if sector % 2 == 0:
                    r, g, b = 86, 70, 54
            row += bytes((r, g, b, a))
        rows.append(bytes(row))
    raw = b"".join(b"\x00" + row for row in rows)
    png = (
        b"\x89PNG\r\n\x1a\n"
        + png_chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
        + png_chunk(b"IDAT", zlib.compress(raw, 9))
        + png_chunk(b"IEND", b"")
    )
    path.write_bytes(png)


def run_appimagetool(appdir: Path, output: Path, workdir: Path) -> None:
    cache = workdir / "appimagetool-x86_64.AppImage"
    if not cache.is_file():
        print(f"downloading appimagetool ...")
        urllib.request.urlretrieve(APPIMAGETOOL_URL, cache)
    cache.chmod(0o755)
    extracted = workdir / "squashfs-root"
    if not (extracted / "AppRun").is_file():
        subprocess.run([str(cache), "--appimage-extract"], cwd=workdir, check=True)
    environment = dict(os.environ, ARCH="x86_64")
    result = subprocess.run(
        [str(extracted / "AppRun"), str(appdir), str(output), "--comp", "zstd"],
        cwd=workdir, check=False, env=environment,
    )
    if result.returncode != 0:
        raise SystemExit("appimagetool failed")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--payload", type=Path, default=ROOT / "dist" / f"PSTEE-Native-Controller-v{VERSION}-preview.zip")
    parser.add_argument("--out-dir", type=Path, default=ROOT / "dist")
    args = parser.parse_args()

    payload = args.payload
    if not payload.is_file():
        raise SystemExit(
            f"missing payload {payload}; build it with\n"
            f"  python3 controller-lab/build_release.py --linux --game-dir <dir>"
        )

    build = args.out_dir / "appimage-build"
    if build.exists():
        subprocess.run(["rm", "-rf", str(build)], check=True)
    appdir = build / f"{APP_NAME}.AppDir"
    (appdir / "usr" / "bin").mkdir(parents=True)
    (appdir / "usr" / "share" / "pstee").mkdir(parents=True)
    (appdir / "usr" / "share" / "icons").mkdir(parents=True)

    (appdir / "AppRun").write_bytes((LAB / "AppRun").read_bytes())
    (appdir / "AppRun").chmod(0o755)
    (appdir / f"{APP_NAME}.desktop").write_text((LAB / f"{APP_NAME}.desktop").read_text())
    icon = appdir / f"{APP_NAME}.png"
    build_icon(icon)
    (appdir / "usr" / "share" / "icons" / f"{APP_NAME}.png").write_bytes(icon.read_bytes())
    (appdir / f"{APP_NAME}.png").chmod(0o644)

    gui = appdir / "usr" / "bin" / "pstee-gui.py"
    gui.write_bytes((LAB / "pstee-gui.py").read_bytes())
    gui.chmod(0o755)

    payload_dir = appdir / "usr" / "share" / "pstee"
    (payload_dir / "install.py").write_bytes((LINUX / "install.py").read_bytes())
    (payload_dir / "uninstall-deck.sh").write_bytes((LINUX / "uninstall-deck.sh").read_bytes())
    (payload_dir / "package.zip").write_bytes(payload.read_bytes())

    args.out_dir.mkdir(parents=True, exist_ok=True)
    output = args.out_dir / f"PSTEE-Deck-Controller-v{VERSION}-x86_64.AppImage"
    run_appimagetool(appdir, output, build)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
