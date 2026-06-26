"""
信号提取框架

架构：
- SignalExtractor: 抽象基类（定义接口）
- RuleBasedSignalExtractor: 规则实现（Phase 1，无 LLM 依赖）
- LLMSignalExtractor: LLM 实现（Phase 2，对接 Ollama/OpenAI）
"""

import logging
import re
from abc import ABC, abstractmethod
from datetime import datetime

logger = logging.getLogger(__name__)


class SignalExtractor(ABC):
    """信号提取器抽象接口"""

    @abstractmethod
    async def extract(self, text: str, source_type: str, metadata: dict) -> dict:
        """
        从文本中提取投资信号

        Args:
            text: 原始文本
            source_type: 来源类型 "qa_interactive" | "uploaded_doc"
            metadata: 附加信息 {"ts_code": ..., "ann_date": ...}

        Returns:
            {
                "signals": [{"type", "content", "gap_type", "strength", "extracted_at"}],
                "summary": str | None,
                "entities": {"concepts": [], "upstream": [], "downstream": [], "competitors": []},
                "sentiment_score": float,  # -1.0 ~ 1.0
                "method": str,
            }
        """
        raise NotImplementedError


class RuleBasedSignalExtractor(SignalExtractor):
    """
    规则化信号提取器（Phase 1 降级方案）
    不依赖任何 LLM API，纯关键词匹配
    """

    # 关键词 → 信号类型映射
    SIGNAL_PATTERNS = {
        "product_expansion": [
            "扩产",
            "新增产能",
            "新建",
            "投产",
            "量产",
            "产品线扩张",
            "新工厂",
            "产业园",
            "项目开工",
            "产能释放",
            "产能爬坡",
        ],
        "supply_chain": [
            "供应商",
            "原材料",
            "采购",
            "供应链",
            "战略合作",
            "上下游",
            "产业链整合",
            "独家供应",
            "供应商准入",
        ],
        "policy_impact": [
            "政策",
            "监管",
            "补贴",
            "税收优惠",
            "行业规划",
            "双碳",
            "碳中和",
            "碳达峰",
            "专精特新",
            "国产替代",
            "进口替代",
        ],
        "management_change": [
            "董事长",
            "总经理",
            "高管",
            "换届",
            "离职",
            "任命",
            "管理层",
            "核心技术人员",
            "首席",
            "cto",
            "ceo",
        ],
        "financial_highlight": [
            "营收增长",
            "净利润",
            "毛利率",
            "订单",
            "合同",
            "回款",
            "现金流",
            "业绩预增",
            "扭亏",
            "大幅增长",
            "超预期",
            "符合预期",
            "不及预期",
            "低于预期",
        ],
        "risk_warning": [
            "风险",
            "诉讼",
            "处罚",
            "商誉减值",
            "存货减值",
            "应收账款",
            "债务",
            "资金紧张",
            "停产",
            "召回",
        ],
    }

    SENTIMENT_WORDS_POSITIVE = [
        "增长",
        "突破",
        "创新",
        "领先",
        "扩张",
        "提升",
        "大增",
        "超预期",
        "大幅",
        "显著",
        "明显",
        "持续",
        "战略",
        "重大",
        "强劲",
        "开门红",
    ]

    SENTIMENT_WORDS_NEGATIVE = [
        "下降",
        "亏损",
        "减少",
        "下滑",
        "不及预期",
        "低于预期",
        "风险",
        "诉讼",
        "处罚",
        "停产",
        "召回",
        "商誉减值",
        "大幅下跌",
    ]

    STRONG_MARKERS = ["大幅", "显著", "明显", "持续", "战略", "重大", "强劲", "首次"]
    WEAK_MARKERS = ["略有", "小幅", "轻微", "尝试", "试产", "小批量"]

    def extract_sync(self, text: str, source_type: str, metadata: dict) -> dict:
        """同步入口（纯规则，无需 LLM，直接同步执行）"""
        # RuleBasedSignalExtractor.extract() 是纯 CPU 规则逻辑，不需要 asyncio
        text_lower = (text or "").lower()
        signals = []
        detected_types = set()

        for signal_type, keywords in self.SIGNAL_PATTERNS.items():
            for kw in keywords:
                if kw in text or kw in text_lower:
                    sentences = re.split(r"[。；！？\n,，]", text or "")
                    for sent in sentences:
                        if kw in sent and len(sent.strip()) > 5:
                            signals.append(
                                {
                                    "type": signal_type,
                                    "content": sent.strip()[:200],
                                    "gap_type": self._infer_gap_type(sent),
                                    "strength": self._infer_strength(sent, kw),
                                    "extracted_at": datetime.now().isoformat(),
                                }
                            )
                            detected_types.add(signal_type)
                            break

        seen = set()
        unique_signals = []
        for s in signals:
            key = (s["type"], s["content"][:50])
            if key not in seen:
                seen.add(key)
                unique_signals.append(s)

        sentiment_score = self._calc_sentiment(text)
        return {
            "signals": unique_signals,
            "summary": None,
            "entities": {},
            "sentiment_score": sentiment_score,
            "method": "rule_based",
            "detected_types": list(detected_types),
        }

    async def extract(self, text: str, source_type: str, metadata: dict) -> dict:
        text_lower = (text or "").lower()
        signals = []
        detected_types = set()

        for signal_type, keywords in self.SIGNAL_PATTERNS.items():
            for kw in keywords:
                if kw in text or kw in text_lower:
                    sentences = re.split(r"[。；！？\n,，]", text or "")
                    for sent in sentences:
                        if kw in sent and len(sent.strip()) > 5:
                            signals.append(
                                {
                                    "type": signal_type,
                                    "content": sent.strip()[:200],
                                    "gap_type": self._infer_gap_type(sent),
                                    "strength": self._infer_strength(sent, kw),
                                    "extracted_at": datetime.now().isoformat(),
                                }
                            )
                            detected_types.add(signal_type)
                            break  # 每种类型只取第一个匹配

        # 去重
        seen = set()
        unique_signals = []
        for s in signals:
            key = (s["type"], s["content"][:50])
            if key not in seen:
                seen.add(key)
                unique_signals.append(s)

        sentiment_score = self._calc_sentiment(text)

        return {
            "signals": unique_signals,
            "summary": None,
            "entities": {},
            "sentiment_score": sentiment_score,
            "method": "rule_based",
            "detected_types": list(detected_types),
        }

    def _infer_gap_type(self, sentence: str) -> str:
        pos = sum(1 for w in self.SENTIMENT_WORDS_POSITIVE if w in sentence)
        neg = sum(1 for w in self.SENTIMENT_WORDS_NEGATIVE if w in sentence)
        if pos > neg:
            return "positive"
        elif neg > pos:
            return "negative"
        return "neutral"

    def _infer_strength(self, sentence: str, keyword: str) -> str:
        if any(m in sentence for m in self.STRONG_MARKERS):
            return "strong"
        elif any(m in sentence for m in self.WEAK_MARKERS):
            return "weak"
        return "medium"

    def _calc_sentiment(self, text: str) -> float:
        text = text or ""
        pos = sum(1 for w in self.SENTIMENT_WORDS_POSITIVE if w in text)
        neg = sum(1 for w in self.SENTIMENT_WORDS_NEGATIVE if w in text)
        total = pos + neg
        if total == 0:
            return 0.0
        return round((pos - neg) / total, 3)


