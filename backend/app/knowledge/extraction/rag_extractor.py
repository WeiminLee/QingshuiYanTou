"""
RAGFlow General 模式知识图谱抽取引擎

参考 RAGFlow rag/graphrag/ 架构，重构 kg_extractor.py 的核心抽取逻辑。

核心差异（相比旧版 kg_extractor.py）：
1. gleaning 循环（最多 N 轮追加抽取）
2. tuple 结构化输出（规避 JSON 解析不稳定）
3. LLM summarization 压缩同名实体描述
4. asyncio 并发控制（Semaphore）
5. 实体/关系按 (source, target) 聚合后统一

投资研究场景的实体类型（3类，2026-04-14 Schema 重构）：
  Company / Product / Metric
  （原 Tech/Industry/Capacity/Event 节点类型已废除，归入属性）

子模块：
  - extraction.rag_prompts: 提示词模板
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections import Counter, defaultdict
from collections.abc import Callable
from typing import Literal, Optional

from pydantic import BaseModel, Field

from app.core.llm_client import chat
from app.knowledge.extraction.chunker import Chunk, chunk_by_token
from app.knowledge.extraction.rag_prompts import (
    ENTITY_TYPES,
    GENERIC_NAME_RETRY_PROMPT,
    get_extraction_prompt,
)

logger = logging.getLogger(__name__)

# 合法的 entity_type 白名单（模块级常量）
VALID_ENTITY_TYPES = frozenset(ENTITY_TYPES)

# 分隔符常量
GRAPH_FIELD_SEP = "<SEP>"

# ── Pydantic 校验模型 ──────────────────────────────────────────────────────

EntityType = Literal["Company", "Product", "Metric"]


class Entity(BaseModel):
    name: str = Field(min_length=1)
    type: EntityType


class Relation(BaseModel):
    entity1: str = Field(min_length=1)
    entity2: str = Field(min_length=1)
    description: str = ""
    confidence: float = 1.0
    stmt_type: Optional[Literal["Fact", "Claim", "Estimate"]] = None
    source: str = ""
    metric_value: Optional[float] = None
    metric_unit: Optional[str] = None
    metric_period: Optional[str] = None
    metric_period_type: Optional[Literal["actual", "forecast", "quarterly", "half-year"]] = None
    metric_sentiment: Optional[Literal["positive", "negative", "neutral"]] = None


class ExtractionOutput(BaseModel):
    entities: list[Entity] = []
    relations: list[Relation] = []


# ── 泛称正则 ──────────────────────────────────────────────────────────────

GENERIC_NAME_PATTERNS = re.compile(
    r'^(公司|本行|本公司|本集团|本企业|该企业|该(公|集)司|我们|我司|我公司)$'
)


def _detect_generic_names(entities: list[dict]) -> bool:
    """检测 entities 中是否包含泛称。"""
    for e in entities:
        name = e.get("entity_name", "")
        if name and GENERIC_NAME_PATTERNS.match(name):
            return True
    return False


def _merge_descriptions_raw(descriptions: list[str]) -> str:
    """
    保留原文的多源合并（不做 LLM summarization）。
    各描述用 GRAPH_FIELD_SEP 分隔，标记来源索引。
    用于注入 properties.descriptions[] 数组。
    """
    if not descriptions:
        return ""
    seen = set()
    unique = []
    for d in descriptions:
        if d and d not in seen:
            seen.add(d)
            unique.append(d)
    return GRAPH_FIELD_SEP.join(unique)


# ── 输出解析 ────────────────────────────────────────────────────────────────


def _is_noise_entity_name(name: str) -> bool:
    value = (name or "").strip()
    if not value:
        return True
    if value in {"---", "--", "-", "###", "##", "#", "RELATES", "METRIC", "Entity", "Relation"}:
        return True
    if re.fullmatch(r"[\W_]+", value, flags=re.UNICODE):
        return True
    if re.match(r"^#{1,6}\s*", value):
        return True
    if any(marker in value for marker in ("实体列表", "关系列表", "RELATES 关系", "METRIC 指标")):
        return True
    return False


def _parse_json_output(raw_text: str) -> tuple[list[dict], list[dict]] | None:
    """解析 LLM 返回的 JSON 字符串，返回 (entities, relations) 或 None。"""
    text = raw_text.strip()
    # 尝试从 markdown 代码块中提取
    if '```json' in text:
        text = text.split('```json', 1)[1].split('```', 1)[0].strip()
    elif '```' in text:
        text = text.split('```', 1)[1].split('```', 1)[0].strip()
    elif '{' not in text:
        logger.warning("No JSON found in LLM output: %s", raw_text[:200])
        return None

    try:
        parsed = ExtractionOutput.model_validate_json(text)
    except Exception as e:
        logger.warning("JSON validation failed: %s, raw text: %s", e, text[:200])
        return None

    # 去重 entities（同名只保留第一个）
    seen = set()
    deduped_entities = []
    for e in parsed.entities:
        if e.name not in seen:
            seen.add(e.name)
            deduped_entities.append({"entity_name": e.name, "entity_type": e.type})
    entities_out = deduped_entities

    # 过滤孤立关系：entity1/entity2 必须在 entities 中
    entity_names = set(e["entity_name"] for e in entities_out)
    valid_relations = [r for r in parsed.relations if r.entity1 in entity_names and r.entity2 in entity_names]

    # 映射为下游字段 + 填充 metric 信息到对应 entity
    relations_out = []
    for r in valid_relations:
        rel = {
            "src_id": r.entity1,
            "tgt_id": r.entity2,
            "description": r.description,
            "weight": r.confidence,
            "stmt_type": r.stmt_type or "Fact",
            "source_ids": [r.source] if r.source else [],
            "keywords": "",
            "direction": "neutral",
            "instance_count": 1,
            "descriptions": [r.description] if r.description else [],
            "has_direction_conflict": False,
        }
        # 把 metric 信息拼到对应 entity 的 metric 字段
        if r.entity2 in entity_names and r.metric_value is not None:
            for e in entities_out:
                if e["entity_name"] == r.entity2 and e["entity_type"] == "Metric":
                    e.setdefault("metric", {
                        "name": r.entity2,
                        "value": r.metric_value,
                        "unit": r.metric_unit,
                        "period": r.metric_period,
                        "period_type": r.metric_period_type,
                        "sentiment": r.metric_sentiment,
                    })
                    break
        relations_out.append(rel)

    # 补全 Entity 必需字段
    for e in entities_out:
        e.setdefault("description", "")
        e.setdefault("source_ids", [])
        e.setdefault("instance_count", 1)

    return entities_out, relations_out


# ── 旧解析器（已废弃，保留空桩兼容导入）─────────────────────────────────────


def _parse_tuple_record(record: str) -> list[str]:
    """已废弃。保留空桩以避免 ImportError。"""
    logger.warning("_parse_tuple_record is deprecated")
    return []


def _normalize_llm_output_line(line: str) -> str:
    """已废弃。保留空桩以避免 ImportError。"""
    return line.strip()


def _parse_entity_relation_blocks(raw_text: str) -> tuple[dict, dict]:
    """已废弃。保留空桩以避免 ImportError。"""
    logger.warning("_parse_entity_relation_blocks is deprecated, use _parse_json_output instead")
    return {}, {}


def _parse_relates(raw_text: str) -> list[dict]:
    """已废弃。保留空桩以避免 ImportError。"""
    logger.warning("_parse_relates is deprecated, use _parse_json_output instead")
    return []


def _parse_metrics(raw_text: str) -> list[dict]:
    """已废弃。保留空桩以避免 ImportError。"""
    logger.warning("_parse_metrics is deprecated, use _parse_json_output instead")
    return []


def _parse_chunk_output(raw_text: str) -> tuple[dict, dict]:
    """已废弃，保留兼容。直接调用 _parse_json_output。"""
    logger.warning("_parse_chunk_output is deprecated, use _parse_json_output instead")
    result = _parse_json_output(raw_text)
    if result is None:
        return {}, {}
    entities, relations = result
    # 转为旧的 (nodes dict, edges dict) 格式（兼容旧调用方）
    nodes: dict = defaultdict(list)
    edges: dict = defaultdict(list)
    for e in entities:
        nodes[e["entity_name"]].append(e)
    for r in relations:
        key = (r["src_id"], r["tgt_id"])
        edges[key].append(r)
    return dict(nodes), dict(edges)


# ── LLM 调用（同步包装）───────────────────────────────────────────────────────


def _call_llm(prompt: str, timeout: int = 300) -> str:
    """同步调用 LLM，包装为 asyncio 线程调用"""
    return chat(prompt, temperature=0.1, timeout=timeout)


async def _call_llm_async(prompt: str, timeout: int = 300) -> str:
    """异步调用 LLM（通过 to_thread 桥接同步 client）"""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: _call_llm(prompt, timeout))


# ── Chunk 预过滤 ───────────────────────────────────────────────────────────────

# 预过滤正则（常驻编译）
_RE_DISCLAIMER = re.compile(
    r"(?:本报告|转载|版权|免责|风险提示|机构介绍|东北证券|中邮证券|东吴证券|国联证券|华泰证券|光大证券|中金公司|中信建投|中信证券|投资评级|投资建议|荐|维持|首次覆盖)[^\n]{0,30}?(?:仅供参考|不构成|禁止|联系|获取|报告来源)",
    re.IGNORECASE,
)
_RE_URL_EMAIL = re.compile(r"https?://|www\.|@.+\.(com|cn|net|org|edu)|/api/v\d+|http\S+")
_RE_BLANK_LINE = re.compile(r"^[\s ]{0,10}$")  # 空白/纯空格行（含不间断空格）
_RE_GIBBERISH = re.compile(r"^[^一-鿿\w]{30,}$")  # 30+连续非汉字/字母/数字


def _prefilter_chunk(content: str) -> str:
    """
    预过滤 Chunk 内容，去除表格行、声明、URL、空行等噪声。

    策略（RAG-Anything separate_content 模式简化版）：
    1. 逐行判断，保留有效行
    2. 表格行：管道符占比高 → 过滤
    3. 声明/封面/风险提示 → 过滤
    4. URL / Email / 文件路径 → 过滤
    5. 纯空白行 → 过滤
    6. 超长无意义符号串 → 过滤

    返回过滤后的文本（可能为空字符串，表示该 chunk 无有效内容可抽取）
    """
    if not content:
        return ""

    effective_lines: list[str] = []
    for raw_line in content.split("\n"):
        line = raw_line.strip()
        # 空白行 → 跳过
        if _RE_BLANK_LINE.match(line or ""):
            continue
        # URL / Email / 文件路径 → 跳过
        if _RE_URL_EMAIL.search(line):
            continue
        # 30+ 连续非汉字/字母/数字（乱码/符号碎片）→ 跳过
        if _RE_GIBBERISH.match(line):
            continue
        # 声明/封面/风险提示行 → 跳过
        if _RE_DISCLAIMER.search(line):
            continue
        # 表格行：统计管道符数量
        pipe_count = line.count("|")
        line_len = len(line)
        if pipe_count >= 3 and pipe_count / line_len > 0.25:
            continue  # 表格行（| 占比 > 25%）

        effective_lines.append(raw_line)

    return "\n".join(effective_lines)


# ── Gleaning 循环 ──────────────────────────────────────────────────────────────


async def _extract_single_chunk(
    chunk: Chunk,
    examples: list[str],
    max_gleanings: int = 0,
    semaphore: asyncio.Semaphore | None = None,
    source_file: str | None = None,
    source_type: str = "uploaded_doc",
) -> tuple[dict, dict]:
    """
    对单个 chunk 执行抽取（单次 JSON 调用 + 泛称重跑）。

    - 单次 LLM 调用（无 gleaning）
    - JSON 输出 → Pydantic 校验
    - 泛称检测 → 触发二次调用
    """
    section_title = getattr(chunk, "heading", "") or ""
    filtered_content = _prefilter_chunk(chunk.content)
    if not filtered_content.strip():
        return {}, {}

    prompt = get_extraction_prompt(source_type, section_title).format(
        input_text=filtered_content,
    )

    async def _call(prompt: str) -> str:
        if semaphore:
            async with semaphore:
                return await _call_llm_async(prompt)
        return await _call_llm_async(prompt)

    # 首轮调用
    raw = await _call(prompt)
    result = _parse_json_output(raw)

    # 首轮失败 → 重试一次
    if result is None:
        raw = await _call(prompt)
        result = _parse_json_output(raw)

    if result is None:
        return {}, {}

    entities, relations = result

    # 泛称检测 → 全量重跑
    if _detect_generic_names(entities):
        logger.info("Detected generic names, retrying with augmented prompt")
        retry_prompt = GENERIC_NAME_RETRY_PROMPT.format(input_text=filtered_content)
        raw = await _call(retry_prompt)
        result = _parse_json_output(raw)
        if result is not None:
            entities, relations = result

    # 注入 source_id
    chunk_key = source_file if source_file else f"chunk:{chunk.chunk_id}"
    for e in entities:
        e["source_id"] = chunk_key
    for r in relations:
        r["source_id"] = chunk_key

    # 转为 (nodes dict, edges dict) 格式
    nodes: dict = defaultdict(list)
    edges: dict = defaultdict(list)
    for e in entities:
        nodes[e["entity_name"]].append(e)
    for r in relations:
        key = (r["src_id"], r["tgt_id"])
        edges[key].append(r)

    return dict(nodes), dict(edges)


# ── 核心抽取器 ────────────────────────────────────────────────────────────────


class RAGExtractor:
    """
    RAGFlow General 模式抽取引擎。

    流程：
      1. 并行抽取所有 chunks（asyncio.Semaphore 控制并发）
      2. 按 entity_name 聚合 nodes，按 (src, tgt) 聚合 edges
      3. 实体合并 → entity_type 投票 + LLM summarization
      4. 关系合并 → weight 累加 + LLM summarization
      5. 返回合并后的实体和关系列表
    """

    def __init__(
        self,
        examples: list[str] | None = None,
        max_gleanings: int = 2,  # 默认 2 轮 gleaning 循环提升实体召回（与 RAGFlow 最佳实践同步）
        max_concurrency: int = 1,
        language: str = "Chinese",
    ):
        self.examples = examples or []
        self.max_gleanings = max_gleanings
        self.max_concurrency = max_concurrency
        self.language = language

    async def extract(
        self,
        text: str,
        chunks: list[Chunk] | None = None,
        max_tokens: int = 2048,
        overlap_tokens: int = 256,
        callback: Callable[[str, float], None] | None = None,
        source_file: str | None = None,
        source_type: str = "uploaded_doc",
    ) -> tuple[list[dict], list[dict]]:
        """
        对文本执行完整抽取流程。

        Args:
            text: 原始文本（当 chunks=None 时用于生成分块）
            chunks: 预分块结果（优先使用，避免二次分块）
            max_tokens: 每块最大 token 数（默认 2048，平衡上下文利用率与信息完整性）
            overlap_tokens: 块间 overlap token 数
            source_file: 来源标识，格式 "filename@YYYY-MM-DD"，用于 descriptions.source 标记
            callback: 进度回调 (message, progress_percent)
            source_type: 数据来源类型，决定使用哪个抽取 prompt（影响置信度映射）

        Returns:
            (merged_entities, merged_relations)
            - merged_entities: list[dict]，字段：entity_name / entity_type / description / source_ids
            - merged_relations: list[dict]，字段：src_id / tgt_id / description / keywords / weight / source_ids
        """
        # Step 1: 分块（优先复用预分块结果）
        if chunks is None:
            chunks = chunk_by_token(text, max_tokens=max_tokens, overlap_tokens=overlap_tokens)
        if not chunks:
            logger.warning("文本为空，跳过抽取")
            return [], []

        callback and callback(f"分块完成，共 {len(chunks)} 个 chunk", 5.0)

        # Step 2: 并行抽取
        semaphore = asyncio.Semaphore(self.max_concurrency)
        tasks = [
            _extract_single_chunk(c, self.examples, self.max_gleanings, semaphore, source_file, source_type)
            for c in chunks
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 收集结果，过滤异常
        all_nodes: dict = defaultdict(list)
        all_edges: dict = defaultdict(list)
        error_count = 0
        for i, res in enumerate(results):
            if isinstance(res, Exception):
                logger.warning("Chunk %d 抽取失败: %s", i, res)
                error_count += 1
                continue
            nodes, edges = res
            for k, v in nodes.items():
                all_nodes[k].extend(v)
            for k, v in edges.items():
                all_edges[k].extend(v)

        callback and callback(
            f"抽取完成: {len(all_nodes)} 实体, {len(all_edges)} 关系（失败 {error_count} 块）",
            40.0,
        )

        # Step 3: 实体合并
        merged_entities = await self._merge_entities(all_nodes)
        callback and callback(f"实体合并完成: {len(merged_entities)} 实体", 70.0)

        # Step 4: 关系合并
        merged_relations = await self._merge_relations(all_edges)
        callback and callback(f"关系合并完成: {len(merged_relations)} 关系", 90.0)

        return merged_entities, merged_relations

    async def _merge_entities(self, all_nodes: dict) -> list[dict]:
        """同名实体跨 chunk 聚合"""
        tasks = []
        for name, instances in all_nodes.items():
            tasks.append(self._merge_single_entity(name, instances))

        results = await asyncio.gather(*tasks, return_exceptions=True)
        merged = []
        for res in results:
            if isinstance(res, Exception):
                logger.warning("实体合并失败: %s", res)
                continue
            if res:
                merged.append(res)
        return merged

    async def _merge_single_entity(self, name: str, instances: list[dict]) -> dict | None:
        """合并单个实体的多条记录"""
        if not instances:
            return None

        # 名称归一化（与 kg_extractor._normalize_name 保持一致）
        name = RAGExtractor._normalize_name_for_merge(name)

        # entity_type 投票（同票时按优先级决定：Company > Product > Metric）
        type_counter = Counter(e_type for e in instances if (e_type := str(e.get("entity_type") or "").strip()))
        if type_counter:
            # 先取最高票数，再从同票类型中按优先级选
            max_count = max(type_counter.values())
            tied = [t for t, c in type_counter.items() if c == max_count]
            # 优先级：Company > Product > Metric > 其他
            priority = {"Company": 0, "Product": 1, "Metric": 2}
            top_type = sorted(tied, key=lambda t: priority.get(t, 99))[0]
        else:
            top_type = "Company"

        # 保留所有原文描述（不做 LLM summarization）
        all_descriptions = [e.get("description", "") for e in instances if e.get("description")]

        # 合并 source_ids（记录来源 chunk）
        source_ids = list(dict.fromkeys(e.get("source_id", "") for e in instances if e.get("source_id")))

        return {
            "entity_name": name,
            "entity_type": top_type,
            "description": all_descriptions[0] if all_descriptions else "",
            "descriptions": all_descriptions,
            "source_ids": source_ids,
            "instance_count": len(instances),
        }

    @staticmethod
    def _normalize_name_for_merge(name: str) -> str:
        """归一化实体名称，与 kg_extractor._normalize_name 保持一致"""
        import re
        import unicodedata

        if not name:
            return ""
        normalized = unicodedata.normalize("NFKC", name)
        normalized = "".join(ch for ch in normalized if ch.isprintable() or ch in "\n\t")
        normalized = re.sub(r"\s+", " ", normalized)
        return normalized.strip()

    async def _merge_relations(self, all_edges: dict) -> list[dict]:
        """同 (src, tgt) 关系聚合"""
        tasks = []
        for (src, tgt), instances in all_edges.items():
            tasks.append(self._merge_single_relation(src, tgt, instances))

        results = await asyncio.gather(*tasks, return_exceptions=True)
        merged = []
        for res in results:
            if isinstance(res, Exception):
                logger.warning("关系合并失败: %s", res)
                continue
            if res:
                merged.append(res)
        return merged

    async def _merge_single_relation(self, src: str, tgt: str, instances: list[dict]) -> dict | None:
        """
        合并单个关系的多个记录。

        合并规则（按 source_file 分组）：
        - 同一 source_file 的多个 description → 合并成一条 dict（text 拼接）
        - 不同 source_file 的描述             → 分别作为独立的 dict 追加
        - 同 source_file 的相同 text         → 去重

        输出格式：descriptions = list[dict]
          每条 dict：{"text": str, "source": str, "source_ids": list[str]}
        """
        if not instances:
            return None

        # ── 按 source_id 分组 ─────────────────────────────────────────
        # source_id = source_file（文件名@日期），由 _extract_single_chunk 传入
        from collections import defaultdict

        by_source: dict[str, list[dict]] = defaultdict(list)
        for inst in instances:
            sid = inst.get("source_id", "") or ""
            if sid:
                by_source[sid].append(inst)

        # ── 每组内合并 → list[dict] ─────────────────────────────────
        descriptions: list[dict] = []
        all_directions: list[str] = []
        all_keywords: list[str] = []
        all_source_ids: list[str] = []
        seen_texts_in_output: set[str] = set()  # 全局去重（跨 source）
        seen_sources: set[str] = set()  # 已有 source 去重

        for sid, group in by_source.items():
            # 同一 source 内的所有 description，拼接
            group_texts: list[str] = []
            group_directions: list[str] = []
            for e in group:
                desc = e.get("description", "").strip()
                if desc and desc not in group_texts:  # 同 source 内去重
                    group_texts.append(desc)
                d = e.get("direction", "neutral")
                if d:
                    group_directions.append(d)

            if not group_texts:
                continue

            # 同 source 的多个描述 → 拼接
            merged_text = GRAPH_FIELD_SEP.join(group_texts)

            if merged_text in seen_texts_in_output:
                # 完全相同的 text（跨 source 去重）
                continue

            seen_texts_in_output.add(merged_text)
            if sid not in seen_sources:
                seen_sources.add(sid)
                all_source_ids.append(sid)

            descriptions.append(
                {
                    "text": merged_text,
                    "source": sid,
                    "source_ids": [sid],
                }
            )
            all_directions.extend(group_directions)

        # ── direction 多数投票 ────────────────────────────────────────
        direction_counter = Counter(all_directions)
        dominant_dir, dominant_count = direction_counter.most_common(1)[0] if direction_counter else ("neutral", 0)
        has_dir_conflict = (
            len(all_directions) >= 2
            and dominant_count < len(all_directions)
            and "negative" in all_directions
            and "positive" in all_directions
        )
        final_direction = "conflict" if has_dir_conflict else dominant_dir

        # ── keywords 合并 ──────────────────────────────────────────────
        for e in instances:
            kw = e.get("keywords", "")
            if kw:
                all_keywords.extend(kw.split(","))
        keywords = ", ".join(dict.fromkeys(k.strip() for k in all_keywords if k.strip()))

        # ── weight 累加 ──────────────────────────────────────────────
        total_weight = sum(max(0, e.get("weight", 5)) for e in instances)

        # Neo4j 只支持原始类型：descriptions 扁平化为 list[str]
        flat_descs = [d["text"] for d in descriptions if isinstance(d, dict) and d.get("text")]
        return {
            "src_id": src,
            "tgt_id": tgt,
            "description": flat_descs[0] if flat_descs else "",
            "descriptions": flat_descs,  # Neo4j 兼容：list[str]
            "keywords": keywords,
            "direction": final_direction,
            "weight": round(total_weight, 2),
            "source_ids": all_source_ids,
            "instance_count": len(instances),
            "has_direction_conflict": has_dir_conflict,
        }


# ── 同步入口（供 kg_extractor.py 调用）───────────────────────────────────────


def extract_sync(
    text: str,
    chunks: list[Chunk] | None = None,
    examples: list[str] | None = None,
    max_gleanings: int = 2,  # 默认 2 轮 gleaning 循环提升实体召回
    max_tokens: int = 512,
    overlap_tokens: int = 0,
    callback: Callable[[str, float], None] | None = None,
    source_file: str | None = None,
    source_type: str = "uploaded_doc",  # B8 fix: 添加 source_type 参数
) -> tuple[list[dict], list[dict]]:
    """
    同步入口函数（用于 FastAPI 同步路由或脚本调用）。

    安全修复：
    - 添加 async 上下文检测，防止 asyncio.run 嵌套崩溃
    - 在 async 上下文中使用 ThreadPoolExecutor 避免嵌套 event loop

    注意：从 async 上下文调用时，建议使用 extract_async 或 asyncio.to_thread(extract_sync, ...)。
    """
    extractor = RAGExtractor(
        examples=examples,
        max_gleanings=max_gleanings,
        max_concurrency=4,
    )

    # 检测是否在 async 上下文中
    try:
        asyncio.get_running_loop()
        # 在 async 上下文中，使用 ThreadPoolExecutor 避免嵌套 asyncio.run
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(
                asyncio.run,
                extractor.extract(
                    text,
                    chunks=chunks,
                    max_tokens=max_tokens,
                    overlap_tokens=overlap_tokens,
                    callback=callback,
                    source_file=source_file,
                    source_type=source_type,
                ),
            )
            return future.result()
    except RuntimeError:
        # 无运行中的事件循环，可以直接使用 asyncio.run
        pass

    return asyncio.run(
        extractor.extract(
            text,
            chunks=chunks,
            max_tokens=max_tokens,
            overlap_tokens=overlap_tokens,
            callback=callback,
            source_file=source_file,
            source_type=source_type,
        )
    )


async def extract_async(
    text: str,
    chunks: list[Chunk] | None = None,
    examples: list[str] | None = None,
    max_gleanings: int = 2,  # 默认 2 轮 gleaning 循环提升实体召回
    max_tokens: int = 512,
    overlap_tokens: int = 0,
    callback: Callable[[str, float], None] | None = None,
    source_file: str | None = None,
    source_type: str = "uploaded_doc",
) -> tuple[list[dict], list[dict]]:
    """异步入口函数"""
    extractor = RAGExtractor(
        examples=examples,
        max_gleanings=max_gleanings,
        max_concurrency=4,
    )
    return await extractor.extract(
        text,
        chunks=chunks,
        max_tokens=max_tokens,
        overlap_tokens=overlap_tokens,
        callback=callback,
        source_file=source_file,
        source_type=source_type,
    )
