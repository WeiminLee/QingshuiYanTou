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

from app.core.llm_client import chat
from app.knowledge.extraction.chunker import Chunk, chunk_by_token
from app.knowledge.extraction.rag_prompts import (
    COMPLETION_DELIMITER,
    CONTINUE_PROMPT,
    ENTITY_TYPES,
    GRAPH_FIELD_SEP,
    SUMMARIZE_PROMPT,
    TUPLE_DELIMITER,
    get_extraction_prompt,
)

logger = logging.getLogger(__name__)

# 合法的 entity_type 白名单（模块级常量）
VALID_ENTITY_TYPES = frozenset(ENTITY_TYPES)


def _merge_descriptions_raw(descriptions: list[str]) -> str:
    """
    保留原文的多源合并（不做 LLM summarization）。
    各描述用 GRAPH_FIELD_SEP 分隔，标记来源索引。
    用于注入 properties.descriptions[] 数组。
    """
    if not descriptions:
        return ""
    # 去重，保持顺序
    seen = set()
    unique = []
    for d in descriptions:
        if d and d not in seen:
            seen.add(d)
            unique.append(d)
    return GRAPH_FIELD_SEP.join(unique)


def _summarize_descriptions(
    entity_or_relation: str,
    descriptions: list[str],
    max_items: int = 12,
) -> str:
    """
    合并同名实体的多条描述。

    B2 fix: 当描述数量超过 max_items 时，调用 LLM summarization 压缩描述，
    防止高频实体累积无界描述导致向量搜索性能下降。

    在 async 上下文中直接调用 module-level 的 async _summarize_descriptions；
    在 sync 上下文中使用 asyncio.run() 调用。
    """
    # 检查是否需要 summarization
    if len(descriptions) <= max_items:
        return _merge_descriptions_raw(descriptions)

    # 需要 summarization，调用 async 版本
    # 注意：在 async context 中应直接调用 module-level async _summarize_descriptions
    # 这里处理 sync context 的情况
    try:
        asyncio.get_running_loop()
        # 在 async context 中，fallback 到 raw merge（避免嵌套 event loop）
        # 调用方应在 async context 中使用 async _summarize_descriptions
        return _merge_descriptions_raw(descriptions)
    except RuntimeError:
        # 无 running loop，可以安全使用 asyncio.run()
        pass

    # Sync context: 使用 asyncio.run() 调用 async summarization
    return asyncio.run(_async_summarize_descriptions(entity_or_relation, descriptions, max_items))


async def _async_summarize_descriptions(
    entity_or_relation: str,
    descriptions: list[str],
    max_items: int = 12,
) -> str:
    """
    异步版本的描述合并。

    当描述数量超过 max_items 时，用 LLM 将多条描述压缩为一条。
    如果 LLM 不可用，降级为保留前 max_items 条描述。
    """
    if len(descriptions) <= max_items:
        return _merge_descriptions_raw(descriptions)

    # 去重后取前 max_items 条
    unique = list(dict.fromkeys(d for d in descriptions if d))[:max_items]

    try:
        prompt = SUMMARIZE_PROMPT.format(
            entity_name=entity_or_relation,
            description_list="\n".join(f"{i + 1}. {d}" for i, d in enumerate(unique)),
        )
        summary = await _call_llm_async(prompt)
        return summary.strip()
    except Exception as e:
        # LLM 不可用，降级为保留前 max_items 条描述
        logger.warning("LLM summarization failed, falling back to max_items limit: %s", e)
        return GRAPH_FIELD_SEP.join(unique)


# ── 输出解析 ────────────────────────────────────────────────────────────────


def _parse_tuple_record(record: str) -> list[str]:
    """用 TUPLE_DELIMITER 切分一条 tuple 记录"""
    parts = record.split(TUPLE_DELIMITER)
    return [p.strip().strip('"').strip("'") for p in parts]


def _normalize_llm_output_line(line: str) -> str:
    """Normalize common Markdown wrappers around structured extraction lines."""
    line = line.strip()
    line = re.sub(r"^\s*[-*+]\s+", "", line)
    line = line.strip().strip("`").strip()
    while len(line) >= 2 and line.startswith("**") and line.endswith("**"):
        line = line[2:-2].strip()
    return line.strip().strip("*").strip()


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


