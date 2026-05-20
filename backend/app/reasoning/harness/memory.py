"""
MemoryManager — 防抖队列 + LLM 摘要

参考 DeerFlow agents/memory/ 的三层架构：
  MemoryUpdateQueue（防抖队列）
  → MemoryUpdater（LLM summarization）
  → MongoDB 持久化

三层设计：
  1. MemoryMiddleware（触发层）：工具调用后触发写入
  2. MemoryUpdateQueue（队列层）：线程安全队列 + 防抖窗口
  3. MemoryUpdater（LLM 层）：批量 summarization → 写入 MongoDB
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)

COLLECTION = "agent_memory"

# ── 防抖配置 ───────────────────────────────────────────────────────────────

DEFAULT_DEBOUNCE_SECONDS = 5.0  # 防抖窗口（秒）
DEFAULT_BATCH_SIZE       = 5     # 批量处理的会话数
DEFAULT_SUMMARY_MAX_TOKENS = 500


# ── MemoryUpdateQueue ───────────────────────────────────────────────────

@dataclass
class MemoryContext:
    """记忆更新上下文"""
    thread_id: str
    agent_name: str | None
    messages: list[dict]  # 原始对话消息
    enqueued_at: float = field(default_factory=time.time)


class MemoryUpdateQueue:
    """
    线程安全的记忆更新队列（防抖设计）。

    防抖策略（DeerFlow 模型）：
      同一 thread_id 的多次更新在 5s 窗口内合并为一次。
      窗口结束后批量处理所有待处理的会话。

    用法：
        queue = MemoryUpdateQueue(updater=MemoryUpdater())
        queue.start()
        # 工具调用后：
        queue.add(thread_id, agent_name, filtered_messages)
        # 退出时：
        queue.stop()
    """

    def __init__(
        self,
        updater: "MemoryUpdater",
        debounce_seconds: float = DEFAULT_DEBOUNCE_SECONDS,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ):
        self._updater = updater
        self._debounce = debounce_seconds
        self._batch_size = batch_size
        self._queue: list[MemoryContext] = []
        self._lock = threading.RLock()
        self._timer: threading.Timer | None = None
        self._running = False
        self._last_flush: float = time.time()

    def add(
        self,
        thread_id: str,
        agent_name: str | None,
        messages: list[dict],
    ) -> None:
        """
        添加记忆更新请求。

        去重：同一 thread_id 只保留最新请求。
        """
        with self._lock:
            # 去重：移除同一 thread_id 的旧请求
            self._queue = [
                ctx for ctx in self._queue if ctx.thread_id != thread_id
            ]
            self._queue.append(MemoryContext(
                thread_id=thread_id,
                agent_name=agent_name,
                messages=messages,
            ))
            self._reset_timer()

    def _reset_timer(self) -> None:
        """重置防抖计时器"""
        if self._timer is not None:
            self._timer.cancel()
        self._timer = threading.Timer(self._debounce, self._flush)
        self._timer.daemon = True
        self._timer.start()

    def _flush(self) -> None:
        """防抖窗口结束后，批量处理所有待处理会话"""
        with self._lock:
            if not self._queue:
                return
            contexts = self._queue[: self._batch_size]
            self._queue = self._queue[self._batch_size:]
            self._last_flush = time.time()

        # 在独立线程中执行（不阻塞 Agent 主流程）
        t = threading.Thread(target=self._process_batch, args=(contexts,), daemon=True)
        t.start()

    def _process_batch(self, contexts: list[MemoryContext]) -> None:
        """批量处理会话（在独立线程中）"""
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self._process_batch_async(contexts))
            loop.close()
        except Exception as e:
            logger.warning(f"[MemoryQueue] Batch process failed: {e}")

    async def _process_batch_async(self, contexts: list[MemoryContext]) -> None:
        """批量处理（异步）"""
        for ctx in contexts:
            try:
                await self._updater.update(ctx.thread_id, ctx.agent_name, ctx.messages)
            except Exception as e:
                logger.warning(
                    f"[MemoryQueue] Failed to update memory "
                    f"for thread={ctx.thread_id}: {e}"
                )

    def stop(self) -> None:
        """停止队列处理（session 结束时调用）"""
        self._running = False
        if self._timer:
            self._timer.cancel()
            self._timer = None
        # 处理剩余项
        with self._lock:
            if self._queue:
                contexts = list(self._queue)
                self._queue.clear()
        if contexts:
            self._process_batch(contexts)


# ── MemoryUpdater ────────────────────────────────────────────────────────

MEMORY_UPDATE_PROMPT = """你是一个记忆整理助手。

给定一段对话历史和当前记忆，请更新记忆内容。

当前记忆：
{current_memory}

对话历史：
{conversation}

