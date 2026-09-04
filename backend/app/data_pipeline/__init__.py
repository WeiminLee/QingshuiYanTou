"""data_pipeline - 数据层本地持久化."""

import app.data_pipeline.ipv4_patch  # noqa: F401 — 强制 IPv4（服务器 IPv6 连通性问题），需在所有数据源请求前生效

__all__ = ["DataFetcher", "Scheduler"]


def __getattr__(name: str):
    if name == "DataFetcher":
        from app.data_pipeline.fetcher import DataFetcher

        return DataFetcher
    if name == "Scheduler":
        from app.data_pipeline.scheduler import Scheduler

        return Scheduler
    raise AttributeError(name)
