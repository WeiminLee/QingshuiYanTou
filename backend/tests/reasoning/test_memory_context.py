"""
tests/reasoning/test_memory_context.py

Phase 5 TDD: MongoDB 记忆 + KG Anchors 集成到 V2 LangChain Agent

Run: uv run --directory backend python -m pytest tests/reasoning/test_memory_context.py -v
"""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock


# ── Constants ──────────────────────────────────────────────────────────────

_THREAD_ID = "thread-abc"
_ANALYST_ID = "test-user"
_MOCK_MEMORY = "## 已知信息\n- 用户关注光模块行业"
_MOCK_KG_ANCHORS = "\n## 会话中反复提及的实体\n- 中际旭创（Company）被提及 3 次"


# ── Helpers ───────────────────────────────────────────────────────────────

def _make_mock_agent(stream_return=None):
    """返回正确 mock 的 agent instance（agent.stream 返回值）"""
    inst = MagicMock()
    inst.stream.return_value = stream_return or []
    return inst


def _reset_agent_cache():
    """清理 _ensure_agent 全局缓存，确保测试间隔离"""
    import app.reasoning.langchain_agent.client as _client_mod
    _client_mod._cached_agent = None
    _client_mod._cached_agent_key = None
    _client_mod._cached_model = None
    _client_mod._cached_tools = None


# ── Test: get_memory_context_async ────────────────────────────────────────


class TestGetMemoryContext:
    """get_memory_context_async() 从 MongoDB 加载记忆"""

    @pytest.mark.anyio
    async def test_returns_empty_when_no_memory(self):
        """无记忆时返回空字符串"""
        from app.reasoning.langchain_agent.prompts.lead_system_prompt import (
            get_memory_context_async,
        )
        with patch(
            "app.reasoning.memory.format_memory_for_prompt_async",
            new_callable=AsyncMock,
            return_value="",
        ):
            result = await get_memory_context_async("thread-no-exist")
            assert result == ""

    @pytest.mark.anyio
    async def test_returns_formatted_memory(self):
        """有记忆时返回格式化的段落"""
        from app.reasoning.langchain_agent.prompts.lead_system_prompt import (
            get_memory_context_async,
        )
        with patch(
            "app.reasoning.memory.format_memory_for_prompt_async",
            new_callable=AsyncMock,
            return_value=_MOCK_MEMORY,
        ):
            result = await get_memory_context_async("thread-123")
            assert "光模块行业" in result
            assert "## 已知信息" in result

    @pytest.mark.anyio
    async def test_loads_from_mongodb_with_thread_id(self):
        """确认使用 thread_id 查询 MongoDB"""
        from app.reasoning.langchain_agent.prompts.lead_system_prompt import (
            get_memory_context_async,
        )
        with patch(
            "app.reasoning.memory.format_memory_for_prompt_async",
            new_callable=AsyncMock,
            return_value="",
        ) as mock_format:
            await get_memory_context_async(
                _THREAD_ID, analyst_id=_ANALYST_ID
            )
            mock_format.assert_awaited_once_with(
                thread_id=_THREAD_ID,
                agent_name=None,
                analyst_id=_ANALYST_ID,
            )

    @pytest.mark.anyio
    async def test_handles_mongodb_error_gracefully(self):
        """MongoDB 异常时降级返回空字符串，不阻断 Agent"""
        from app.reasoning.langchain_agent.prompts.lead_system_prompt import (
            get_memory_context_async,
        )
        with patch(
            "app.reasoning.memory.format_memory_for_prompt_async",
            new_callable=AsyncMock,
            side_effect=Exception("MongoDB connection failed"),
        ):
            result = await get_memory_context_async("thread-fail")
            assert result == ""


# ── Test: apply_prompt_template memory 注入 ────────────────────────────────


class TestPromptTemplateMemoryInjection:
    """apply_prompt_template() 将 memory_content 注入 <memory> 标签"""

    def test_memory_content_in_tag(self):
        """memory_content 参数注入 <memory>...</memory> 标签"""
        from app.reasoning.langchain_agent.prompts.lead_system_prompt import (
            apply_prompt_template,
        )
        result = apply_prompt_template(memory_content=_MOCK_MEMORY)
        assert "<memory>" in result
        assert "</memory>" in result
        assert "光模块行业" in result

    def test_empty_memory_content_produces_empty_tag(self):
        """空 memory_content 时 <memory></memory> 为空"""
        from app.reasoning.langchain_agent.prompts.lead_system_prompt import (
            apply_prompt_template,
        )
        result = apply_prompt_template(memory_content="")
        start = result.find("<memory>") + len("<memory>")
        end = result.find("</memory>")
        inner = result[start:end].strip()
        assert inner == ""


