"""tests/conftest.py — 全局 pytest 配置"""

import pytest


def pytest_configure(config):
    config.addinivalue_line("markers", "integration: integration tests (require external services)")


def pytest_collection_modifyitems(config, items):
    skip_integration = pytest.mark.skip(
        reason="integration tests skipped by default; run with -m integration to include"
    )
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip_integration)
