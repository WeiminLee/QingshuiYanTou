"""
验证 minishare IRM 代码已全部移除。
"""
import importlib
import inspect
import sys


class TestMinishareClientNoIrm:

    def test_minishare_client_no_irm_methods(self):
        """DataSourceClientMinishare 不再有 get_irm / iter_irm_by_date_range / iter_irm_by_date_range_async"""
        from app.data_pipeline.minishare_client import DataSourceClientMinishare

        assert not hasattr(DataSourceClientMinishare, "get_irm"), "get_irm 应已被移除"
        assert not hasattr(DataSourceClientMinishare, "iter_irm_by_date_range"), "iter_irm_by_date_range 应已被移除"
        assert not hasattr(DataSourceClientMinishare, "iter_irm_by_date_range_async"), "iter_irm_by_date_range_async 应已被移除"

    def test_minishare_client_no_irm_property(self):
        """DataSourceClientMinishare 不再有 irm_available 属性"""
        from app.data_pipeline.minishare_client import DataSourceClientMinishare

        assert not hasattr(DataSourceClientMinishare, "irm_available"), "irm_available 应已被移除"

    def test_minishare_client_init_no_irm_api(self):
        """DataSourceClientMinishare.__init__ 不再初始化 _irm_api"""
        from app.data_pipeline.minishare_client import DataSourceClientMinishare

        source = inspect.getsource(DataSourceClientMinishare.__init__)
        # 不应包含 irm_token 或 _irm_api 的引用
        assert "irm_token" not in source, "__init__ 不应引用 irm_token"
        assert "_irm_api" not in source, "__init__ 不应引用 _irm_api"


class TestFetcherNoMinishareIrm:

    def test_fetcher_no_minishare_irm_methods(self):
        """DataFetcher 不再有 fetch_minishare_irm / fetch_minishare_irm_history"""
        from app.data_pipeline.fetcher import DataFetcher

        assert not hasattr(DataFetcher, "fetch_minishare_irm"), "fetch_minishare_irm 应已被移除"
        assert not hasattr(DataFetcher, "fetch_minishare_irm_history"), "fetch_minishare_irm_history 应已被移除"

    def test_fetcher_no_minishare_client_irm_usage(self):
        """fetcher 源码不再引用 minishare_client 的 IRM 相关属性和方法"""
        import app.data_pipeline.fetcher as fetcher_mod

        source = inspect.getsource(fetcher_mod)

        # 不应再引用 minishare IRM 的方法（akshare 的 get_irm 不是 minishare 的）
        forbidden = [
            "irm_available",
            "iter_irm_by_date_range",
            "iter_irm_by_date_range_async",
            "fetch_minishare_irm",
            "minishare_client.get_irm",
            "minishare_client.irm_available",
        ]
        for attr in forbidden:
            assert attr not in source, f"fetcher.py 不应引用 {attr}"