class LLMSignalExtractor(SignalExtractor):
    """
    LLM 驱动的信号提取器（Phase 2 可选）
    对接 Ollama 或 OpenAI-compatible API
    """

    def __init__(self, base_url: str | None = None, model: str = "qwen2.5:7b"):
        import os

        self.base_url = base_url or os.getenv("OLLAMA_URL", "http://localhost:11434")
        self.model = model

    async def extract(self, text: str, source_type: str, metadata: dict) -> dict:
        import httpx

        prompt = self._build_prompt(text, source_type, metadata)
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{self.base_url}/api/generate",
                    json={"model": self.model, "prompt": prompt, "stream": False},
                )
                response.raise_for_status()
                result = response.json()
                llm_text = result.get("response", "")
                return await self._parse_llm_response(llm_text)
        except Exception as e:
            logger.warning(f"LLM 调用失败，降级为规则提取: {e}")
            fallback = RuleBasedSignalExtractor()
            return await fallback.extract(text, source_type, metadata)

    def _build_prompt(self, text: str, source_type: str, metadata: dict) -> str:
        return f"""你是一个专业的投资研究分析师。请从以下文本中提取投资相关信息。

文本来源类型：{source_type}
股票代码：{metadata.get("ts_code", "未知")}
日期：{metadata.get("ann_date", "未知")}

文本内容：
{text[:3000]}

请以JSON格式输出分析结果：
{{
  "signals": [
    {{"type": "信号类型", "content": "信号内容摘要（少于50字）", "gap_type": "positive/negative/neutral", "strength": "strong/medium/weak"}}
  ],
  "summary": "文档摘要（少于200字）",
  "entities": {{"concepts": [], "upstream": [], "downstream": [], "competitors": []}},
  "sentiment_score": -1.0到1.0的情感得分
}}

只输出JSON，不要有其他内容。"""

    async def _parse_llm_response(self, llm_text: str) -> dict:
        match = re.search(r"\{.*\}", llm_text, re.DOTALL)
        if match:
            import json

            try:
                parsed = json.loads(match.group())
                parsed["method"] = "llm"
                parsed["signals"] = [
                    {**s, "extracted_at": datetime.now().isoformat()} for s in parsed.get("signals", [])
                ]
                return parsed
            except json.JSONDecodeError:
                pass
        # 解析失败，降级
        fallback = RuleBasedSignalExtractor()
        return await fallback.extract("", "", {})


