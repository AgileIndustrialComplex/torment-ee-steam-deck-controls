# PST:EE Controller Mod — Steam Deck / Linux installer

Controller support for **Planescape: Torment Enhanced Edition** on the **native
Linux build** (the Steam Deck default) and the Windows build under Proton:
direct left-stick party movement, right-stick camera, radial action menu,
dialogue and inventory navigation.

```
./install-deck.sh
```

That is the whole install.

Prefer a window? Grab
[PSTEE-Deck-Controller-v0.3.1-x86_64.AppImage](https://github.com/AgileIndustrialComplex/torment-ee-steam-deck-controls/releases/download/v0.3.1/PSTEE-Deck-Controller-v0.3.1-x86_64.AppImage)
from the releases, double-click it in Desktop Mode, and watch the same
installation run inside a scrollable log window (the payload is bundled; no
network needed). The log is also written to
`~/.cache/pstee-controller-deck/install.log`.

---

## Native Linux build (recommended — this is what your Deck has)

The mod needs **no Proton and no compatibility-tool change** - one
`LD_PRELOAD` launch option loads the native bridge before the game starts.
The installer maintains a space-free symlink (ld.so splits `LD_PRELOAD` on
spaces, and the game folder has spaces) and prints the exact option to paste.

Requirements:

- The game's **native** install folder — it contains a `Torment` binary next
  to `chitin.key`. If Steam downloaded the Windows depot instead (you see
  `Torment.exe`), switch Properties → Compatibility back to native and let it
  re-download.
- The verified Linux executable (SHA-256
  `e615763edb57427e3efded67296c357e2563ee40ebc2aef929e1f180e1b5846e`, Steam
  build 25492483, the same 3.2.2.0 content as the Windows target).
- **Keep Steam Input enabled** with a gamepad-only template. The bridge reads
  the pad through the game's own SDL; with Steam Input disabled, the Deck's
  built-in pad may not be visible to the game at all.

Install:

```bash
cd ~/Downloads/pstee-deck
./install-deck.sh
```

It finds the game automatically, verifies the executable fingerprint and the
payload checksums, stages every file, and only then writes. It also creates
the `~/.cache/pstee-controller-deck/bridge.so` symlink used by the launch
option. Use `--import-saves` to copy your existing local saves into the mod's
separate profile.

The launch option to paste into Steam (the installer prints it too):

```
LD_PRELOAD="/home/deck/.cache/pstee-controller-deck/bridge.so" %command%
```

Uninstall removes the symlink; clear the Launch Options field afterwards.

Manual path if auto-detection fails:

```bash
./install-deck.sh --game-dir "/run/media/deck/sdcard/steamapps/common/Planescape Torment Enhanced Edition"
./install-deck.sh --package /path/to/PSTEE-Native-Controller-v0.3.1-preview.zip
```

GOG installs with a `game/` subfolder work too — pass the outer folder.

No root, no system packages, nothing installed outside the game folder and
`~/.cache/pstee-controller-deck`.

### Saves

The mod runs on its own profile — **Planescape Torment - Controller Lab** —
under `~/.local/share/`, so your original saves and settings are untouched.
Import them with:

```bash
./install-deck.sh --import-saves
```

### Uninstall

```bash
./uninstall-deck.sh
```

Restores every replaced file byte-for-byte from the backups in
`.pstee-controller-deck/backups/`. If you edited an installed file afterwards
it refuses rather than clobbering your edits, and tells you where the backup is.

## Windows build under Proton

The upstream Windows bridge is a DLL injected into a suspended `Torment.exe`,
so the Windows depot is required, plus one launch option. See
[the repo README](https://github.com/AgileIndustrialComplex/torment-ee-steam-deck-controls#linux-and-steam-deck)
for the two Steam settings, or run `./install.py launch-option` after
installing into a Proton game copy.

## Usage

```bash
bash install-deck.sh                     # detect + install
bash install-deck.sh --import-saves      # also copy existing local saves
bash install-deck.sh --game-dir "/run/media/deck/sdcard/steamapps/common/Planescape Torment Enhanced Edition"
bash install-deck.sh --package /path/to/PSTEE-Native-Controller-v0.3.1-preview.zip
bash uninstall-deck.sh                   # restore original files
python3 install.py status                # per-file installed/DIFF report
python3 install.py detect                # what was found, and its state
python3 install.py install --allow-unknown-exe   # different game build, at your own risk
```

The payload ZIP is downloaded from this project's release and every file is
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

## Tests

```bash
PSTEE_PREVIEW_ZIP=/path/to/PSTEE-Xbox-Controller-v0.3.1-preview.zip python3 test_install.py
```

Real payload binaries are not committed, so the tests take them from a release
ZIP (or `PSTEE_PAYLOAD_DIR`; the native payload dir can be set with
`PSTEE_NATIVE_PAYLOAD_DIR` — otherwise synthetic stubs cover the installer
logic). Everything else is synthetic: KEY/BIFF fixtures, a fixture
`ui-patch.json`, a fake executable and a simulated Steam layout, so no game
files are needed and nothing touches a real installation.

Covered: KEY/BIFF parsing including multi-BIFF libraries (BIF index in the
locator's high bits), ambiguous and out-of-range locators; patch application
with hash enforcement; install/uninstall byte-exact round-trip on both the
native and Proton layouts; native layout detection, the GOG `game/` subfolder,
the no-executable refusal and native save import from `~/.local/share`; refusal
of foreign executables and custom UIs; Steam discovery via
`appmanifest_466300.acf` and `libraryfolders.vdf` with symlinked roots
de-duplicated; save import collisions, idempotent re-runs and incomplete-slot
skips; and the launch option rewriting the exe inside a simulated Proton
command line containing spaces.

The native bridge itself has its own model tests — nearby interactions, 48
WALK/RUN renewals, 20 lagging-follower renewals, 80 RUN retargets, 48 WALK
turns, camera follow/pan/zoom, movie guard and marked-key filtering:

```bash
python3 ../../controller-lab/build_plugin_linux.py --check
```

## Known limitations

- Physical controller behaviour on real Deck hardware is unverified here; the
  bridge was validated against the real game binary's symbol table and the
  model tests above.
- The Windows build's steering wait/face gates and destination-marker draw
  gate are not ported to Linux yet. Movement still routes through the stock
  group order path; followers may briefly play their idle or turn-around
  animations during stick-driven regrouping.
- If buttons do nothing, read `controller-runtime.log` next to the game
  executable: no file means the bridge never loaded (check the M_PSTPAD.lua
  load path), a file with no input rows means the pad was not visible to the
  game's SDL (check Steam Input).
