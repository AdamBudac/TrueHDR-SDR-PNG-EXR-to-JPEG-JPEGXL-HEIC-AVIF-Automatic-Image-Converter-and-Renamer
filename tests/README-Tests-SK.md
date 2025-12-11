## Testy

- **Unit testy** (`tests/unit_tests.py`): spusti `pytest tests/unit_tests.py`.
- **Integračný (headless) test** (`tests/integration_test.py`): spusti `python tests/integration_test.py`; vyčistí `render/output`, načíta default `AppSettings`, spustí celý `ProcessingWorker` bez GUI a loguje na stdout.

Pred testami maj nástroje (`ffmpeg`, `cjpeg`, `cjxl`, `heif-enc`, `avifenc`) v PATH.
Integračný test používa reálny obsah `render/`.
