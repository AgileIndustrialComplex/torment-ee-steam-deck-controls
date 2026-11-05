#!/usr/bin/env python3
"""Install the PST:EE Xbox Controller Mod on Linux / Steam Deck.

The upstream mod ships a PowerShell installer plus a Windows launcher that
injects a DLL into a suspended Torment.exe. That works under Proton, but the
installer itself needs PowerShell. This is a stdlib-only port that performs the
same file operations natively, so it runs inside Konsole on SteamOS.

Usage:
    python3 install.py detect                      # find the game + report state
    python3 install.py install [--game-dir D] [--package P] [--allow-unknown-exe]
    python3 install.py uninstall [--game-dir D]
    python3 install.py status [--game-dir D]
    python3 install.py launch-option [--game-dir D]

Ported behaviour (must stay byte-identical to upstream):
  * stock UI.menu is read from chitin.key + data/*.bif
  * ui-patch.json hunks are applied with source and target SHA-256 checks
  * engine.lua engine_name is renamed to the Controller Lab profile
  * every replaced file is backed up and restored exactly on uninstall
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import shutil
import struct
import sys
import urllib.request
import zipfile
from pathlib import Path

APPID = "466300"
RELEASE_VERSION = "0.1.31"
_ARCHIVE = f"PSTEE-Xbox-Controller-v{RELEASE_VERSION}-preview.zip"
# The binaries come from upstream's releases. Set PSTEE_MOD_SOURCE to a repo
# slug (e.g. a fork that publishes its own release) to override.
RELEASE_REPOS = (
    os.environ.get("PSTEE_MOD_SOURCE"),
    "NiksonLichev/planescape-torment-enhanced-edition-xbox-controller-mod",
)
RELEASE_URLS = tuple(
    f"https://github.com/{repo}/releases/download/v{RELEASE_VERSION}/{_ARCHIVE}"
    for repo in RELEASE_REPOS
    if repo
)
SUPPORTED_EXE_SHA256 = "99ae15860cfdbcdaad0f48e005eee21444046b21de848c1deab9367e8246a3c5"

STATE_DIR = ".pstee-controller-deck"
MOD_FILES = [
    "engine.lua",
    "ControllerLab.exe",
    "override/M_PSTPAD.lua",
    "override/pstcontroller.dll",
    "override/UI.menu",
    "override/PSTPRAD.bam",
    "override/PSTPSEL.bam",
]
PROFILE_OLD = "Planescape Torment - Enhanced Edition"
PROFILE_NEW = "Planescape Torment - Controller Lab"


class InstallError(Exception):
    pass


# --------------------------------------------------------------------------- #
# hashing / io helpers
# --------------------------------------------------------------------------- #

def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_path(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".pstee-tmp")
    with tmp.open("wb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


# --------------------------------------------------------------------------- #
# Steam discovery
# --------------------------------------------------------------------------- #

def steam_roots() -> list[Path]:
    home = Path.home()
    candidates = [
        home / ".steam/steam",
        home / ".steam/root",
        home / ".local/share/Steam",
        home / ".var/app/com.valvesoftware.Steam/.local/share/Steam",
        Path("/run/media/mmcblk0p1/steamapps"),
        Path("/run/media/deck/sdcard"),
    ]
    roots: list[Path] = []
    for path in candidates:
        if path.name == "steamapps":
            path = path.parent
        if path.is_dir() and path not in roots:
            roots.append(path)
    return roots


def libraries(root: Path) -> list[Path]:
    libs = [root]
    vdf = root / "steamapps" / "libraryfolders.vdf"
    if vdf.is_file():
        try:
            text = vdf.read_text(errors="replace")
        except OSError:
            text = ""
        for match in re.finditer(r'"path"\s*"([^"]+)"', text):
            candidate = Path(match.group(1).replace("\\\\", "\\"))
            if candidate.is_dir() and candidate not in libs:
                libs.append(candidate)
    return libs


def game_candidates() -> list[Path]:
    found: list[Path] = []
    for root in steam_roots():
        for lib in libraries(root):
            acf = lib / "steamapps" / f"appmanifest_{APPID}.acf"
            if acf.is_file():
                match = re.search(r'"installdir"\s*"([^"]+)"', acf.read_text(errors="replace"))
                if match:
                    candidate = lib / "steamapps" / "common" / match.group(1)
                    if candidate.is_dir():
                        found.append(candidate)
            common = lib / "steamapps" / "common"
            if common.is_dir():
                for entry in common.iterdir():
                    if entry.is_dir() and "planescape" in entry.name.lower():
                        found.append(entry)

    # ~/.steam/steam usually symlinks to ~/.local/share/Steam, so the same
    # folder can be reached twice; report it once.
    unique: list[Path] = []
    seen: set[Path] = set()
    for path in found:
        try:
            key = path.resolve()
        except OSError:
            key = path
        if key not in seen:
            seen.add(key)
            unique.append(path)
    return unique


def looks_like_game(path: Path) -> bool:
    return (path / "chitin.key").is_file() and (path / "engine.lua").is_file()


def resolve_game(game_dir: str | None) -> Path:
    if game_dir:
        path = Path(game_dir).expanduser().resolve()
        if not looks_like_game(path):
            raise InstallError(
                f"{path} is not a PST:EE game folder (no chitin.key/engine.lua)."
            )
        if not (path / "Torment.exe").is_file():
            raise InstallError(
                f"No Torment.exe in {path}.\n"
                "On Steam Deck the game defaults to the native Linux build. Force Proton first:\n"
                "  Steam > this game > Properties > Compatibility >\n"
                "  'Force the use of a specific Steam Play compatibility tool' > Proton 9.0 or newer.\n"
                "Wait for the Windows depot to download, then re-run this installer."
            )
        return path

    candidates = [c for c in game_candidates() if looks_like_game(c)]
    with_exe = [c for c in candidates if (c / "Torment.exe").is_file()]
    if with_exe:
        return with_exe[0].resolve()
    if candidates:
        raise InstallError(
            f"Found {candidates[0]} but it has no Torment.exe - this is the native\n"
            "Linux build. Force Proton for the game in Steam properties, then re-run."
        )
    raise InstallError(
        "Could not find Planescape: Torment Enhanced Edition.\n"
        "Pass the folder that contains Torment.exe explicitly with --game-dir."
    )


def compat_prefix(game_dir: Path) -> Path | None:
    for root in steam_roots():
        for lib in libraries(root):
            pfx = lib / "steamapps" / "compatdata" / APPID / "pfx"
            if pfx.is_dir():
                return pfx
    return None


# --------------------------------------------------------------------------- #
# KEY / BIFF reading (port of Read-GameUI)
# --------------------------------------------------------------------------- #

def read_game_ui(game_dir: Path) -> bytes:
    key = (game_dir / "chitin.key").read_bytes()
    if len(key) < 24 or key[:8] != b"KEY V1  ":
        raise InstallError("Unsupported chitin.key format.")
    bif_count, count, bif_table, table = struct.unpack_from("<4I", key, 8)
    if table + count * 14 > len(key) or bif_table + bif_count * 12 > len(key):
        raise InstallError("Invalid KEY table bounds.")

    locator = None
    for index in range(count):
        offset = table + index * 14
        name = key[offset:offset + 8].rstrip(b"\x00").decode("ascii", "replace")
        kind = struct.unpack_from("<H", key, offset + 8)[0]
        if name == "UI" and kind == 0x408:
            if locator is not None:
                raise InstallError("Duplicate UI resource.")
            locator = struct.unpack_from("<I", key, offset + 10)[0]
    if locator is None:
        raise InstallError("UI.menu was not found in game resources.")

    bif_index = locator >> 20
    if bif_index >= bif_count:
        raise InstallError("Invalid BIFF index.")
    entry = bif_table + bif_index * 12
    name_offset = struct.unpack_from("<I", key, entry + 4)[0]
    name_length = struct.unpack_from("<H", key, entry + 8)[0]
    if name_offset + name_length > len(key):
        raise InstallError("Invalid BIFF filename.")
    bif_name = key[name_offset:name_offset + name_length].rstrip(b"\x00").decode("ascii", "replace")
    bif_name = bif_name.replace("\\", "/")
    bif_path = game_dir / bif_name
    if not bif_path.is_file():
        raise InstallError(f"BIFF file missing: {bif_path}")

    bif = bif_path.read_bytes()
    if len(bif) < 20 or bif[:8] != b"BIFFV1  ":
        raise InstallError("Unsupported BIFF format.")
    file_count, file_table = struct.unpack_from("<2I", bif, 8)[0], struct.unpack_from("<I", bif, 16)[0]
    if file_table + file_count * 16 > len(bif):
        raise InstallError("Invalid BIFF table bounds.")

    match = None
    for index in range(file_count):
        offset = file_table + index * 16
        resid, res_off, res_len, res_kind = struct.unpack_from("<IIIH", bif, offset)
        if (resid & 0x3FFF) == (locator & 0x3FFF):
            if match is not None:
                raise InstallError("Ambiguous BIFF UI locator.")
            match = (res_off, res_len, res_kind)
    if not match or match[2] != 0x408:
        raise InstallError("Invalid BIFF UI locator.")
    res_off, res_len, _ = match
    if res_off + res_len > len(bif):
        raise InstallError("Truncated UI resource.")
    raw = bif[res_off:res_off + res_len]
    text = raw.decode("utf-8-sig", "strict")
    return text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")


# --------------------------------------------------------------------------- #
# UI patch (port of Apply-UiPatch)
# --------------------------------------------------------------------------- #

def apply_ui_patch(source: bytes, patch: dict) -> bytes:
    if sha256_bytes(source) != patch["sourceSha256"]:
        raise InstallError(
            "The stock UI in this game copy differs from the supported build.\n"
            "Nothing was changed. Use a clean game copy (verify files in Steam)."
        )
    out = bytearray()
    cursor = 0
    for hunk in patch["hunks"]:
        start, delete = int(hunk["start"]), int(hunk["delete"])
        if start < cursor or delete < 0 or start + delete > len(source):
            raise InstallError("Invalid UI patch bounds.")
        out += source[cursor:start]
        out += base64.b64decode(hunk["insert"])
        cursor = start + delete
    out += source[cursor:]
    result = bytes(out)
    if sha256_bytes(result) != patch["targetSha256"]:
        raise InstallError("UI patch output checksum failed.")
    return result


# --------------------------------------------------------------------------- #
# package handling
# --------------------------------------------------------------------------- #

def load_package(package: str | None, cache_dir: Path) -> tuple[Path, dict]:
    """Return (package_root, manifest)."""
    if package:
        path = Path(package).expanduser().resolve()
        if path.suffix.lower() == ".zip":
            return extract_zip(path, cache_dir)
        return check_package(path)

    existing = [p for p in cache_dir.glob("PSTEE-Xbox-Controller-v*-preview") if p.is_dir()]
    for candidate in existing:
        try:
            return check_package(candidate)
        except InstallError:
            continue

    cache_dir.mkdir(parents=True, exist_ok=True)
    archive = cache_dir / _ARCHIVE
    print(f"Downloading mod payload v{RELEASE_VERSION} ...")
    errors = []
    for url in RELEASE_URLS:
        try:
            with urllib.request.urlopen(url, timeout=120) as response:
                atomic_write(archive, response.read())
            break
        except Exception as exc:  # noqa: BLE001 - network is best-effort
            errors.append(f"{url}: {exc}")
    else:
        raise InstallError(
            "Could not download the mod package:\n  " + "\n  ".join(errors) +
            "\nDownload the release ZIP manually and pass --package /path/to.zip"
        )
    return extract_zip(archive, cache_dir)


def extract_zip(archive: Path, cache_dir: Path) -> tuple[Path, dict]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as zf:
        root_name = zf.namelist()[0].split("/")[0]
        target = cache_dir / root_name
        if not target.is_dir():
            for member in zf.infolist():
                resolved = (cache_dir / member.filename).resolve()
                if not str(resolved).startswith(str(cache_dir.resolve())):
                    raise InstallError("Unsafe path inside package archive.")
            zf.extractall(cache_dir)
    return check_package(target)


def check_package(root: Path) -> tuple[Path, dict]:
    manifest_path = root / "manifest.json"
    payload = root / "payload"
    if not manifest_path.is_file() or not payload.is_dir():
        raise InstallError(
            f"{root} is not a complete preview package (missing manifest.json/payload).\n"
            "Download the ready-to-install preview ZIP, not the source archive."
        )
    manifest = json.loads(manifest_path.read_text())
    for entry in manifest["payload"]:
        path = root / entry["path"]
        if not path.is_file():
            raise InstallError(f"Package file missing: {entry['path']}")
        if sha256_path(path) != entry["sha256"]:
            raise InstallError(f"Package checksum failed: {entry['path']}")
    return root, manifest


# --------------------------------------------------------------------------- #
# install / uninstall
# --------------------------------------------------------------------------- #

def find_patch_asset(package: Path) -> dict:
    return json.loads((package / "payload" / "ui-patch.json").read_text())


def read_engine(game_dir: Path) -> str:
    return (game_dir / "engine.lua").read_text(encoding="utf-8-sig")


def patched_engine(text: str) -> str:
    pattern = re.compile(r"(?m)^[ \t]*engine_name[ \t]*=[^\r\n]*")
    if len(pattern.findall(text)) != 1:
        raise InstallError("Unexpected engine.lua layout; no files changed.")
    return pattern.sub(f'engine_name="{PROFILE_NEW}"', text)


def build_file_payload(game_dir: Path, package: Path) -> dict[str, bytes]:
    patch = find_patch_asset(package)
    ui_override = game_dir / "override" / "UI.menu"
    if ui_override.is_file():
        current = ui_override.read_bytes().decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
        if sha256_bytes(current.encode("utf-8")) != patch["sourceSha256"]:
            raise InstallError(
                "A custom override/UI.menu is installed (Infinity UI++ etc.).\n"
                "This preview cannot merge other UI mods. Use a clean game copy."
            )
        stock_ui = current.encode("utf-8")
    else:
        stock_ui = read_game_ui(game_dir)

    payload = {
        "engine.lua": patched_engine(read_engine(game_dir)).encode("utf-8"),
        "ControllerLab.exe": (package / "payload" / "ControllerLab.exe").read_bytes(),
        "override/M_PSTPAD.lua": (package / "payload" / "M_PSTPAD.lua").read_bytes(),
        "override/pstcontroller.dll": (package / "payload" / "pstcontroller.dll").read_bytes(),
        "override/UI.menu": apply_ui_patch(stock_ui, patch),
        "override/PSTPRAD.bam": (package / "payload" / "PSTPRAD.bam").read_bytes(),
        "override/PSTPSEL.bam": (package / "payload" / "PSTPSEL.bam").read_bytes(),
    }
    if sha256_bytes(payload["override/UI.menu"]).lower() != patch["targetSha256"]:
        raise InstallError("Internal error: patched UI does not match target hash.")
    return payload


def load_state(game_dir: Path) -> dict | None:
    path = game_dir / STATE_DIR / "state.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        raise InstallError(f"Corrupt state file: {path}")


def cmd_install(args) -> int:
    game_dir = resolve_game(args.game_dir)
    print(f"Game folder: {game_dir}")

    exe_hash = sha256_path(game_dir / "Torment.exe")
    if exe_hash != SUPPORTED_EXE_SHA256:
        if not args.allow_unknown_exe:
            raise InstallError(
                "Torment.exe fingerprint is not the verified Windows 3.2.2.0 build.\n"
                f"  found:    {exe_hash}\n"
                f"  expected: {SUPPORTED_EXE_HASH_DISPLAY}\n"
                "The mod's native DLL uses build-specific offsets. Re-run with\n"
                "--allow-unknown-exe only if you accept that movement/camera may misbehave."
            )
        print("WARNING: unrecognised Torment.exe - the native bridge may misbehave.")

    package, manifest = load_package(args.package, Path(args.cache_dir).expanduser())
    print(f"Package:     {package.name} (v{manifest.get('version')})")

    state = load_state(game_dir)
    if state and state.get("status") == "installed":
        raise InstallError("The mod is already installed. Run 'uninstall' first.")

    payload = build_file_payload(game_dir, package)

    backup_id = os.urandom(8).hex()
    backup_root = game_dir / STATE_DIR / "backups" / backup_id
    entries = []
    # Stage everything before touching the game.
    staged: list[tuple[Path, Path]] = []
    for index, relative in enumerate(MOD_FILES):
        target = game_dir / relative
        data = payload[relative]
        backup_name = f"{index:02d}.bin"
        existed = target.is_file()
        original_hash = None
        if existed:
            original = target.read_bytes()
            original_hash = sha256_bytes(original)
            atomic_write(backup_root / backup_name, original)
            if sha256_path(backup_root / backup_name) != original_hash:
                raise InstallError("Backup verification failed.")
        entries.append(
            {
                "path": relative,
                "backup": backup_name,
                "existed": existed,
                "originalHash": original_hash,
                "installedHash": sha256_bytes(data),
            }
        )
        stage = game_dir / STATE_DIR / "stage" / backup_id / backup_name
        atomic_write(stage, data)
        staged.append((stage, target))

    state = {
        "version": manifest.get("version", RELEASE_VERSION),
        "status": "installing",
        "backupSet": backup_id,
        "tormentExe": exe_hash,
        "files": entries,
    }
    atomic_write(game_dir / STATE_DIR / "state.json", json.dumps(state, indent=2).encode())

    try:
        for stage, target in staged:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(stage), str(target))
        shutil.rmtree(game_dir / STATE_DIR / "stage" / backup_id, ignore_errors=True)
        state["status"] = "installed"
        atomic_write(game_dir / STATE_DIR / "state.json", json.dumps(state, indent=2).encode())
    except Exception:
        state["status"] = "rolled-back"
        cmd_uninstall_files(game_dir, state, check_installed=False)
        atomic_write(game_dir / STATE_DIR / "state.json", json.dumps(state, indent=2).encode())
        raise

    print(f"Installed controller mod v{state['version']}.")
    if args.import_saves:
        import_saves(game_dir)
    print()
    print_launch_help(game_dir)
    return 0


def cmd_uninstall_files(game_dir: Path, state: dict, check_installed: bool = True) -> None:
    """Validate every entry first, then restore.

    Validation and mutation must be separate passes: a conflict on the last
    file must not leave the game half-uninstalled.
    """
    for entry in state["files"]:
        relative = entry["path"]
        if relative not in MOD_FILES:
            raise InstallError("Invalid backup manifest.")
        if check_installed:
            target = game_dir / relative
            if not target.is_file() or sha256_path(target) != entry["installedHash"]:
                raise InstallError(
                    f"{relative} changed after installation. Restore it manually;\n"
                    f"backup is in {game_dir / STATE_DIR / 'backups' / state['backupSet']}."
                )
        if entry["existed"]:
            backup = game_dir / STATE_DIR / "backups" / state["backupSet"] / entry["backup"]
            if not backup.is_file() or sha256_path(backup) != entry["originalHash"]:
                raise InstallError("Backup checksum failed.")

    for entry in state["files"]:
        target = game_dir / entry["path"]
        if entry["existed"]:
            backup = game_dir / STATE_DIR / "backups" / state["backupSet"] / entry["backup"]
            atomic_write(target, backup.read_bytes())
        elif target.is_file():
            target.unlink()


def cmd_uninstall(args) -> int:
    game_dir = resolve_game(args.game_dir)
    state = load_state(game_dir)
    if not state:
        raise InstallError("No install state found; nothing to uninstall.")
    cmd_uninstall_files(game_dir, state)
    state["status"] = "uninstalled"
    atomic_write(game_dir / STATE_DIR / "state.json", json.dumps(state, indent=2).encode())
    print(f"Uninstalled. Original files restored in {game_dir}")
    print("Backups are kept in " + str(game_dir / STATE_DIR / "backups" / state["backupSet"]))
    return 0


# --------------------------------------------------------------------------- #
# save import (Proton prefix)
# --------------------------------------------------------------------------- #

def documents_dirs(pfx: Path | None) -> list[Path]:
    found = []
    if pfx:
        users = pfx / "drive_c" / "users"
        if users.is_dir():
            for user in users.iterdir():
                docs = user / "Documents"
                if docs.is_dir():
                    found.append(docs)
    docs = Path.home() / "Documents"
    if docs.is_dir():
        found.append(docs)
    return found


def import_saves(game_dir: Path) -> None:
    pfx = compat_prefix(game_dir)
    if not pfx:
        print("Save import skipped: no Proton prefix found for app 466300.")
        return
    source = target = None
    for docs in documents_dirs(pfx):
        candidate = docs / PROFILE_OLD / "save"
        if candidate.is_dir():
            source = candidate
            target = docs / PROFILE_NEW / "save"
            break
    if not source or target is None:
        print(f"Save import skipped: no '{PROFILE_OLD}' save folder in the Proton prefix.")
        return

    target.mkdir(parents=True, exist_ok=True)
    used = {entry.name for entry in target.iterdir()}
    next_index = max([int(n) for n in used if n.isdigit()], default=0) + 1

    def slot_digest(path: Path) -> str:
        """Content fingerprint so identical copies are never duplicated."""
        h = hashlib.sha256()
        for item in sorted(path.iterdir()):
            if item.is_file() and not item.name.startswith("."):
                h.update(item.name.encode())
                h.update(item.read_bytes())
        return h.hexdigest()

    existing_digests = {
        slot_digest(entry)
        for entry in target.iterdir()
        if entry.is_dir() and not entry.name.startswith(".")
    }
    copied = skipped = 0
    for slot in sorted(source.iterdir()):
        if not slot.is_dir():
            continue
        if not (slot / "BALDUR.gam").is_file() or not any(slot.glob("*.SAV")):
            continue
        digest = slot_digest(slot)
        if digest in existing_digests:
            skipped += 1
            continue
        if slot.name.isdigit() and slot.name not in used:
            name = slot.name
        else:
            # Name collisions get a free slot number; nothing is merged.
            while f"{next_index:08d}" in used:
                next_index += 1
            name = f"{next_index:08d}"
            next_index += 1
        staging = target / f".import-{name}"
        shutil.copytree(slot, staging)
        shutil.move(str(staging), str(target / name))
        used.add(name)
        existing_digests.add(digest)
        copied += 1
    print(f"Imported {copied} save slot(s) into the Controller Lab profile ({skipped} already present).")
    print(f"  from {source}\n  to   {target}")


# --------------------------------------------------------------------------- #
# reporting
# --------------------------------------------------------------------------- #

SUPPORTED_EXE_HASH_DISPLAY = SUPPORTED_EXE_SHA256


def launch_option(game_dir: Path) -> str:
    """Swap the game executable for the mod launcher inside Steam's command.

    Proton documents the `echo %command% | sed ... | sh` form, and it keeps
    Steam's quoting intact for install paths containing spaces. The launcher
    must be the process Steam starts because it injects the DLL into a
    suspended Torment.exe; starting Torment.exe directly skips the bridge.
    """
    return """echo "%command%" | sed 's|Torment[.]exe|ControllerLab.exe|' | sh"""


def print_launch_help(game_dir: Path) -> None:
    print("Steam Deck / Linux launch setup")
    print("-" * 60)
    print("1. Steam > Planescape: Torment: Enhanced Edition > Properties >")
    print("   Compatibility: force a Proton version (9.0 or newer).")
    print("2. Properties > Launch Options - paste exactly:")
    print()
    print("   " + launch_option(game_dir))
    print()
    print("3. Properties > Controller: keep Steam Input ENABLED with a pad-only")
    print("   template (gamepad buttons, no keyboard/mouse bindings). The mod reads")
    print("   XInput; disabling Steam Input leaves the Deck's built-in pad invisible.")
    print()
    print("4. Start the game, then press and release A once to arm controller mode.")


def cmd_status(args) -> int:
    game_dir = resolve_game(args.game_dir)
    state = load_state(game_dir)
    print(f"Game folder: {game_dir}")
    exe = game_dir / "Torment.exe"
    print(f"Torment.exe: {sha256_path(exe) if exe.is_file() else 'MISSING'}")
    if not state:
        print("Mod:         not installed")
        return 0
    print(f"Mod:         {state['status']} (v{state.get('version')}, backups {state['backupSet'][:8]})")
    for entry in state["files"]:
        path = game_dir / entry["path"]
        ok = path.is_file() and sha256_path(path) == entry["installedHash"]
        print(f"  {'ok  ' if ok else 'DIFF'} {entry['path']}")
    return 0


def cmd_detect(args) -> int:
    candidates = game_candidates()
    if not candidates:
        print("No Planescape: Torment Enhanced Edition install found.")
        print("Searched:", ", ".join(str(r) for r in steam_roots()) or "(no Steam roots)")
        return 1
    for candidate in candidates:
        exe = candidate / "Torment.exe"
        state = load_state(candidate) if looks_like_game(candidate) else None
        print(f"{candidate}")
        print(f"  Torment.exe: {'yes ' + sha256_path(exe)[:16] if exe.is_file() else 'no (native Linux build - force Proton)'}")
        print(f"  mod:         {state['status'] if state else 'not installed'}")
    return 0


def cmd_launch_option(args) -> int:
    game_dir = resolve_game(args.game_dir)
    print(launch_option(game_dir))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="PST:EE controller mod installer for Linux/Steam Deck")
    parser.add_argument("command", choices=["install", "uninstall", "status", "detect", "launch-option"])
    parser.add_argument("--game-dir", help="folder containing Torment.exe")
    parser.add_argument("--package", help="preview ZIP or extracted package folder")
    parser.add_argument("--cache-dir", default="~/.cache/pstee-controller-deck")
    parser.add_argument("--allow-unknown-exe", action="store_true")
    parser.add_argument("--import-saves", action="store_true")
    args = parser.parse_args(argv)

    handlers = {
        "install": cmd_install,
        "uninstall": cmd_uninstall,
        "status": cmd_status,
        "detect": cmd_detect,
        "launch-option": cmd_launch_option,
    }
    try:
        return handlers[args.command](args)
    except InstallError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
