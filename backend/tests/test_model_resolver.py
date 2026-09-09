"""模型可用性自动回退 resolver 单测。

覆盖：主模型可用/主模型不可用→flash→minimax→任选 的挑选顺序；
403 标记坏模型排除；TTL 后主模型恢复切回；retry-after 解析。
全程 mock 网关列表拉取，不发真实网络请求。
"""

import asyncio

import pytest

from app.config import settings
from app.core import llm_client as lc
from app.knowledge.extraction.rag_extractor import _extract_retry_after


@pytest.fixture(autouse=True)
def _reset_resolver_state():
    """每个用例重置进程级 resolver 状态，避免相互污染。"""
    lc._effective_model = None
    lc._effective_set_at = 0.0
    lc._unavailable_models = set()
    lc._available_cache = None
    lc._available_ts = 0.0
    yield
    lc._effective_model = None
    lc._effective_set_at = 0.0
    lc._unavailable_models = set()
    lc._available_cache = None
    lc._available_ts = 0.0


@pytest.fixture
def _cfg(monkeypatch):
    """固定抽取模型主选与回退偏好。"""
    monkeypatch.setattr(settings, "llm_extraction_model", "deepseek-v4-flash")
    monkeypatch.setattr(settings, "llm_extraction_fallback_order", "flash,minimax,*")
    monkeypatch.setattr(settings, "llm_extraction_model_ttl", 300)
    monkeypatch.setattr(settings, "llm_model_list_cache_ttl", 300)
    monkeypatch.setattr(settings, "llm_api_key", "sk-test")
    monkeypatch.setattr(settings, "llm_base_url", "http://gw.test/v1")


class _Holder:
    models: list[str] = []


@pytest.fixture
def _fake_fetch(monkeypatch):
    """让 fetch 返回可控列表（模拟 GET /v1/models）。"""
    holder = _Holder()

    async def fake_fetch(force: bool = False):
        return list(holder.models)

    monkeypatch.setattr(lc, "fetch_available_models_async", fake_fetch)
    return holder


# ── 挑选顺序 ─────────────────────────────────────────────────────────────


def test_primary_used_when_available(_cfg, _fake_fetch):
    """主模型未被标记坏 → 直接用主模型，不依赖列表（零网络）。"""
    _fake_fetch.models = ["deepseek-v4-flash", "glm-5.3-flash"]
    assert asyncio.run(lc.get_extraction_model()) == "deepseek-v4-flash"
    assert lc._effective_model is None  # 未切换


def test_fallback_flash_when_primary_gone(_cfg, _fake_fetch):
    """主模型 403 不可用 → 切到含 flash 的可用模型。"""
    _fake_fetch.models = ["glm-5.3-flash", "glm-5.3", "minimax-m2.7"]
    switched = asyncio.run(lc.mark_extraction_model_unavailable("deepseek-v4-flash"))
    assert switched == "glm-5.3-flash"
    assert asyncio.run(lc.get_extraction_model()) == "glm-5.3-flash"


def test_fallback_minimax_no_flash(_cfg, _fake_fetch):
    """无 flash → 含 minimax 的模型。"""
    _fake_fetch.models = ["glm-5.3", "minimax-m2.7", "kimi-k3"]
    switched = asyncio.run(lc.mark_extraction_model_unavailable("deepseek-v4-flash"))
    assert switched == "minimax-m2.7"


def test_fallback_any_when_no_pref(_cfg, _fake_fetch):
    """既无 flash 也无 minimax → 任选第一个可用。"""
    _fake_fetch.models = ["glm-5.3", "kimi-k3"]
    switched = asyncio.run(lc.mark_extraction_model_unavailable("deepseek-v4-flash"))
    assert switched == "glm-5.3"


def test_bad_flash_excluded_then_minimax(_cfg, _fake_fetch):
    """标记过的坏模型不再被选中：flash 也 403 后应退到 minimax。"""
    _fake_fetch.models = ["glm-5.3-flash", "minimax-m2.7"]
    first = asyncio.run(lc.mark_extraction_model_unavailable("deepseek-v4-flash"))
    assert first == "glm-5.3-flash"
    second = asyncio.run(lc.mark_extraction_model_unavailable(first))
    assert second == "minimax-m2.7"


def test_no_fallback_returns_none(_cfg, _fake_fetch):
    """列表为空 → 返回 None，由调用方退回原模型报错。"""
    _fake_fetch.models = []
    assert asyncio.run(lc.mark_extraction_model_unavailable("deepseek-v4-flash")) is None


# ── TTL：主模型恢复切回 ─────────────────────────────────────────────────


def test_revert_to_primary_after_ttl(_cfg, _fake_fetch, monkeypatch):
    """切到 flash 后过 TTL，主模型恢复可用 → 切回主模型。"""
    _fake_fetch.models = ["glm-5.3-flash"]
    asyncio.run(lc.mark_extraction_model_unavailable("deepseek-v4-flash"))
    assert lc._effective_model == "glm-5.3-flash"
    # 手动让 TTL 过期，并让主模型重新出现在列表
    lc._effective_set_at = 0.0
    _fake_fetch.models = ["deepseek-v4-flash", "glm-5.3-flash"]
    assert asyncio.run(lc.get_extraction_model()) == "deepseek-v4-flash"


# ── retry-after 解析 ─────────────────────────────────────────────────────


def test_extract_retry_after_parsing():
    assert _extract_retry_after("retry-after: 5") == 5.0
    assert _extract_retry_after("HTTP/1.1 429, retry-after: 5") == 5.0
    assert _extract_retry_after("{\"retry_after\":5}") == 5.0
    assert _extract_retry_after("普通错误，无 retry-after") is None
    assert _extract_retry_after("Error code: 403 model_not_available") is None
