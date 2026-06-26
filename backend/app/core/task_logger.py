"""
定时任务日志记录工具

用法:
    from app.core.task_logger import task_logger, log_start, log_end

    log_start("sync_stock_pool")
    try:
        result = do_sync()
        log_end("sync_stock_pool", success=True, info=f"pool={result}")
    except Exception as e:
        log_end("sync_stock_pool", success=False, info=str(e))
        raise
"""

import time as _time
from datetime import datetime
from pathlib import Path

# 日志目录
_LOG_DIR = Path(__file__).resolve().parent.parent.parent / "logs" / "sync"
_LOG_DIR.mkdir(parents=True, exist_ok=True)


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _now() -> str:
    return datetime.now().strftime("%H:%M:%S")


def _log_path(task_name: str) -> Path:
    return _LOG_DIR / f"{task_name}_{_today()}.log"


def log_start(task_name: str) -> None:
    """记录任务开始"""
    line = f"[{task_name}] {_today()} {_now()} START"
    path = _log_path(task_name)
    with open(path, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def log_end(task_name: str, success: bool, info: str = "") -> None:
    """
    记录任务结束

    Args:
        task_name: 任务名（不含日期）
        success: 是否成功
        info: 附加信息，如 "pool=919" 或 "error=rate limit"
    """
    status = "SUCCESS" if success else "FAILED"
    line = f"[{task_name}] {_today()} {_now()} {status} {info}"
    path = _log_path(task_name)
    with open(path, "a", encoding="utf-8") as f:
        f.write(line + "\n")


class TaskLogger:
    """
    上下文管理器，适合与 try/except 配合使用：

        tl = TaskLogger("sync_stock_pool")
        tl.start()
        try:
            do_work()
            tl.end(success=True, info="count=100")
        except Exception as e:
            tl.end(success=False, info=str(e))
            raise
    """

    def __init__(self, task_name: str):
        self.task_name = task_name
        self.started_at: float = 0

    def start(self) -> None:
        self.started_at = _time.time()
        log_start(self.task_name)

    def end(self, success: bool, info: str = "") -> None:
        if self.started_at:
            duration = int(_time.time() - self.started_at)
            info = f"{info} duration={duration}s" if info else f"duration={duration}s"
        log_end(self.task_name, success, info)

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, _exc_tb):
        if exc_type:
            self.end(success=False, info=str(exc_val))
        # 成功时由调用方决定是否 end(success=True)
        return False
