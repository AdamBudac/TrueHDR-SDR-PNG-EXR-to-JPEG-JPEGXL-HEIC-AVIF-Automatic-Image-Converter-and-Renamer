"""Entry point – launches GUI by default, CLI when ``--cli`` is given.

Can be run either as ``python src/main.py`` or ``python -m src.main``.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure the project root is on sys.path so that ``from src.xxx`` imports work
# regardless of how this script is invoked.
_PROJECT_ROOT = str(Path(__file__).resolve().parents[1])
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


def main() -> None:
    if "--cli" in sys.argv:
        # Remove the --cli flag so argparse doesn't see it
        sys.argv.remove("--cli")
        from src.cli import run_cli
        raise SystemExit(run_cli())
    else:
        from src.gui import run_gui
        raise SystemExit(run_gui())


if __name__ == "__main__":
    main()
