"""Phase 31 D-A1 — data_source.get_stock_kline + ts_code baostock 格式转换

占位测试 — Wave 1 Plan 02 完成实现后启用。
"""


class TestTsCodeFormatConvert:
    def test_sh_prefix(self):
        from app.data_pipeline.data_source import _ts_to_bs

        assert _ts_to_bs("600000.SH") == "sh.600000"

    def test_sz_prefix(self):
        from app.data_pipeline.data_source import _ts_to_bs

        assert _ts_to_bs("000001.SZ") == "sz.000001"

    def test_bare_numeric_6x_to_sh(self):
        from app.data_pipeline.data_source import _ts_to_bs

        assert _ts_to_bs("600000") == "sh.600000"

    def test_bare_numeric_0x_to_sz(self):
        from app.data_pipeline.data_source import _ts_to_bs

        assert _ts_to_bs("000001") == "sz.000001"

    def test_invalid_format_raises(self):
        import pytest as _pytest

        from app.data_pipeline.data_source import _ts_to_bs

        with _pytest.raises(ValueError):
            _ts_to_bs("BADCODE")
        with _pytest.raises(ValueError):
            _ts_to_bs("12345")  # 5 位数字非法


class TestGetStockKlineFields:
    """D-A1 baostock 单股 daily 接口字段映射"""

    def test_returns_list_of_dict_with_tradestatus(self):
        from unittest.mock import MagicMock, patch

        from app.data_pipeline.data_source import DataSourceClient

        client = DataSourceClient()
        with patch("app.data_pipeline.data_source.bs") as mock_bs:
            mock_rs = MagicMock()
            mock_rs.error_code = "0"
            mock_rs.next.side_effect = [True, False]
            mock_rs.get_row_data.return_value = [
                "2026-05-12",
                "sh.600000",
                "10.0",
                "10.5",
                "9.8",
                "10.2",
                "10.0",
                "1000000",
                "10200000",
                "1.5",
                "2.0",
                "1",
                "0",
            ]
            mock_bs.query_history_k_data_plus.return_value = mock_rs
            client._bs_logged_in = True
            records = client.get_stock_kline("600000.SH", "20260501", "20260512")
            assert len(records) == 1
            assert records[0]["tradestatus"] == "1"
            assert records[0]["isST"] == "0"
