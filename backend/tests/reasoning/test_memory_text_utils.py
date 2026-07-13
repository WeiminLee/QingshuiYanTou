from app.reasoning.langchain_agent.memory.text_utils import (
    jaccard_similarity,
    normalize_subject,
)


def test_jaccard_identical_is_one():
    assert jaccard_similarity("光模块景气度高", "光模块景气度高") == 1.0


def test_jaccard_disjoint_is_zero():
    assert jaccard_similarity("abcd", "wxyz") == 0.0


def test_jaccard_partial_between_zero_and_one():
    score = jaccard_similarity("用户想减仓", "用户想加仓")
    assert 0.0 < score < 1.0


def test_jaccard_empty_inputs():
    assert jaccard_similarity("", "") == 1.0
    assert jaccard_similarity("a", "") == 0.0


def test_jaccard_short_strings_equal():
    assert jaccard_similarity("光", "光") == 1.0
    assert jaccard_similarity("光", "电") == 0.0


def test_normalize_subject_collapses_whitespace():
    assert normalize_subject("  800G  光模块 ") == "800G 光模块"


def test_normalize_subject_fullwidth_to_halfwidth():
    assert normalize_subject("８００Ｇ") == "800G"
