#!/usr/bin/env python3
"""GTK window that runs the PST:EE controller mod installer and streams its
output into a scrollable log. PyGObject/GTK3 is used because SteamOS ships
both; nothing is compiled.

    python3 pstee-gui.py <payload-dir>

The payload directory holds install.py and the release ZIP; installation is
--package based, so no network is needed. The same log is mirrored to
~/.cache/pstee-controller-deck/install.log.
"""
from __future__ import annotations

import os
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

        subtitle = Gtk.Label(label="Installing the native controller mod…")
        subtitle.set_halign(Gtk.Align.START)
        outer.pack_start(subtitle, False, False, 0)

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

        buttons = Gtk.Box(spacing=8)
        outer.pack_start(buttons, False, False, 0)
        self.close_button = Gtk.Button.new_with_mnemonic("_Close")
        self.close_button.set_sensitive(False)
        self.close_button.connect("clicked", Gtk.main_quit)
        buttons.pack_end(self.close_button, False, False, 0)

        LOG_MIRROR.parent.mkdir(parents=True, exist_ok=True)
        self.mirror = LOG_MIRROR.open("w", encoding="utf-8")

        GLib.idle_add(self.start_install)

    def start_install(self) -> bool:
        command = [
            sys.executable,
            str(self.payload_dir / "install.py"),
            "install",
            "--package",
            str(self.payload_dir / "package.zip"),
        ]
        self.append("$ " + " ".join(str(part) for part in command) + "\n")
        self.process = subprocess.Popen(
            command,
            cwd=str(self.payload_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        threading.Thread(target=self.pump_output, daemon=True).start()
        return False

    def pump_output(self) -> None:
        assert self.process.stdout is not None
        for line in self.process.stdout:
            GLib.idle_add(self.append, line)
        code = self.process.wait()
        GLib.idle_add(self.finished, code)

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
            summary = "\nInstallation finished successfully.\n"
        else:
            summary = f"\nInstallation failed (exit {code}). The messages above explain why.\n"
        self.append(summary)
        try:
            self.mirror.close()
        except OSError:
            pass
        self.close_button.set_sensitive(True)
        return False


def main() -> int:
    if len(sys.argv) != 2:
        print(f"usage: {sys.argv[0]} <payload-dir>", file=sys.stderr)
        return 2
    payload = Path(sys.argv[1])
    window = InstallerWindow(payload)
    window.show_all()
    Gtk.main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
