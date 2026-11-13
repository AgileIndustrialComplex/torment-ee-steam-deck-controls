#!/usr/bin/env python3
"""Derive the native bridge binding table from the Linux PST:EE ELF.

The Linux Torment binary ships unstripped, so every engine address the bridge
needs resolves by symbol name instead of by hand-derived RVA. This script
reads the game executable, resolves the binding table below, validates
anchor expectations, and emits native/linux_offsets.h for the build.

Run it against a game copy whose SHA-256 is already recorded in
linux_offsets.h (or pass --update to write the new fingerprint); re-run for
any future game build and commit the regenerated header with it.

Usage:
    python3 inspect_linux.py --game-dir <dir> [--update]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
import subprocess
import sys
from pathlib import Path

LAB = Path(__file__).resolve().parent
HEADER = LAB / "native" / "linux_offsets.h"

GAME_BINARY = "Torment"

# name -> (mangled symbol, kind, comment). kind: func|obj|slot|member|const
BINDINGS = [
    # -- engine globals -------------------------------------------------- #
    ("g_pBaldurChitin", "g_pBaldurChitin", "obj", "the CBaldurChitin global pointer"),
    ("object_rows", "_ZN16CGameObjectArray8m_pArrayE", "obj", "first row; rows are base+slot*16"),
    ("object_max_index", "_ZN16CGameObjectArray15m_maxArrayIndexE", "obj", "highest used slot"),
    ("reference_width", "_ZN8CVidMode11SCREENWIDTHE", "obj", "reference resolution width"),
    ("reference_height", "_ZN8CVidMode12SCREENHEIGHTE", "obj", "reference resolution height"),
    ("vtable_cgamesprite", "_ZTV11CGameSprite", "obj", "+0x10 is the value stored in sprite objects"),
    # -- lua (statically linked into the game) --------------------------- #
    ("lua_pushcclosure", "lua_pushcclosure", "func", ""),
    ("lua_pushnumber", "lua_pushnumber", "func", ""),
    ("lua_tonumberx", "lua_tonumberx", "func", ""),
    ("lua_setglobal", "lua_setglobal", "func", "registers PSTPadNative on the engine state"),
    ("luaL_newstate", "luaL_newstate", "func", "called by bootstrapLua; replayed by its trampoline"),
    ("g_lua", "g_lua", "obj", "the engine's single lua_State*"),
    ("bootstrap_lua", "_Z12bootstrapLuav", "func", "creates g_lua and opens the libraries; patched to register the bridge"),
    # -- engine functions ------------------------------------------------ #
    ("group_clear_actions", "_ZN8CAIGroup12ClearActionsEv", "func", "CAIGroup::ClearActions()"),
    ("group_move", "_ZN8CAIGroup14GroupSetTargetE6CPointisS0_", "func", "CAIGroup::GroupSetTarget(CPoint,int,short,CPoint)"),
    ("prepare_group_run", "_ZN9CGameArea17SetupPartyRunningEv", "func", "CGameArea::SetupPartyRunning()"),
    ("clear_pending_actions", "_ZN11CGameAIBase12ClearActionsEi", "func", "CGameAIBase::ClearActions(int)"),
    ("request_move_path", "_ZN11CGameSprite11MoveToPointERK6CPoint", "func", "CGameSprite::MoveToPoint(const CPoint&): writes the current-action point then replans asynchronously; uint16 return is compared against ACTION_DONE by the engine (CGameSprite::RemoveTraps)"),
    ("set_world_view", "_ZN12CScreenWorld11StartScrollE6CPoints", "func", "CScreenWorld::StartScroll(CPoint,short)"),
    ("get_selected_character", "_ZN12CScreenWorld20GetSelectedCharacterEv", "func", "vtable slot +0x1c8 of CScreenWorld"),
    ("get_bounding", "_ZN14CGameContainer11GetBoundingEv", "func", "vtable slot +0x188; returns the 16-byte CRect in rax:rdx"),
    ("on_action_button", "_ZN11CGameObject14OnActionButtonERK6CPoint", "func", "vtable slot +0x80 of game objects"),
    ("process_events", "_ZN7CChitin13ProcessEventsEv", "func", "patched prologue for movie skip / marked-key filtering"),
    ("ui_do_file", "_Z8uiDoFilePKc", "func", "Lua file loader; wrapped to log every executed chunk"),
    ("cvideo_set_pointer", "_ZN8CVidMode10SetPointerEP8CVidCell7CResRefhi", "func", "patched to suppress cursor updates while the mod hides the cursor"),
    ("cwarp_on_event", "_ZN5CWarp7OnEventEP9SDL_Event", "func", "loaded by the ProcessEvents prologue we relocate"),
    # -- SDL (statically linked into the game) --------------------------- #
    ("sdl_poll_event", "SDL_PollEvent", "func", ""),
    ("sdl_push_event", "SDL_PushEvent", "func", ""),
    ("sdl_wait_event_timeout", "SDL_WaitEventTimeout", "func", ""),
    ("sdl_get_mouse_focus", "SDL_GetMouseFocus", "func", ""),
    ("sdl_get_keyboard_focus", "SDL_GetKeyboardFocus", "func", ""),
    ("sdl_get_mouse_state", "SDL_GetMouseState", "func", ""),
    ("sdl_get_window_size", "SDL_GetWindowSize", "func", ""),
    ("sdl_get_window_id", "SDL_GetWindowID", "func", ""),
    ("sdl_get_ticks", "SDL_GetTicks", "func", ""),
    ("sdl_warp_mouse_in_window", "SDL_WarpMouseInWindow", "func", ""),
    ("sdl_get_scancode_from_key", "SDL_GetScancodeFromKey", "func", ""),
    ("sdl_show_cursor", "SDL_ShowCursor", "func", ""),
    ("sdl_add_event_watch", "SDL_AddEventWatch", "func", ""),
    ("sdl_num_joysticks", "SDL_NumJoysticks", "func", ""),
    ("sdl_is_game_controller", "SDL_IsGameController", "func", ""),
    ("sdl_game_controller_open", "SDL_GameControllerOpen", "func", ""),
    ("sdl_game_controller_get_axis", "SDL_GameControllerGetAxis", "func", ""),
    ("sdl_game_controller_get_button", "SDL_GameControllerGetButton", "func", ""),
    ("sdl_game_controller_close", "SDL_GameControllerClose", "func", ""),
]

# CBaldurChitin member offsets. The Windows 3.2.2.0 exe used 0x10c8/0x10d8/
# 0x1148 here; the Linux build inserts 0x50 bytes before that region, which
# the pair (chitin+0x1118 == CInfGame, verified in CScreenWorld::StartScroll
# and CBaldurProjector::TimerSynchronousUpdate) and chitin+0x1128 ==
# CBaldurProjector (CChitin::Init) fix in place. chitin+0x260/0x268 are used
# unchanged by CChitin::SelectEngine / the CVidMode::ResetViewport caller.
CHITIN_MEMBERS = [
    ("CHITIN_GAME", 0x1118, "CInfGame*"),
    ("CHITIN_ACTIVE_ENGINE", 0x260, "CWarp* currently active"),
    ("CHITIN_VIDEO", 0x268, "CVidMode*"),
    ("CHITIN_MOVIE_PROJECTOR", 0x1128, "CBaldurProjector*"),
    ("CHITIN_WORLD_SCREEN", 0x1198, "CScreenWorld*"),
]

# Cross-build invariants used to validate a freshly derived table.
SANITY = {
    "lua_pushcclosure": (100, 400),
    "lua_pushnumber": (16, 64),
    "group_move": (4000, 12000),
    "process_events": (2000, 9000),
    "sdl_poll_event": (60, 400),
}


def sha256_path(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_symbols(binary: Path) -> dict[str, tuple[int, int]]:
    out = subprocess.run(
        ["readelf", "-sW", str(binary)], capture_output=True, text=True, check=True
    ).stdout
    symbols: dict[str, tuple[int, int]] = {}
    for line in out.splitlines():
        m = re.match(
            r"\s*\d+:\s+([0-9a-f]+)\s+(\d+|0x[0-9a-f]+)\s+(FUNC|OBJECT)\s+\S+\s+\S+\s+\S+\s+(\S+)",
            line,
        )
        if m and int(m.group(1), 16):
            name = m.group(4).split("@")[0]
            size = int(m.group(2), 16) if m.group(2).startswith("0x") else int(m.group(2))
            symbols.setdefault(name, (int(m.group(1), 16), size))
    return symbols


def check_prologue(binary: Path, addr: int, size: int) -> bytes:
    """Return the raw first bytes of a function for the patch-site check."""
    out = subprocess.run(
        ["readelf", "-SW", str(binary)], capture_output=True, text=True, check=True
    ).stdout
    raw = b""
    with binary.open("rb") as fh:
        data = fh.read()
    for line in out.splitlines():
        m = re.match(
            r"\s*\[\s*\d+\]\s+(\S+)\s+(\S+)\s+([0-9a-f]+)\s+([0-9a-f]+)\s+([0-9a-f]+)",
            line,
        )
        if m and m.group(2) != "NOBITS":
            vaddr, off, sz = int(m.group(3), 16), int(m.group(4), 16), int(m.group(5), 16)
            if vaddr and vaddr <= addr < vaddr + sz:
                fo = off + (addr - vaddr)
                raw = data[fo : fo + size]
                break
    if len(raw) != size:
        raise SystemExit(f"cannot read {size} bytes at 0x{addr:x}")
    return raw


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game-dir", type=Path, required=True)
    parser.add_argument("--update", action="store_true", help="rewrite the pinned fingerprint")
    parser.add_argument("--json", type=Path, help="also write the table as JSON")
    args = parser.parse_args()

    binary = args.game_dir / GAME_BINARY
    if not binary.is_file():
        raise SystemExit(f"{binary} not found (native Linux game layout expected)")

    fingerprint = sha256_path(binary)
    symbols = load_symbols(binary)

    table = {}
    for c_name, symbol, kind, comment in BINDINGS:
        if symbol not in symbols:
            raise SystemExit(f"symbol not found in {binary.name}: {symbol}")
        addr, size = symbols[symbol]
        if kind == "func" and not size:
            raise SystemExit(f"zero-size symbol: {symbol}")
        table[c_name] = {"symbol": symbol, "addr": addr, "size": size, "comment": comment}

    for name, (lo, hi) in SANITY.items():
        if not lo <= table[name]["size"] <= hi:
            raise SystemExit(
                f"size sanity failed for {name}: {table[name]['size']} not in [{lo},{hi}]"
            )

    if table["vtable_cgamesprite"]["addr"] & 7:
        raise SystemExit("misaligned vtable symbol")

    # Patch-site prologues: the runtime refuses to patch unless these match.
    sites = {
        "process_events": (table["process_events"]["addr"], 17),
        "cvideo_set_pointer": (table["cvideo_set_pointer"]["addr"], 27),
        "bootstrap_lua": (table["bootstrap_lua"]["addr"], 13),
        "ui_do_file": (table["ui_do_file"]["addr"], 18),
    }
    prologues = {
        name: check_prologue(binary, addr, size).hex() for name, (addr, size) in sites.items()
    }

    header_text = HEADER.read_text() if HEADER.exists() else ""
    pinned = re.search(r'LX_ENGINE_SHA256\s+"([0-9a-f]{64})"', header_text)
    if pinned and pinned.group(1) != fingerprint and not args.update:
        raise SystemExit(
            "fingerprint mismatch\n"
            f"  header: {pinned.group(1)}\n"
            f"  binary: {fingerprint}\n"
            "Re-run with --update after re-verifying the binary, or use the game copy "
            "the header was generated from."
        )

    lines = [
        "/* Generated by controller-lab/inspect_linux.py from the Linux PST:EE",
        " * executable. Do not edit by hand; re-run the script against a game copy",
        " * and commit the result together with the fingerprint change.",
        " *",
        " * Every address resolves by symbol name from the unstripped ELF; the",
        " * bridge verifies the executable SHA-256 and the patch-site prologues",
        " * before binding anything.",
        " */",
        f'#define LX_ENGINE_SHA256 "{fingerprint}"',
        "",
    ]
    for c_name, _, kind, comment in BINDINGS:
        entry = table[c_name]
        if comment:
            lines.append(f"/* {comment} */")
        addr = entry["addr"]
        if c_name == "vtable_cgamesprite":
            # The value stored in object instances points past the Itanium
            # vtable header (offset-to-top + typeinfo), i.e. symbol + 0x10.
            addr += 0x10
            lines.append("/* object vptr value = _ZTV symbol + 0x10 */")
        lines.append(f"#define LX_{c_name.upper()}_ADDR 0x{addr:x}u")
        lines.append(f"#define LX_{c_name.upper()}_SIZE {entry['size']}u")
        lines.append("")
    for c_name, offset, comment in CHITIN_MEMBERS:
        lines.append(f"/* {comment} */")
        lines.append(f"#define {c_name} 0x{offset:x}u")
        lines.append("")
    for name, hexbytes in prologues.items():
        lines.append(f'#define LX_{name.upper()}_PROLOGUE "{hexbytes}"')
        lines.append(f"#define LX_{name.upper()}_PROLOGUE_SIZE {len(hexbytes) // 2}u")
        lines.append("")
    lines.append("/* vtable slot (byte offset) of the selected-portrait getter on the active screen */")
    lines.append("#define LX_SLOT_SELECTED_GETTER 0x1c8u")
    lines.append("/* vtable slots on game objects (CGameObject hierarchy) */")
    lines.append("#define LX_SLOT_OBJECT_CLICK 0x80u")
    lines.append("#define LX_SLOT_CONTAINER_BOUNDS 0x188u")
    lines.append("")
    HEADER.write_text("\n".join(lines))

    print(f"fingerprint: {fingerprint}")
    for c_name, _, _, _ in BINDINGS:
        e = table[c_name]
        print(f"  {c_name:32s} 0x{e['addr']:08x}  size {e['size']:5d}  {e['symbol']}")
    print(f"wrote {HEADER}")

    if args.json:
        payload = {
            "engineSha256": fingerprint,
            "binary": GAME_BINARY,
            "bindings": {k: v for k, v in table.items()},
            "chitinMembers": {c: o for c, o, _ in CHITIN_MEMBERS},
            "prologues": prologues,
        }
        args.json.write_text(json.dumps(payload, indent=2))
        print(f"wrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
