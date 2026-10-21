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
            max_retries=1,
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
            max_retries=1,
            http_client=httpx.AsyncClient(
                timeout=httpx.Timeout(60.0, connect=10.0),
                trust_env=False,
            ),
        )
    return _async_client


DEFAULT_MODEL = "MiniMax-M2.7-highspeed"  # 本地默认值，仅作 chat_async() 参数兜底


def _strip_thinking_tags(text: str) -> str:
    """移除 LLM 思考标签"""
    # 跨行标签
    text = re.sub(r"<thinking>[\s\S]*?</thinking>", "", text)
    text = re.sub(r"<context>[\s\S]*?</context>", "", text)
    text = re.sub(r"<reflection>[\s\S]*?</reflection>", "", text)
    # 单行思考:  thinking xxx -->
    text = re.sub(r" thinking[\s\S]*?-->", "", text)
    return text.strip()


def _disable_thinking(kwargs: dict, *, force: bool = False) -> None:
    """按后端类型关闭推理模型的 thinking，就地写入 kwargs。

    各后端关思考的协议不同，必须分别处理（写错等于没关，模型会持续吐思考链，
    长文本下直接耗尽 180s 超时——实测 Qwen3.6 未关 16.7s vs 关闭 1.19s）：
      · DeepSeek / MiniMax / pjlab 网关：extra_body["thinking"] = {"type": "disabled"}
      · vLLM（Qwen 系等）：chat_template_kwargs["enable_thinking"] = False

    触发条件：force=True，或显式配置 LLM_DISABLE_THINKING=true，或模型名命中已知推理模型。
    """
    from app.config import settings

    model = str(kwargs.get("model") or "").lower()
    if not (
        force
        or getattr(settings, "llm_disable_thinking", False)
        or "deepseek" in model
        or "minimax" in model
    ):
        return

    base_url = str(getattr(settings, "llm_base_url", "") or "").lower()
    # openai SDK 只接受 extra_body 里的未知字段；vLLM 侧再从 extra_body 展开到请求体
    if "vllm" in base_url or "qwen" in model:
        kwargs["extra_body"] = {"chat_template_kwargs": {"enable_thinking": False}}
    else:
        kwargs["extra_body"] = {"thinking": {"type": "disabled"}}



async def chat_async(
    prompt: str,
    model: str | None = None,
    temperature: float = 0.1,
    timeout: int = 180,
    thinking: bool = False,
    max_tokens: int | None = None,
    stream: bool = False,
    force_disable_thinking: bool = False,
) -> str:
    """Async LLM 调用 — 不阻塞事件循环

    stream=True：用流式请求累计 delta 返回。网关（pjlab nginx）60s 超时只掐
    「无数据返回」的请求，流式下 token 持续到达即可超过该限制，适合长文本抽取。
    """
    from app.config import settings

    client = await get_async_llm_client()
    kwargs: dict = {
        "model": model or settings.llm_model or DEFAULT_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
        "timeout": timeout,
    }
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens
    # 推理模型默认开启 thinking，不显式关闭会输出思考文字污染 JSON，且长文本下
    # 思考链会耗尽超时（实测 Qwen3.6 未关思考 16.7s vs 关闭 1.19s，约 14 倍差距）
    # force_disable_thinking 只给必须拿到干净 JSON 的调用（signal 研究推导）。
    _disable_thinking(kwargs, force=force_disable_thinking)
    if stream:
        kwargs["stream"] = True
        chunks: list[str] = []
        stream_resp = await client.chat.completions.create(**kwargs)
        # 总超时兜底：minimax thinking 泄漏会持续吐 token 导致流式永不结束，
        # httpx 的 read timeout 只掐「无数据」，掐不住「一直有 thinking 数据」。
        import time as _stream_time
        _stream_start = _stream_time.monotonic()
        async for chunk in stream_resp:
            if _stream_time.monotonic() - _stream_start > timeout:
                raise TimeoutError(f"LLM stream total timeout {timeout}s")
            if chunk.choices:
                delta = chunk.choices[0].delta.content
                if delta:
                    chunks.append(delta)
        content = "".join(chunks)
        return _strip_thinking_tags(content)
    response = await client.chat.completions.create(**kwargs)
    content = response.choices[0].message.content or ""
    return _strip_thinking_tags(content)


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


# ═══════════════════════════════════════════════════════════════════════════
# 模型可用性自动回退 resolver
#  用途：当某模型被网关以 403 model_not_available 拒绝时，重新拉取 /v1/models
#        可用列表，按偏好（主模型 → fallback_order 子串 → 任选）挑一个可用模型
#        作为运行时替换；替换结果带 TTL，超时后重新探测，主模型恢复即切回。
#  只在真的撞到 403 时才拉列表，正常路径零额外开销。
# ═══════════════════════════════════════════════════════════════════════════
import asyncio as _asyncio
import time as _time
from typing import Optional

