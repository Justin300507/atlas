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
