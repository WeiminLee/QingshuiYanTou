"""
实体消解（Entity Resolution）

参考 RAGFlow entity_resolution.py，实现：
1. 相似度预过滤（数字差异 / 编辑距离 / Jaccard）
2. 批量 LLM 判断是否合并
3. 图合并 + pagerank 重算

适用类型：Company / Product / Tech
（Industry / Metric / Event 暂不消解）
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from dataclasses import dataclass

try:
    import editdistance
except ModuleNotFoundError:  # pragma: no cover - exercised only when optional dep missing

    class _EditDistanceFallback:
        @staticmethod
        def eval(a: str, b: str) -> int:
            if a == b:
                return 0
            prev = list(range(len(b) + 1))
            for i, ca in enumerate(a, start=1):
                cur = [i]
                for j, cb in enumerate(b, start=1):
                    cur.append(
                        min(
                            prev[j] + 1,
                            cur[j - 1] + 1,
                            prev[j - 1] + (ca != cb),
                        )
                    )
                prev = cur
            return prev[-1]

    editdistance = _EditDistanceFallback()

logger = logging.getLogger(__name__)

# ── 分隔符 ────────────────────────────────────────────────────────────────

RECORD_DELIMITER = "##"
ENTITY_INDEX_DELIMITER = "<|>"
RESOLUTION_RESULT_DELIMITER = "&&"

# ── 相似度预过滤 ───────────────────────────────────────────────────────


def _is_english(s: str) -> bool:
    try:
        s.encode("utf-8").decode("ascii")
        return True
    except UnicodeDecodeError:
        return False


def _cross_language_alias(a: str, b: str) -> bool:
    """
    Return True if names a and b appear together as aliases for the same company.
    Handles cross-language pairs like ('英伟达', 'NVIDIA').
    Delegates to StockNameResolver (PostgreSQL + supplemental_aliases.json).
    """
    from app.knowledge.stock_name_resolver import get_stock_name_resolver

    return get_stock_name_resolver().is_same_company(a, b)


def _has_digit_in_2gram_diff(a: str, b: str) -> bool:
    """2-gram 数字差异检测：有数字的 n-gram 在两边不同 → 直接排除"""

    def to_2gram_set(s):
        return {s[i : i + 2] for i in range(len(s) - 1)}

    set_a = to_2gram_set(a)
    set_b = to_2gram_set(b)
    diff = set_a ^ set_b
    return any(c.isdigit() for pair in diff for c in pair)


def is_similarity(a: str, b: str) -> bool:
    """
    快速相似度预过滤。
    返回 True 表示候选对可能相同，值得送 LLM 进一步判断。
    """
    if not a or not b:
        return False
    # 数字差异检测
    if _has_digit_in_2gram_diff(a, b):
        return False
    # 英文：编辑距离
    if _is_english(a) and _is_english(b):
        return editdistance.eval(a.lower(), b.lower()) <= min(len(a), len(b)) // 2
    # 中英/跨语言别名：两者都在 aliases names 数组中出现过 → 同一实体
    if _cross_language_alias(a, b):
        return True

    # 其他语言：字符集 Jaccard
    set_a, set_b = set(a), set(b)
    max_l = max(len(set_a), len(set_b))
    if max_l < 4:
        return len(set_a & set_b) > 1
    return len(set_a & set_b) / max_l >= 0.8


# ── 赛道上下文别名消歧 ────────────────────────────────────────────────
# sector_tags 通过 StockNameResolver 获取（PostgreSQL industry + supplemental_aliases.json sector_tags）


def _get_sector_tags(entity_name: str, node_metadata: dict | None = None) -> set[str]:
    """
    Return sector tags for an entity name.
    Combines StockNameResolver sector data with node metadata `sector` field.
    """
    from app.knowledge.stock_name_resolver import get_stock_name_resolver

    tags: set[str] = set(get_stock_name_resolver().get_sector_tags(entity_name))
    # From node metadata
    if node_metadata:
        meta_sector = node_metadata.get("sector") or node_metadata.get("sector_tags")
        if meta_sector:
            if isinstance(meta_sector, list):
                tags.update(meta_sector)
            else:
                tags.add(str(meta_sector))
    return tags


def _sectors_disjoint(
    a_name: str,
    b_name: str,
    a_meta: dict | None,
    b_meta: dict | None,
) -> bool:
    """
    Return True if both entities have known sector info AND their sector sets are disjoint.
    Disjoint sectors means same name refers to different companies → skip pair.
    """
    sectors_a = _get_sector_tags(a_name, a_meta)
    sectors_b = _get_sector_tags(b_name, b_meta)
    if not sectors_a or not sectors_b:
        return False  # Unknown sectors → cannot disambiguate, keep candidate
    return sectors_a.isdisjoint(sectors_b)


# ── LLM 消解 Prompt ────────────────────────────────────────────────────

ENTITY_RESOLUTION_PROMPT = """-Goal-
请判断以下实体对是否为同一实体。

