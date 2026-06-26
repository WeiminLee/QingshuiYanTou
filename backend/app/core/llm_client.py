"""
LLM 客户端

统一接入 litellm 代理（http://localhost:4000/v1）
OpenAI 兼容接口，支持 minimax2.5 / kimi-k2.5 / MiniMax-M2.7-highspeed
"""

import re

import httpx
from openai import OpenAI

# 优先从 settings 读取（settings 已在启动时校验 .env 完整性）
# 避免在模块加载时抛 KeyError
_client: OpenAI | None = None
_async_client: OpenAI | None = None


def get_llm_client() -> OpenAI:
    global _client
    if _client is None:
        from app.config import settings

        # 配置连接超时（10秒）和读取超时（60秒）
        _client = OpenAI(
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            http_client=httpx.Client(
                timeout=httpx.Timeout(60.0, connect=10.0),
                trust_env=False,
            ),
        )
    return _client


async def get_async_llm_client():
    """Async LLM client — 使用 AsyncOpenAI，不阻塞事件循环"""
    global _async_client
    if _async_client is None:
        from openai import AsyncOpenAI

        from app.config import settings

        # 配置连接超时（10秒）和读取超时（60秒）
        _async_client = AsyncOpenAI(
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            http_client=httpx.AsyncClient(
                timeout=httpx.Timeout(60.0, connect=10.0),
                trust_env=False,
            ),
        )
    return _async_client


DEFAULT_MODEL = "MiniMax-M2.7-highspeed"  # 本地默认值，仅作 chat() 参数兜底


def _strip_thinking_tags(text: str) -> str:
    """移除 LLM 思考标签"""
    # 跨行标签
    text = re.sub(r"<thinking>[\s\S]*?</thinking>", "", text)
    text = re.sub(r"<context>[\s\S]*?</context>", "", text)
    text = re.sub(r"<reflection>[\s\S]*?</reflection>", "", text)
    # 单行思考: <think> xxx -->
    text = re.sub(r"<think>[\s\S]*?-->", "", text)
    return text.strip()


async def chat_async(
    prompt: str,
    model: str | None = None,
    temperature: float = 0.1,
    timeout: int = 180,
) -> str:
    """Async LLM 调用 — 不阻塞事件循环"""
    from app.config import settings

    client = await get_async_llm_client()
    response = await client.chat.completions.create(
        model=model or settings.llm_model or DEFAULT_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
        timeout=timeout,
    )
    return response.choices[0].message.content or ""


async def chat_async_stream_with_tools(
    messages: list[dict],
    tools: list[dict] | None,
    model: str | None = None,
    temperature: float = 0.1,
    timeout: int = 180,
):
    """
    Async LLM 流式调用（支持 function calling）。

    配合 SSE 推送，实现打字机效果。
    当模型返回 tool_calls 时，流结束后 yield 一次 tool_calls 信息。

    Args:
        messages: [{"role": "system"/"user"/"assistant", "content": str}, ...]
        tools: OpenAI tools schema 列表
        model/temperature/timeout: 同 chat_async_stream

    Yields:
        str: 每个 delta token
        dict: {"__tool_calls__": [(name, arguments_str), ...]}  仅在有 tool_calls 时 yield 一次
    """
    from app.config import settings

    client = await get_async_llm_client()
    kwargs: dict = {
        "model": model or settings.llm_model or DEFAULT_MODEL,
        "messages": messages,
        "temperature": temperature,
        "timeout": timeout,
        "stream": True,
    }
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"

    stream = await client.chat.completions.create(**kwargs)
    response_text = ""

    # 收集 tool_calls：arguments 可能分多个 chunk 到达
    tool_calls_buf: list[tuple[str, str]] = []  # [(name, accumulated_arguments_str), ...]
    current_tc: dict[int, dict] = {}  # index → {name, arguments_str}

    async for chunk in stream:
        delta = chunk.choices[0].delta.content
        if delta:
            response_text += delta
            yield delta

        if chunk.choices[0].delta.tool_calls:
            for tc_delta in chunk.choices[0].delta.tool_calls:
                idx = tc_delta.index
                if tc_delta.function:
                    if idx not in current_tc:
                        current_tc[idx] = {"name": "", "arguments_str": ""}
                    if tc_delta.function.name:
                        current_tc[idx]["name"] = tc_delta.function.name
                    if tc_delta.function.arguments:
                        current_tc[idx]["arguments_str"] += tc_delta.function.arguments

    # 流结束后，如果有 tool_calls 则一次性 yield
    if current_tc:
        tool_calls_buf = [(entry["name"], entry["arguments_str"]) for _, entry in sorted(current_tc.items())]
        yield {"__tool_calls__": tool_calls_buf}


# 同步版本（供非 async 上下文使用，如 kg_extractor 等）
def chat(
    prompt: str,
    model: str | None = None,
    temperature: float = 0.1,
    timeout: int = 180,
) -> str:
    from app.config import settings

    client = get_llm_client()
    response = client.chat.completions.create(
        model=model or settings.llm_model or DEFAULT_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
        timeout=timeout,
    )
    return response.choices[0].message.content or ""


