"""
web_fetch — Jina AI Reader 网页正文提取工具

参考 DeerFlow deerflow/community/jina_ai/tools.py:
- 使用 Jina AI 免费 Reader 端点 https://r.jina.ai/
- 直接 GET 请求即可，无需 API key
- 返回 Markdown 格式的页面正文（自动去除广告/导航）
- 支持 timeout 配置
"""
from __future__ import annotations

import logging
import urllib.parse
from typing import Annotated

import httpx
from langchain_core.tools import tool

logger = logging.getLogger(__name__)

# Jina AI Reader 端点（无需 API key）
_JINA_READER_URL = "https://r.jina.ai/"


@tool("web_fetch")
def web_fetch(
    url: Annotated[str, "要抓取的网页 URL（必须以 http:// 或 https:// 开头）"],
    timeout: Annotated[int, "超时时间（秒），默认 30"] = 30,
) -> str:
    """
    抓取网页正文内容，返回 Markdown 格式的纯净文本。

    使用 Jina AI Reader 自动去除广告、导航栏、页脚等干扰内容。
    适用于：
    - 财经新闻页面原文
    - 交易所/监管机构公告
    - 上市公司官网内容
    - 研究报告网页版

    注意：
    - 仅支持公开网页
    - 二进制内容（PDF/图片等）无法正确提取
    - 某些网站有反爬限制可能失败
    """
    try:
        # 安全检查：仅允许 http/https
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return f"错误：仅支持 http/https 协议的 URL，当前: {url}"

        headers = {
            "Accept": "text/plain",
            "User-Agent": (
                "Mozilla/5.0 (compatible; QingShuiTouYan/1.0; "
                "+https://github.com/anthropics/claude-code)"
            ),
        }

        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            response = client.get(_JINA_READER_URL + url, headers=headers, timeout=timeout)
            response.raise_for_status()

        content = response.text.strip()

        if not content:
            return f"警告：页面为空或无法提取正文内容\n\nURL: {url}"

        # 截断过长内容（防止 token 浪费）
        MAX_CHARS = 8000
        if len(content) > MAX_CHARS:
            content = content[:MAX_CHARS] + f"\n\n...（内容已截断，原文 {len(content)} 字符）"

        return f"## 网页内容\n\n**来源：** {url}\n\n{content}"

    except httpx.TimeoutException:
        return f"错误：请求超时（{timeout}秒），请稍后重试或检查 URL 是否可访问\n\nURL: {url}"
    except httpx.HTTPStatusError as e:
        logger.warning(f"[web_fetch] HTTP {e.response.status_code}: {url}")
        return f"错误：网页返回 HTTP {e.response.status_code}，可能需要登录或被禁止访问\n\nURL: {url}"
    except httpx.RequestError as e:
        logger.warning(f"[web_fetch] Request error: {e}")
        return f"错误：无法连接目标网页：{e}\n\nURL: {url}"
    except Exception as e:
        logger.warning(f"[web_fetch] Unexpected error: {e}")
        return f"错误：抓取失败 {e}\n\nURL: {url}"
