"""
RateLimiter - API 限速器

基于滑动窗口的限速器，确保在指定时间窗口内的请求数不超过限制。
迁移自 data_access_mvp/src/utils/rate_limiter.py

E2 fix: 添加 AsyncRateLimiter 类，使用 asyncio.sleep 而非 time.sleep，
避免在异步上下文中阻塞事件循环。
"""
import asyncio
import time
import threading
import logging
from collections import deque

logger = logging.getLogger(__name__)


class RateLimiter:
    """
    基于滑动窗口的限速器
    确保在指定时间窗口内的请求数不超过限制
    """

    def __init__(self, max_requests: int = 60, window_seconds: float = 60.0, name: str = "API"):
        """
        Args:
            max_requests: 窗口内最大请求数
            window_seconds: 窗口时间（秒）
            name: 名称（用于日志）
        """
        self.name = name
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._timestamps: deque = deque()
        self._lock = threading.Lock()

    def acquire(self) -> bool:
        """
        获取一个请求许可

        Returns:
            True 表示可以发送请求，False 表示已达上限需等待
        """
        with self._lock:
            now = time.time()

            # 清理过期的 timestamps
            while self._timestamps and self._timestamps[0] < now - self.window_seconds:
                self._timestamps.popleft()

            if len(self._timestamps) < self.max_requests:
                self._timestamps.append(now)
                return True

            # 已达上限，计算需等待的时间
            oldest = self._timestamps[0]
            wait_time = self.window_seconds - (now - oldest) + 0.1
            logger.debug(f"{self.name} 限速触发，需等待 {wait_time:.1f} 秒")
            return False

    def wait_and_acquire(self):
        """
        阻塞等待直到获取到许可。

        WARNING: 此方法会阻塞线程。在异步上下文中，
        推荐使用 AsyncRateLimiter.wait_and_acquire()，
        或通过 ``await asyncio.to_thread(limiter.wait_and_acquire)`` 调用。

        E2 fix: 对于异步代码路径，请使用 AsyncRateLimiter。
        """
        while True:
            if self.acquire():
                return
            # 没获取到，精确计算需要等待的时间再 sleep
            with self._lock:
                now = time.time()
                if self._timestamps:
                    oldest = self._timestamps[0]
                    wait_time = self.window_seconds - (now - oldest)
                else:
                    wait_time = self.window_seconds
            if wait_time > 0:
                time.sleep(wait_time)

    def get_remaining(self) -> int:
        """获取当前窗口剩余可用次数"""
        with self._lock:
            now = time.time()
            while self._timestamps and self._timestamps[0] < now - self.window_seconds:
                self._timestamps.popleft()
            return max(0, self.max_requests - len(self._timestamps))


class AsyncRateLimiter:
    """
    异步版本的 RateLimiter，使用 asyncio.sleep 而非 time.sleep。

    E2 fix: 在异步上下文中使用此限速器，避免阻塞事件循环。

    用法示例：
        limiter = AsyncRateLimiter(max_requests=1, window_seconds=1.0)
        await limiter.wait_and_acquire()
    """

    def __init__(self, max_requests: int = 60, window_seconds: float = 60.0, name: str = "API"):
        """
        Args:
            max_requests: 窗口内最大请求数
            window_seconds: 窗口时间（秒）
            name: 名称（用于日志）
        """
        self.name = name
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._timestamps: list[float] = []
        self._lock: asyncio.Lock | None = None

    def _get_lock(self) -> asyncio.Lock:
        """延迟创建 lock（必须在 async context 中）"""
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    async def acquire(self) -> bool:
        """
        异步获取一个请求许可

        Returns:
            True 表示可以发送请求，False 表示已达上限需等待
        """
        lock = self._get_lock()
        async with lock:
            now = time.time()

            # 清理过期的 timestamps
            self._timestamps = [t for t in self._timestamps if t > now - self.window_seconds]

            if len(self._timestamps) < self.max_requests:
                self._timestamps.append(now)
                return True

            # 已达上限，计算需等待的时间
            oldest = self._timestamps[0]
            wait_time = self.window_seconds - (now - oldest) + 0.1
            logger.debug(f"{self.name} 限速触发，需等待 {wait_time:.1f} 秒")
            return False

    async def wait_and_acquire(self) -> bool:
        """
        非阻塞等待直到获取到许可（使用 asyncio.sleep）。

        Returns:
            True 表示成功获取许可
        """
        while True:
            if await self.acquire():
                return True
            # 计算等待时间
            lock = self._get_lock()
            async with lock:
                now = time.time()
                self._timestamps = [t for t in self._timestamps if t > now - self.window_seconds]
                if self._timestamps:
                    oldest = self._timestamps[0]
                    wait_time = self.window_seconds - (now - oldest)
                else:
                    wait_time = self.window_seconds
            if wait_time > 0:
                await asyncio.sleep(wait_time)  # 非阻塞！

    async def get_remaining(self) -> int:
        """获取当前窗口剩余可用次数"""
        lock = self._get_lock()
        async with lock:
            now = time.time()
            self._timestamps = [t for t in self._timestamps if t > now - self.window_seconds]
            return max(0, self.max_requests - len(self._timestamps))

    @classmethod
    def from_sync(cls, limiter: RateLimiter) -> "AsyncRateLimiter":
        """从同步 RateLimiter 创建对应的异步版本"""
        return cls(
            max_requests=limiter.max_requests,
            window_seconds=limiter.window_seconds,
            name=limiter.name,
        )