def _parse_entity_relation_blocks(raw_text: str) -> tuple[dict, dict]:
    """
    解析单个 chunk 的 LLM 输出。

    支持三种格式（优先格式1）：
    格式1（V2 新格式，关系 = text + weight）：
      Entity: 实体名称(类型)
        属性: key=value, key=value, ...
      Relation: 实体A → 实体B
        关系陈述: "..."
        weight: 1.0 或 0.x
    格式2（V1 旧格式，向后兼容）：
      Entity: 公司名称(Company)
      Relation: 公司→产品: 描述 | 方向 | 强度
    格式3（tuple 格式，备用）：
      Entity(name, type, description)

    Returns:
        nodes: dict[name -> list[dict]]
        edges: dict[(src, tgt) -> list[dict]]
    """
    nodes: dict = defaultdict(list)
    edges: dict = defaultdict(list)

    # ── V2 新格式解析 ────────────────────────────────────────────────
    # 匹配: "Entity: 名称(类型)" 或带属性行
    v2_entity_pattern = re.compile(r"^Entity\s*:\s*(.+?)\s*\(\s*([^\)]+)\s*\)\s*$")
    v2_attr_pattern = re.compile(r"^\s*属性\s*[:：]\s*(.+)")
    # 匹配 V2 关系块
    v2_rel_src_pattern = re.compile(r"^Relation\s*:\s*(.+?)\s*→\s*(.+?)\s*$")
    v2_rel_text_pattern = re.compile(r"^\s*关系陈述\s*[:：]\s*['\"]?(.+?)['\"]?\s*$")
    v2_rel_weight_pattern = re.compile(r"^\s*weight\s*[:：]\s*(\d+(?:\.\d+)?)\s*$")
    # 匹配 V1 旧格式（向后兼容）
    v1_rel_pattern = re.compile(
        r"^Relation\s*:\s*(.+?)\s*→\s*(.+?)\s*:\s*(.+?)\s*\|\s*([\w]+)\s*(?:\|(\d+(?:\.\d+)?))?\s*$"
    )
    # 合法的 entity_type（白名单）
    valid_entity_types = VALID_ENTITY_TYPES

    current_entity: tuple = None  # (name, e_type)
    current_section_type: str | None = None
    current_rel: dict = None  # {src, tgt, description, weight}

    for line in raw_text.split("\n"):
        line_stripped = _normalize_llm_output_line(line)
        if not line_stripped or line_stripped == COMPLETION_DELIMITER:
            continue

        tuple_parts = _parse_tuple_record(line_stripped)
        if len(tuple_parts) >= 4:
            name, maybe_type, desc = tuple_parts[0], tuple_parts[1], tuple_parts[2]
            if maybe_type in valid_entity_types and not _is_noise_entity_name(name):
                nodes[name].append(
                    {
                        "entity_name": name,
                        "entity_type": maybe_type,
                        "description": desc,
                    }
                )
                continue
        if len(tuple_parts) >= 5:
            src, relation, tgt = tuple_parts[0], tuple_parts[1], tuple_parts[2]
            if src and tgt and relation and not _is_noise_entity_name(src) and not _is_noise_entity_name(tgt):
                try:
                    weight = float(tuple_parts[3])
                except (ValueError, TypeError):
                    weight = 1.0
                desc = tuple_parts[4] if len(tuple_parts) > 4 else relation
                edges[(src, tgt)].append(
                    {
                        "src_id": src,
                        "tgt_id": tgt,
                        "description": desc or relation,
                        "keywords": relation,
                        "direction": "neutral",
                        "weight": weight,
                    }
                )
                continue

        section = line_stripped.rstrip(":：").strip()
        if section in valid_entity_types:
            current_section_type = section
            current_entity = None
            current_rel = None
            continue

        if current_section_type and not line_stripped.endswith(":") and not line_stripped.endswith("："):
            structured_prefixes = (
                "RELATES:",
                "METRIC:",
                "Relation:",
                "Entity:",
                "关系描述:",
                "关系描述：",
                "关系陈述:",
                "关系陈述：",
                "置信度:",
                "置信度：",
                "来源:",
                "来源：",
                "name:",
                "value:",
                "unit:",
                "period:",
                "period_type:",
                "sentiment:",
            )
            if line_stripped.startswith(structured_prefixes):
                current_section_type = None
            else:
                bullet_name = re.sub(r"[（(].*?[）)]$", "", line_stripped).strip()
                if (
                    bullet_name
                    and current_section_type != "Metric"
                    and len(bullet_name) <= 50
                    and not _is_noise_entity_name(bullet_name)
                ):
                    nodes[bullet_name].append(
                        {
                            "entity_name": bullet_name,
                            "entity_type": current_section_type,
                            "description": "",
                        }
                    )
                    continue

        # V2 Entity 行
        em = v2_entity_pattern.match(line_stripped)
        if em:
            name, e_type = em.group(1).strip(), em.group(2).strip()
            if name and e_type and e_type in valid_entity_types and not _is_noise_entity_name(name):
                current_entity = (name, e_type)
                nodes[name].append(
                    {
                        "entity_name": name,
                        "entity_type": e_type,
                        "description": "",
                    }
                )
            else:
                current_entity = None
            continue

        # V2 属性行（附加到当前 entity）
        if current_entity is not None:
            am = v2_attr_pattern.match(line_stripped)
            if am:
                attr_text = am.group(1).strip()
                name, e_type = current_entity
                if nodes[name] and nodes[name][-1]["description"] == "":
                    nodes[name][-1]["description"] = attr_text
                continue

        # V2 Relation 起始行
        rm_src = v2_rel_src_pattern.match(line_stripped)
        if rm_src:
            current_section_type = None
            src, tgt = rm_src.group(1).strip(), rm_src.group(2).strip()
            if _is_noise_entity_name(src) or _is_noise_entity_name(tgt):
                current_rel = None
                continue
            current_rel = {"src_id": src, "tgt_id": tgt, "description": "", "weight": 1.0}
            continue

        # V2 关系陈述行
        if current_rel is not None:
            rm_text = v2_rel_text_pattern.match(line_stripped)
            if rm_text:
                current_rel["description"] = rm_text.group(1).strip()
                continue
            rm_weight = v2_rel_weight_pattern.match(line_stripped)
            if rm_weight:
                try:
                    current_rel["weight"] = float(rm_weight.group(1))
                except ValueError:
                    pass
                # 关系结束，写入 edges
                # B4 fix: 不排序，保留 (src, tgt) 原始顺序以维护关系方向
                if current_rel.get("src_id") and current_rel.get("tgt_id"):
                    key = (current_rel["src_id"], current_rel["tgt_id"])
                    edges[key].append(
                        {
                            "src_id": current_rel["src_id"],
                            "tgt_id": current_rel["tgt_id"],
                            "description": current_rel.get("description", ""),
                            "keywords": "",
                            "direction": "neutral",
                            "weight": current_rel.get("weight", 1.0),
                        }
                    )
                current_rel = None
                continue

        # V1 旧格式 Relation 行（向后兼容）
        v1m = v1_rel_pattern.match(line_stripped)
        if v1m:
            src, tgt = v1m.group(1).strip(), v1m.group(2).strip()
            desc, direction = v1m.group(3).strip(), v1m.group(4).strip().lower()
            if _is_noise_entity_name(src) or _is_noise_entity_name(tgt):
                continue
            weight_str = v1m.group(5)
            try:
                weight = float(weight_str) if weight_str else 5.0
            except (ValueError, TypeError):
                weight = 5.0
            if src and tgt:
                # B4 fix: 不排序，保留 (src, tgt) 原始顺序以维护关系方向
                key = (src, tgt)
                edges[key].append(
                    {
                        "src_id": src,
                        "tgt_id": tgt,
                        "description": desc,
                        "keywords": "",
                        "direction": direction,
                        "weight": weight,
                    }
                )
            continue

        # V1 Entity 行（向后兼容）
        v1_entity_pattern = re.compile(r"^Entity\s*:\s*(.+?)\s*\(\s*([^\)]+)\s*\)(?:\s*/\s*(.+))?$")
        v1em = v1_entity_pattern.match(line_stripped)
        if v1em:
            name, e_type = v1em.group(1).strip(), v1em.group(2).strip()
            desc = (v1em.group(3) or "").strip()
            if name and e_type and e_type in valid_entity_types and not _is_noise_entity_name(name):
                nodes[name].append(
                    {
                        "entity_name": name,
                        "entity_type": e_type,
                        "description": desc,
                    }
                )

    return dict(nodes), dict(edges)


