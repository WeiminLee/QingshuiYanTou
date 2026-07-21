from app.reasoning.runtime.run_ledger import build_readiness_binding


def test_build_readiness_binding_parses_agent_context():
    context = "\n".join(
        [
            "<data_readiness>",
            "as_of=2026-07-21T09:30:00+08:00",
            "overall_status=degraded",
            "rules:",
            "sources:",
            "- kline: stale; latest_data_date=2026-07-17; lag_days=2; threshold=1 trading_day; recommendation=数据已滞后 2 天",
            "- announcement: fresh; latest_data_date=2026-07-21; lag_days=0; threshold=1 calendar_day; recommendation=数据处于日级可靠窗口内。",
            "answer_boundary=基于截至最新可用日期的数据，避免强时效判断。",
            "</data_readiness>",
        ]
    )

    binding = build_readiness_binding(context)

    assert binding["overall_status"] == "degraded"
    assert binding["as_of"] == "2026-07-21T09:30:00+08:00"
    assert binding["answer_boundary"] == "基于截至最新可用日期的数据，避免强时效判断。"
    assert binding["conclusion_policy"] == "degraded"
    assert binding["is_time_sensitive_allowed"] is True
    assert binding["stale_sources"] == ["kline"]
    assert binding["failed_sources"] == []
    assert binding["sources"][0]["source"] == "kline"
    assert binding["sources"][0]["status"] == "stale"
    assert binding["sources"][0]["latest_data_date"] == "2026-07-17"


def test_build_readiness_binding_marks_unavailable_as_blocked():
    context = "\n".join(
        [
            "<data_readiness>",
            "overall_status=unavailable",
            "readiness_error=database down",
            "answer_boundary=关键数据缺失或同步失败，不得输出强结论。",
            "</data_readiness>",
        ]
    )

    binding = build_readiness_binding(context)

    assert binding["overall_status"] == "unavailable"
    assert binding["readiness_error"] == "database down"
    assert binding["conclusion_policy"] == "blocked"
    assert binding["is_time_sensitive_allowed"] is False
