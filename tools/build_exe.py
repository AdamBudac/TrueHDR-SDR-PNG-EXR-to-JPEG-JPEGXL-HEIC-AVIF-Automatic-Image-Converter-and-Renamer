"""Build a single-file Windows EXE via PyInstaller.

Usage
-----
    python tools/build_exe.py

The resulting executable is placed in ``dist/TrueHDRConverter.exe``.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths (relative to project root)
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENTRY_POINT = PROJECT_ROOT / "src" / "main.py"
STYLES_QSS = PROJECT_ROOT / "src" / "styles.qss"
EXE_NAME = "TrueHDRConverter"


def main() -> int:
    if not ENTRY_POINT.exists():
        print(f"ERROR: entry point not found: {ENTRY_POINT}", file=sys.stderr)
        return 1

    cmd: list[str] = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",                      # overwrite without asking
        "--clean",                          # remove previous build cache
        "--noconsole",                      # windowed (no terminal window)
        "--onefile",                        # single EXE
        "--name", EXE_NAME,                 # output name
        "--add-data", f"{STYLES_QSS}{';' if sys.platform == 'win32' else ':'}src",
        str(ENTRY_POINT),
    ]

    print("Running:", " ".join(cmd))
    result = subprocess.run(cmd, cwd=str(PROJECT_ROOT))

    if result.returncode == 0:
        exe_path = PROJECT_ROOT / "dist" / f"{EXE_NAME}.exe"
        print(f"\nBuild successful: {exe_path}")
    else:
        print(f"\nBuild failed (exit code {result.returncode})", file=sys.stderr)

    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
