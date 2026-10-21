"""
data_pipeline.api - 数据相关 API

路由：
- stocks: 股票搜索（插件侧唯一在读的入口）
"""

from app.data_pipeline.api.stocks import router as stocks_router

__all__ = [
    "stocks_router",
]
