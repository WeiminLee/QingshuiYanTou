"""
conftest.py — reasoning 模块的 pytest 配置和共享 fixtures。
"""
import sys
from pathlib import Path

# 将 backend/ 加入路径，使测试可以 `from app.reasoning import ...`
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
