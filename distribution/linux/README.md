# Linux / Steam Deck installer

Ports the Windows installer (`Install.ps1`) to stdlib Python so the mod can be
installed from Konsole on SteamOS or any Linux box running the game under
Proton.

```
bash install-deck.sh
```

No root, no system packages, no PowerShell. Files are written only inside the
game folder; the download cache is `~/.cache/pstee-controller-deck`.

## Force Proton first

Steam ships a **native Linux build** of PST:EE. It has no `Torment.exe`, and
the mod is a Windows DLL injection, so the Windows depot is mandatory:

1. Steam → the game → right-click → **Properties** → **Compatibility**
2. Tick **Force the use of a specific Steam Play compatibility tool**
3. Choose **Proton 9.0** or newer and let the depot download

The installer verifies this and stops with the same instruction if
`Torment.exe` is missing.

## Launch options are required

Properties → **Launch Options**:

```
echo "%command%" | sed 's|Torment[.]exe|ControllerLab.exe|' | sh
```

`ControllerLab.exe` creates `Torment.exe` suspended and injects
`override/pstcontroller.dll` before it runs. Starting `Torment.exe` directly
skips the injection, `PSTPadNative` is never registered, and every button is
inert — the Lua fallback (`package.loadlib`) is not the supported path. The
substitution happens inside Steam's own command so the Proton prefix, and
therefore the save profile, is identical to a normal launch.

## Controller setting differs from Windows

Properties → **Controller**: keep **Steam Input enabled**, with a **gamepad-only**
template (no keyboard or mouse bindings).

The README's "Disable Steam Input" step is Windows advice for a physical Xbox
pad, which is already an XInput device. On a Deck, Steam Input is what presents
the built-in controls as an XInput pad; disabling it leaves the mod with no
input at all.

## Usage

```bash
bash install-deck.sh                     # detect + install
bash install-deck.sh --import-saves      # also copy existing local saves
bash install-deck.sh --game-dir "/run/media/deck/sdcard/steamapps/common/Planescape Torment Enhanced Edition"
bash install-deck.sh --package /path/to/PSTEE-Xbox-Controller-v0.1.31-preview.zip
bash uninstall-deck.sh                   # restore original files
python3 install.py status                # per-file installed/DIFF report
python3 install.py detect                # what was found, and its state
```

The payload ZIP is downloaded from upstream's release and every file is
verified against `manifest.json` before anything is written. Set
`PSTEE_MOD_SOURCE=<owner>/<repo>` to pull from a different release repo.

## Behaviour preserved from the Windows installer

- stock `UI.menu` is read from `chitin.key` + `data/*.bif`, then patched with
  `ui-patch.json`, with the source and target SHA-256 both enforced
- `engine.lua` is renamed to the `Planescape Torment - Controller Lab` profile,
  so the mod runs on its own saves and settings
- every replaced file is backed up under `.pstee-controller-deck/` and restored
  byte-for-byte on uninstall
- a foreign executable, an existing custom `UI.menu`, or a differing stock UI
  is refused rather than overwritten
- a file edited after installation is never clobbered on uninstall

Differences: state lives in `.pstee-controller-deck/` instead of
`.pstcontroller/`, uninstall is `uninstall-deck.sh`, and save import reads the
Proton prefix at `.../compatdata/466300/pfx/...` instead of `Documents`.

## Tests

```bash
PSTEE_PREVIEW_ZIP=/path/to/PSTEE-Xbox-Controller-v0.1.31-preview.zip python3 test_install.py
```

Real payload binaries are not committed, so the tests take them from a release
ZIP (or `PSTEE_PAYLOAD_DIR`). Everything else is synthetic: KEY/BIFF fixtures,
a fixture `ui-patch.json`, a fake `.exe` and a simulated Steam layout, so no
game files are needed and nothing touches a real installation.

Covered: KEY/BIFF parsing including multi-BIFF libraries (BIF index in the
locator's high bits), ambiguous and out-of-range locators; patch application
with hash enforcement; install/uninstall byte-exact round-trip; mid-list
uninstall conflict aborting before any write; refusal of foreign executables,
custom UIs and the native-Linux layout; Steam discovery via
`appmanifest_466300.acf` and `libraryfolders.vdf` with symlinked roots
de-duplicated; save import collisions, idempotent re-runs and incomplete-slot
skips; and the launch option rewriting the exe inside a simulated Proton
command line containing spaces.

## Known limitation

DLL injection under Proton is **unverified** — it relies on suspended-process
`LdrLoadDll` plus `SDL_*` lookups inside the engine image. If the mod loads but
buttons do nothing, read `controller-loader.log` and `controller-runtime.log`
in the game folder: the loader log shows whether injection succeeded, and that
distinguishes "loader never ran" (launch option) from "injected but no input"
(Steam Input / XInput).
