"""Settings for the climpact-web tests: local mode, with the data folder in a temporary
folder so tests never touch the user's own (the database is in memory in tests)."""

import atexit
import os
import shutil
import tempfile

for _name in [name for name in os.environ if name.startswith("CLIMPACT_WEB_")]:
    del os.environ[_name]
# The tests' own database is SQLite in memory. A Postgres DATABASE_URL (CI's web-postgres
# job) is kept for test_queue_postgres.py, which runs workers on a database of its own.
_database_url = os.environ.pop("DATABASE_URL", "")
if _database_url.startswith(("postgres://", "postgresql://")):
    os.environ["CLIMPACT_TEST_POSTGRES_URL"] = _database_url
_data_dir = tempfile.mkdtemp(prefix="climpact-web-test-")
atexit.register(shutil.rmtree, _data_dir, ignore_errors=True)
os.environ["CLIMPACT_WEB_DATA_DIR"] = _data_dir

from climpact_web.settings import *  # noqa: E402, F403

HELP_STRICT = True  # an unknown help topic id fails the test instead of being logged
