"""清水投研系统 - 后端服务入口（2026-04-08 四能力架构）"""
from contextlib import asynccontextmanager
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.data_pipeline.api import stocks_router, data_router, information_router, monitor_router
from app.data_pipeline.scheduler import Scheduler as DataPipelineScheduler
from app.reasoning.api import agent_router, stats_router
from app.api.logs import router as logs_router
from app.reasoning.subagents.polling import router as subagent_router
from app.knowledge.api import concept_router, entities_router, relations_router, kg_extraction_router
from app.knowledge.api.feedback import router as feedback_router
from app.knowledge.api.knowledge_package import router as knowledge_package_router
from app.utils.auth import verify_api_key, verify_api_key_optional


_data_scheduler: DataPipelineScheduler | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """生命周期管理：启动时初始化调度器，关闭时优雅退出。"""
    global _data_scheduler

    print(f"启动 {settings.app_name}...")

    # 数据采集调度器（研报/K线/概念/互动易/股票同步）
    # 多 worker 部署时应通过 ENABLE_API_SCHEDULER=false 关闭 API 内置调度，
    # 并改用 `python -m app.data_pipeline.scheduler` 独立进程，避免重复执行任务。
    if settings.enable_api_scheduler:
        _data_scheduler = DataPipelineScheduler(run_now=False)
        _data_scheduler.start()
        print("数据采集调度器已启动")
    else:
        print("数据采集调度器未在 API 进程启动（ENABLE_API_SCHEDULER=false）")

    # Warm StockNameResolver cache from PostgreSQL
    from app.knowledge.stock_name_resolver import get_stock_name_resolver
    resolver = get_stock_name_resolver()
    await resolver.warm_cache()
    print(f"StockNameResolver 已加载: {resolver.size()} 条名称映射")

    yield

    if _data_scheduler is not None:
        _data_scheduler.stop()
        print("数据采集调度器已关闭")
    from app.core.mongodb import close_mongo_client
    from app.core.neo4j_client import close_async_driver
    await close_mongo_client()
    await close_async_driver()
    print(f"关闭 {settings.app_name}...")


app = FastAPI(title=settings.app_name, version="1.0", lifespan=lifespan)
# CORS 配置：从 settings.cors_origins 读取，逗号分隔
cors_origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {"status": "ok"}


# 注册路由
# 写操作路由（必须认证）
app.include_router(stocks_router, prefix="/api/v1/stocks", tags=["股票"], dependencies=[Depends(verify_api_key)])
app.include_router(monitor_router, prefix="/api/v1/monitor", tags=["监控告警"], dependencies=[Depends(verify_api_key)])
app.include_router(subagent_router, dependencies=[Depends(verify_api_key)])
app.include_router(entities_router, tags=["知识构建"], dependencies=[Depends(verify_api_key)])
app.include_router(relations_router, tags=["知识构建"], dependencies=[Depends(verify_api_key)])
app.include_router(kg_extraction_router, tags=["知识构建"], dependencies=[Depends(verify_api_key)])
app.include_router(feedback_router, dependencies=[Depends(verify_api_key)])
# 读操作路由（已有自身Depends，不重复叠加）
app.include_router(agent_router, prefix="/api/v1/agent")  # 自带Depends
app.include_router(data_router, prefix="/api/v1/data", tags=["数据"], dependencies=[Depends(verify_api_key_optional)])
app.include_router(stats_router, prefix="/api/v1/stats", tags=["统计"], dependencies=[Depends(verify_api_key_optional)])
app.include_router(concept_router, prefix="/api/v1/concept", tags=["概念评分"], dependencies=[Depends(verify_api_key_optional)])
app.include_router(knowledge_package_router, prefix="/api/v1/knowledge", tags=["知识构建"], dependencies=[Depends(verify_api_key_optional)])
app.include_router(information_router, prefix="/api/v1/information", tags=["资讯"], dependencies=[Depends(verify_api_key_optional)])
# 日志查询路由（读操作，可选认证）
app.include_router(logs_router, prefix="/api/v1/logs", tags=["日志"])
