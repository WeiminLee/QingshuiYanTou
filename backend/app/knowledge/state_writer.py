"""
状态写入模块

将状态机推断的行业状态和状态跃迁写入 Neo4j。
"""
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.knowledge.state_machine import IndustryState, StateTransition

logger = logging.getLogger(__name__)


def _looks_like_ts_code(s: str) -> bool:
    """判断字符串是否为股票代码格式"""
    return bool(
        s
        and len(s) >= 8
        and "." in s
        and s.replace(".", "").replace("-", "").isalnum()
    )


def write_state_to_neo4j(
    ts_code: str,
    state: "IndustryState",
    source_name: str,
    source_type: str,
) -> None:
    """将推断的行业状态写入 Company 节点的 properties"""
    try:
        from app.core.neo4j_client import run_write
        from app.knowledge.state_machine import describe_state

        entity_id = f"C:{ts_code}" if _looks_like_ts_code(ts_code) else f"CO:{ts_code}"
        run_write(
            """
            MATCH (n)
            WHERE n.entity_id = $entity_id
            SET n.industry_state = $state,
                n.state_description = $desc,
                n.state_source = $source_name,
                n.state_updated_at = datetime()
            """,
            {
                "entity_id": entity_id,
                "state": state.value,
                "desc": describe_state(state),
                "source_name": source_name,
            },
        )
        logger.debug("状态写入 Neo4j: %s → %s", entity_id, state.value)
    except Exception as e:
        logger.warning("状态写入 Neo4j 失败 [%s]: %s", ts_code, e)


def write_transition_to_neo4j(
    ts_code: str,
    transition: "StateTransition",
    source_name: str,
    source_type: str,
) -> None:
    """
    将状态跃迁写入 Neo4j。

    创建 Company 节点的 from_state → to_state STATE_TRANSITION 关系。
    """
    try:
        from app.core.neo4j_client import run_write
        from app.knowledge.state_machine import describe_state

        entity_id = f"C:{ts_code}" if _looks_like_ts_code(ts_code) else f"CO:{ts_code}"

        run_write(
            """
            # B9 fix: 使用 (n) 匹配所有节点，通过 entity_id 过滤（支持 CO:xxx 格式）
            MATCH (n)
            WHERE n.entity_id = $entity_id
            MERGE (n)-[r:STATE_TRANSITION {
                from_state: $from_state,
                to_state: $to_state,
            }]->(n)
            ON CREATE SET
                r.direction = $direction,
                r.evidence = $evidence,
                r.confidence = $confidence,
                r.source = $source_name,
                r.source_type = $source_type,
                r.created_at = datetime()
            ON MATCH SET
                r.updated_at = datetime()
            """,
            {
                "entity_id": entity_id,
                "from_state": transition.from_state.value,
                "to_state": transition.to_state.value,
                "direction": transition.direction,
                "evidence": transition.evidence[:200] if transition.evidence else "",
                "confidence": transition.confidence,
                "source_name": source_name,
                "source_type": source_type,
            },
        )
        logger.debug("状态跃迁写入 Neo4j: %s → %s", transition.from_state.value, transition.to_state.value)
    except Exception as e:
        logger.warning("状态跃迁写入 Neo4j 失败 [%s]: %s", ts_code, e)