# ── Test: client.py harness bug ───────────────────────────────────────────


class TestClientKgAnchorsBug:
    """client.py 中 harness 未定义先引用的 bug 修复"""

    def test_client_no_harness_reference_before_definition(self):
        """
        client.py 在 harness 变量定义前不应引用它。

        Bug (已修复): 原代码第 197 行 `if harness is not None`
        但 harness 在第 226 行才定义，导致 KG anchors 永远不注入。

        修复后：harness 在 line ~195 定义，line ~197 引用，顺序正确。
        """
        import inspect
        from app.reasoning.langchain_agent import client

        source = inspect.getsource(client.run_lead_agent)
        lines = source.splitlines()

        # 找定义行
        define_lines = [
            i
            for i, line in enumerate(lines, start=1)
            if "harness: HarnessManager | None = None" in line
        ]
        assert define_lines, "未找到 harness 定义行"
        first_def = define_lines[0]

        # 找所有实际引用 harness 变量（非赋值）的行
        # 排除：import 语句、函数签名、注释
        harness_use_lines = []
        for i, line in enumerate(lines, start=1):
            stripped = line.strip()
            # 跳过空行、注释、import
            if not stripped or stripped.startswith("#") or stripped.startswith("from ") or stripped.startswith("import "):
                continue
            # 跳过函数签名中的 harness 参数
            if "def run_lead_agent" in line or "harness_config" in line:
                continue
            if "harness" in line:
                harness_use_lines.append(i)

        bad_refs = [l for l in harness_use_lines if l < first_def]
        assert not bad_refs, (
            f"harness 在第 {first_def} 行定义，但被提前引用: {bad_refs}"
        )


# ── Test: run_lead_agent memory 流程 ──────────────────────────────────────


class TestClientRunLeadAgentMemoryFlow:
    """client.py run_lead_agent() 正确传递 memory_content 到 system prompt"""

    @pytest.mark.anyio
    async def test_loads_memory_before_agent_creation(self):
        """run_lead_agent 在构建 system_prompt 前加载记忆"""
        _reset_agent_cache()
        from app.reasoning.langchain_agent import client as _client_mod
        from app.reasoning.langchain_agent.client import run_lead_agent
        from app.reasoning.langchain_agent.prompts.lead_system_prompt import (
            apply_prompt_template,
        )

        # 捕获传给 apply_prompt_template 的 memory_content 参数
        captured_memory: list[str] = []

        original_apply = apply_prompt_template

        def mock_apply(*args, **kwargs):
            mem = kwargs.get("memory_content", "")
            if mem:
                captured_memory.append(mem)
            return original_apply(*args, **kwargs)

        with patch(
            "app.reasoning.langchain_agent.client._pre_search",
            new_callable=AsyncMock,
            return_value="",
        ), patch(
            "app.reasoning.langchain_agent.client._get_tools",
            return_value=[],
        ), patch(
            "app.reasoning.langchain_agent.client._ensure_agent"
        ) as mock_agent, patch(
            "app.reasoning.langchain_agent.client._build_agent_config",
            return_value={"configurable": {}},
        ), patch.object(
            _client_mod, "_create_chat_model"
        ), patch.object(
            _client_mod, "_load_memory_context",
            new_callable=AsyncMock, return_value=_MOCK_MEMORY
        ), patch.object(
            _client_mod, "check_clarification", return_value=None
        ):
            mock_agent.return_value = (_make_mock_agent([]), None)

            await run_lead_agent(
                question="分析锂电池",
                thread_id=_THREAD_ID,
            )

            args, kwargs = mock_agent.call_args
            system_prompt = kwargs.get("system_prompt") or ""
            assert "光模块行业" in system_prompt, (
                f"memory_content 未注入到 system_prompt"
            )

    @pytest.mark.anyio
    async def test_memory_loaded_with_correct_thread_id(self):
        """memory_context 使用与请求相同的 thread_id"""
        _reset_agent_cache()
        from app.reasoning.langchain_agent.client import run_lead_agent
        from app.reasoning.langchain_agent import client as _client_mod

        captured: list[str] = []

        async def capture(thread_id_, **kw):
            captured.append(thread_id_)
            return ""

        with patch(
            "app.reasoning.langchain_agent.client._pre_search",
            new_callable=AsyncMock,
            return_value="",
        ), patch(
            "app.reasoning.langchain_agent.client._get_tools",
            return_value=[],
        ), patch(
            "app.reasoning.langchain_agent.client._ensure_agent"
        ) as mock_agent, patch(
            "app.reasoning.langchain_agent.client._build_agent_config",
            return_value={"configurable": {}},
        ), patch.object(
            _client_mod, "_load_memory_context", capture
        ), patch.object(
            _client_mod, "_create_chat_model"
        ), patch.object(
            _client_mod, "check_clarification", return_value=None
        ):
            mock_agent.return_value = (_make_mock_agent([]), None)

            await run_lead_agent(
                question="分析光模块",
                thread_id=_THREAD_ID,
            )

            assert _THREAD_ID in captured, (
                f"memory 未使用请求的 thread_id={_THREAD_ID}，"
                f"实际捕获: {captured}"
            )