-Steps-
1. 判断两个实体是否相同
2. 使用 **{record_delimiter}** 作为列表分隔符

######################
-Examples-
######################
Example 1:

判断类型: Product
实体 A: television
实体 B: TV

回答: 两个名称指代同一产品。
################
Output:
({ENTITY_INDEX_DELIMITER}1{ENTITY_INDEX_DELIMITER}, {RESOLUTION_RESULT_DELIMITER}yes{RESOLUTION_RESULT_DELIMITER}, 为同一产品。) {RECORD_DELIMITER}
({ENTITY_INDEX_DELIMITER}2{ENTITY_INDEX_DELIMITER}, {RESOLUTION_RESULT_DELIMITER}no{RESOLUTION_RESULT_DELIMITER}, 为不同产品。) {RECORD_DELIMITER}

######################
-Real Data-
######################
判断类型: {entity_type}
{questions}
######################
Output:"""


def _build_resolution_prompt(entity_type: str, pairs: list[tuple[str, str]]) -> str:
    """构建批量消解 Prompt"""
    questions_parts = []
    for i, (a, b) in enumerate(pairs, start=1):
        questions_parts.append(f"实体 A: {a}\n实体 B: {b}")

    questions_text = "\n\n".join(f"Question {i}: {q}" for i, q in enumerate(questions_parts, start=1))

    return ENTITY_RESOLUTION_PROMPT.format(
        entity_type=entity_type,
        questions=questions_text,
        record_delimiter=RECORD_DELIMITER,
        ENTITY_INDEX_DELIMITER=ENTITY_INDEX_DELIMITER,
        RESOLUTION_RESULT_DELIMITER=RESOLUTION_RESULT_DELIMITER,
    )


def _parse_resolution_result(
    response: str,
    num_pairs: int,
) -> list[int]:
    """
    解析 LLM 消解结果。
    Returns: indices of pairs that should be merged (1-indexed)
    """
    result = []
    records = response.split(RECORD_DELIMITER)
    for record in records:
        record = record.strip()
        if not record:
            continue
        # 找索引
        m_idx = re.search(
            rf"{re.escape(ENTITY_INDEX_DELIMITER)}(\d+){re.escape(ENTITY_INDEX_DELIMITER)}",
            record,
        )
        if not m_idx:
            continue
        idx = int(m_idx.group(1))
        if idx < 1 or idx > num_pairs:
            continue
        # 找 yes/no
        m_yes = re.search(
            rf"{re.escape(RESOLUTION_RESULT_DELIMITER)}\s*yes\s*{re.escape(RESOLUTION_RESULT_DELIMITER)}",
            record,
            re.IGNORECASE,
        )
        if m_yes:
            result.append(idx)
    return result


# ── 消解核心 ───────────────────────────────────────────────────────────


@dataclass
class ResolutionPair:
    """候选消解对"""

    a: str  # entity_name A
    b: str  # entity_name B
    entity_type: str


@dataclass
class EntityResolutionResult:
    """消解结果"""

    merged_pairs: list[tuple[str, str]]  # [(name_a, name_b), ...] 待合并的对
    total_candidates: int
    resolved_count: int


async def resolve_entities(
    nodes: list[dict],
    callback=None,
) -> EntityResolutionResult:
    """
    对实体列表执行批量消解。

    Args:
        nodes: RAGExtractor 返回的实体列表，每项含 entity_name / entity_type
        callback: 进度回调

    Returns:
        EntityResolutionResult，包含待合并的对列表
    """
    # 只对 Company / Product 消解（V1.2 Schema，Tech 暂不消解）
    TARGET_TYPES = {"Company", "Product"}

    # 按类型分组
    by_type: dict[str, list[str]] = defaultdict(list)
    for n in nodes:
        e_type = n.get("entity_type", "")
        if e_type in TARGET_TYPES:
            by_type[e_type].append(n.get("entity_name", ""))

    # 生成候选对（已过滤 TARGET_TYPES）
    candidate_pairs: list[ResolutionPair] = []
    import itertools

    for e_type, names in by_type.items():
        unique_names = list(dict.fromkeys(n for n in names if n))
        for a, b in itertools.combinations(unique_names, 2):
            if not is_similarity(a, b):
                continue
            # 赛道上下文消歧：同名公司但 sector 无交集 → 跳过
            if e_type == "Company" and _sectors_disjoint(a, b, None, None):
                continue
            candidate_pairs.append(ResolutionPair(a=a, b=b, entity_type=e_type))

    total_candidates = len(candidate_pairs)
    logger.info("实体消解候选对: %d 对", total_candidates)
    callback and callback(f"候选对: {total_candidates} 对")

    if not candidate_pairs:
        return EntityResolutionResult(merged_pairs=[], total_candidates=0, resolved_count=0)

    # 批量送 LLM（每批最多 50 对）
    BATCH_SIZE = 50
    all_merged: list[tuple[str, str]] = []

    for i in range(0, len(candidate_pairs), BATCH_SIZE):
        batch = candidate_pairs[i : i + BATCH_SIZE]
        pairs_text = [(p.a, p.b) for p in batch]
        e_type = batch[0].entity_type

        prompt = _build_resolution_prompt(e_type, pairs_text)
        try:
            from app.core.llm_client import chat_async

            response = await chat_async(prompt, temperature=0.1, timeout=60)
        except Exception as e:
            logger.warning("LLM 消解批次 %d 失败: %s", i // BATCH_SIZE + 1, e)
            continue

        merged_indices = _parse_resolution_result(response, len(batch))
        for idx in merged_indices:
            pair = batch[idx - 1]  # 1-indexed
            all_merged.append((pair.a, pair.b))

        logger.debug(
            "批次 %d: %d 候选 → %d 合并",
            i // BATCH_SIZE + 1,
            len(batch),
            len(merged_indices),
        )

    logger.info(
        "实体消解完成: %d 候选 → %d 确认合并",
        total_candidates,
        len(all_merged),
    )
    callback and callback(f"确认合并: {len(all_merged)} 对")

    return EntityResolutionResult(
        merged_pairs=all_merged,
        total_candidates=total_candidates,
        resolved_count=len(all_merged),
    )


# ── 合并操作（写入 Neo4j）─────────────────────────────────────────────


def apply_merges(
    merged_pairs: list[tuple[str, str]],
    entity_id_map: dict[str, str],
    callback=None,
) -> int:
    """
    将合并对应用到 Neo4j：保留 entity_id 更"规范"的，删除另一个。

    Args:
        merged_pairs: [(name_a, name_b), ...] 待合并的对
        entity_id_map: name → entity_id 映射

    Returns:
        实际合并的数量
    """
    if not merged_pairs:
        return 0

    from app.knowledge.entity_service import get_entity

    merged_count = 0
    for name_a, name_b in merged_pairs:
        eid_a = entity_id_map.get(name_a)
        eid_b = entity_id_map.get(name_b)
        if not eid_a or not eid_b or eid_a == eid_b:
            continue

        # 优先保留 C: 开头的（上市）
        if eid_a.startswith("C:") and not eid_b.startswith("C:"):
            keep_id, discard_id = eid_a, eid_b
        elif eid_b.startswith("C:") and not eid_a.startswith("C:"):
            keep_id, discard_id = eid_b, eid_a
        else:
            # 都非上市：保留字典序靠前的 entity_id
            keep_id, discard_id = (eid_a, eid_b) if eid_a < eid_b else (eid_b, eid_a)

        try:
            # 获取被丢弃节点的属性
            discard_node = get_entity(discard_id)
            get_entity(keep_id)

            if discard_node:
                # 将 discard 的关系迁移到 keep
                _migrate_relationships(discard_id, keep_id)
                # 删除 discard 节点
                _delete_entity(discard_id)
                logger.debug("合并: %s → %s（保留）", discard_id, keep_id)
                merged_count += 1

            callback and callback(f"合并 {discard_id} → {keep_id}")
        except Exception as e:
            logger.warning("合并实体失败 [%s → %s]: %s", discard_id, keep_id, e)

    return merged_count


def _migrate_relationships(from_id: str, to_id: str):
    """
    将被丢弃节点的关系迁移到保留节点。

    BUG-12 修复：分别处理双向关系，防止方向丢失。
    - 原关系 (a)->(b) → 新关系 (保留节点)->(b)
    - 原关系 (b)->(a) → 新关系 (b)->(保留节点)
    """
    from app.core.neo4j_client import write_transaction

    # 处理 (a)-[r]->(b) 类型的关系
    cypher_outgoing = """
    MATCH (a)-[r]->(b)
    WHERE a.entity_id = $from_id
    WITH a, r, b
    MERGE (c:Entity {entity_id: $to_id})
    MERGE (c)-[r2]->(b)
    SET r2 = properties(r)
    DELETE r
    """
    # 处理 (b)-[r]->(a) 类型的关系（反向）
    cypher_incoming = """
    MATCH (b)-[r]->(a)
    WHERE a.entity_id = $from_id
    WITH a, r, b
    MERGE (c:Entity {entity_id: $to_id})
    MERGE (b)-[r2]->(c)
    SET r2 = properties(r)
    DELETE r
    """
    with write_transaction() as tx:
        tx.run(cypher_outgoing, from_id=from_id, to_id=to_id)
        tx.run(cypher_incoming, from_id=from_id, to_id=to_id)


def _delete_entity(entity_id: str):
    """删除节点"""
    from app.core.neo4j_client import run_write

    run_write(
        "MATCH (n {entity_id: $eid}) DETACH DELETE n",
        eid=entity_id,
    )
