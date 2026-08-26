"""Minishare IRM provider contract tests."""

from types import SimpleNamespace

import pandas as pd


def test_minishare_irm_routes_sh_by_company(monkeypatch):
    from app.data_pipeline import minishare_client as module

    calls = []

    class Api:
        def irm_qa_sh(self, **kwargs):
            calls.append(kwargs)
            return pd.DataFrame(
                [{"ts_code": "600000.SH", "name": "浦发银行", "q": "问题", "a": "回答", "trade_date": "20260825"}]
            )

    monkeypatch.setattr(module.settings, "minishare_irm_token", "token")
    monkeypatch.setattr(module, "ms", SimpleNamespace(pro_api=lambda _token: Api()))

    client = module.DataSourceClientMinishare()
    records = client.get_irm("600000.SH", start_date="20260819", end_date="20260826")

    assert calls == [{"ts_code": "600000.SH", "start_date": "20260819", "end_date": "20260826"}]
    assert records == [
        {
            "stock_code": "600000.SH",
            "stock_name": "浦发银行",
            "question": "问题",
            "answer": "回答",
            "question_time": "20260825",
            "answer_time": "20260825",
            "trade_date": "20260825",
            "exchange": "SH",
        }
    ]


def test_minishare_irm_routes_sz_by_company(monkeypatch):
    from app.data_pipeline import minishare_client as module

    calls = []

    class Api:
        def irm_qa_sz(self, **kwargs):
            calls.append(kwargs)
            return pd.DataFrame()

    monkeypatch.setattr(module.settings, "minishare_irm_token", "token")
    monkeypatch.setattr(module, "ms", SimpleNamespace(pro_api=lambda _token: Api()))

    client = module.DataSourceClientMinishare()
    assert client.get_irm("000001.SZ", start_date="20260819", end_date="20260826") == []
    assert calls == [{"ts_code": "000001.SZ", "start_date": "20260819", "end_date": "20260826"}]
