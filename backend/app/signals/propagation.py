from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.signals.extractor import SignalCandidate


@dataclass(frozen=True)
class PropagationCandidate:
    target_name: str
    target_type: str
    relation_path: str
    direction: str
    impact_horizon: str
    confidence: float
    reasoning: str
    evidence_refs: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


def build_lightweight_propagations(candidate: SignalCandidate) -> list[PropagationCandidate]:
    signal_type = candidate.signal_type
    if signal_type == "policy":
        return [
            PropagationCandidate(
                target_name=candidate.subject_name,
                target_type="concept",
                relation_path="政策主题 -> 产业投入 -> 相关供应链",
                direction="beneficiary",
                impact_horizon="medium",
                confidence=0.68,
                reasoning="政策强度提升可能改善相关产业链的中期需求预期。",
            )
        ]
    if signal_type == "capex":
        return [
            PropagationCandidate(
                target_name="相关供应链",
                target_type="sector",
                relation_path="资本开支增加 -> 订单能见度提升 -> 供应链盈利弹性",
                direction="beneficiary",
                impact_horizon="short",
                confidence=0.7,
                reasoning="大客户资本开支增加通常会提升供应链订单兑现概率。",
            )
        ]
    if signal_type == "mass_production":
        return [
            PropagationCandidate(
                target_name=candidate.subject_name,
                target_type="product",
                relation_path="量产确认 -> 订单兑现概率提升 -> 供应链需求增强",
                direction="beneficiary",
                impact_horizon="short",
                confidence=0.72,
                reasoning="量产从验证阶段进入交付阶段，可能改变市场对兑现节奏的预期。",
            )
        ]
    if signal_type == "risk":
        return [
            PropagationCandidate(
                target_name=candidate.subject_name,
                target_type="company",
                relation_path="风险事件 -> 短期兑现承压 -> 持仓波动风险",
                direction="risk",
                impact_horizon="immediate",
                confidence=0.72,
                reasoning="风险事件可能影响短期业绩兑现或估值稳定性。",
            )
        ]
    return [
        PropagationCandidate(
            target_name=candidate.subject_name,
            target_type=candidate.subject_type,
            relation_path="信号变化 -> 预期修正 -> 研究下钻",
            direction="uncertain",
            impact_horizon="medium",
            confidence=0.55,
            reasoning="该信号需要结合知识库、持仓和市场数据进一步验证。",
        )
    ]
