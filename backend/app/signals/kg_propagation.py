from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol

from app.signals.extractor import SignalCandidate
from app.signals.propagation import PropagationCandidate

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class KGEdge:
    src: str
    rel_type: str
    tgt: str
    weight: float = 1.0
    text: str = ""
    target_type: str = "entity"


@dataclass(frozen=True)
class KGPath:
    nodes: list[str]
    edges: list[KGEdge]


class KGPathProvider(Protocol):
    async def fetch_paths(self, entity: str, *, max_hops: int = 2) -> list[KGPath]:
        """Fetch KG paths from entity with at most max_hops edges."""


class Neo4jKGPathProvider:
    async def fetch_paths(self, entity: str, *, max_hops: int = 2) -> list[KGPath]:
        if not entity or max_hops < 1:
            return []
        max_hops = min(max_hops, 2)
        try:
            from app.core.neo4j_client import get_async_driver

            driver = await get_async_driver()
            async with driver.session() as session:
                records = await session.run(
                    """
                    MATCH p = (a)-[rels:RELATES*1..2]->(b)
                    WHERE toLower(a.name) CONTAINS toLower($entity)
                    WITH p, rels, reduce(score = 0.0, r IN rels | score + coalesce(r.weight, 1.0)) AS score
                    RETURN [node IN nodes(p) | node.name] AS path_nodes,
                           [idx IN range(0, size(rels)-1) | {
                             src: startNode(rels[idx]).name,
                             tgt: endNode(rels[idx]).name,
                             type: type(rels[idx]),
                             text: coalesce(rels[idx].text, rels[idx].description, type(rels[idx])),
                             weight: coalesce(rels[idx].weight, 1.0),
                             target_labels: labels(endNode(rels[idx]))
                           }] AS edges,
                           length(p) AS hops
                    ORDER BY score DESC
                    LIMIT 20
                    """,
                    entity=entity,
                )
                return neo4j_rows_to_paths(await records.data())
        except Exception as exc:
            logger.warning("[SignalKG] fetch_paths failed for %s: %s", entity, exc)
            return []


_UPSTREAM_RELS = {"UPSTREAM", "SUPPLIES", "SUPPLIES_TO", "COMPONENT_OF", "MATERIAL_FOR"}
_DOWNSTREAM_RELS = {"DOWNSTREAM", "CUSTOMER", "USED_BY", "APPLICATION", "APPLIES_TO"}
_COMPETITIVE_RELS = {"COMPETES_WITH", "PEER", "SAME_INDUSTRY", "SIMILAR_TO"}
_RISK_SIGNALS = {"risk"}


def neo4j_rows_to_paths(rows: list[dict]) -> list[KGPath]:
    paths: list[KGPath] = []
    for row in rows:
        nodes = [str(node) for node in row.get("path_nodes", []) if node]
        raw_edges = row.get("edges", []) or []
        edges: list[KGEdge] = []
        for raw in raw_edges:
            if not isinstance(raw, dict):
                continue
            edges.append(
                KGEdge(
                    src=str(raw.get("src") or ""),
                    rel_type=str(raw.get("type") or raw.get("rel_type") or "RELATES"),
                    tgt=str(raw.get("tgt") or ""),
                    weight=float(raw.get("weight") if raw.get("weight") is not None else 1.0),
                    text=str(raw.get("text") or ""),
                    target_type=_labels_to_target_type(raw.get("target_labels") or raw.get("labels") or []),
                )
            )
        path = KGPath(nodes=nodes, edges=edges)
        if _is_supported_path(path):
            paths.append(path)
    return paths


def build_kg_propagations(candidate: SignalCandidate, paths: list[KGPath]) -> list[PropagationCandidate]:
    propagations: list[PropagationCandidate] = []
    seen: set[tuple[str, str, str]] = set()
    for path in paths:
        if not _is_supported_path(path):
            continue
        target_name = path.nodes[-1]
        target_type = path.edges[-1].target_type or "entity"
        secondary_type = _secondary_type(candidate, path)
        direction = _direction(candidate, secondary_type)
        relation_path = _format_relation_path(path)
        key = (target_name, target_type, relation_path)
        if key in seen:
            continue
        seen.add(key)
        confidence = _path_confidence(candidate, path)
        propagations.append(
            PropagationCandidate(
                target_name=target_name,
                target_type=target_type,
                relation_path=relation_path,
                direction=direction,
                impact_horizon=_impact_horizon(candidate, secondary_type),
                confidence=confidence,
                reasoning=_reasoning(candidate, path, secondary_type),
                evidence_refs=[_evidence_ref(candidate)],
                metadata={
                    "secondary_type": secondary_type,
                    "path_nodes": list(path.nodes),
                    "path_edges": [
                        {
                            "src": edge.src,
                            "rel_type": edge.rel_type,
                            "tgt": edge.tgt,
                            "weight": edge.weight,
                            "text": edge.text,
                        }
                        for edge in path.edges
                    ],
                    "path_hops": len(path.edges),
                    "primary_signal_type": candidate.signal_type,
                    "primary_subject": candidate.subject_name,
                },
            )
        )
    propagations.sort(key=lambda item: item.confidence, reverse=True)
    return propagations


