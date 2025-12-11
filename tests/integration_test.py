from pathlib import Path
import logging
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from script import AppSettings, ProcessingWorker, detect_tools  # noqa: E402


def main() -> int:
    # Input directory with source PNG/EXR files
    input_dir = Path("render").resolve()
    if not input_dir.exists():
        print(f"Input directory not found: {input_dir}")
        return 1

    # Prepare logger to stdout
    logger = logging.getLogger("headless-test")
    logger.setLevel(logging.INFO)
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(handler)

    # Use default settings (or adjust here if needed)
    settings = AppSettings()
    tool_map = detect_tools()

    # Clear output if exists (to avoid collisions during repeated runs)
    output_dir = input_dir / "output"
    if output_dir.exists():
        for item in output_dir.iterdir():
            if item.is_file() or item.is_symlink():
                item.unlink(missing_ok=True)
            else:
                # best-effort cleanup of subdirs if any
                import shutil
                shutil.rmtree(item, ignore_errors=True)

    worker = ProcessingWorker(input_dir, settings, tool_map, logger)
    try:
        worker.process()
        print("Headless conversion completed.")
        return 0
    except Exception as exc:  # noqa: BLE001
        logger.exception("Headless conversion failed: %s", exc)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