def get_akshare_async_limiter() -> AsyncRateLimiter:
    """获取异步版本的 akshare 限速器。

    E2 fix: 在异步代码路径中使用此限速器。

    用法：
        limiter = get_akshare_async_limiter()
        await limiter.wait_and_acquire()
    """
    return AsyncRateLimiter(max_requests=1, window_seconds=1.0, name="akshare-async")


# ── akshare 接口限速器 ──────────────────────────────────────────
# akshare 接口本身无公开速率限制，保守每秒 1 次，避免反爬封 IP（D-D2 接入点）
_akshare_limiter: RateLimiter | None = None


def get_akshare_limiter() -> RateLimiter:
    """获取全局 akshare 接口限速器（每秒 1 次，约 60 次/分钟）。

    Phase 31 D-D1：由旧名"巨潮API限速器"改名而来。
    接入点（D-D2）：fetcher.fetch_reports / fetch_irm / fetch_concept 中
    akshare 调用前必须 ``await asyncio.to_thread(get_akshare_limiter().wait_and_acquire)``。
    """
    global _akshare_limiter
    if _akshare_limiter is None:
        _akshare_limiter = RateLimiter(max_requests=1, window_seconds=1.0, name="akshare")
    return _akshare_limiter


# ── 巨潮 PDF 下载限速器 ──────────────────────────────────────────
# PDF 下载每个文件间隔 1 秒，防止触发反爬
_cninfo_pdf_limiter: RateLimiter | None = None


def get_cninfo_pdf_limiter() -> RateLimiter:
    """获取全局巨潮 PDF 下载限速器（每秒 1 个文件）"""
    global _cninfo_pdf_limiter
    if _cninfo_pdf_limiter is None:
        _cninfo_pdf_limiter = RateLimiter(max_requests=1, window_seconds=1.0, name="巨潮PDF下载")
    return _cninfo_pdf_limiter


# ── 巨潮 API 限速器（异步） ──────────────────────────────────────
# Phase 03 plan 03-01 / D-06：API 查询 1 req/sec
# CninfoClient.query_announcements 在 async 上下文中通过此限速器节流，
# 避免阻塞事件循环（不要使用同步 RateLimiter）。
_cninfo_api_limiter: AsyncRateLimiter | None = None


def get_cninfo_api_limiter() -> AsyncRateLimiter:
    """获取全局巨潮 API 异步限速器（每秒 1 次请求）。

    用于 ``CninfoClient.query_announcements`` 等异步方法。
    单例模式，确保所有协程共享同一滑动窗口。

    用法:
        await get_cninfo_api_limiter().wait_and_acquire()
    """
    global _cninfo_api_limiter
    if _cninfo_api_limiter is None:
        _cninfo_api_limiter = AsyncRateLimiter(
            max_requests=1,
            window_seconds=1.0,
            name="cninfo-api",
        )
    return _cninfo_api_limiter
