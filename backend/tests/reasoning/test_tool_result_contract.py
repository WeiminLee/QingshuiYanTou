from app.reasoning.runtime.run_ledger import build_readiness_binding
from app.reasoning.runtime.tool_contract import build_tool_result_contract


def test_build_tool_result_contract_binds_tool_to_stale_readiness_source():
    readiness = build_readiness_binding(
        "\n".join(
            [
                "<data_readiness>",
                "overall_status=degraded",
                "sources:",
                "- kline: stale; latest_data_date=2026-07-17; lag_days=2; threshold=1 trading_day; recommendation=滞后",
                "</data_readiness>",
            ]
        )
    )

    contract = build_tool_result_contract(
        tool_name="get_kline",
        tool_call_id="call-1",
        preview="查询到 30 条K线数据",
        success=True,
        source_layer="market",
        readiness_binding=readiness,
        original_len=3000,
        duration_ms=123.4,
    )

    assert contract["tool_call_id"] == "call-1"
    assert contract["tool"] == "get_kline"
    assert contract["data_source"] == "kline"
    assert contract["data_status"] == "stale"
    assert contract["latest_data_date"] == "2026-07-17"
    assert contract["stale"] is True
    assert contract["time_sensitive_allowed"] is True
    assert contract["original_len"] == 3000


def test_build_tool_result_contract_marks_failure_error_type():
    contract = build_tool_result_contract(
        tool_name="get_announcement",
        tool_call_id="call-2",
        preview="[数据服务暂不可用] 工具 get_announcement 本次未能返回数据",
        success=False,
        source_layer="disclosure",
        readiness_binding={},
        original_len=80,
        duration_ms=10,
    )

    assert contract["data_source"] == "announcement"
    assert contract["success"] is False
    assert contract["error_type"] == "tool_failure"
