"""
Token 计数器 — 精确计数 + 启发式回退

使用 tiktoken 进行模型感知的精确 token 计数，
不可用时回退到字符启发式（中文约 1.8 字符/token，英文约 4 字符/token）。
"""

import logging
import re
from functools import lru_cache

logger = logging.getLogger(__name__)

# tiktoken 为可选依赖，import 失败时走回退路径
_TIKTOKEN_AVAILABLE = False
try:
    import tiktoken

    _TIKTOKEN_AVAILABLE = True
except ImportError:
    logger.debug("tiktoken not available, falling back to heuristic token estimation")


# 中文字符范围（CJK Unified Ideographs + CJK Extension A/B 等常见范围）
_CJK_CHARS = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]")


@lru_cache(maxsize=16)
def _get_tiktoken_encoding(model_name: str | None) -> object | None:
    """获取 tiktoken encoding，按模型名缓存。

    优先匹配已知模型 → 按 encoding 家族回退 → None。
    """
    if not _TIKTOKEN_AVAILABLE:
        return None
    try:
        return tiktoken.encoding_for_model(model_name or "gpt-4o")
    except KeyError:
        pass
    try:
        # 中国模型通常兼容 cl100k_base（MiniMax、Qwen、DeepSeek 等）
        return tiktoken.get_encoding("cl100k_base")
    except Exception:
        return None


def count_tokens(
    text: str,
    model_name: str | None = None,
) -> int:
    """计算文本的 token 数。

    Args:
        text: 输入文本
        model_name: 模型名，用于选择 tiktoken encoding（默认为 None → cl100k_base）

    Returns:
        token 数
    """
    if not text:
        return 0

    encoding = _get_tiktoken_encoding(model_name)
    if encoding is not None:
        try:
            return len(encoding.encode(text, disallowed_special=()))
        except Exception as e:
            logger.debug("tiktoken encoding failed, falling back to heuristic: %s", e)

    return _heuristic_token_count(text)


def count_message_tokens(
    content: str | list | None,
    model_name: str | None = None,
) -> int:
    """计算 LangChain 消息 content 字段的 token 数。

    支持多模态消息（content 为 list[dict]），只计 type=="text" 的块。
    """
    if not content:
        return 0
    if isinstance(content, str):
        return count_tokens(content, model_name)
    if isinstance(content, list):
        total = 0
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                total += count_tokens(block.get("text", ""), model_name)
            elif isinstance(block, str):
                total += count_tokens(block, model_name)
        return total
    return count_tokens(str(content), model_name)


def count_messages_tokens(
    messages: list,
    model_name: str | None = None,
) -> int:
    """计算消息列表的总 token 数。

    Args:
        messages: LangChain 消息列表（需要 content 属性）
        model_name: 模型名

    Returns:
        所有消息 content 的 token 数之和
    """
    total = 0
    for msg in messages:
        content = getattr(msg, "content", None) or ""
        total += count_message_tokens(content, model_name)
        # 每条消息额外计入少量开销（role 标记、格式等）
        # LangChain 消息序列化通常每条加 ~3 tokens
        total += 3
    return total


def _heuristic_token_count(text: str) -> int:
    """无 tiktoken 时的启发式估算。

    估算逻辑：
    - 中文字符 ~1.8 字符/token
    - 非中文文本 ~4 字符/token
    - 空格/换行按 1 字符/token 算（对 LLM 通常是 id 级别压缩）
    """
    cjk_chars = len(_CJK_CHARS.findall(text))
    other_chars = len(text) - cjk_chars
    # CJK ≈ 1.8 chars/token，非 CJK ≈ 4 chars/token
    # whitespace 快速通道（短文本避免过度估计）
    cjk_tokens = cjk_chars / 1.8
    other_tokens = other_chars / 4.0
    return max(1, int(cjk_tokens + other_tokens + 0.5))
