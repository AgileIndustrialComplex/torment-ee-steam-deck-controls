#!/usr/bin/env python3
"""Hermetic tests for install.py against synthetic KEY/BIFF fixtures.

No real game files, no Steam library, no network. Mirrors upstream's
test_distribution.py approach: a fake executable and a synthetic UI patch
replace the real ones, so only the installer logic is under test.

    python3 test_install.py
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import struct
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import install  # noqa: E402

FAKE_EXE = b"Fixture only: not a PE executable and never launched."
STOCK_UI = (
    "-- stock ui fixture\n"
    "function onButton()\n"
    "\tprint('hello')\n"
    "end\n"
    "M_LAST = 1\n"
)
# Two hunks: one replacing a statement, one inserting a line.
HUNK_A = ("\tprint('hello')\n", "\tprint('hello'); \"$PSTController.MenuOpened('X'); \n")
HUNK_B = ("M_LAST = 1\n", "M_LAST = 1\nM_EXTRA = 2\n")


def make_patch(source: str) -> tuple[dict, bytes]:
    """Build a ui-patch.json equivalent for the fixture UI."""
    hunks = []
    target = source
    # Apply in order, tracking byte offsets on the normalised text.
    data = source.encode()
    out = bytearray()
    cursor = 0
    for old, new in (HUNK_A, HUNK_B):
        idx = data.find(old.encode(), cursor)
        assert idx >= 0, old
        out += data[cursor:idx]
        out += new.encode()
        cursor = idx + len(old.encode())
        hunks.append(
            {
                "start": idx,
                "delete": len(old.encode()),
                "insert": base64.b64encode(new.encode()).decode(),
            }
        )
    out += data[cursor:]
    target = bytes(out)
    patch = {
        "format": 1,
        "sourceSha256": hashlib.sha256(data).hexdigest(),
        "targetSha256": hashlib.sha256(target).hexdigest(),
        "hunks": hunks,
    }
    return patch, target


def build_bif(resources: list[tuple[int, int, bytes]]) -> bytes:
    """resources: (resid, resource_kind, data)."""
    table = 20
    offset = table + len(resources) * 16
    entries = b""
    body = b""
    for resid, kind, data in resources:
        entries += struct.pack("<IIIHH", resid, offset + len(body), len(data), kind, 0)
        body += data
    return b"BIFFV1  " + struct.pack("<3I", len(resources), 0, table) + entries + body


def build_key(bifs: list[tuple[str, bytes]], files: list[tuple[bytes, int, int, int]]) -> bytes:
    """bifs: (key_name, bytes). files: (resname, kind, bif_index, resid).

    locator packs the BIF index in the high bits and the resource id low, so a
    resource with colliding low bits in another BIF must never be selected.
    """
    header_len = 24
    bif_table = header_len
    name_table = bif_table + len(bifs) * 12
    names = b""
    bif_rows = b""
    for name, data in bifs:
        encoded = name.encode() + b"\x00"
        bif_rows += struct.pack("<IIHH", len(data), name_table + len(names), len(encoded), 0)
        names += encoded
    file_table = name_table + len(names)
    file_rows = b""
    for resname, kind, bif_index, resid in files:
        file_rows += struct.pack("<8sHI", resname, kind, (bif_index << 20) | resid)
    key = (
        b"KEY V1  "
        + struct.pack("<4I", len(bifs), len(files), bif_table, file_table)
        + bif_rows
        + names
        + file_rows
    )
    return key


def write_fixture(path: Path, key: bytes, bif_blobs: dict[str, bytes]) -> None:
    for name in {*bif_blobs}:
        target = path / name
        target.parent.mkdir(parents=True, exist_ok=True)
    for name, data in bif_blobs.items():
        (path / name).write_bytes(data)
    (path / "chitin.key").write_bytes(key)


def build_fixture_game(path: Path, stock_ui_text: str, extra_files=None) -> None:
    path.mkdir(parents=True)
    (path / "data").mkdir()
    (path / "override").mkdir()
    # Game resources carry a UTF-8 BOM; the installer must strip it.
    original = b"\xef\xbb\xbf" + stock_ui_text.encode()
    bif = build_bif([(0, 0x408, original)])
    key = build_key([("data/test.bif", bif)], [(b"UI", 0x408, 0, 0)])
    write_fixture(path, key, {"data/test.bif": bif})
    (path / "Torment.exe").write_bytes(FAKE_EXE)
    (path / "engine.lua").write_bytes(b'engine_name="Fixture original profile"\r\nengine_mode=3\r\n')
    (path / "override/unrelated.lua").write_bytes(b"-- keep this unrelated file unchanged\n")


def payload_source() -> Path:
    """Locate real payload binaries.

    Order: an explicit --payload-dir, then a local release ZIP handed over via
    PSTEE_PREVIEW_ZIP, then ./payload next to this file. Real binaries are
    never committed, so CI passes a downloaded release ZIP.
    """
    override = os.environ.get("PSTEE_PAYLOAD_DIR")
    if override:
        path = Path(override).expanduser()
        if path.is_dir():
            return path
        raise SystemExit(f"PSTEE_PAYLOAD_DIR is not a directory: {path}")

    archive = os.environ.get("PSTEE_PREVIEW_ZIP")
    if archive:
        extract = Path(__file__).parent / ".payload-cache"
        with zipfile.ZipFile(archive) as zf:
            for member in zf.namelist():
                if "/payload/" in member:
                    name = member.rsplit("/", 1)[-1]
                    if name:
                        extract.mkdir(parents=True, exist_ok=True)
                        (extract / name).write_bytes(zf.read(member))
        return extract

    local = Path(__file__).parent / "payload"
    if local.is_dir():
        return local
    raise SystemExit(
        "No payload binaries found. Download the v" + install.RELEASE_VERSION +
        " preview ZIP and set PSTEE_PREVIEW_ZIP=/path/to.zip, "
        "or pass PSTEE_PAYLOAD_DIR=/path/to/payload"
    )


def build_package(root: Path, patch: dict, target: bytes) -> Path:
    """Copy the real payload and swap in the fixture patch + exe hash."""
    package = root / "package" / f"PSTEE-Xbox-Controller-v{install.RELEASE_VERSION}-preview"
    payload = package / "payload"
    payload.mkdir(parents=True)
    release = payload_source()
    for name in ("ControllerLab.exe", "M_PSTPAD.lua", "PSTPRAD.bam", "PSTPSEL.bam", "pstcontroller.dll"):
        shutil.copy2(release / name, payload / name)
    (payload / "ui-patch.json").write_text(json.dumps(patch))
    manifest = {
        "version": "0.1.31",
        "preview": True,
        "exeSha256": hashlib.sha256(FAKE_EXE).hexdigest(),
        "payload": [],
    }
    for name in sorted(p.name for p in payload.iterdir()):
        manifest["payload"].append(
            {
                "path": f"payload/{name}",
                "sha256": hashlib.sha256((payload / name).read_bytes()).hexdigest(),
            }
        )
    (package / "manifest.json").write_text(json.dumps(manifest))
    return package


def snapshot(path: Path) -> dict[str, bytes]:
    return {
        f.relative_to(path).as_posix(): f.read_bytes()
        for f in sorted(path.rglob("*"))
        if f.is_file() and install.STATE_DIR not in f.relative_to(path).parts
    }


def test_key_parsing(stock: str) -> None:
    """Multi-BIFF keys: locator high bits select the BIF, low bits the resource."""
    original = b"\xef\xbb\xbf" + stock.encode()
    decoy = b"decoy: same low 14 bits, other BIF"
    bif0 = build_bif([(0x4C02, 0x408, decoy)])
    bif1 = build_bif([(0xC02, 0x408, original), (0xC03, 0x409, b"other")])
    assert (0x4C02 & 0x3FFF) == (0xC02 & 0x3FFF), "fixture must actually collide"

    bifs = [("data/a.bif", bif0), ("data/b.bif", bif1)]
    with tempfile.TemporaryDirectory() as tmp:
        game = Path(tmp) / "multi"
        game.mkdir()
        # The UI resource lives in BIF 1 while a colliding id sits in BIF 0.
        key = build_key(bifs, [(b"UI", 0x408, 1, 0xC02)])
        write_fixture(game, key, {"data/a.bif": bif0, "data/b.bif": bif1})
        assert install.read_game_ui(game) == stock.encode(), "wrong BIF selected"

        # Two UI entries in the file table are ambiguous and must be refused.
        dup = build_key(bifs, [(b"UI", 0x408, 1, 0xC02), (b"UI", 0x408, 1, 0xC02)])
        write_fixture(game, dup, {"data/a.bif": bif0, "data/b.bif": bif1})
        try:
            install.read_game_ui(game)
        except install.InstallError as exc:
            assert "Duplicate" in str(exc), exc
        else:
            raise AssertionError("ambiguous UI resource accepted")

        # A locator pointing past the BIF table must be refused, not trusted.
        oob = build_key(bifs, [(b"UI", 0x408, 9, 0xC02)])
        write_fixture(game, oob, {"data/a.bif": bif0, "data/b.bif": bif1})
        try:
            install.read_game_ui(game)
        except install.InstallError as exc:
            assert "BIFF index" in str(exc), exc
        else:
            raise AssertionError("out-of-range BIFF index accepted")


def test_steam_layout(stock: str) -> None:
    """Discovery via appmanifest, and save import inside a Proton prefix."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "Steam"
        common = root / "steamapps" / "common"
        gamedir = common / "Planescape Torment Enhanced Edition"
        (root / "steamapps").mkdir(parents=True)
        (root / "steamapps" / f"appmanifest_{install.APPID}.acf").write_text(
            '"AppState"\n{\n\t"appid"\t\t"466300"\n'
            '\t"installdir"\t\t"Planescape Torment Enhanced Edition"\n}\n'
        )
        gamedir.mkdir(parents=True)
        build_fixture_game_payload(gamedir, stock)

        # A second library on an SD card, referenced from libraryfolders.vdf.
        sdcard = Path(tmp) / "sdcard"
        (sdcard / "steamapps").mkdir(parents=True)
        (sdcard / "steamapps" / "libraryfolders.vdf").write_text("")
        (root / "steamapps" / "libraryfolders.vdf").write_text(
            '"libraryfolders"\n{\n\t"0"\n\t{\n\t\t"path"\t\t"%s"\n\t}\n'
            '\t"1"\n\t{\n\t\t"path"\t\t"%s"\n\t}\n}\n' % (root, sdcard)
        )

        install.steam_roots = lambda: [root]
        found = install.game_candidates()
        assert gamedir.resolve() in [f.resolve() for f in found], found
        assert install.resolve_game(None).resolve() == gamedir.resolve()

        # Save import: Proton prefix Documents hold the original profile.
        pfx = root / "steamapps" / "compatdata" / install.APPID / "pfx"
        docs = pfx / "drive_c" / "users" / "steamuser" / "Documents"
        old_save = docs / install.PROFILE_OLD / "save" / "000000001"
        old_save.mkdir(parents=True)
        (old_save / "BALDUR.gam").write_bytes(b"gam")
        (old_save / "BALDUR.SAV").write_bytes(b"sav")
        (old_save / "BALDUR.bmp").write_bytes(b"bmp")
        # An incomplete slot must be skipped, not copied.
        (docs / install.PROFILE_OLD / "save" / "000000002").mkdir()
        # A pre-existing target slot must be preserved, ours takes a free name.
        existing = docs / install.PROFILE_NEW / "save" / "000000001"
        existing.mkdir(parents=True)
        (existing / "BALDUR.gam").write_bytes(b"pre-existing")

        assert install.compat_prefix(gamedir).resolve() == pfx.resolve()
        install.import_saves(gamedir)

        target = docs / install.PROFILE_NEW / "save"
        assert (existing / "BALDUR.gam").read_bytes() == b"pre-existing", "existing slot overwritten"
        slots = sorted(p.name for p in target.iterdir())
        assert len(slots) == 2, slots
        copied = [s for s in slots if s != "000000001"][0]
        assert (target / copied / "BALDUR.SAV").read_bytes() == b"sav"
        assert not any(p.name.startswith(".import-") for p in target.iterdir()), "staging left behind"
        assert not (target / "000000002").exists(), "incomplete slot imported"

        # A second import must not duplicate the same slot.
        install.import_saves(gamedir)
        assert sorted(p.name for p in target.iterdir()) == slots, "duplicate import"


