"""
Tavily Search Tool — 联网实时检索
"""

import asyncio
import logging
from typing import Annotated

import httpx
from langchain_core.tools import tool

logger = logging.getLogger(__name__)


@tool("tavily_search")
def tavily_search(
    query: Annotated[str, "搜索关键词（中文，支持复合词）"],
    max_results: Annotated[int, "最大返回结果数，默认5条，最多10条"] = 5,
    days: Annotated[int, "时间范围（天），默认30天"] = 30,
) -> str:
    """联网搜索实时市场信息、新闻、政策动态。使用中文关键词搜索，返回结构化结果。输入搜索词和日期范围，返回相关资讯列表。"""
    try:
        asyncio.get_running_loop()
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor() as pool:
            fut = pool.submit(asyncio.run, _asearch(query, max_results, days))
            return fut.result()
    except RuntimeError:
        return asyncio.run(_asearch(query, max_results, days))


async def _asearch(query: str, max_results: int, days: int) -> str:
    try:
        from app.config import settings

        max_results = min(max_results, 10)
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": settings.tavily_api_key,
                    "query": query,
                    "max_results": max_results,
                    "days": days,
                    "include_answer": True,
                },
            )
            response.raise_for_status()
            data = response.json()

        results = data.get("results", [])
        if not results:
            answer = data.get("answer", "")
            return f"未找到「{query}」的相关结果。{answer}" if answer else f"未找到「{query}」的相关结果。"

        lines = [f"## 联网检索：「{query}」\n\n"]
        for i, r in enumerate(results, 1):
            title = r.get("title", "无标题")
            url = r.get("url", "")
            snippet = r.get("content", "")[:200]
            lines.append(f"**{i}. {title}**\n   {snippet}...\n   来源：[{url}]({url})\n\n")

        answer = data.get("answer")
        if answer:
            lines.append(f"**AI 摘要：**\n{answer}\n")

        return "".join(lines)
    except Exception as e:
        logger.warning(f"[TavilySearchTool] failed: {e}")
        return f"联网检索失败：{e}"
