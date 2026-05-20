"""
ToolExecutor — 增强版工具执行器

Phase 3 特性：
- ToolResult 结构化返回（替代 tuple）
- 超时控制（asyncio.wait_for）
- 重试机制（RetryStrategy 集成）
- 并发执行（asyncio.gather + asyncio.Semaphore）
- SSE 安全截断（truncate_for_sse）
- NEVER_PARALLEL 工具串行保证

与 client.py ToolExecutor 的区别：
- 返回 ToolResult dataclass（而非 tuple[str, str]）
- 支持 RetryStrategy（重试配置）
- 支持超时控制
- SSE 截断方法
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

from app.reasoning.langchain_agent.retry import ExponentialBackoff, NoRetry, RetryStrategy

logger = logging.getLogger(__name__)

# ── 常量 ───────────────────────────────────────────────────────────

DEFAULT_TIMEOUT = 30.0
SLOW_TOOL_THRESHOLD_MS = 5000
SSE_MAX_LENGTH = 2000

# 永远禁止并发的工具
NEVER_PARALLEL = frozenset({
    "clarify",
    "present_chart",
    "write_file",
})


# ── ToolResult ────────────────────────────────────────────────────


@dataclass
class ToolResult:
    """
    工具执行结果（替代 tuple[str, str]）。

    字段：
        tool_name: 工具名称
        success: 是否成功
        result: 执行结果字符串（原始，注入 LLM 上下文）
        duration_ms: 执行耗时（毫秒）
        error: 错误信息（失败时）
        attempts: 重试次数
        preview: Phase F: SSE 推送用的描述性摘要（从 Markdown 解析）
    """

    tool_name: str
    success: bool
    result: str
    duration_ms: float
    error: str | None = None
    attempts: int = 1
    preview: str | None = None

    def __repr__(self) -> str:
        status = "✓" if self.success else "✗"
        return (
            f"ToolResult({self.tool_name} {status} "
            f"({self.duration_ms:.0f}ms, attempts={self.attempts}))"
        )

    def truncate_for_sse(self, max_length: int = SSE_MAX_LENGTH) -> str:
        """
        SSE 安全截断：超长结果截断并添加省略提示。

        Args:
            max_length: 最大字符数

        Returns:
            截断后的字符串（不超过 max_length）
        """
        if len(self.result) <= max_length:
            return self.result
        return self.result[: max_length - 3] + "..."


# ── Phase F: Preview 生成 ───────────────────────────────────────────────


import re


def build_preview(tool_name: str, raw_result: str) -> str:
    """
    从工具返回的 Markdown 文本中解析统计信息，生成描述性 preview。

    策略：
    - 工具返回的是格式化 Markdown，不是 JSON
    - 从 Markdown 文本中用正则提取结构化统计字段
    - 返回一个简短描述（通常 30-100 字符），比原始数据小 10-100x

    各工具的 Markdown 格式（来自 agent_explorer）：
    - get_kline:     "...，共{num}条..."
    - tavily_search:  "**1.** title\n   来源：..."
    - get_announcement: "## 公告检索结果（共 {total} 条..."
    - get_research_report: "## 研报检索结果（共 {total} 条..."
    - get_concept_hot: "## 概念板块热度排名（...，共 {num} 条）"
    - get_market_breadth: "→ 市场情绪：**{sentiment}**，上涨家数占优"
    - neo4j_traverse: "实体「...」的直接关系（{num} 条）"
    - get_irm:       "## ...互动易（共 {total} 条..."
    - present_chart:  "图表已生成：{url}"
    - get_stock_profile: "- **主营业务**：..."
    """
    if not raw_result or not raw_result.strip():
        return f"{tool_name} 无返回结果"

    # 错误信息
    if any(raw_result.startswith(p) for p in ("K线查询失败", "联网检索失败",
                                                 "公告检索失败", "研报检索失败",
                                                 "概念板块热度查询失败", "市场宽度查询失败",
                                                 "图谱查询失败", "股票概况查询失败",
                                                 "互动易查询失败", "图表渲染失败")):
        return raw_result.split("（")[0] if "（" in raw_result else raw_result[:80]

    # get_kline: "...，共{num}条..."
    m = re.search(r"共(\d+)条", raw_result)
    if m:
        return f"查询到 {m.group(1)} 条K线数据"

    # tavily_search: "**1.** ..." 格式，计数
    count = len(re.findall(r"^\*\*\d+\.", raw_result, re.MULTILINE))
    if count > 0:
        return f"找到 {count} 篇相关文章"

    # get_announcement / get_research_report / get_irm: "（共 {num} 条，..."
    m = re.search(r"（共\s*(\d+)\s*条", raw_result)
    if m:
        label = {
            "get_announcement": "条公告",
            "get_research_report": "篇研报",
            "get_irm": "条互动易问答",
        }.get(tool_name, "条")
        return f"获取到 {m.group(1)}{label}"

    # get_concept_hot: "...（{num} 条）"
    m = re.search(r"（(\d+)\s*条）", raw_result)
    if m:
        return f"热度排名共 {m.group(1)} 个板块"

    # get_market_breadth: "→ 市场情绪：**{word}**，..."
    m = re.search(r"市场情绪[：:]*\s*\*\*([^*]+)\*\*", raw_result)
    if m:
        sentiment = m.group(1).strip()
        return f"市场情绪：{sentiment}"

    # neo4j_traverse: "实体「...」的直接关系（{num} 条）"
    m = re.search(r"的直接关系[（(](\d+)\s*条", raw_result)
    if m:
        return f"获取到 {m.group(1)} 条关系"

    # present_chart: "图表已生成：{url}"
    if "图表已生成" in raw_result:
        return "图表已生成"
    if "图表渲染失败" in raw_result:
        return "图表渲染失败"

    # get_stock_profile: 提取主营业务关键词
    m = re.search(r"主营业务[：:]*\s*([^\"\n]{4,60})", raw_result)
    if m:
        return f"主营业务：{m.group(1).strip()[:40]}"

    # 兜底：工具名 + 前50字符
    snippet = raw_result.strip()[:60].replace("\n", " ")
    return f"{tool_name}：{snippet}"


# ── 参数类型校验 ──────────────────────────────────────────────────


def _check_type(value, expected_type: str) -> bool:
    """
    判断 value 是否匹配 JSON Schema type。
    覆盖基础类型：string / integer / number / boolean / array / object。
    """
    if expected_type == "string":
        return isinstance(value, str)
    if expected_type in ("integer", "number"):
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected_type == "boolean":
        return isinstance(value, bool)
    if expected_type == "array":
        return isinstance(value, list)
    if expected_type == "object":
        return isinstance(value, dict)
    return True


# ── ToolExecutor ──────────────────────────────────────────────────


class ToolExecutor:
    """
    增强版工具执行器。

    特性：
    - ToolResult 结构化返回
    - 超时控制（asyncio.wait_for）
    - 重试机制（RetryStrategy 集成）
    - 并发执行（asyncio.gather + Semaphore）
    - SSE 安全截断

    使用方式：
        executor = ToolExecutor(tools=[...], default_timeout=30.0)
        result = await executor.execute_single("get_kline", {"ts_code": "300308.SZ"})
    """

    def __init__(
        self,
        tools: list,
        tool_configs: dict | None = None,
        default_timeout: float = DEFAULT_TIMEOUT,
        default_retry: RetryStrategy | None = None,
        max_concurrent: int = 8,
    ):
        self._tools = {t.name: t for t in tools}
        self._configs = tool_configs or {}
        self._default_timeout = default_timeout
        self._default_retry = default_retry or NoRetry()
        self._max_concurrent = max_concurrent
        self._semaphore = asyncio.Semaphore(max_concurrent)

    # ── 工具配置查询 ────────────────────────────────────────────

    def _get_tool(self, name: str):
        return self._tools.get(name)

    def _get_timeout(self, tool_name: str) -> float:
        cfg = self._configs.get(tool_name, {})
        return cfg.get("timeout", self._default_timeout)

    def _get_retry(self, tool_name: str) -> RetryStrategy:
        cfg = self._configs.get(tool_name, {})
        if "retry" in cfg:
            return cfg["retry"]
        return self._default_retry

    # ── 核心执行 ──────────────────────────────────────────────

    async def execute_single(
        self,
        tool_name: str,
        tool_args: dict,
    ) -> ToolResult:
        """
        执行单个工具（带超时和重试）。

        Args:
            tool_name: 工具名称
            tool_args: 工具参数

        Returns:
            ToolResult 结构化结果
        """
        start_time = time.perf_counter()
        tool = self._get_tool(tool_name)
        timeout = self._get_timeout(tool_name)
        retry = self._get_retry(tool_name)

        if tool is None:
            duration_ms = (time.perf_counter() - start_time) * 1000
            return ToolResult(
                tool_name=tool_name,
                success=False,
                result="",
                duration_ms=duration_ms,
                error=f"Tool '{tool_name}' not found",
            )

        # 参数校验
        if validation_error := self._validate_args(tool, tool_args):
            duration_ms = (time.perf_counter() - start_time) * 1000
            return ToolResult(
                tool_name=tool_name,
                success=False,
                result="",
                duration_ms=duration_ms,
                error=validation_error,
                attempts=1,
                preview=f"{tool_name} 参数校验失败",
            )

        attempts = 0

        async def _do_invoke() -> str:
            nonlocal attempts
            attempts += 1

            tool_fn = tool.invoke
            if asyncio.iscoroutinefunction(tool_fn):
                return await asyncio.wait_for(tool_fn(tool_args), timeout=timeout)
            else:
                return await asyncio.wait_for(
                    asyncio.to_thread(tool_fn, tool_args),
                    timeout=timeout,
                )

        try:
            raw_result = await retry.execute(_do_invoke)
            duration_ms = (time.perf_counter() - start_time) * 1000

            if duration_ms > SLOW_TOOL_THRESHOLD_MS:
                logger.warning(
                    f"[ToolExecutor] Slow tool: {tool_name} took {duration_ms:.0f}ms"
                )

            return ToolResult(
                tool_name=tool_name,
                success=True,
                result=str(raw_result) if raw_result is not None else "",
                duration_ms=duration_ms,
                attempts=attempts,
                preview=build_preview(tool_name, str(raw_result) if raw_result is not None else ""),
            )

        except asyncio.TimeoutError:
            duration_ms = (time.perf_counter() - start_time) * 1000
            logger.warning(f"[ToolExecutor] {tool_name} timed out after {timeout}s")
            return ToolResult(
                tool_name=tool_name,
                success=False,
                result="",
                duration_ms=duration_ms,
                error=f"Tool '{tool_name}' timed out after {timeout}s",
                attempts=attempts,
                preview=f"{tool_name} 执行超时",
            )

        except Exception as e:
            duration_ms = (time.perf_counter() - start_time) * 1000
            logger.error(f"[ToolExecutor] {tool_name} failed: {e}")
            return ToolResult(
                tool_name=tool_name,
                success=False,
                result=f"[{tool_name} 执行异常] {type(e).__name__}: {e}",
                duration_ms=duration_ms,
                error=str(e),
                attempts=attempts,
                preview=f"{tool_name} 执行失败",
            )

    # ── 参数校验 ──────────────────────────────────────────────

    def _validate_args(self, tool, tool_args: dict) -> str | None:
        """
        校验工具参数是否符合 schema。

        Args:
            tool: 工具实例
            tool_args: 待校验的参数

        Returns:
            None 校验通过
            str   校验失败的错误信息
        """
        get_meta = getattr(tool, "get_meta", None)
        if not get_meta:
            return None

        try:
            schema = get_meta()["function"]["parameters"]
        except Exception:
            return None

        required: list[str] = schema.get("required", [])
        for param in required:
            if param not in tool_args:
                return f"Missing required parameter: '{param}'"

        properties: dict = schema.get("properties", {})
        for param_name, param_value in tool_args.items():
            if param_name not in properties:
                continue
            expected_type = properties[param_name].get("type", "string")
            if not _check_type(param_value, expected_type):
                return (
                    f"Invalid type for '{param_name}': "
                    f"expected {expected_type}, got {type(param_value).__name__}"
                )

        return None

    # ── 批量执行 ──────────────────────────────────────────────

    def _should_parallel(self, tool_calls: list[dict]) -> bool:
        """
        判断一组 tool_calls 是否可安全并发。

        规则：
        - NEVER_PARALLEL 工具存在 → 不并发
        - 所有工具均在 SAFE_TO_PARALLEL 集合 → 可并发
        """
        names = [tc.get("name", "") for tc in tool_calls]

        # NEVER_PARALLEL 禁止
        if any(name in NEVER_PARALLEL for name in names):
            return False

        # 已知可并发工具（从工具注册表动态获取更佳，当前硬编码已知安全工具）
        # Bug #7 修复：添加 present_chart（遗漏的工具）
        SAFE_TO_PARALLEL = frozenset({
            "get_kline",
            "get_concept_hot",
            "get_market_breadth",
            "neo4j_traverse",
            "tavily_search",
            "get_stock_profile",
            "get_irm",
            "get_research_report",
            "get_announcement",
            "present_chart",  # Bug #7 修复：添加缺失的工具
        })
        if any(name not in SAFE_TO_PARALLEL for name in names):
            return False

        return True

    async def execute_batch(
        self,
        tool_calls: list[dict],
        allow_parallel: bool = True,
    ) -> list[ToolResult]:
        """
        批量执行工具调用。

        Args:
            tool_calls: [{"name": "...", "args": {...}}, ...]
            allow_parallel: 是否允许并发（False 强制串行）

        Returns:
            ToolResult 列表（顺序与 tool_calls 一致）
        """
        if not tool_calls:
            return []

        if allow_parallel and self._should_parallel(tool_calls):
            return await self._execute_parallel(tool_calls)
        else:
            return await self._execute_serial(tool_calls)

    async def _execute_parallel(self, tool_calls: list[dict]) -> list[ToolResult]:
        """并发执行所有工具"""
        logger.info(
            f"[ToolExecutor] 并发执行 {len(tool_calls)} 个工具: "
            f"{[tc['name'] for tc in tool_calls]}"
        )

        async def _with_semaphore(tc: dict) -> ToolResult:
            async with self._semaphore:
                return await self.execute_single(tc.get("name", ""), tc.get("args", {}))

        results = await asyncio.gather(
            *[_with_semaphore(tc) for tc in tool_calls],
            return_exceptions=False,
        )
        return list(results)

    async def _execute_serial(self, tool_calls: list[dict]) -> list[ToolResult]:
        """串行执行所有工具"""
        logger.info(
            f"[ToolExecutor] 串行执行 {len(tool_calls)} 个工具: "
            f"{[tc['name'] for tc in tool_calls]}"
        )
        results = []
        for tc in tool_calls:
            result = await self.execute_single(tc.get("name", ""), tc.get("args", {}))
            results.append(result)
        return results
