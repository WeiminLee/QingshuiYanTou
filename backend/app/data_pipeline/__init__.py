"""
data_pipeline - 数据层本地持久化

迁移自 data_access_mvp 项目，提供数据采集、存储、调度功能。
"""

import app.data_pipeline.ipv4_patch  # noqa: F401 — 强制 IPv4（服务器 IPv6 连通性问题），需在所有数据源请求前生效

from app.data_pipeline.fetcher import DataFetcher
from app.data_pipeline.scheduler import Scheduler

__all__ = ["DataFetcher", "Scheduler"]