def _parse_relates(raw_text: str) -> list[dict]:
    """Parse RELATES blocks."""
    relates: list[dict] = []
    current: dict | None = None
    rel_pattern = re.compile(r"^RELATES\s*:\s*(.+?)\s*→\s*(.+?)\s*$")
    rel_inline_weight_pattern = re.compile(r"^RELATES\s*:\s*(.+?)\s*→\s*(.+?)\s*\(?\s*([\d.]+)\s*\)?\s*$")
    text_pattern = re.compile(r"^\s*关系描述\s*[:：]\s*['\"]?(.+?)['\"]?\s*$")
    weight_pattern = re.compile(r"^\s*置信度\s*[:：]\s*(\d+(?:\.\d+)?)\s*$")
    stmt_type_pattern = re.compile(r"^\s*陈述类型\s*[:：]\s*(Fact|Claim|Estimate)\s*$", re.IGNORECASE)
    source_pattern = re.compile(r"^\s*来源\s*[:：]\s*['\"]?(.+?)['\"]?\s*$")

    def flush() -> None:
        nonlocal current
        if (
            current
            and current.get("from_entity")
            and current.get("to_entity")
            and not _is_noise_entity_name(current.get("from_entity", ""))
            and not _is_noise_entity_name(current.get("to_entity", ""))
        ):
            relates.append(current)
        current = None

    for raw_line in raw_text.splitlines():
        line = _normalize_llm_output_line(raw_line)
        if not line:
            continue
        match = rel_pattern.match(line)
        if match:
            flush()
            current = {
                "from_entity": match.group(1).strip(),
                "to_entity": match.group(2).strip(),
                "text": "",
                "weight": 1.0,
                "stmt_type": "Fact",
                "source": "",
            }
            continue
        # 内联权重格式: RELATES: A → B (0.7)
        inline_match = rel_inline_weight_pattern.match(line)
        if inline_match:
            flush()
            try:
                weight_val = float(inline_match.group(3))
                weight_val = max(0.0, min(1.0, weight_val))
            except ValueError:
                weight_val = 1.0
            current = {
                "from_entity": inline_match.group(1).strip(),
                "to_entity": inline_match.group(2).strip(),
                "text": "",
                "weight": weight_val,
                "stmt_type": "Fact",
                "source": "",
            }
            continue
        if current is None:
            continue
        text_match = text_pattern.match(line)
        if text_match:
            current["text"] = text_match.group(1).strip()[:100]
            continue
        weight_match = weight_pattern.match(line)
        if weight_match:
            try:
                current["weight"] = float(weight_match.group(1))
            except ValueError:
                current["weight"] = 1.0
            continue
        source_match = source_pattern.match(line)
        if source_match:
            current["source"] = source_match.group(1).strip()
            continue
        stmt_match = stmt_type_pattern.match(line)
        if stmt_match:
            current["stmt_type"] = stmt_match.group(1).capitalize()
    flush()
    return relates


