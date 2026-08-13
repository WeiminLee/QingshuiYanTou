from app.reasoning.langchain_agent.client import _build_analysis_report, _build_trace_metadata
from app.reasoning.output.report import AnalysisReport


def test_build_trace_metadata_groups_tools_and_evidence_refs():
    trace = _build_trace_metadata(
        tool_calls=[
            {"id": "call-graph", "name": "neo4j_traverse", "args": {"entity": "光模块"}},
            {"id": "call-ann", "name": "get_announcement", "args": {"ts_code": "300308.SZ"}},
            {"id": "call-report", "name": "get_research_report", "args": {"query": "光模块"}},
        ],
        tool_results=[
            {
                "id": "call-graph",
                "name": "neo4j_traverse",
                "result": "获取到 12 条关系",
                "success": True,
                "turn": 1,
                "original_len": 3000,
                "duration_ms": 120.0,
            },
            {
                "id": "call-ann",
                "name": "get_announcement",
                "result": "获取到 3条公告",
                "success": True,
                "turn": 1,
                "original_len": 1200,
                "duration_ms": 80.0,
            },
            {
                "id": "call-report",
                "name": "get_research_report",
                "result": "获取到 5篇研报",
                "success": True,
                "turn": 2,
                "original_len": 1500,
                "duration_ms": 95.0,
            },
        ],
        background="<background>相关背景知识</background>",
        graph_context="[图谱上下文] 光模块 的直接关系（2 条）",
        turns=2,
        run_id="run-1",
    )

    assert trace["trace_summary"]["tool_call_count"] == 3
    assert trace["trace_summary"]["tool_result_count"] == 3
    assert trace["trace_summary"]["source_layer_count"] >= 4
    assert trace["trace_summary"]["evidence_ref_count"] >= 4
    assert trace["trace_summary"]["graph_ref_count"] == 2

    layers = {layer["key"]: layer for layer in trace["source_layers"]}
    assert layers["graph"]["label"] == "知识图谱"
    assert layers["disclosure"]["label"] == "公告与公司披露"
    assert layers["research"]["label"] == "研报与外部研究"
    assert layers["background"]["label"] == "向量背景知识"

    graph_ref = trace["graph_refs"][0]
    assert graph_ref["relation_count"] == 12
    assert graph_ref["tool"] == "neo4j_traverse"

    audit = {item["tool_call_id"]: item for item in trace["tool_audit"]}
    assert audit["call-ann"]["source_layer"] == "disclosure"
    assert audit["call-ann"]["args"] == {"ts_code": "300308.SZ"}
    assert audit["call-ann"]["contract"]["data_source"] == "announcement"
    assert audit["call-ann"]["contract"]["success"] is True


def test_build_trace_metadata_binds_readiness_context_as_evidence():
    trace = _build_trace_metadata(
        tool_calls=[],
        tool_results=[],
        background="",
        graph_context="",
        freshness_context="\n".join(
            [
                "<data_readiness>",
                "as_of=2026-07-21T09:30:00+08:00",
                "overall_status=degraded",
                "sources:",
                "- kline: stale; latest_data_date=2026-07-17; lag_days=2; threshold=1 trading_day; recommendation=数据已滞后 2 天",
                "answer_boundary=基于截至最新可用日期的数据，避免强时效判断。",
                "</data_readiness>",
            ]
        ),
        turns=0,
        run_id="run-freshness",
    )

    assert trace["readiness_binding"]["overall_status"] == "degraded"
    assert trace["readiness_binding"]["stale_sources"] == ["kline"]
    assert trace["trace_summary"]["readiness_status"] == "degraded"
    assert trace["trace_summary"]["traceable"] is True
    assert trace["evidence_refs"][0]["id"] == "DATA_READINESS"
    assert trace["evidence_refs"][0]["metadata"]["conclusion_policy"] == "degraded"


