import os
from pathlib import Path

TEST_ROOT = Path("/tmp/dev-team-simulator-tests")
os.environ["SIMULATOR_DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
os.environ["SIMULATOR_WORKSPACE_ROOT"] = str(TEST_ROOT)

import pytest


@pytest.fixture(autouse=True)
def original_channel_fixtures(monkeypatch):
    """历史协议夹具继续验证原渠道，OpenCode 用例显式启用新路由。"""
    from backend.app.config import settings
    monkeypatch.setattr(settings, "opencode_enabled", False)