# ── 信号持久化（写入 Neo4j Event 节点）─────────────────────────────────


def persist_signals_to_neo4j(
    signals_result: dict,
    ts_code: str,
    source_type: str,
    source_document_id: str = "",
) -> list[str]:
    """
    将 signal_extractor 的结果写入 Neo4j Event 节点。

    每条 signal → 一个 Event 节点，entity_id = E:{ts_code}:{date}:{hash}
    Event 节点属性：signal_type / signal_content / gap_type /
                   signal_strength / sentiment_score / source_type

    Returns:
        写入的 Event entity_id 列表

    调用场景：
      - kg_extractor.extract_text_async 返回后（Phase 31 D-C1 清理后的唯一调用路径）
    """
    import hashlib
    from datetime import date

    from app.knowledge.entity_service import upsert_event

    signals = signals_result.get("signals", [])
    if not signals:
        return []

    written_ids: list[str] = []
    today_str = date.today().strftime("%Y%m%d")

    for sig in signals:
        sig_type = sig.get("type", "unknown")
        content = sig.get("content", "")[:200]  # 截断防止过长
        gap_type = sig.get("gap_type", "neutral")
        strength = sig.get("strength", "medium")
        sentiment = signals_result.get("sentiment_score", 0.0)

        # 生成稳定的 entity_id（基于内容 hash）
        id_content = f"{ts_code}:{today_str}:{sig_type}:{content[:50]}"
        hash_suffix = hashlib.md5(id_content.encode("utf-8")).hexdigest()[:16].upper()
        entity_id = f"E:{ts_code}:{today_str}:{hash_suffix}"

        properties = {
            "signal_type": sig_type,
            "signal_content": content,
            "gap_type": gap_type,
            "signal_strength": strength,
            "sentiment_score": sentiment,
            "source_type": source_type,
            "source_document_id": source_document_id,
            "extracted_at": datetime.now().isoformat(),
        }

        try:
            _, is_new = upsert_event(
                ts_code=ts_code,
                event_date=today_str,
                event_title=f"[{sig_type}] {content[:30]}",
                source_type=source_type,
                source_name="signal_extractor",
                properties=properties,
                confidence=0.75,
            )
            written_ids.append(entity_id)
            logger.debug(
                "Signal Event 入库: %s (%s, %s)",
                entity_id,
                sig_type,
                gap_type,
            )
        except Exception as e:
            logger.warning("Signal Event 入库失败 [%s]: %s", entity_id, e)

    logger.info(
        "Signal 持久化完成: %d 条 signal → %d 个 Event 节点",
        len(signals),
        len(written_ids),
    )
    return written_ids