def test_build_trace_metadata_marks_stale_tool_contract_from_readiness():
    trace = _build_trace_metadata(
        tool_calls=[{"id": "call-kline", "name": "get_kline", "args": {"ts_code": "300308.SZ"}}],
        tool_results=[
            {
                "id": "call-kline",
                "name": "get_kline",
                "result": "查询到 30 条K线数据",
                "success": True,
                "turn": 1,
                "original_len": 3000,
                "duration_ms": 88,
            }
        ],
        freshness_context="\n".join(
            [
                "<data_readiness>",
                "overall_status=degraded",
                "sources:",
                "- kline: stale; latest_data_date=2026-07-17; lag_days=2; threshold=1 trading_day; recommendation=滞后",
                "</data_readiness>",
            ]
        ),
    )

    contract = trace["tool_audit"][0]["contract"]
    assert contract["data_source"] == "kline"
    assert contract["data_status"] == "stale"
    assert contract["stale"] is True
    assert trace["evidence_refs"][1]["metadata"]["contract"]["latest_data_date"] == "2026-07-17"


def test_analysis_report_to_dict_exposes_trace_fields():
    report = AnalysisReport(report_id="r1", topic="测试", raw_analysis="结论")
    report.trace_summary = {"traceable": True, "tool_call_count": 1}
    report.source_layers = [{"key": "graph", "label": "知识图谱"}]
    report.evidence_refs = [{"id": "TOOL:1", "content": "获取到 1 条关系"}]
    report.tool_audit = [{"tool": "neo4j_traverse"}]
    report.graph_refs = [{"relation_count": 1}]

    data = report.to_dict()

    assert data["trace_summary"]["traceable"] is True
    assert data["source_layers"][0]["key"] == "graph"
    assert data["evidence_refs"][0]["id"] == "TOOL:1"
    assert data["tool_audit"][0]["tool"] == "neo4j_traverse"
    assert data["graph_refs"][0]["relation_count"] == 1


def test_build_analysis_report_accepts_trace_metadata():
    trace = {
        "trace_summary": {"traceable": True},
        "source_layers": [{"key": "market"}],
        "evidence_refs": [{"id": "TOOL:kline"}],
        "tool_audit": [{"tool": "get_kline"}],
        "graph_refs": [],
        "readiness_binding": {"overall_status": "fresh", "conclusion_policy": "normal"},
    }

    report = _build_analysis_report(topic="行情分析", raw_analysis="分析内容", turns=1, trace=trace)
    data = report.to_dict()

    assert data["trace_summary"] == {"traceable": True}
    assert data["source_layers"] == [{"key": "market"}]
    assert data["evidence_refs"] == [{"id": "TOOL:kline"}]
    assert data["tool_audit"] == [{"tool": "get_kline"}]
    assert data["readiness_binding"] == {"overall_status": "fresh", "conclusion_policy": "normal"}


def test_analysis_report_markdown_renders_trace_section():
    report = AnalysisReport(report_id="r2", topic="可信推理测试", raw_analysis="分析内容")
    report.trace_summary = {
        "turns": 2,
        "successful_tool_count": 2,
        "tool_result_count": 3,
        "source_layer_count": 2,
        "evidence_ref_count": 2,
        "graph_ref_count": 1,
    }
    report.source_layers = [
        {
            "key": "graph",
            "label": "知识图谱",
            "confidence": "TIER2_THIRD_PARTY",
            "tool_count": 1,
            "success_count": 1,
            "items": [{"preview": "获取到 12 条关系"}],
        }
    ]
    report.graph_refs = [{"tool": "neo4j_traverse", "relation_count": 12, "preview": "获取到 12 条关系"}]
    report.evidence_refs = [
        {
            "source_name": "公告与公司披露",
            "confidence": "TIER3_SELF_DISCLOSED",
            "content": "获取到 3 条公告",
        }
    ]
    report.tool_audit = [
        {
            "tool": "neo4j_traverse",
            "source_layer": "graph",
            "success": True,
            "duration_ms": 100.0,
            "preview": "获取到 12 条关系",
        }
    ]

    markdown = report.to_markdown()

    assert "## 可信推理链" in markdown
    assert "### 来源层" in markdown
    assert "### 图谱引用" in markdown
    assert "### 证据引用" in markdown
    assert "### 工具审计" in markdown
    assert "知识图谱" in markdown
    assert "neo4j_traverse" in markdown
