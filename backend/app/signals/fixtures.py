from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.signals.evidence_ingestion import _upsert_signal_records, extract_evidence_signal_records_with_kg
from app.signals.kg_propagation import KGEdge, KGPath


class StaticKGPathProvider:
    def __init__(self, paths_by_entity: dict[str, list[KGPath]]):
        self._paths_by_entity = paths_by_entity

    async def fetch_paths(self, entity: str, *, max_hops: int = 2) -> list[KGPath]:
        return [path for path in self._paths_by_entity.get(entity, []) if len(path.edges) <= max_hops]


def build_concept_board_fixture_records(concept: str = "optical_module") -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    evidence_items, provider = _fixture_inputs(concept)
    return _extract_fixture_records_sync(evidence_items, provider)


async def build_concept_board_fixture_records_async(
    concept: str = "optical_module",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    evidence_items, provider = _fixture_inputs(concept)
    return await _extract_fixture_records(evidence_items, provider)


async def seed_concept_board_fixture(session: AsyncSession, concept: str = "optical_module") -> dict[str, int | str]:
    signals, propagations = await build_concept_board_fixture_records_async(concept)
    signals_upserted, propagations_upserted = await _upsert_signal_records(session, signals, propagations)
    await session.commit()
    return {
        "concept": concept,
        "signals_upserted": signals_upserted,
        "propagations_upserted": propagations_upserted,
    }


async def _extract_fixture_records(
    evidence_items: list[dict[str, Any]],
    provider: StaticKGPathProvider,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    all_signals: list[dict[str, Any]] = []
    all_propagations: list[dict[str, Any]] = []

    for evidence in evidence_items:
        signals, propagations = await extract_evidence_signal_records_with_kg(evidence, provider)
        all_signals.extend(signals)
        all_propagations.extend(propagations)
    return all_signals, all_propagations


def _extract_fixture_records_sync(
    evidence_items: list[dict[str, Any]],
    provider: StaticKGPathProvider,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    import asyncio

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(_extract_fixture_records(evidence_items, provider))
    raise RuntimeError("build_concept_board_fixture_records cannot run inside an active event loop")


def _fixture_inputs(concept: str) -> tuple[list[dict[str, Any]], StaticKGPathProvider]:
    if concept != "optical_module":
        raise ValueError(f"unsupported concept fixture: {concept}")

    evidence_items = [
        {
            "evidence_id": "EV:fixture:optical:800g-delivery",
            "source_type": "announcement",
            "source_name": "fixture公告",
            "source_id": "fixture-800g-delivery",
            "text_excerpt": "公司 800G 光模块已进入批量交付阶段，客户导入进展顺利。",
            "subject_hint": {"title": "中际旭创 800G 光模块批量交付"},
            "source_ref": {"url": "fixture://optical-module/800g-delivery"},
            "metadata": {"tags": ["中际旭创"], "fixture": True, "concept": concept},
        },
        {
            "evidence_id": "EV:fixture:optical:capex",
            "source_type": "news",
            "source_name": "fixture新闻",
            "source_id": "fixture-ai-capex",
            "text_excerpt": "北美云厂商资本开支显著增加，AI 算力投入继续上修。",
            "subject_hint": {"title": "北美云厂商 AI CAPEX 增加"},
            "source_ref": {"url": "fixture://optical-module/ai-capex"},
            "metadata": {"tags": ["北美云厂商"], "fixture": True, "concept": concept},
        },
    ]

    provider = StaticKGPathProvider(
        {
            "中际旭创": [
                KGPath(
                    nodes=["中际旭创", "800G光模块", "光芯片"],
                    edges=[
                        KGEdge(src="中际旭创", rel_type="RELATES", tgt="800G光模块", weight=0.92, text="生产 800G 光模块", target_type="product"),
                        KGEdge(src="800G光模块", rel_type="UPSTREAM", tgt="光芯片", weight=0.84, text="上游依赖光芯片", target_type="concept"),
                    ],
                ),
                KGPath(
                    nodes=["中际旭创", "800G光模块", "高速PCB"],
                    edges=[
                        KGEdge(src="中际旭创", rel_type="RELATES", tgt="800G光模块", weight=0.92, text="生产 800G 光模块", target_type="product"),
                        KGEdge(src="800G光模块", rel_type="UPSTREAM", tgt="高速PCB", weight=0.78, text="高速传输依赖 PCB", target_type="concept"),
                    ],
                ),
            ],
            "北美云厂商": [
                KGPath(
                    nodes=["北美云厂商", "AI算力基础设施", "800G光模块"],
                    edges=[
                        KGEdge(src="北美云厂商", rel_type="CAPEX_TO", tgt="AI算力基础设施", weight=0.86, text="资本开支投向 AI 算力", target_type="concept"),
                        KGEdge(src="AI算力基础设施", rel_type="DOWNSTREAM", tgt="800G光模块", weight=0.8, text="算力建设拉动高速光模块", target_type="product"),
                    ],
                )
            ],
        }
    )
    return evidence_items, provider
