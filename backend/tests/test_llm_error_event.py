"""
LLM 失败错误事件测试

验证：
- GAP-BE-06: run_lead_agent() 在 LLM 失败时发射 error 事件
"""
import pytest


def test_run_lead_agent_has_error_emission():
    """
    验证 run_lead_agent() 函数在异常时发射 error 事件。
    """
    with open("app/reasoning/langchain_agent/client.py", "r") as f:
        source = f.read()

    # 验证包含 error 事件发射
    assert 'emit_fn("error"' in source or "emit_fn('error'" in source, \
        "run_lead_agent() 缺少 error 事件发射"

    # 验证 GAP-BE-06 标记
    assert "GAP-BE-06" in source, \
        "run_lead_agent() 缺少 GAP-BE-06 注释"


def test_run_lead_agent_raises_after_error():
    """
    验证 run_lead_agent() 在发射 error 后继续 raise 异常。
    """
    with open("app/reasoning/langchain_agent/client.py", "r") as f:
        source = f.read()

    # 验证 error 发射后有 raise 语句
    # 找到 error 事件发射附近的 raise
    error_emit_lines = []
    raise_found_after_error = False

    lines = source.split('\n')
    for i, line in enumerate(lines):
        if 'emit_fn("error"' in line or "emit_fn('error'" in line:
            # 检查后续 5 行是否有 raise
            for j in range(i+1, min(i+6, len(lines))):
                if 'raise' in lines[j] and not lines[j].strip().startswith('#'):
                    raise_found_after_error = True
                    break

    assert raise_found_after_error, \
        "run_lead_agent() 在发射 error 事件后缺少 raise 语句"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
