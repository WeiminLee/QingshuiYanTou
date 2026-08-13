from app.reasoning.context.router import MemoryRouter


def test_signal_id_routes_to_relation_reasoning():
    result = MemoryRouter().classify("请分析这个信号", signal_id="SIG:abc")

    assert result.route == "relation_reasoning"
    assert result.reason == "signal_id provided"
    assert "signal_context" in result.required_context


def test_portfolio_question_routes_to_factual_lookup():
    result = MemoryRouter().classify("我是否持有中际旭创？")

    assert result.route == "factual_lookup"
    assert result.required_context == ["user_snapshot"]


def test_portfolio_fact_keyword_takes_priority_over_summary_keyword():
    result = MemoryRouter().classify("总结我的持仓")

    assert result.route == "factual_lookup"


def test_long_history_question_routes_to_broad_synthesis():
    result = MemoryRouter().classify("总结过去一个月我关注方向的变化")

    assert result.route == "broad_synthesis"
    assert "user_snapshot" in result.required_context


def test_default_routes_to_relation_reasoning():
    result = MemoryRouter().classify("光模块怎么看？")

    assert result.route == "relation_reasoning"
    assert result.reason == "default"
