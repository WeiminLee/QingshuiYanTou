# backend/tests/test_linklayer_llm_extract.py
"""LLM 浅提取器测试：纯逻辑（prompt/解析/缓存），LLM 调用打桩。"""
import pytest

from app.knowledge.linklayer.llm_extract import KEYWORD_PROMPT_VERSION, parse_llm_json


def test_parse_llm_json_plain():
    got = parse_llm_json('{"company": ["中晶科技"], "product": ["8英寸抛光硅片"], "metric": []}')
    assert got["company"] == ["中晶科技"]
    assert got["product"] == ["8英寸抛光硅片"]


def test_parse_llm_json_with_code_fence():
    raw = '```json\n{"company": [], "product": [], "metric": []}\n```'
    assert parse_llm_json(raw) is not None


def test_parse_llm_json_invalid_returns_none():
    assert parse_llm_json("我认为不是") is None


def test_metric_value_passthrough():
    raw = '{"company": [], "product": [], "metric": [{"name": "毛利率", "value": 45, "unit": "%", "period": "2026H1"}]}'
    got = parse_llm_json(raw)
    assert got["metric"][0]["value"] == 45


def test_keyword_prompt_version():
    assert KEYWORD_PROMPT_VERSION == "kw_v1"


@pytest.mark.integration
def test_extract_keywords_real_llm():
    """integration：真实 LLM 网关。"""
