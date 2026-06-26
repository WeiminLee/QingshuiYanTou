"""
回补任务集中配置

目的：把"数据回补的时间范围 + 个股范围"集中在此，避免每个 sync_*.py 各自硬编码。

配置项可由 .env 覆盖：
    BACKFILL_START_DATE=20240101
    BACKFILL_END_DATE=20260620        # 为空则默认 today
    BACKFILL_SCOPE=tech_mvp           # tech_mvp | all
    BACKFILL_WHITELIST_FILE=...       # 自定义白名单文件路径

读取顺序：
    1. 环境变量 / .env
    2. backend/app/data_pipeline/backfill_config.py 内默认值
    3. backend/data/board_concept/tech_ts_codes.txt 提供白名单

只读模块，使用方：
    from app.data_pipeline.backfill_config import (
        load_backfill_settings,
        get_scope_ts_codes,
        filter_scope,
    )

    cfg = load_backfill_settings()
    if cfg.scope == "tech_mvp":
        codes = cfg.ts_codes  # set[str]
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# 默认值（可被 .env 覆盖）
# ─────────────────────────────────────────────
DEFAULT_START_DATE = "20240101"  # MVP 阶段：从 2024 年起回补
DEFAULT_END_DATE = ""  # 空字符串 = 今天
DEFAULT_SCOPE = "tech_mvp"  # tech_mvp | all
DEFAULT_WHITELIST_FILE = Path(__file__).resolve().parent.parent.parent / "data" / "board_concept" / "tech_ts_codes.txt"


@dataclass(frozen=True)
class BackfillSettings:
    """回补任务的统一配置。

    Attributes:
        start_date:  起始日 (YYYYMMDD)
        end_date:    结束日 (YYYYMMDD)，为今天的字符串
        scope:       'tech_mvp' 仅回补白名单 ; 'all' 全市场
        whitelist_file: 白名单 ts_code 文件路径
        ts_codes:    展开后的白名单 ts_code 集合（scope=all 时为空集合）
    """

    start_date: str
    end_date: str
    scope: str
    whitelist_file: Path
    ts_codes: frozenset[str] = field(default_factory=frozenset)

    def filter_codes(self, codes):
        """根据 scope 过滤 ts_code 列表。scope=all 时不过滤。"""
        if self.scope == "all":
            return list(codes)
        return [c for c in codes if c in self.ts_codes]

    def is_in_scope(self, ts_code: str) -> bool:
        if self.scope == "all":
            return True
        return ts_code in self.ts_codes


def _read_whitelist(path: Path) -> frozenset[str]:
    if not path.exists():
        logger.warning("回补白名单文件不存在: %s（自动降级为空集合）", path)
        return frozenset()
    codes = set()
    for raw in path.read_text(encoding="utf-8").splitlines():
        code = raw.strip()
        if not code or code.startswith("#"):
            continue
        codes.add(code)
    return frozenset(codes)


def _resolve_end_date(value: str) -> str:
    if value:
        return value
    return datetime.now().strftime("%Y%m%d")


@lru_cache(maxsize=1)
def load_backfill_settings() -> BackfillSettings:
    """从环境变量 + 默认值构造一份 BackfillSettings。"""

    start_date = os.environ.get("BACKFILL_START_DATE", DEFAULT_START_DATE).strip()
    end_date = _resolve_end_date(os.environ.get("BACKFILL_END_DATE", DEFAULT_END_DATE).strip())
    scope = os.environ.get("BACKFILL_SCOPE", DEFAULT_SCOPE).strip().lower() or DEFAULT_SCOPE
    if scope not in ("tech_mvp", "all"):
        logger.warning("BACKFILL_SCOPE=%s 非法，回退到 tech_mvp", scope)
        scope = "tech_mvp"

    whitelist_file = Path(os.environ.get("BACKFILL_WHITELIST_FILE", "").strip() or DEFAULT_WHITELIST_FILE)
    ts_codes = _read_whitelist(whitelist_file) if scope == "tech_mvp" else frozenset()

    cfg = BackfillSettings(
        start_date=start_date,
        end_date=end_date,
        scope=scope,
        whitelist_file=whitelist_file,
        ts_codes=ts_codes,
    )
    logger.info(
        "BackfillSettings: scope=%s start=%s end=%s whitelist=%d (file=%s)",
        cfg.scope,
        cfg.start_date,
        cfg.end_date,
        len(cfg.ts_codes),
        cfg.whitelist_file,
    )
    return cfg


# ─────────────────────────────────────────────
# 方便快捷的辅助函数
# ─────────────────────────────────────────────
def get_scope_ts_codes() -> frozenset[str]:
    return load_backfill_settings().ts_codes


def is_in_scope(ts_code: str) -> bool:
    return load_backfill_settings().is_in_scope(ts_code)


def filter_scope(items, key=lambda x: x):
    """对任意可迭代对象按 ts_code 维度过滤。

    Args:
        items: 可迭代对象
        key:   从每个元素提取 ts_code 的函数
    """
    cfg = load_backfill_settings()
    if cfg.scope == "all":
        return list(items)
    return [item for item in items if key(item) in cfg.ts_codes]


def reset_settings_cache() -> None:
    """测试或脚本中修改环境变量后重新加载配置。"""
    load_backfill_settings.cache_clear()
