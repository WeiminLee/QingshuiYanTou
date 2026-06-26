"""Phase 31 D-D1 — rate_limiter get_cninfo_limiter → get_akshare_limiter 改名"""


class TestAkshareLimiterRename:
    """D-D1 get_akshare_limiter 替代 get_cninfo_limiter"""

    def test_get_akshare_limiter_exists(self):
        from app.data_pipeline.rate_limiter import get_akshare_limiter

        limiter = get_akshare_limiter()
        assert limiter.name == "akshare"
        assert limiter.max_requests == 1
        assert limiter.window_seconds == 1.0

    def test_get_cninfo_limiter_removed(self):
        """旧名 get_cninfo_limiter 应不再存在（避免歧义）"""
        import app.data_pipeline.rate_limiter as rl_mod

        assert not hasattr(rl_mod, "get_cninfo_limiter"), "get_cninfo_limiter 必须已改名为 get_akshare_limiter"

    def test_get_cninfo_pdf_limiter_unchanged(self):
        """D-D3 PDF 下载限速器保留不变（file_storage.py 接入点）"""
        from app.data_pipeline.rate_limiter import get_cninfo_pdf_limiter

        limiter = get_cninfo_pdf_limiter()
        assert limiter.name == "巨潮PDF下载"
        assert limiter.max_requests == 1
        assert limiter.window_seconds == 1.0

    def test_singleton(self):
        from app.data_pipeline.rate_limiter import get_akshare_limiter

        assert get_akshare_limiter() is get_akshare_limiter()