# ── Test: KG Anchors 注入 ────────────────────────────────────────────────


class TestKgAnchorsInjection:
    """KG Anchors 通过 HarnessManager 注入到 system prompt"""

    @pytest.mark.anyio
    async def test_kg_anchors_passed_to_prompt_when_enabled(self):
        """harness_config.kg_anchors_enabled=True 时，kg_anchors 注入 system prompt"""
        _reset_agent_cache()
        from app.reasoning.langchain_agent.client import run_lead_agent
        from app.reasoning.langchain_agent.integrations import HarnessConfig
        from app.reasoning.langchain_agent import client as _client_mod

        with patch(
            "app.reasoning.langchain_agent.client._pre_search",
            new_callable=AsyncMock,
            return_value="",
        ), patch(
            "app.reasoning.langchain_agent.client._get_tools",
            return_value=[],
        ), patch(
            "app.reasoning.langchain_agent.client._ensure_agent"
        ) as mock_agent, patch(
            "app.reasoning.langchain_agent.client._build_agent_config",
            return_value={"configurable": {}},
        ), patch(
            "app.reasoning.langchain_agent.client.format_kg_anchors",
            return_value=_MOCK_KG_ANCHORS,
        ), patch.object(
            _client_mod, "_create_chat_model"
        ), patch.object(
            _client_mod, "check_clarification", return_value=None
        ):
            mock_agent.return_value = (_make_mock_agent([]), None)

            await run_lead_agent(
                question="分析中际旭创",
                thread_id="anchors-thread",
                harness_config=HarnessConfig(kg_anchors_enabled=True),
            )

            args, kwargs = mock_agent.call_args
            system_prompt = kwargs.get("system_prompt") or ""
            assert "中际旭创" in system_prompt, (
                "KG Anchors 未注入 system_prompt"
            )

    @pytest.mark.anyio
    async def test_kg_anchors_absent_when_disabled(self):
        """kg_anchors_enabled=False 时，不注入 kg_anchors"""
        from app.reasoning.langchain_agent.client import run_lead_agent
        from app.reasoning.langchain_agent.integrations import HarnessConfig
        from app.reasoning.langchain_agent import client as _client_mod

        with patch(
            "app.reasoning.langchain_agent.client._pre_search",
            new_callable=AsyncMock,
            return_value="",
        ), patch(
            "app.reasoning.langchain_agent.client._get_tools",
            return_value=[],
        ), patch(
            "app.reasoning.langchain_agent.client._ensure_agent"
        ) as mock_agent, patch(
            "app.reasoning.langchain_agent.client._build_agent_config",
            return_value={"configurable": {}},
        ), patch(
            "app.reasoning.langchain_agent.client._load_memory_context",
            new_callable=AsyncMock,
            return_value="",
        ), patch(
            "app.reasoning.langchain_agent.integrations.format_kg_anchors",
            return_value=_MOCK_KG_ANCHORS,
        ), patch.object(
            _client_mod, "_create_chat_model"
        ), patch.object(
            _client_mod, "check_clarification", return_value=None
        ):
            mock_agent.return_value = (_make_mock_agent([]), None)

            await run_lead_agent(
                question="分析光模块",
                thread_id="no-anchors-thread",
                harness_config=HarnessConfig(kg_anchors_enabled=False),
            )

            args, kwargs = mock_agent.call_args
            system_prompt = kwargs.get("system_prompt") or (args[2] if len(args) > 2 else "")
            assert "Company）被提及" not in system_prompt, (
                "KG Anchors 不应在 kg_anchors_enabled=False 时注入"
            )
