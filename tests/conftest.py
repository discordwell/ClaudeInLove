"""
Shared pytest fixtures and test environment setup.

App state (data/, logs/, browser profile) is redirected into a temporary
directory *before* importing ``src``. The package builds its global config
and a file-based log handler at import time, so this prevents test runs from
creating those directories inside the repository.
"""

import os
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="claudeinlove-tests-"))
os.environ["DATA_DIR"] = str(_TMP / "data")
os.environ["LOG_DIR"] = str(_TMP / "logs")
os.environ["BROWSER_USER_DATA_DIR"] = str(_TMP / "browser")
os.environ["LOG_LEVEL"] = "WARNING"

import pytest_asyncio

from src.core.database import Database


@pytest_asyncio.fixture
async def db(tmp_path):
    """A connected Database backed by a fresh temp-file SQLite database."""
    database = Database(db_path=tmp_path / "test.db")
    await database.connect()
    try:
        yield database
    finally:
        await database.close()
