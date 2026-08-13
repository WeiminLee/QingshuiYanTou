from app.reasoning.runtime.turn_context import AgentTurnContext


def test_agent_turn_context_binds_readiness_on_create():
    ctx = AgentTurnContext(
        run_id="run-1",
        thread_id="thread-1",
        question="分析 300308.SZ",
        freshness_context="\n".join(
            [
                "<data_readiness>",
                "overall_status=degraded",
                "- kline: stale; latest_data_date=2026-07-17; lag_days=2; threshold=1 trading_day; recommendation=滞后",
                "answer_boundary=基于截至最新可用日期的数据，避免强时效判断。",
                "</data_readiness>",
            ]
        ),
    )

    assert ctx.readiness_binding["overall_status"] == "degraded"
    assert ctx.readiness_binding["stale_sources"] == ["kline"]
    assert ctx.raw_analysis == ""
    assert ctx.to_trace_inputs() == {
        "tool_calls": [],
        "tool_results": [],
        "background": "",
        "graph_context": "",
        "agent_context": {},
        "freshness_context": ctx.freshness_context,
        "turns": 0,
        "run_id": "run-1",
    }


def test_agent_turn_context_tracks_tool_records_and_analysis():
    ctx = AgentTurnContext(run_id="run-2", thread_id="thread-2", question="行情分析")
    ctx.tool_calls.append({"id": "call-1", "name": "get_kline"})
    ctx.tool_results.append({"id": "call-1", "name": "get_kline", "success": True})
    ctx.full_content.extend(["第一段", "第二段"])
    ctx.turns = 3
    ctx.truncated = True

    assert ctx.raw_analysis == "第一段第二段"
    assert ctx.to_result_base() == {
        "content": "第一段第二段",
        "reasoning": "第一段第二段",
        "turns": 3,
        "tool_calls": [{"id": "call-1", "name": "get_kline"}],
        "tool_results": [{"id": "call-1", "name": "get_kline", "success": True}],
        "thread_id": "thread-2",
        "truncated": True,
    }
