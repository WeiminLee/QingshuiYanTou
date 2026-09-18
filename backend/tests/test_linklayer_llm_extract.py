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


def test_parse_llm_json_non_list_fields_dropped():
    got = parse_llm_json('{"company": "中晶科技", "product": null, "metric": "毛利率"}')
    assert got == {"company": [], "product": [], "metric": []}


def test_parse_llm_json_null_fields_returns_valid_dict():
    got = parse_llm_json('{"company": null, "product": null, "metric": null}')
    assert got == {"company": [], "product": [], "metric": []}


def test_parse_llm_json_single_line_code_fence():
    raw = '```json {"company": ["中晶科技"], "product": [], "metric": []}```'
    got = parse_llm_json(raw)
    assert got is not None
    assert got["company"] == ["中晶科技"]


def test_keyword_prompt_version():
    assert KEYWORD_PROMPT_VERSION == "kw_v2"


async def test_extract_keywords_missing_cached_result_is_cache_miss(monkeypatch):
    """version 匹配但 result 缺失 → 视为缓存未命中，走 LLM 重新提取。"""
    from app.knowledge import evidence_service as es
    from app.knowledge.linklayer import llm_extract

    async def fake_chat(prompt, **kw):
        return '{"company": ["中晶科技"], "product": [], "metric": []}'

    async def fake_update(self, evidence_id, payload):
        pass

    monkeypatch.setattr(llm_extract, "chat_async", fake_chat)
    monkeypatch.setattr(es.EvidenceService, "update_keyword_extraction", fake_update)
    evidence = {
        "evidence_id": "EV:cache-miss",
        "text_excerpt": "中晶科技量产",
        "keyword_extraction": {"version": "kw_v1"},  # result 缺失
    }
    got = await llm_extract.extract_keywords(evidence)
    assert got == {"company": ["中晶科技"], "product": [], "metric": []}


@pytest.mark.integration
def test_extract_keywords_real_llm():
    """integration：真实 LLM 网关。"""
