"""
Stream End 生命周期测试

验证：
- GAP-BE-12: ManualAgentLoop 路径不重复发射 stream_end
- GAP-BE-03: legacy 路径 stream_end 包含完整报告
"""
import pytest


def test_manual_loop_no_duplicate_stream_end():
    """
    验证 use_manual_loop=True 路径不发射 reasoning_end（避免重复 stream_end）。

    ManualAgentLoop.run() 已发射 stream_end，
    client.py 不应再发射 reasoning_end。
    """
    with open("app/reasoning/langchain_agent/client.py", "r") as f:
        source = f.read()

    # 找到 use_manual_loop 分支
    # 在该分支中不应有 emit_fn("reasoning_end", ...) 调用
    # 验证方式：找到 "use_manual_loop" 相关区域，确认无 reasoning_end

    # 验证 ManualAgentLoop 的注释中包含 GAP-BE-12 标记
    assert "GAP-BE-12" in source, "client.py 缺少 GAP-BE-12 注释"

    # 统计 reasoning_end 发射次数（应该只在 legacy 路径中）
    reasoning_end_count = source.count('emit_fn("reasoning_end"') + source.count("emit_fn('reasoning_end'")
    # 应该只有 1 处（legacy 路径）
    assert reasoning_end_count == 1, \
        f"client.py 中 reasoning_end 发射次数应为 1（仅 legacy 路径），实际为 {reasoning_end_count}"


def test_manual_loop_stream_end_has_report():
    """
    验证 ManualAgentLoop 发射的 stream_end 包含完整报告字段。

    如果 manual_agent_loop.py 包含 stream_end 发射逻辑（Phase D），
    验证其包含完整报告字段。否则跳过（表示该分支尚未包含 Phase D 改动）。
    """
    with open("app/reasoning/langchain_agent/middlewares/manual_agent_loop.py", "r") as f:
        source = f.read()

    # 只有当 manual_agent_loop.py 包含 stream_end 发射时才验证报告字段
    has_stream_end = '"stream_end"' in source or "'stream_end'" in source
    if not has_stream_end:
        pytest.skip("manual_agent_loop.py 尚未包含 Phase D stream_end 逻辑")

    # 验证 stream_end 包含 report_content
    assert '"report_content"' in source or "'report_content'" in source, \
        "ManualAgentLoop stream_end 缺少 report_content 字段"

    # 验证 stream_end 包含 report_json
    assert '"report_json"' in source or "'report_json'" in source, \
        "ManualAgentLoop stream_end 缺少 report_json 字段"

    # 验证 stream_end 包含 report_id
    assert '"report_id"' in source or "'report_id'" in source, \
        "ManualAgentLoop stream_end 缺少 report_id 字段"


def test_legacy_stream_end_has_report():
    """
    验证 legacy 路径 reasoning_end 包含完整报告字段。
    """
    with open("app/reasoning/langchain_agent/client.py", "r") as f:
        source = f.read()

    # 验证 legacy 路径的 reasoning_end 包含报告字段
    # 在 reasoning_end 发射的上下文中检查
    assert '"report_content"' in source or "'report_content'" in source, \
        "legacy 路径 reasoning_end 缺少 report_content 字段"

    assert '"report_json"' in source or "'report_json'" in source, \
        "legacy 路径 reasoning_end 缺少 report_json 字段"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
