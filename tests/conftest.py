import os
from pathlib import Path

TEST_ROOT = Path("/tmp/dev-team-simulator-tests")
os.environ["SIMULATOR_DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
os.environ["SIMULATOR_WORKSPACE_ROOT"] = str(TEST_ROOT)

