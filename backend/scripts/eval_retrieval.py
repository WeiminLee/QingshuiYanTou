"""检索评估 runner：对 gold set 计算 Recall@k / 命中率 / MRR。

用法:
  python backend/scripts/eval_retrieval.py --backend semantic --k 20
  python backend/scripts/eval_retrieval.py --backend link --k 20

backend 说明:
  - semantic: 现有 Qdrant 向量检索基线（chunks 通道），作为 P0 基线；
  - link:     链接层 backend（Task 9/10 完成后接入 pull_history / scan_dimension）。

口径说明（为何以命中率/MRR 为主、Recall 仅作参考）:
  cross_section 类 gold 只标注了少量「代表性」证据（如 3 条），而候选池
  可达数百（实测 cross_section-margin-001 候选 875），Recall@k 分母是标注数、
  分子是标注命中数，天然偏低且对 k 极敏感，无法反映真实检索质量。
  命中率（top-k 内是否至少命中一条）与 MRR（首条命中的排名倒数）对
  「标注不全但池很大」的场景更稳健，故作为主口径输出；跨类型均值也一并给出。

数据收集协议（回填真实 evidence_id）:
  gold set 中的 expected_evidence_ids / hard_negative_evidence_ids 目前是两类占位：
  1. "<真实evidence_id_N>" —— brief 中的 worked example 占位；
  2. "EV:<64位hex>"       —— 格式样例 ID（sha256("<query_id>:<n>")），并非真实数据。
  占位状态下 Recall 数字无意义。操作员须按以下步骤回填真实 ID 后再运行评估：

  1. 从 minishare_announcements 池选真实公司（或直接使用条目 subject）；
  2. 在 Mongo 中检索该公司证据：
     db.kg_evidence.find({"subject_hint.ts_code": "<ts_code>"})
     （subject_hint 为 {"ts_code", "company_name"} 结构；可再按 text_excerpt /
     source_name 中的关键词过滤，如 "产线" "毛利率"）；
  3. 逐条人工确认相关性（时间线类看演进覆盖，横截面类看跨公司命中）后，
     将真实 evidence_id（格式 "EV:" + sha256，见 app/knowledge/evidence.py
     的 stable_evidence_id）替换进 expected_evidence_ids；
  4. hard_negative_evidence_ids 可选，预留后续精细评估，暂不参与 Recall@k。
"""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _load_env() -> None:
    """加载 backend/.env（app.config 只读 cwd 的 .env，从仓库根运行时须显式加载）。"""
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_bytes().decode("utf-8", errors="replace").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())


_load_env()

DEFAULT_GOLD = str(Path(__file__).resolve().parent.parent / "eval" / "gold_set_v1.json")


async def retrieve_link(entry: dict, k: int) -> list[str]:
    """链接层 backend：按排名返回 evidence_id 列表（去重保序，供 MRR 计算）。"""
    from app.knowledge.linklayer.queries import pull_history, scan_dimension

    if entry["type"] == "timeline":
        result = await pull_history(entry["subject"], dimension=entry.get("dimension"), limit=k)
    else:
        result = await scan_dimension(entry["dimension"], scope=entry.get("scope"), limit=k)
    return _dedup([it["evidence_id"] for it in result["items"]])


async def retrieve_semantic(entry: dict, k: int) -> list[str]:
    """基线 backend：doc_chunks 通道纯向量检索（与 docstring 声明一致）。

    不用 hybrid_vector_search：其 RRF 合并把 entities/relations 的结果
    （payload 无 evidence_id，永不命中）混进 global top-k，压缩 chunks
    排名并系统性低估基线。评估语义召回只与本 lane 的 evidence 向量有关。
    """
    from app.knowledge.vector_client import (
        COLLECTION_CHUNKS,
        get_embedding_model,
        get_vector_client,
    )

    embedder = get_embedding_model()
    q_vec = (await embedder.aembed([entry["question"]]))[0]
    results = get_vector_client().search(
        collection=COLLECTION_CHUNKS, query_vector=q_vec, top_k=k
    )
    return _dedup([r.payload.get("evidence_id") for r in results if r.payload.get("evidence_id")])


def _dedup(seq: list[str]) -> list[str]:
    """去重保序：MRR 依赖首次出现位置。"""
    seen: set[str] = set()
    out: list[str] = []
    for x in seq:
        if x and x not in seen:
            seen.add(x)
            out.append(x)
    return out


def _reciprocal_rank(got: list[str], expected: set[str]) -> float:
    """首条命中（expected ∩ got）的排名倒数；无命中返回 0。"""
    for rank, evid in enumerate(got, start=1):
        if evid in expected:
            return 1.0 / rank
    return 0.0


async def main() -> None:
    parser = argparse.ArgumentParser(description="对 gold set 计算 Recall@k / 命中率 / MRR")
    parser.add_argument("--backend", choices=["link", "semantic"], required=True)
    parser.add_argument("--gold", default=DEFAULT_GOLD)
    parser.add_argument("--k", type=int, default=20)
    args = parser.parse_args()

    entries = json.loads(Path(args.gold).read_text(encoding="utf-8"))
    retrieve = retrieve_semantic if args.backend == "semantic" else retrieve_link
    recalls: list[float] = []
    hits: list[int] = []
    rrs: list[float] = []
    by_type: dict[str, list[int]] = {}
    for entry in entries:
        got = await retrieve(entry, args.k)
        expected = set(entry["expected_evidence_ids"])
        inter = set(got) & expected
        recall = len(inter) / len(expected) if expected else 0.0
        hit = int(bool(inter))
        rr = _reciprocal_rank(got, expected)
        recalls.append(recall)
        hits.append(hit)
        rrs.append(rr)
        by_type.setdefault(entry.get("type", "?"), []).append(hit)
        print(
            f"{entry['query_id']}: Recall@{args.k} = {recall:.2f} "
            f"hit={hit} rr={rr:.2f} (found={len(got)})"
        )
    n = len(entries)
    print(f"== {args.backend} mean Recall@{args.k} = {sum(recalls) / n:.3f}")
    print(f"== {args.backend} hit rate@{args.k} = {sum(hits) / n:.3f}")
    print(f"== {args.backend} MRR@{args.k} = {sum(rrs) / n:.3f}")
    print(f"-- {args.backend} hit rate by type:")
    for t, hs in sorted(by_type.items()):
        print(f"   {t:<16} {sum(hs) / len(hs):.3f}  (n={len(hs)})")


if __name__ == "__main__":
    asyncio.run(main())