def chat_json(
    prompt: str,
    model: str | None = None,
    temperature: float = 0.1,
    timeout: int = 180,
) -> dict:
    text = chat(prompt, model=model, temperature=temperature, timeout=timeout)
    text = _strip_thinking_tags(text)

    # 尝试多种 JSON 提取方式
    for extract_fn in [
        _extract_json_from_code_block,
        _extract_json_naked,
    ]:
        result = extract_fn(text)
        if result is not None:
            return result

    raise ValueError(f"LLM 返回非 JSON 内容: {text[:300]}")


def _extract_json_from_code_block(text: str) -> dict | None:
    """从 markdown 代码块中提取 JSON"""
    import json

    for marker in ["```json\n", "```json", "```\n", "```"]:
        start = text.find(marker)
        if start == -1:
            continue
        start += len(marker)
        end = text.find("```", start)
        if end == -1:
            continue
        try:
            return json.loads(text[start:end].strip())
        except json.JSONDecodeError:
            continue
    return None


def _extract_json_naked(text: str) -> dict | None:
    """尝试将整个文本作为 JSON 解析"""
    import json

    text = text.strip()
    # 去掉开头的空白和可能的描述文字
    # 找第一个 { 和最后一个 }
    start = text.find("{")
    if start == -1:
        return None
    end = text.rfind("}")
    if end == -1 or end <= start:
        return None
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None


# ── Function Calling ───────────────────────────────────────────────


class ToolCall:
    """结构化的工具调用对象"""

    def __init__(self, name: str, arguments: dict, id: str = ""):
        self.name = name
        self.arguments = arguments
        self.id = id


# ── 带重试机制的 LLM 调用 ──────────────────────────────────────────────

# 默认 LLM 重试策略
# 参考 hermes-agent 的 ExponentialBackoff 模式
DEFAULT_LLM_RETRY_EXCEPTIONS = (
    httpx.ConnectError,
    httpx.TimeoutException,
    httpx.HTTPStatusError,  # 5xx 错误
    httpx.RemoteProtocolError,
)


async def chat_async_with_retry(
    prompt: str,
    model: str | None = None,
    temperature: float = 0.1,
    timeout: int = 180,
    max_attempts: int = 3,
    base_delay: float = 2.0,
    max_delay: float = 60.0,
) -> str:
    """
    带重试机制的异步 LLM 调用。

    重试策略：
    - 指数退避 + 解相关抖动
    - max_attempts=3（总共最多 3 次）
    - base_delay=2.0s, max_delay=60.0s
    - 仅重试连接/超时/5xx 错误

    Args:
        prompt: 输入文本
        model: 模型名称
        temperature: 温度参数
        timeout: 单次调用超时
        max_attempts: 最大尝试次数
        base_delay: 首次重试延迟
        max_delay: 最大延迟

    Returns:
        LLM 返回的文本

    Raises:
        最后一次失败的异常（超过 max_attempts）
    """
    from app.core.retry import ExponentialBackoff

    retry_strategy = ExponentialBackoff(
        max_attempts=max_attempts,
        base_delay=base_delay,
        max_delay=max_delay,
        jitter=True,
        retryable_exceptions=DEFAULT_LLM_RETRY_EXCEPTIONS,
    )

    async def _call():
        return await chat_async(prompt, model=model, temperature=temperature, timeout=timeout)

    return await retry_strategy.execute(_call)


def chat_with_retry(
    prompt: str,
    model: str | None = None,
    temperature: float = 0.1,
    timeout: int = 180,
    max_attempts: int = 3,
    base_delay: float = 2.0,
    max_delay: float = 60.0,
) -> str:
    """
    带重试机制的同步 LLM 调用。

    调用方如处于 async 上下文，请直接使用 chat_async_with_retry()。

    重试策略：
    - 指数退避 + 解相关抖动
    - max_attempts=3（总共最多 3 次）
    - base_delay=2.0s, max_delay=60.0s
    - 仅重试连接/超时/5xx 错误

    Args:
        prompt: 输入文本
        model: 模型名称
        temperature: 温度参数
        timeout: 单次调用超时
        max_attempts: 最大尝试次数
        base_delay: 首次重试延迟
        max_delay: 最大延迟

    Returns:
        LLM 返回的文本

    Raises:
        最后一次失败的异常（超过 max_attempts）
    """
    import asyncio

    return asyncio.run(
        chat_async_with_retry(
            prompt,
            model=model,
            temperature=temperature,
            timeout=timeout,
            max_attempts=max_attempts,
            base_delay=base_delay,
            max_delay=max_delay,
        )
    )


def chat_json_with_retry(
    prompt: str,
    model: str | None = None,
    temperature: float = 0.1,
    timeout: int = 180,
    max_attempts: int = 3,
) -> dict:
    """
    带重试机制的 JSON LLM 调用。

    Args:
        同 chat_with_retry

    Returns:
        解析后的 JSON dict

    Raises:
        ValueError: JSON 解析失败
        其他异常: LLM 调用失败
    """
    text = chat_with_retry(prompt, model=model, temperature=temperature, timeout=timeout, max_attempts=max_attempts)
    text = _strip_thinking_tags(text)

    for extract_fn in [_extract_json_from_code_block, _extract_json_naked]:
        result = extract_fn(text)
        if result is not None:
            return result

    raise ValueError(f"LLM 返回非 JSON 内容: {text[:300]}")
