#!/usr/bin/env python3
"""Build the Linux native bridge and run its model tests.

Usage:
    python3 build_plugin_linux.py            # build libpstcontroller.so
    python3 build_plugin_linux.py --check    # build + compile + run the tests

The bridge only needs libc and the generated offset table; the engine's own
Lua and SDL implementations are called by address inside the game process.
Any C11 compiler works (cc, gcc, clang, or `zig cc`).
"""
import argparse
import os
import subprocess
import sys
from pathlib import Path

LAB = Path(__file__).resolve().parent
NATIVE = LAB / "native"
SOURCES = ["pstcontroller_linux.c"]
OUTPUT = NATIVE / "libpstcontroller.so"

CANDIDATE_COMPILERS = os.environ.get("CC", "").split() or ["cc", "gcc", "clang", "zig"]


def compiler_command(compiler: str) -> list[str]:
    if compiler.endswith("zig"):
        # Match the glibc baseline of the supported game build era so the
        # shared object loads wherever the stock Torment binary runs.
        return [compiler, "cc", "-target", "x86_64-linux-gnu.2.17"]
    return [compiler]


def build(compiler: str) -> None:
    command = compiler_command(compiler) + [
        "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
        "-fPIC", "-shared", "-fvisibility=hidden",
        str(NATIVE / SOURCES[0]),
        "-o", str(OUTPUT),
    ]
    print(" ".join(command))
    result = subprocess.run(command, cwd=NATIVE)
    if result.returncode != 0:
        raise SystemExit(f"build failed with {compiler}")
    print(f"built {OUTPUT}")


def check(compiler: str) -> None:
    test_binary = NATIVE / "test_native_linux"
    command = compiler_command(compiler) + [
        "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
        str(NATIVE / "test_native_linux.c"),
        "-o", str(test_binary),
    ]
    print(" ".join(command))
    result = subprocess.run(command + ["-lm"], cwd=NATIVE)
    if result.returncode != 0:
        raise SystemExit("native test build failed")
    result = subprocess.run([str(test_binary)], cwd=NATIVE)
    if result.returncode != 0:
        raise SystemExit("native test failed")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="also build and run the model tests")
    args = parser.parse_args()

    for candidate in CANDIDATE_COMPILERS:
        if subprocess.run(["which", candidate], capture_output=True).returncode == 0:
            build(candidate)
            if args.check:
                check(candidate)
            return 0
    raise SystemExit("no C compiler found (tried: " + ", ".join(CANDIDATE_COMPILERS) + ")")


if __name__ == "__main__":
    raise SystemExit(main())
