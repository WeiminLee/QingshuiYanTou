"""Tests for IRM answer classifier."""

from __future__ import annotations

from app.knowledge.extraction.irm_classifier import (
    classify_irm_answer,
    classify_irm_evidence,
    extraction_tier,
    needs_llm,
    needs_rules,
)


def test_empty_boilerplate_only() -> None:
    assert classify_irm_answer("尊敬的投资者，您好。感谢您对公司的关注。") == "empty"
    assert classify_irm_answer("尊敬的投资者，您好！感谢您的关注！") == "empty"
    assert classify_irm_answer("投资者您好，感谢您对公司的关注！") == "empty"
    assert classify_irm_answer("您好，感谢关注。") == "empty"


def test_empty_no_content() -> None:
    assert classify_irm_answer("") == "empty"
    assert classify_irm_answer("   ") == "empty"


def test_complex_long_answer() -> None:
    long_text = "公司坚持前瞻布局，紧扣政策导向，在聚焦主业发展的基础上。" * 30
    assert len(long_text) >= 300
    assert classify_irm_answer(long_text) == "complex"


def test_complex_with_deferral_suffix() -> None:
    para = (
        "公司坚持上市公司治理的独立性和规范性。根据相关法规，公司建立了完善的法人治理结构。"
        "董事会决策独立于控股股东，管理层执行董事会的决议。公司重大投资决策均基于自身战略和市场化评估。"
        "日常经营管理中，公司已建立信息披露、关联交易回避等机制，确保业务、财务、人员独立。"
    )
    text = para * 3 + "所有重大事项均以公告为准。感谢您对公司的关注！"
    assert len(text) >= 300
    assert classify_irm_answer(text) == "complex"


def test_defer_short() -> None:
    assert classify_irm_answer("具体经营数据请以公告为准。感谢您的关注！") == "defer"
    assert classify_irm_answer("公司将依规披露重大业务合作事项，请以公告为准。谢谢您的关注！") == "defer"
    assert classify_irm_answer("公司如有重组计划，将会及时信披。") == "defer"
    assert classify_irm_answer("上述相关情况详见公司2025年8月28日发布的公告。感谢关注。") == "defer"


def test_data_shareholder_count() -> None:
    text = "尊敬的投资者您好！截至2026年5月20日，公司股东总户数为19849户，感谢关注！"
    assert classify_irm_answer(text) == "data"


def test_data_revenue() -> None:
    text = "近三年光伏玻璃业务分别实现营收34.12亿元、57.53亿元、69.63亿元。"
    assert classify_irm_answer(text) == "data"


def test_data_percentage() -> None:
    text = "国际业务增速达到20%，免疫增长超过了30%。"
    assert classify_irm_answer(text) == "data"


def test_simple_confirmation() -> None:
    assert classify_irm_answer("公司目前没有相关计划。") == "simple"
    assert classify_irm_answer("公司规范经营，不存在提问所述相关事项。") == "simple"
    assert classify_irm_answer("公司已收到业绩承诺方支付的全部补偿款项。") == "simple"


def test_simple_short_with_content() -> None:
    assert classify_irm_answer("环氧丙烷项目将于年内择机投产。") == "simple"


def test_simple_with_boilerplate_wrap() -> None:
    text = "尊敬的投资者，您好！公司目前没有相关计划。公司深入践行5X战略计划。感谢您对公司的关注！"
    assert classify_irm_answer(text) == "simple"


def test_extraction_tier_values() -> None:
    assert extraction_tier("empty") == 0
    assert extraction_tier("defer") == 0
    assert extraction_tier("simple") == 1
    assert extraction_tier("data") == 1
    assert extraction_tier("complex") == 2


def test_needs_llm() -> None:
    assert not needs_llm("empty")
    assert not needs_llm("defer")
    assert not needs_llm("simple")
    assert not needs_llm("data")
    assert needs_llm("complex")


def test_needs_rules() -> None:
    assert not needs_rules("empty")
    assert not needs_rules("defer")
    assert needs_rules("simple")
    assert needs_rules("data")
    assert needs_rules("complex")


def test_classify_evidence_from_metadata() -> None:
    evidence = {
        "source_type": "irm",
        "metadata": {
            "question": "公司最新股东人数是多少？",
            "answer": "尊敬的投资者您好！截至最新报告期，公司股东总人数为42855户，感谢关注！",
        },
    }
    assert classify_irm_evidence(evidence) == "data"


def test_classify_evidence_from_text_excerpt() -> None:
    evidence = {
        "source_type": "irm",
        "text_excerpt": "问：股东人数？答：尊敬的投资者您好！截至最新报告期，公司股东总人数为42855户，感谢关注！",
    }
    assert classify_irm_evidence(evidence) == "data"


def test_classify_evidence_empty_metadata() -> None:
    evidence = {
        "source_type": "irm",
        "text_excerpt": "问：你好\n答：投资者您好，感谢关注。",
    }
    assert classify_irm_evidence(evidence) == "empty"


def test_classify_evidence_no_metadata() -> None:
    evidence = {"source_type": "irm", "text_excerpt": ""}
    assert classify_irm_evidence(evidence) == "empty"
