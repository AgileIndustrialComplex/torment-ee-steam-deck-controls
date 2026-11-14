#!/usr/bin/env python3
"""GTK front end for the PST:EE controller mod installer.

    python3 pstee-gui.py <payload-dir>

The window opens by printing the current install status, then offers three
actions: Install, Reinstall and Uninstall. Each runs the stdlib installer
(distribution/linux/install.py) against the bundled package and streams its
output into the scrollable log. The log is also mirrored to
~/.cache/pstee-controller-deck/install.log.

PyGObject/GTK3 is used because SteamOS ships both; nothing is compiled.
"""
from __future__ import annotations

import subprocess
import sys
import threading
from pathlib import Path

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk  # noqa: E402

TITLE = "Plancescape Toement: EE Steam Deck controller support"
HEADING = "What can change the nature of a man?"
LOG_MIRROR = Path.home() / ".cache" / "pstee-controller-deck" / "install.log"


class InstallerWindow(Gtk.Window):
    def __init__(self, payload_dir: Path) -> None:
        super().__init__(title=TITLE)
        self.payload_dir = payload_dir
        self.set_default_size(820, 560)
        self.connect("destroy", Gtk.main_quit)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        outer.set_border_width(16)
        self.add(outer)

        heading = Gtk.Label()
        heading.set_markup(f"<span size='x-large' weight='bold'>{HEADING}</span>")
        heading.set_halign(Gtk.Align.START)
        outer.pack_start(heading, False, False, 0)

        buttons = Gtk.Box(spacing=8)
        outer.pack_start(buttons, False, False, 0)
        self.action_buttons = {}
        for label, action in (
            ("_Install", "install"),
            ("_Reinstall", "reinstall"),
            ("_Uninstall", "uninstall"),
        ):
            button = Gtk.Button.new_with_mnemonic(label)
            button.connect("clicked", self.on_action, action)
            buttons.pack_start(button, False, False, 0)
            self.action_buttons[action] = button

        self.scrolled = Gtk.ScrolledWindow()
        self.scrolled.set_hexpand(True)
        self.scrolled.set_vexpand(True)
        self.scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        outer.pack_start(self.scrolled, True, True, 0)

        self.view = Gtk.TextView()
        self.view.set_editable(False)
        self.view.set_cursor_visible(False)
        self.view.set_wrap_mode(Gtk.WrapMode.WORD)
        self.view.set_left_margin(8)
        self.view.set_top_margin(8)
        self.buffer = self.view.get_buffer()
        self.mark = self.buffer.create_mark("end", self.buffer.get_end_iter(), False)
        self.scrolled.add(self.view)

        self.close_button = Gtk.Button.new_with_mnemonic("_Close")
        self.close_button.connect("clicked", Gtk.main_quit)
        bottom = Gtk.Box(spacing=8)
        bottom.pack_end(self.close_button, False, False, 0)
        outer.pack_start(bottom, False, False, 0)

        LOG_MIRROR.parent.mkdir(parents=True, exist_ok=True)
        self.mirror = LOG_MIRROR.open("w", encoding="utf-8")

        GLib.idle_add(self.run_status)

    # ---------------------------------------------------------------- actions
    def installer_command(self, action: str) -> list:
        command = [sys.executable, str(self.payload_dir / "install.py")]
        if action == "install":
            command += ["install", "--package", str(self.payload_dir / "package.zip")]
        elif action == "reinstall":
            command += ["reinstall", "--package", str(self.payload_dir / "package.zip")]
        else:
            command += ["uninstall"]
        return command

    def run_status(self) -> bool:
        self.run_commands([[sys.executable, str(self.payload_dir / "install.py"), "status"]])
        return False

    def on_action(self, button, action: str) -> None:
        self.run_commands([self.installer_command(action)])

    def run_commands(self, commands: list) -> None:
        for button in self.action_buttons.values():
            button.set_sensitive(False)
        threading.Thread(target=self.work, args=(commands,), daemon=True).start()

    # ------------------------------------------------------------------ worker
    def work(self, commands: list) -> None:
        overall = 0
        for command in commands:
            self.append("$ " + " ".join(str(part) for part in command) + "\n")
            process = subprocess.Popen(
                command,
                cwd=str(self.payload_dir),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            assert process.stdout is not None
            for line in process.stdout:
                GLib.idle_add(self.append, line)
            code = process.wait()
            if code != 0:
                overall = code
            self.append("exit: %d\n" % code)
        GLib.idle_add(self.finished, overall)

    def append(self, line: str) -> bool:
        self.buffer.insert(self.buffer.get_end_iter(), line)
        self.view.scroll_to_mark(self.mark, 0.0, False, 0.0, 0.0)
        try:
            self.mirror.write(line)
            self.mirror.flush()
        except OSError:
            pass
        return False

    def finished(self, code: int) -> bool:
        if code == 0:
            summary = "\nDone.\n"
        else:
            summary = "\nFailed (exit %d). The messages above explain why.\n" % code
        self.append(summary)
        for button in self.action_buttons.values():
            button.set_sensitive(True)
        return False


def main() -> int:
    if len(sys.argv) != 2:
        print(f"usage: {sys.argv[0]} <payload-dir>", file=sys.stderr)
        return 2
    window = InstallerWindow(Path(sys.argv[1]))
    window.show_all()
    Gtk.main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
