"""
conftest.py — reasoning 模块的 pytest 配置和共享 fixtures。
"""

import os
import sys
from pathlib import Path

# 将 backend/ 加入路径，使测试可以 `from app.reasoning import ...`
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# 设置最小化的环境变量以支持配置加载
# 使用 postgresql+asyncpg URL 以避免需要 aiosqlite
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://localhost/test")
os.environ.setdefault("MONGODB_URL", "mongodb://localhost:27017/test")
os.environ.setdefault("LLM_API_KEY", "test-key")
os.environ.setdefault("NEO4J_PASSWORD", "test-password")
os.environ.setdefault("MASTER_PASSWORD", "test-master-pass-1234")
