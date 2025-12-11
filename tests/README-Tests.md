## Tests

- **Unit tests** (`tests/unit_tests.py`): run `pytest tests/unit_tests.py`.
- **Integration (headless) test** (`tests/integration_test.py`): run `python tests/integration_test.py`; it clears `render/output`, loads default `AppSettings`, runs the full `ProcessingWorker` without GUI, and logs to stdout.

Have the tools (`ffmpeg`, `cjpeg`, `cjxl`, `heif-enc`, `avifenc`) in PATH before testing.
The integration test uses the real contents of `render/`.
