import os
import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).parent.parent


def test_importing_main_configures_root_logging_handlers():
    # Run in a fresh subprocess, not inside pytest itself -- pytest's own
    # logging plugin installs a handler on the root logger, which would mask
    # whether app.main's basicConfig call actually does anything on its own.
    # This is the real regression: before it was added, logger.info() calls
    # anywhere in the app were silently dropped in a plain `uvicorn` process,
    # since nothing outside of tests ever configured the root logger.
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import logging\n"
            "from app.main import logger\n"
            "print('handlers=', len(logging.getLogger().handlers))\n"
            "print('info_enabled=', logger.isEnabledFor(logging.INFO))\n",
        ],
        cwd=BACKEND_DIR,
        capture_output=True,
        text=True,
        check=True,
    )

    assert "handlers= 0" not in result.stdout
    assert "info_enabled= True" in result.stdout


def test_startup_logs_the_resolved_config():
    # Found while reviewing startup logs for this session's observability
    # pass: resolve_cors_origins() either raises (refuses to start) or
    # silently returns a list -- an operator setting ATLAS_ALLOWED_ORIGINS
    # had no log confirmation the value was actually read, short of
    # triggering a real cross-origin request. Run in a subprocess for the
    # same reason as the test above: import-time logging.basicConfig only
    # does something observable outside of pytest's own log capture.
    result = subprocess.run(
        [sys.executable, "-c", "import app.main\n"],
        cwd=BACKEND_DIR,
        capture_output=True,
        text=True,
        check=True,
        env={**os.environ, "ATLAS_ALLOWED_ORIGINS": "https://example.com"},
    )

    assert "startup config:" in result.stderr
    assert "https://example.com" in result.stderr
