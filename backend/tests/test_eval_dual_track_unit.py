import json

from scripts.eval_dual_track import DEFAULT_CASES, bare_tool_name, judge_case


def test_judge_requires_tool_and_phrase():
    case = {
        "must_call_tools": ["compare_metric"],
        "answer_must_include_any": ["预期差", "毛利率"],
    }
    assert judge_case(
        case,
        answer="存在预期差：毛利率横比…",
        tools_called=["compare_metric", "fetch_evidence"],
    )
    assert not judge_case(case, answer="随便看看", tools_called=["compare_metric"])
    assert not judge_case(
        case,
        answer="存在预期差：毛利率",
        tools_called=["semantic_search"],
    )


def test_judge_must_call_any_of():
    case = {
        "must_call_tools": ["compare_metric"],
        "must_call_any_of": ["pull_history", "fetch_evidence"],
        "answer_must_include_any": ["预期差"],
    }
    assert judge_case(
        case,
        answer="存在预期差",
        tools_called=["compare_metric", "fetch_evidence"],
    )
    assert not judge_case(
        case,
        answer="存在预期差",
        tools_called=["compare_metric"],
    )


def test_bare_tool_name():
    assert bare_tool_name("mcp__qingshui_data__compare_metric") == "compare_metric"
    assert bare_tool_name("compare_metric") == "compare_metric"


def test_default_cases_is_v2_eleven():
    """Direct eval_dual_track.py invocation must score v2 (11 cases), not v1 (3)."""
    assert DEFAULT_CASES.name == "expected_gap_cases_v2.json"
    assert DEFAULT_CASES.is_file()
    cases = json.loads(DEFAULT_CASES.read_text(encoding="utf-8"))
    assert len(cases) == 11
