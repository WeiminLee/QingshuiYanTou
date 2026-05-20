"""
SubAgent 配置模型
"""
from pydantic import BaseModel


class SubAgentConfig(BaseModel):
    """SubAgent 执行器配置"""
    max_workers: int = 3       # 线程池最大工作线程数
    timeout_seconds: int = 300   # 单个任务超时时间（5分钟）
    max_retries: int = 1        # 失败重试次数