def _parse_metrics(raw_text: str) -> list[dict]:
    """Parse METRIC blocks."""
    metrics: list[dict] = []
    current: dict | None = None
    metric_pattern = re.compile(r"^METRIC\s*:\s*(.+?)\s*$")
    field_pattern = re.compile(r"^\s*(name|value|unit|period|period_type|sentiment)\s*[:：]\s*(.+?)\s*$")

    def flush() -> None:
        nonlocal current
        if current and current.get("name") and current.get("period"):
            metrics.append(current)
        current = None

    for raw_line in raw_text.splitlines():
        line = _normalize_llm_output_line(raw_line)
        if not line:
            continue
        match = metric_pattern.match(line)
        if match:
            flush()
            current = {"name": match.group(1).strip()}
            continue
        if current is None:
            continue
        field_match = field_pattern.match(line)
        if field_match:
            key, value = field_match.group(1), field_match.group(2).strip().strip('"')
            current[key] = None if value.lower() in ("null", "none", "") else value
    flush()
    return metrics


def _parse_chunk_output(raw_text: str) -> tuple[dict, dict]:
    """Parse chunk output with RELATES and METRIC blocks."""
    nodes, edges = _parse_entity_relation_blocks(raw_text)

    for rel in _parse_relates(raw_text):
        key = (rel["from_entity"], rel["to_entity"])
        edges.setdefault(key, []).append(
            {
                "src_id": rel["from_entity"],
                "tgt_id": rel["to_entity"],
                "description": rel.get("text", ""),
                "keywords": "",
                "direction": "neutral",
                "weight": rel.get("weight", 1.0),
                "source": rel.get("source", ""),
                "stmt_type": rel.get("stmt_type", "Fact"),
            }
        )

    for metric in _parse_metrics(raw_text):
        name = metric["name"]
        nodes.setdefault(name, []).append(
            {
                "entity_name": name,
                "entity_type": "Metric",
                "description": "",
                "metric": metric,
            }
        )

    return nodes, edges


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
    max_gleanings: int = 2,
    semaphore: asyncio.Semaphore | None = None,
    source_file: str | None = None,
    source_type: str = "uploaded_doc",
) -> tuple[dict, dict]:
    """
    对单个 chunk 执行抽取 + gleaning 循环。

    改进：
    - 预过滤：表格行/声明/URL/噪声在调用 LLM 前清洗
    - 只发送 CONTINUE_PROMPT，不重发完整历史（节省 token + 减少 LLM 疲劳）
    - 固定最多 gleaning 轮次（不依赖 LOOP_PROMPT 二次调用）
    - JSON 终止判断（解析失败则提前停止）
    - source_id = source_file，用于 descriptions.source 标记
    - section_title 注入到 EXTRACTION_PROMPT（chunk.heading 作为章节上下文）
    """
    section_title = getattr(chunk, "heading", "") or ""
    # 预过滤：去除表格行、声明、URL 等噪声
    filtered_content = _prefilter_chunk(chunk.content)
    if not filtered_content.strip():
        # 无有效内容，跳过 LLM 调用
        return {}, {}
    initial_prompt = get_extraction_prompt(source_type, section_title).format(
        input_text=filtered_content,
    )

    async def _call(prompt: str) -> str:
        if semaphore:
            async with semaphore:
                return await _call_llm_async(prompt)
        return await _call_llm_async(prompt)

    # 初始抽取
    raw = await _call(initial_prompt)
    nodes, edges = _parse_chunk_output(raw)

    # gleaning 循环：只追加 CONTINUE_PROMPT，不发历史
    for _ in range(max_gleanings):
        # 解析失败的空响应 → 提前终止
        if not raw.strip():
            break

        continuation = await _call(CONTINUE_PROMPT)
        if not continuation.strip():
            break

        more_nodes, more_edges = _parse_chunk_output(continuation)
        if not more_nodes and not more_edges:
            break  # 没有新内容，提前终止

        for k, v in more_nodes.items():
            nodes.setdefault(k, []).extend(v)
        for k, v in more_edges.items():
            edges.setdefault(k, []).extend(v)
        raw = continuation

    # 注入 source_id，用于 descriptions.source 标记
    # source_file = "filename@YYYY-MM-DD"；无则降级为 chunk:id 格式
    chunk_key = source_file if source_file else f"chunk:{chunk.chunk_id}"
    for name in nodes:
        for item in nodes[name]:
            item["source_id"] = chunk_key
    for key in edges:
        for item in edges[key]:
            item["source_id"] = chunk_key

    return nodes, edges


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