# ── 信号持久化（写入 Company 节点属性，替代 Event 节点）─────────────────


def persist_signals_to_company_props(
    signals_result: dict,
    ts_code: str,
    source_type: str,
    source_document_id: str = "",
) -> dict:
    """
    将信号提取结果写入 Company 节点属性（替代 Event 节点）。

    Company 节点新增属性：
      - signals:        list[str]  所有信号的 JSON 序列化数组
      - signal_types:   list[str]  信号类型去重列表
      - signal_summary: str        最新 3 条信号摘要（逗号分隔）
      - latest_signal_at: str      ISO 时间戳

    signals_result 格式（与 RuleBasedSignalExtractor.extract_sync 返回一致）：
      {
        "signals": [{"type": "...", "content": "...", "gap_type": "...", "strength": "..."}],
        "sentiment_score": 0.0,
      }

    Returns:
        写入状态 dict（写入条数 / 信号类型 / 最新摘要）
    """
    from app.core.neo4j_client import run, run_write

    signals = signals_result.get("signals", [])
    if not signals:
        return {"written": 0, "signal_types": [], "summary": ""}

    entity_id = f"C:{ts_code}"
    written_at = datetime.now().isoformat()

    # 读取现有哪些信号（避免每次追加丢失旧数据）
    existing_signals: list[dict] = []
    result = run(
        "MATCH (n:Company {entity_id: $eid}) RETURN n.signals AS signals",
        params={"eid": entity_id},
    )
    if result and result[0].get("signals"):
        import json as _json

        try:
            raw = result[0].get("signals")
            # 兼容：可能是 list[dict] 或 list[str]（JSON 字符串）
            if not raw:
                existing_signals = []
            elif isinstance(raw, list) and len(raw) > 0 and isinstance(raw[0], str):
                existing_signals = _json.loads(raw[0]) if raw else []
            elif isinstance(raw, list):
                existing_signals = list(raw)
            else:
                existing_signals = []
        except Exception:
            existing_signals = []

    # 追加新信号（带元数据）
    for sig in signals:
        existing_signals.append(
            {
                "type": sig.get("type", "unknown"),
                "content": sig.get("content", "")[:200],
                "gap_type": sig.get("gap_type", "neutral"),
                "strength": sig.get("strength", "medium"),
                "sentiment_score": signals_result.get("sentiment_score", 0.0),
                "source_type": source_type,
                "source_document_id": source_document_id,
                "written_at": written_at,
            }
        )

    # 构建去重类型列表 & 最新 3 条摘要
    signal_types = list(dict.fromkeys(s["type"] for s in existing_signals))
    recent = existing_signals[-3:]
    summary = " | ".join(f"[{s['type']}] {s['content'][:40]}" for s in recent)

    import json as _json

    signals_json = _json.dumps(existing_signals, ensure_ascii=False)

    try:
        run_write(
            "MATCH (n:Company {entity_id: $eid}) "
            "SET n.signals = $signals_json, "
            "    n.signal_types = $signal_types, "
            "    n.signal_summary = $summary, "
            "    n.latest_signal_at = $written_at",
            params={
                "eid": entity_id,
                "signals_json": signals_json,  # Neo4j 存为字符串，读取时 JSON.parse
                "signal_types": signal_types,
                "summary": summary,
                "written_at": written_at,
            },
        )
        logger.debug(
            "Company 信号写入 [%s]: %d 条，类型=%s",
            entity_id,
            len(signals),
            signal_types,
        )
        return {
            "written": len(signals),
            "signal_types": signal_types,
            "summary": summary,
        }
    except Exception as e:
        logger.warning("Company 信号写入失败 [%s]: %s", entity_id, e)
        return {"written": 0, "signal_types": [], "summary": ""}