def build_fixture_game_payload(path: Path, stock: str) -> None:
    """Populate an existing directory as a game folder."""
    (path / "data").mkdir(exist_ok=True)
    (path / "override").mkdir(exist_ok=True)
    original = b"\xef\xbb\xbf" + stock.encode()
    bif = build_bif([(0, 0x408, original)])
    write_fixture(path, build_key([("data/test.bif", bif)], [(b"UI", 0x408, 0, 0)]), {"data/test.bif": bif})
    (path / "Torment.exe").write_bytes(FAKE_EXE)
    (path / "engine.lua").write_bytes(b'engine_name="Fixture original profile"\r\n')


def test_launch_option() -> None:
    """The launch option must swap the exe inside Steam's own command line."""
    import subprocess

    option = install.launch_option(Path("/nonexistent"))
    assert "%command%" in option and "ControllerLab.exe" in option
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        proton = tmp_path / "proton"
        proton.write_text('#!/bin/bash\nprintf "%s\\n" "$@"\n')
        proton.chmod(0o755)
        # Install path with spaces, like the real Steam folder name.
        exe = tmp_path / "Planescape Torment Enhanced Edition" / "Torment.exe"
        steam_cmd = f"{proton} waitforexitandrun '{exe}'"
        script = tmp_path / "run.sh"
        script.write_text(option.replace("%command%", steam_cmd) + "\n")
        result = subprocess.run(["bash", str(script)], capture_output=True, text=True, timeout=20)
        assert result.returncode == 0, result.stderr
        lines = result.stdout.strip().splitlines()
        assert lines[0] == "waitforexitandrun", lines
        expected = str(exe.parent / "ControllerLab.exe")
        assert lines[1] == expected, f"got {lines[1]!r} want {expected!r}"


