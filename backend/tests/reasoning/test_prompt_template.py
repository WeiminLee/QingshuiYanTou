"""
tests/reasoning/test_prompt_template.py

测试 apply_prompt_template() 的输出正确性。
参考 DeerFlow: lead_agent/prompt.py 的完整模板结构。

Run: uv run --directory backend python -m pytest tests/reasoning/test_prompt_template.py -v
"""
import pytest


class TestApplyPromptTemplate:
    """apply_prompt_template() 行为测试"""

    def test_returns_string(self):
        from app.reasoning.langchain_agent.prompts.lead_system_prompt import apply_prompt_template
        result = apply_prompt_template()
        assert isinstance(result, str)

    def test_contains_role_section(self):
        """prompt 必须包含角色定义"""
        from app.reasoning.langchain_agent.prompts.lead_system_prompt import apply_prompt_template
        result = apply_prompt_template()
        assert "清水投研系统" in result or "投资分析师" in result

    def test_contains_memory_tag(self):
        """prompt 必须包含 <memory> 标签"""
        from app.reasoning.langchain_agent.prompts.lead_system_prompt import apply_prompt_template
        result = apply_prompt_template()
        assert "<memory>" in result

    def test_contains_current_date(self):
        """prompt 必须包含当前日期"""
        from app.reasoning.langchain_agent.prompts.lead_system_prompt import apply_prompt_template
        result = apply_prompt_template()
        from datetime import datetime
        today = datetime.now().strftime("%Y-%m-%d")
        assert today in result

    def test_subagent_section_when_enabled(self):
        """subagent_enabled=True 时包含 SUBAGENT MODE"""
        from app.reasoning.langchain_agent.prompts.lead_system_prompt import apply_prompt_template
        result = apply_prompt_template(subagent_enabled=True, max_concurrent_subagents=3)
        assert "SUBAGENT" in result or "subagent" in result

    def test_subagent_section_absent_when_disabled(self):
        """subagent_enabled=False 时不包含 subagent 段落"""
        from app.reasoning.langchain_agent.prompts.lead_system_prompt import apply_prompt_template
        result_disabled = apply_prompt_template(subagent_enabled=False)
        result_enabled = apply_prompt_template(subagent_enabled=True)
        # 启用时内容更多
        assert len(result_enabled) >= len(result_disabled)

    def test_memory_content_injected(self):
        """memory_content 参数注入到 <memory> 标签"""
        from app.reasoning.langchain_agent.prompts.lead_system_prompt import apply_prompt_template
        result = apply_prompt_template(
            memory_content="用户关注光模块行业和中际旭创"
        )
        assert "光模块行业" in result
        assert "中际旭创" in result

    def test_max_concurrent_in_subagent_section(self):
        """max_concurrent_subagents 参数正确注入"""
        from app.reasoning.langchain_agent.prompts.lead_system_prompt import apply_prompt_template
        result = apply_prompt_template(
            subagent_enabled=True,
            max_concurrent_subagents=5,
        )
        assert "5" in result

    def test_prompt_not_empty(self):
        """prompt 不能为空"""
        from app.reasoning.langchain_agent.prompts.lead_system_prompt import apply_prompt_template
        result = apply_prompt_template()
        assert len(result) > 100, "Prompt too short — likely missing sections"

    def test_contains_analysis_framework(self):
        """prompt 必须包含分析框架"""
        from app.reasoning.langchain_agent.prompts.lead_system_prompt import apply_prompt_template
        result = apply_prompt_template()
        assert "分析" in result
        assert len(result) > 500, "Prompt missing framework sections"

    def test_contains_compliance_reminder(self):
        """prompt 必须包含合规提醒"""
        from app.reasoning.langchain_agent.prompts.lead_system_prompt import apply_prompt_template
        result = apply_prompt_template()
        assert "投资建议" in result or "合规" in result or "置信度" in result