要求：
1. 提取对话中的关键事实（公司名、产品、指标、事件）
2. 保留已确认的事实，追加新事实
3. 如果发现矛盾，保留分歧
4. 只保留与投资研究相关的信息
5. 输出格式为分层 JSON：
{{"workContext": {{"summary": "用户当前关注...（1-2句话）", "updatedAt": "ISO时间戳"}},
 "topOfMind": {{"summary": "高频提及：X（Y次），Z（W次）", "updatedAt": "ISO时间戳"}},
 "facts": [{{"content": "...", "category": "financial/industry/personal", "confidence": 0.0-1.0, "source": "来源"}}]}}

- workContext: 用户当前分析的核心主题和目标
- topOfMind: 本次对话中反复提及的高频实体
- facts: 带置信度和分类的关键事实
- confidence: 0.0-1.0，有明确数据来源≥0.8，主观判断≤0.6
- category: financial（财务数据）/ industry（行业动态）/ personal（用户偏好）

JSON 输出：
"""


class MemoryUpdater:
    """
    LLM 驱动的记忆更新器。

    流程：
      1. 获取当前记忆
      2. 格式化对话历史
      3. 调用 LLM 生成更新（轻量模型）
      4. 解析 JSON 并更新 MongoDB
    """

    def __init__(
        self,
        llm_model: str = "minimax2.5",
        max_tokens: int = DEFAULT_SUMMARY_MAX_TOKENS,
    ):
        self._llm_model = llm_model
        self._max_tokens = max_tokens

    async def update(
        self,
        thread_id: str,
        agent_name: str | None,
        messages: list[dict],
    ) -> None:
        """执行一次记忆更新"""
        if not messages:
            return

        # 过滤消息（只保留用户输入 + 最终 AI 回复）
        filtered = self._filter_messages(messages)
        if not filtered:
            return

        # 格式化对话
        conversation = self._format_conversation(filtered)

        # 获取当前记忆
        current = await self._get_current_memory(thread_id, agent_name)

        # 调用 LLM 更新
        work_context = None
        top_of_mind = None
        try:
            import json
            prompt = MEMORY_UPDATE_PROMPT.format(
                current_memory=json.dumps(current, ensure_ascii=False),
                conversation=conversation,
            )
            from app.core.llm_client import chat
            response = chat(prompt, model=self._llm_model, temperature=0.1, timeout=30)
            update_data = json.loads(response)
            facts = update_data.get("facts", [])
            work_context = update_data.get("workContext")
            top_of_mind = update_data.get("topOfMind")
        except Exception as e:
            logger.warning(f"[MemoryUpdater] LLM update failed: {e}, falling back to simple append")
            facts = self._simple_extract(filtered)

        # 写入 MongoDB
        await self._write_memory(
            thread_id,
            agent_name,
            facts,
            work_context=work_context,
            top_of_mind=top_of_mind,
        )

    def _filter_messages(self, messages: list[dict]) -> list[dict]:
        """只保留用户输入和最终 AI 回复"""
        result = []
        for m in messages:
            role = m.get("role", "")
            content = m.get("content", "")
            if role in ("user", "assistant") and content:
                result.append({"role": role, "content": content[:500]})  # 截断
        return result

    def _format_conversation(self, messages: list[dict]) -> str:
        """格式化对话为文本"""
        lines = []
        for m in messages:
            role = "用户" if m["role"] == "user" else "AI"
            lines.append(f"{role}：{m['content'][:200]}")
        return "\n".join(lines)

    async def _get_current_memory(self, thread_id: str, agent_name: str | None) -> dict:
        """获取当前记忆"""
        try:
            from app.core.mongodb import get_mongo_db
            db = get_mongo_db()
            coll = db[COLLECTION]
            doc = await coll.find_one({
                "thread_id": thread_id,
                "agent_name": agent_name,
            })
            return doc if doc else {}
        except Exception as e:
            logger.warning("读取记忆失败 [%s/%s]: %s", thread_id, agent_name, e)
            return {}

    async def _write_memory(
        self,
        thread_id: str,
        agent_name: str | None,
        facts: list[dict],
        work_context: dict | None = None,
        top_of_mind: dict | None = None,
    ) -> None:
        """写入分层记忆到 MongoDB（workContext / topOfMind / facts）"""
        from datetime import datetime
        now = datetime.now().isoformat()
        try:
            from app.core.mongodb import get_mongo_db
            db = get_mongo_db()
            coll = db[COLLECTION]

            update_doc: dict = {
                "facts": facts,
                "updatedAt": now,
            }
            if work_context:
                update_doc["workContext"] = work_context
            if top_of_mind:
                update_doc["topOfMind"] = top_of_mind

            await coll.update_one(
                {"thread_id": thread_id, "agent_name": agent_name},
                {"$set": update_doc},
                upsert=True,
            )
            logger.info(
                f"[MemoryUpdater] Written {len(facts)} facts "
                f"for thread={thread_id}, agent={agent_name}"
            )
        except Exception as e:
            logger.warning(f"[MemoryUpdater] Write failed: {e}")

    def _simple_extract(self, messages: list[dict]) -> list[dict]:
        """降级方案：简单提取关键句"""
        facts = []
        for m in messages:
            content = m["content"]
            if len(content) > 10:
                facts.append({
                    "content": content[:200],
                    "category": "fact",
                    "confidence": 0.5,  # 降级路径默认中等置信度
                })
        return facts[:20]  # 最多 20 条


# ── MemoryManager ─────────────────────────────────────────────────────

class MemoryManager:
    """
    记忆管理器。

    封装防抖队列 + LLM 更新器，提供简洁接口。

    用法：
        manager = MemoryManager()
        manager.start()
        # 工具调用后：
        manager.update(thread_id, agent_name, messages)
        # 退出：
        manager.stop()
    """

    def __init__(
        self,
        debounce_seconds: float = DEFAULT_DEBOUNCE_SECONDS,
        llm_model: str = "minimax2.5",
    ):
        self._updater = MemoryUpdater(llm_model=llm_model)
        self._queue = MemoryUpdateQueue(self._updater, debounce_seconds=debounce_seconds)

    def start(self) -> None:
        self._queue._running = True

    def stop(self) -> None:
        self._queue.stop()

    def update(
        self,
        thread_id: str,
        agent_name: str | None,
        messages: list[dict],
    ) -> None:
        """触发记忆更新（有防抖）"""
        self._queue.add(thread_id, agent_name, messages)

    def flush(self) -> None:
        """立即刷新队列（session 结束时调用）"""
        self._queue._flush()


# ── KG Anchor ────────────────────────────────────────────────────────────────
# 轻量级追踪：会话中频繁提到的实体（Company / Product / Metric）
# 用于注入 System Prompt，帮助 Agent 保持上下文焦点
# 不同于记忆 facts，KG Anchor 记录实体被提及的次数（mention_count）


KG_COLLECTION = "kg_anchors"


async def get_kg_anchors(thread_id: str, top_k: int = 10, analyst_id: str = "default") -> list[dict]:
    """
    获取会话中高频提及的实体（KG Anchor）。

    用于 System Prompt 注入，格式：
      - 中际旭创（Company）被提及 3 次
      - 光模块（Product）被提及 2 次
    """
    try:
        from app.core.mongodb import get_mongo_db
        db = get_mongo_db()
        coll = db[KG_COLLECTION]
        cursor = coll.find(
            {"thread_id": thread_id, "analyst_id": analyst_id},
            sort=[("mention_count", -1)],
            limit=top_k,
        )
        anchors = await cursor.to_list(length=top_k)
        return anchors
    except Exception as e:
        logger.warning("读取KG锚点失败 [%s/%s]: %s", thread_id, analyst_id, e)
        return []


async def increment_kg_anchor(
    thread_id: str,
    entity_id: str,
    entity_name: str,
    entity_type: str,  # "Company" | "Product" | "Metric"
    analyst_id: str = "default",
) -> None:
    """
    实体被提及时调用，mention_count +1。

    与 KGExtractor 的区别：
      - KGExtractor 抽取的是知识图谱中的客观实体关系
      - KG Anchor 追踪的是本次会话中主观高频提及的实体
    """
    try:
        from app.core.mongodb import get_mongo_db
        from datetime import datetime
        db = get_mongo_db()
        coll = db[KG_COLLECTION]
        await coll.update_one(
            {"thread_id": thread_id, "entity_id": entity_id, "analyst_id": analyst_id},
            {
                "$inc": {"mention_count": 1},
                "$set": {
                    "entity_name": entity_name,
                    "entity_type": entity_type,
                    "analyst_id": analyst_id,
                    "last_mentioned": datetime.now().isoformat(),
                },
            },
            upsert=True,
        )
    except Exception as e:
        logger.warning(f"[KGAnchor] increment failed: {e}")


def format_kg_anchors_for_prompt(thread_id: str, analyst_id: str = "default") -> str:
    """
    同步格式化 KG Anchor 列表，用于注入 System Prompt。

    调用时创建新的事件循环，避免与 uvloop 冲突。
    """
    import asyncio
    try:
        asyncio.get_running_loop()
        # 有事件循环，用 ThreadPool
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            fut = pool.submit(asyncio.run, get_kg_anchors(thread_id, analyst_id=analyst_id))
            anchors = fut.result(timeout=10)
    except RuntimeError:
        anchors = asyncio.run(get_kg_anchors(thread_id, analyst_id=analyst_id))

    if not anchors:
        return ""

    lines = ["\n## 会话中反复提及的实体"]
    for a in anchors:
        lines.append(f"- {a['entity_name']}（{a['entity_type']}）被提及 {a['mention_count']} 次")
    return "\n".join(lines)
