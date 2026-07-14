"""tests/conftest.py — 全局 pytest 配置"""

import os
import tempfile

import pytest

# 在导入 app.config 之前注入占位配置：app.config 在 import 期即校验 4 个必填项
# （DATABASE_URL/MONGODB_URL/LLM_API_KEY/NEO4J_PASSWORD），否则 RuntimeError 使整个
# 测试模块无法收集。此处仅当环境未提供时补占位值，让单元测试无需真实 .env 即可运行；
# 需要真实外部服务的用例应标记 @pytest.mark.integration。
#
# MINISHARE_DATA_ROOT：FileStorage.__init__ 会对 settings.minishare_data_root 执行
# mkdir(parents=True)，而其默认值是硬编码的 Linux 外接盘路径（config.py），在开发/CI
# 机器上不存在且只读，导致任何构造 DataFetcher()/FileStorage() 的单元测试崩溃。此处
# 指向可写临时目录，属占位配置性质，与上面 4 项同理。
_TEST_DATA_ROOT = os.path.join(tempfile.gettempdir(), "qingshui_test_data_root")
_TEST_ENV_DEFAULTS = {
    "DATABASE_URL": "postgresql+asyncpg://test:test@localhost:5432/test",
    "MONGODB_URL": "mongodb://localhost:27017/test",
    "LLM_API_KEY": "test-key",
    "NEO4J_PASSWORD": "test-password",
    "MINISHARE_DATA_ROOT": _TEST_DATA_ROOT,
}
for _k, _v in _TEST_ENV_DEFAULTS.items():
    os.environ.setdefault(_k, _v)


def pytest_configure(config):
    config.addinivalue_line("markers", "integration: integration tests (require external services)")


def pytest_collection_modifyitems(config, items):
    skip_integration = pytest.mark.skip(
        reason="integration tests skipped by default; run with -m integration to include"
    )
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip_integration)
