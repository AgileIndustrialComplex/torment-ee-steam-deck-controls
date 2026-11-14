# Controller Lab - developer workspace

Current release: **0.3.0**. Read the public [README](../distribution/README.md)
and [controls](../distribution/CONTROLS.md) for installation and gameplay.
[PROTOTYPE.md](PROTOTYPE.md) describes the implementation and guard conditions;
[MENU-CHECKS.md](MENU-CHECKS.md) records the current navigation check scope.

Use a separate writable game copy and the Controller Lab profile. Never use the
original game installation as a development target. The launcher checks the
supported executable and loads the native bridge; Torment.exe is unchanged on disk.

The stock GetDriveModeEnabled binding returns constant false on the examined
Windows executable. INI joystick/drive switches alone do not enable the console
controller interface. This mod supplies its own XInput/Lua/UI bridge.

Build the Windows bridge with Build-Plugin.ps1 -Check and the Linux bridge
with `python3 build_plugin_linux.py --check` (any C11 compiler; the .so
must stay at a GLIBC_2.17 symbol baseline for SteamOS). Regenerate the
Linux binding table with `python3 inspect_linux.py --game-dir <dir>
--update` after any game update. Generate packages with
build_release.py --game-dir, and run test_menu_navigation.py plus
test_distribution.py. Local tools, stock fixtures, copied game data, backups,
logs and save profiles are excluded from public packages.
