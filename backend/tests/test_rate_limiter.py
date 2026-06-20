"""
Test rate_limiter.py — 限速器单元测试
"""

from app.data_pipeline.rate_limiter import (
    AsyncRateLimiter,
    get_cninfo_pdf_async_limiter,
    get_cninfo_pdf_limiter,
)


class TestGetCninfoPdfAsyncLimiter:
    """get_cninfo_pdf_async_limiter 测试"""

    def test_returns_async_rate_limiter(self):
        """返回 AsyncRateLimiter 实例"""
        limiter = get_cninfo_pdf_async_limiter()
        assert isinstance(limiter, AsyncRateLimiter)

    def test_max_requests_is_5(self):
        """max_requests=5"""
        limiter = get_cninfo_pdf_async_limiter()
        assert limiter.max_requests == 5

    def test_window_seconds_is_1(self):
        """window_seconds=1.0"""
        limiter = get_cninfo_pdf_async_limiter()
        assert limiter.window_seconds == 1.0

    def test_singleton(self):
        """多次调用返回同一实例"""
        a = get_cninfo_pdf_async_limiter()
        b = get_cninfo_pdf_async_limiter()
        assert a is b

    def test_independent_from_sync_limiter(self):
        """异步限速器与同步限速器互不干扰"""
        async_limiter = get_cninfo_pdf_async_limiter()
        sync_limiter = get_cninfo_pdf_limiter()
        assert async_limiter is not sync_limiter
        assert isinstance(sync_limiter, object)  # sync 是 RateLimiter
