"""
data_pipeline.api - 数据相关 API

路由：
- stocks: 股票信息、情报包、K线
- data: 数据查询（互动易、公告、研报）
- information: 资讯查询
- monitor: 监控告警
"""

from app.data_pipeline.api.data import router as data_router
from app.data_pipeline.api.information import router as information_router
from app.data_pipeline.api.monitor import router as monitor_router
from app.data_pipeline.api.stocks import router as stocks_router

__all__ = [
    "stocks_router",
    "data_router",
    "information_router",
    "monitor_router",
]
