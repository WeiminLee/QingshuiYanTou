"""Test that V1.3 Schema is unified — no V4 remnants in prompts.

注：commit 8d1d8ef 将抽取重写为 JSON 输出，EXTRACTION_PROMPT_V13 统一为 EXTRACTION_PROMPT，
旧的文本标记（METRIC:/RELATES:）改为 JSON 字段（relations/stmt_type/metric_period）。
"""

from app.knowledge.extraction.rag_prompts import (
    DEFAULT_ENTITY_TYPES,
    ENTITY_TYPES,
    EXTRACTION_PROMPT,
    get_extraction_prompt,
)


def test_entity_types_is_v13():
    """ENTITY_TYPES must be exactly 3 types: Company, Product, Metric."""
    assert ENTITY_TYPES == ["Company", "Product", "Metric"]


def test_default_entity_types_is_v13():
    """DEFAULT_ENTITY_TYPES must point to V1.3 3-type list."""
    assert DEFAULT_ENTITY_TYPES == ENTITY_TYPES


def test_no_entity_types_v4_exported():
    """ENTITY_TYPES_V4 must not exist in the module."""
    from app.knowledge.extraction import rag_prompts

    assert not hasattr(rag_prompts, "ENTITY_TYPES_V4")


def test_v13_prompt_has_3_entity_types():
    """Unified prompt must only list 3 entity types."""
    prompt = EXTRACTION_PROMPT
    assert "Company" in prompt
    assert "Product" in prompt
    assert "Metric" in prompt
    # V4 types must NOT appear as entity type headers
    assert "Category（分类）" not in prompt
    assert "Application（应用）" not in prompt
    assert "Technology（技术）" not in prompt
    assert "Project（项目）" not in prompt


def test_v13_prompt_has_stmt_type():
    """Unified prompt must include stmt_type (Fact/Claim/Estimate)."""
    prompt = EXTRACTION_PROMPT
    assert "陈述类型" in prompt
    assert "Fact" in prompt
    assert "Claim" in prompt
    assert "Estimate" in prompt


def test_v13_prompt_has_metric_format():
    """Unified prompt must include structured Metric output (JSON metric_* 字段)."""
    prompt = EXTRACTION_PROMPT
    assert "Metric" in prompt
    assert "metric_period" in prompt


def test_v13_prompt_has_relates_format():
    """Unified prompt must include relations JSON format with stmt_type."""
    prompt = EXTRACTION_PROMPT
    assert "relations" in prompt
    assert "stmt_type" in prompt
    assert "陈述类型" in prompt


def test_v13_prompt_has_noise_rules():
    """Unified prompt must include noise prohibition rules."""
    prompt = EXTRACTION_PROMPT
    assert "禁止行为" in prompt


def test_get_extraction_prompt_returns_v13_for_all_source_types():
    """get_extraction_prompt must return V1.3 prompt for all source types."""
    for source_type in (
        "cninfo",
        "irm",
        "cninfo_announcement",
        "announcement",
        "annual_report",
        "prospectus",
        "招股书",
        "research",
    ):
        prompt = get_extraction_prompt(source_type)
        assert "Company" in prompt
        assert "Category（分类）" not in prompt


def test_no_announcement_v4_source_type():
    """announcement_v4 source_type must not appear in routing logic."""
    prompt = get_extraction_prompt("announcement_v4")
    # Should still get V1.3 prompt, not a V4-specific one
    assert "Category（分类）" not in prompt


def test_relation_service_no_v4_function_names():
    """relation_service must not have upsert_relates_v4."""
    from app.knowledge import relation_service

    assert not hasattr(relation_service, "upsert_relates_v4")
    assert hasattr(relation_service, "upsert_relates")


def test_rag_extractor_no_v4_function_names():
    """rag_extractor must not have _v4 suffixed function names."""
    from app.knowledge.extraction import rag_extractor

    assert not hasattr(rag_extractor, "_parse_relates_v4")
    assert not hasattr(rag_extractor, "_parse_metrics_v4")
    assert not hasattr(rag_extractor, "_parse_chunk_output_v4")
    assert hasattr(rag_extractor, "_parse_relates")
    assert hasattr(rag_extractor, "_parse_metrics")
    assert hasattr(rag_extractor, "_parse_chunk_output")


def test_rag_extractor_valid_entity_types_is_v13():
    """VALID_ENTITY_TYPES must only contain 3 types."""
    from app.knowledge.extraction.rag_extractor import VALID_ENTITY_TYPES

    assert VALID_ENTITY_TYPES == frozenset({"Company", "Product", "Metric"})
