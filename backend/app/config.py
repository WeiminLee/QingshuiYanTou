"""
配置文件 - Pydantic Settings（应用级配置）

注意：
  - 元数据常量（source_type / confidence_tier）请使用 app.core.config
  - 本文件仅包含应用级配置（数据库连接、LLM、App 设置等）
"""
import os
from functools import lru_cache
from pathlib import Path
from pydantic_settings import BaseSettings
from pydantic import Field


def _load_env() -> None:
    """将 .env 文件中的变量加载到 os.environ，供 Pydantic 读取"""
    # 优先用已有环境变量，不覆盖
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.exists():
        raw = env_path.read_bytes().decode("utf-8", errors="replace")
        for line in raw.splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                key = k.strip()
                if key and key not in os.environ:
                    os.environ[key] = v.strip()


_load_env()


class Settings(BaseSettings):
    """应用配置（敏感字段无默认值，必须从 .env 读取）"""

    # Database
    database_url: str = ""
    mongodb_url: str = ""
    redis_url: str = "redis://localhost:6379/0"

    # Tushare
    tushare_token: str = ""
    tushare_http_url: str = "http://121.205.88.198:8000/tushare-proxy"

    # HTTP 代理（用于请求外部数据接口）
    http_proxy: str = ""  # 如 "http://proxyhk.zte.com.cn:80"，空则不使用代理

    # LLM（LiteLLM 代理）
    ollama_url: str = "http://localhost:11434"
    llm_api_key: str = ""   # 必须从 LLM_API_KEY 环境变量读取
    llm_base_url: str = "http://localhost:4000/v1"
    llm_model: str = "MiniMax-M2.7-highspeed"

    # Neo4j（图数据库）
    neo4j_url: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = ""

    # 本地 BGE-M3 Embedding 服务（http://0.0.0.0:8000/api/v1/embed）
    embedding_api_url: str = "http://localhost:8000"
    embedding_api_key: str = ""

    # Tencent Cloud Hunyuan Embedding API（Phase 06 - 已弃用）
    hunyuan_api_key: str = ""
    hunyuan_model: str = "hunyuan-embedding"
    hunyuan_embedding_url: str = "https://api.hunyuan.cloud.tencent.com/v1/embeddings"
    # BGE-M3 dense 向量维度
    embedding_dimension: int = 1024

    # 向量数据库（Qdrant）
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str = ""
    qdrant_collection: str = "qingshui"
    pre_search_top_k: int = 10

    # App
    app_name: str = "清水投研系统"
    debug: bool = False  # 生产环境应为 False，避免敏感日志泄露
    api_key: str = ""   # API 访问密钥，必填
    cors_origins: str = "http://localhost:3000,http://localhost:8080"  # CORS 允许的 origins，逗号分隔
    enable_api_scheduler: bool = True  # 多 worker 部署时应关闭，改用独立 scheduler 进程

    # Agent runtime hardening
    agent_journal_enabled: bool = True
    agent_journal_max_events: int = 500
    agent_memory_queue_enabled: bool = True
    agent_memory_debounce_seconds: float = 2.0
    tool_health_ttl_seconds: int = 60

    # Tavily（联网检索）
    tavily_api_key: str = ""

    # 钉钉通知
    dingtalk_webhook_url: str = ""

    # minishare（备选数据源）
    minishare_research_token: str = ""   # 研报授权码
    minishare_irm_token: str = ""        # 互动易（董秘问答）授权码

    # 数据资产目录（永久存储）
    data_assets_root: Path = Path("/home/10241671/DataSets/Stocks")

    # minishare 外部数据存储路径（PDF/文件，与项目 storage 分离）
    minishare_data_root: Path = Path("/home/lwm/qingshui_data")

    class Config:
        env_file = ".env"
        extra = "ignore"

    def _validate_required(self) -> None:
        """启动时校验必须字段，防硬编码默认值误用"""
        missing = []
        if not self.database_url:
            missing.append("DATABASE_URL")
        if not self.mongodb_url:
            missing.append("MONGODB_URL")
        if not self.llm_api_key:
            missing.append("LLM_API_KEY")
        if not self.neo4j_password:
            missing.append("NEO4J_PASSWORD")
        if missing:
            raise RuntimeError(
                f"缺少必需的配置项，请检查 .env 文件: {', '.join(missing)}"
            )


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s._validate_required()
    return s


settings = get_settings()


# ── 数据资产目录便捷访问 ───────────────────────────────────

def data_path(*subdirs: str) -> Path:
    """获取数据资产目录下的子路径，如 data_path("cninfo", "announcements")"""
    return settings.data_assets_root.joinpath(*subdirs)


DATA_PATHS = {
    "announcements":     data_path("announcements"),
    "industry_reports":  data_path("industry_reports"),
    "stock_reports":     data_path("stock_reports"),
    "documents":         data_path("documents"),
    "bulletins":         data_path("announcements"),  # 新浪/巨潮等公告 PDF（按 {SH600519}/2026-03/ 保存）
}