def _is_supported_path(path: KGPath) -> bool:
    if not path.nodes or not path.edges:
        return False
    if len(path.edges) > 2:
        return False
    if len(path.nodes) != len(path.edges) + 1:
        return False
    return True


def _labels_to_target_type(labels: list) -> str:
    normalized = {str(label).lower() for label in labels}
    if "company" in normalized:
        return "company"
    if "product" in normalized:
        return "product"
    if "concept" in normalized:
        return "concept"
    if "industry" in normalized:
        return "industry"
    if "metric" in normalized:
        return "metric"
    if "technology" in normalized:
        return "technology"
    if "application" in normalized:
        return "application"
    return "entity"


def _secondary_type(candidate: SignalCandidate, path: KGPath) -> str:
    rels = {edge.rel_type.upper() for edge in path.edges}
    if candidate.signal_type in _RISK_SIGNALS:
        return "risk_contagion"
    if rels & _UPSTREAM_RELS:
        return "supply_chain_validation"
    if rels & _DOWNSTREAM_RELS:
        return "customer_demand_validation"
    if rels & _COMPETITIVE_RELS:
        return "competitive_readthrough"
    if candidate.signal_type in {"policy", "capacity", "capex"}:
        return "industry_readthrough"
    return "expectation_gap_candidate_unverified"


def _direction(candidate: SignalCandidate, secondary_type: str) -> str:
    if candidate.polarity == "risk" or secondary_type == "risk_contagion":
        return "risk"
    if secondary_type in {
        "industry_readthrough",
        "supply_chain_validation",
        "customer_demand_validation",
        "expectation_gap_candidate_unverified",
    }:
        return "beneficiary"
    if secondary_type == "competitive_readthrough":
        return "uncertain"
    return "uncertain"


def _impact_horizon(candidate: SignalCandidate, secondary_type: str) -> str:
    if candidate.signal_type in {"risk"}:
        return "immediate"
    if candidate.signal_type in {"mass_production", "order", "earnings"}:
        return "short"
    if secondary_type == "industry_readthrough":
        return "medium"
    return "short"


def _path_confidence(candidate: SignalCandidate, path: KGPath) -> float:
    edge_score = sum(max(0.0, min(float(edge.weight), 1.0)) for edge in path.edges) / len(path.edges)
    primary_score = max(0.0, min(candidate.strength / 100, 1.0))
    source_score = max(0.0, min(candidate.confidence, 1.0))
    hops_penalty = 0.04 * (len(path.edges) - 1)
    score = source_score * 0.3 + primary_score * 0.3 + edge_score * 0.4 - hops_penalty
    return round(max(0.0, min(score, 1.0)), 3)


def _format_relation_path(path: KGPath) -> str:
    parts: list[str] = []
    for index, edge in enumerate(path.edges):
        if index == 0:
            parts.append(edge.src)
        label = edge.text or edge.rel_type
        parts.append(f"-[{label}]->")
        parts.append(edge.tgt)
    return " ".join(parts)


def _reasoning(candidate: SignalCandidate, path: KGPath, secondary_type: str) -> str:
    target = path.nodes[-1]
    if secondary_type == "supply_chain_validation":
        return f"{candidate.subject_name} 的{candidate.signal_type}信号沿 KG 上游路径传导，可能验证 {target} 的需求或订单弹性。"
    if secondary_type == "customer_demand_validation":
        return f"{candidate.subject_name} 的{candidate.signal_type}信号沿 KG 下游/客户路径传导，可能验证 {target} 的需求变化。"
    if secondary_type == "competitive_readthrough":
        return f"{candidate.subject_name} 的变化通过 KG 同业/竞品关系映射到 {target}，需要比较披露节奏和市场反应。"
    if secondary_type == "risk_contagion":
        return f"{candidate.subject_name} 的风险信号沿 KG 路径传导到 {target}，需要检查同链条风险暴露。"
    if secondary_type == "industry_readthrough":
        return f"{candidate.subject_name} 的信号沿 KG 行业路径传导，可能说明 {target} 的景气或投入预期变化。"
    return f"{candidate.subject_name} 的一阶信号沿 KG 路径传导到 {target}，可作为预期差候选但仍需验证。"


def _evidence_ref(candidate: SignalCandidate) -> dict:
    return {
        "source_type": candidate.source_type,
        "source_id": candidate.source_id,
        "source_title": candidate.source_title,
        "source_url": candidate.source_url,
        "evidence_excerpt": candidate.evidence_excerpt,
        "evidence_id": candidate.metadata.get("evidence_id") if isinstance(candidate.metadata, dict) else None,
    }