# —— 进程级状态（单 key 单进程，均可用模块变量）——
_effective_model: Optional[str] = None        # 当前实际生效的模型名（None=用主模型）
_effective_set_at: float = 0.0                # 切换时间戳（用于 TTL 回探主模型）
_unavailable_models: set[str] = set()         # 已知 403 的模型，选择时排除
_available_cache: Optional[list[str]] = None  # 最近一次 /models 列表
_available_ts: float = 0.0
_models_lock = _asyncio.Lock()                # 防并发拉取打爆网关


async def fetch_available_models_async(force: bool = False) -> list[str]:
    """拉取网关可用模型 id 列表。失败时返回空表（调用方应回退到主模型，维持原状）。"""
    from app.config import settings

    global _available_cache, _available_ts
    if (
        not force
        and _available_cache is not None
        and _time.monotonic() - _available_ts < settings.llm_model_list_cache_ttl
    ):
        return list(_available_cache)

    async with _models_lock:
        # 双检锁
        if (
            not force
            and _available_cache is not None
            and _time.monotonic() - _available_ts < settings.llm_model_list_cache_ttl
        ):
            return list(_available_cache)
        base = (settings.llm_base_url or "").rstrip("/")
        if not base:
            return []
        try:
            async with httpx.AsyncClient(timeout=10.0, trust_env=False) as client:
                r = await client.get(
                    f"{base}/models",
                    headers={"Authorization": f"Bearer {settings.llm_api_key}"},
                )
                if r.status_code != 200:
                    return list(_available_cache or [])
                data = r.json()
                ids = [m.get("id") for m in data.get("data", []) if m.get("id")]
                _available_cache = ids
                _available_ts = _time.monotonic()
                return ids
        except Exception:
            # 网络/网关抖动：保留旧缓存，避免每次 403 都死磕
            return list(_available_cache or [])


def _pick_available_model(available: list[str]) -> Optional[str]:
    """按 主模型 → fallback_order 子串 → 任选 顺序挑选可用模型，排除已知 403 的。"""
    from app.config import settings

    primary = settings.llm_extraction_model
    usable = [m for m in available if m not in _unavailable_models]
    if not usable:
        return None
    # 1) 主模型可用（且未被标记坏）→ 直接返回
    if primary in usable:
        return primary
    # 2) 按 fallback_order 子串依次匹配
    order = settings.llm_extraction_fallback_order or "*"
    for token in (part.strip() for part in order.split(",")):
        if not token:
            continue
        if token == "*":
            return usable[0]
        hit = next((m for m in usable if token.lower() in m.lower()), None)
        if hit:
            return hit
    # 3) 兜底：任一可用
    return usable[0]


async def get_extraction_model(force_refresh: bool = False) -> str:
    """返回当前抽取应使用的模型名。

    - 未发生 403 时：返回主模型 settings.llm_extraction_model（零网络开销）。
    - 已切换到回退模型且未超 TTL：返回回退模型。
    - TTL 过期：重新探测；主模型若恢复可用则切回主模型。
    """
    from app.config import settings

    global _effective_model, _effective_set_at
    primary = settings.llm_extraction_model
    # 无替换在册，或替换已过期 → 主模型可用即用主模型
    if _effective_model is None or (
        _time.monotonic() - _effective_set_at > settings.llm_extraction_model_ttl
    ):
        if primary not in _unavailable_models:
            return primary
        # 主模型被标记坏且替换过期：重查可用列表决定是否仍不可用
        avail = await fetch_available_models_async(force=force_refresh)
        if primary in avail:
            _unavailable_models.discard(primary)
            return primary

    eff = _effective_model
    if eff is not None and eff not in _unavailable_models:
        return eff

    # 当前替换已失效 → 重选
    avail = await fetch_available_models_async(force=True)
    chosen = _pick_available_model(avail)
    if chosen is not None:
        _effective_model = chosen
        _effective_set_at = _time.monotonic()
        return chosen
    # 实在挑不出：退回主模型（宁可用原模型报错，也别默默换到不合适的）
    return primary


async def mark_extraction_model_unavailable(model: str) -> Optional[str]:
    """主模型/当前模型被 403 model_not_available 拒绝时调用：
    标记其不可用 → 重新拉取可用列表 → 返回一个替换模型（或 None）。

    返回的替换模型已缓存为进程级"当前生效模型"，供后续 chunk 复用。
    """
    global _effective_model, _effective_set_at
    _unavailable_models.add(model)
    avail = await fetch_available_models_async(force=True)
    chosen = _pick_available_model(avail)
    if chosen is None:
        return None
    _effective_model = chosen
    _effective_set_at = _time.monotonic()
    if chosen != model:
        import logging

        logging.getLogger(__name__).warning(
            "模型 %s 不可用，抽取自动切换至 %s（可用=%d 个）", model, chosen, len(avail)
        )
    return chosen