def run(args: list[str]) -> int:
    return install.main(args)


def expect_error(args: list[str], needle: str) -> None:
    """main() returns 2 and prints to stderr on InstallError."""
    import contextlib
    import io

    err = io.StringIO()
    out = io.StringIO()
    with contextlib.redirect_stderr(err), contextlib.redirect_stdout(out):
        code = install.main(args)
    assert code == 2, f"expected refusal, got exit {code}\n{out.getvalue()}\n{err.getvalue()}"
    assert needle.lower() in err.getvalue().lower(), f"missing {needle!r} in: {err.getvalue()}"


def test() -> None:
    stock = STOCK_UI.replace("\r\n", "\n")
    patch, target = make_patch(stock)
    with tempfile.TemporaryDirectory(prefix="pstee-deck-test-") as tmp:
        tmp_path = Path(tmp)
        package = build_package(tmp_path, patch, target)
        install.SUPPORTED_EXE_SHA256 = hashlib.sha256(FAKE_EXE).hexdigest()
        install.SUPPORTED_EXE_HASH_DISPLAY = hashlib.sha256(FAKE_EXE).hexdigest()

        test_key_parsing(stock)
        test_steam_layout(stock)
        test_launch_option()

        # --- UI patch arithmetic ------------------------------------------
        assert install.apply_ui_patch(stock.encode(), patch) == target
        try:
            install.apply_ui_patch(b"-- wrong source\n", patch)
        except install.InstallError as exc:
            assert "differs from the supported build" in str(exc)
        else:
            raise AssertionError("UI patch accepted a foreign source")

        # --- install -------------------------------------------------------
        game = tmp_path / "fixture game with spaces"
        build_fixture_game(game, stock)
        before = snapshot(game)
        assert run(["install", "--game-dir", str(game), "--package", str(package)]) == 0

        assert (game / "override/UI.menu").read_bytes() == target
        assert (game / "override/M_PSTPAD.lua").is_file()
        assert (game / "override/pstcontroller.dll").is_file()
        assert (game / "ControllerLab.exe").is_file()
        assert 'engine_name="Planescape Torment - Controller Lab"' in (game / "engine.lua").read_text()
        assert (game / "override/unrelated.lua").read_bytes() == before["override/unrelated.lua"]

        state = json.loads((game / install.STATE_DIR / "state.json").read_text())
        assert state["status"] == "installed"
        assert len(state["files"]) == 7
        assert not (game / install.STATE_DIR / "stage" / state["backupSet"]).exists(), "staging left behind"

        # install is not idempotently dangerous
        expect_error(["install", "--game-dir", str(game), "--package", str(package)], "already installed")

        # --- status --------------------------------------------------------
        import contextlib
        import io

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            assert run(["status", "--game-dir", str(game)]) == 0
        assert "ok   override/UI.menu" in buf.getvalue(), buf.getvalue()

        # --- uninstall restores exact bytes --------------------------------
        assert run(["uninstall", "--game-dir", str(game)]) == 0
        assert snapshot(game) == before, "uninstall must restore original bytes exactly"
        assert (game / install.STATE_DIR / "backups" / state["backupSet"]).is_dir()

        # --- reinstall keeps the previous backup set -----------------------
        assert run(["install", "--game-dir", str(game), "--package", str(package)]) == 0
        second = json.loads((game / install.STATE_DIR / "state.json").read_text())
        assert second["backupSet"] != state["backupSet"]
        assert (game / install.STATE_DIR / "backups" / state["backupSet"]).is_dir()

        # --- edited files are never clobbered ------------------------------
        lua = game / "override/M_PSTPAD.lua"
        lua.write_bytes(lua.read_bytes() + b"\n-- later user edit\n")
        edited = snapshot(game)
        expect_error(["uninstall", "--game-dir", str(game)], "changed after installation")
        assert snapshot(game) == edited, "refused uninstall must not touch files"
        lua.write_bytes((package / "payload/M_PSTPAD.lua").read_bytes())
        assert run(["uninstall", "--game-dir", str(game)]) == 0
        assert snapshot(game) == before

        # --- foreign executable is refused ---------------------------------
        wrong = tmp_path / "wrong executable"
        build_fixture_game(wrong, stock)
        (wrong / "Torment.exe").write_bytes(b"unsupported executable")
        wrong_before = snapshot(wrong)
        expect_error(["install", "--game-dir", str(wrong), "--package", str(package)], "fingerprint")
        assert snapshot(wrong) == wrong_before
        assert not (wrong / install.STATE_DIR).exists()

        # --- existing custom UI mod is refused -----------------------------
        custom = tmp_path / "custom ui"
        build_fixture_game(custom, stock)
        (custom / "override/UI.menu").write_bytes(b"\xef\xbb\xbf-- some other UI mod\n")
        custom_before = snapshot(custom)
        expect_error(["install", "--game-dir", str(custom), "--package", str(package)], "custom override/UI.menu")
        assert snapshot(custom) == custom_before

        # --- native Linux build (no Torment.exe) is refused clearly --------
        native = tmp_path / "native linux"
        build_fixture_game(native, stock)
        (native / "Torment.exe").unlink()
        expect_error(["install", "--game-dir", str(native), "--package", str(package)], "Force Proton")

        # --- launch option string ------------------------------------------
        opt = install.launch_option(game)
        assert "ControllerLab.exe" in opt and "%command%" in opt

    print("all installer tests passed")


if __name__ == "__main__":
    test()
