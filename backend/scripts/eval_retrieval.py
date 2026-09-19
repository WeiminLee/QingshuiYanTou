"""检索评估 runner：对 gold set 计算 Recall@k。

用法:
  python backend/scripts/eval_retrieval.py --backend semantic --k 20
  python backend/scripts/eval_retrieval.py --backend link --k 20

backend 说明:
  - semantic: 现有 Qdrant 向量检索基线（chunks 通道），作为 P0 基线；
  - link:     链接层 backend（Task 9/10 完成后接入 pull_history / scan_dimension）。

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


async def retrieve_link(entry: dict, k: int) -> set[str]:
    """链接层 backend：Task 9/10 完成后接入 pull_history / scan_dimension。"""
    from app.knowledge.linklayer.queries import pull_history, scan_dimension

    if entry["type"] == "timeline":
        result = await pull_history(entry["subject"], dimension=entry.get("dimension"), limit=k)
        return {it["evidence_id"] for it in result["items"]}
    result = await scan_dimension(entry["dimension"], scope=entry.get("scope"), limit=k)
    return {it["evidence_id"] for it in result["items"]}


async def retrieve_semantic(entry: dict, k: int) -> set[str]:
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
    return {r.payload.get("evidence_id") for r in results if r.payload.get("evidence_id")}


async def main() -> None:
    parser = argparse.ArgumentParser(description="对 gold set 计算 Recall@k / 命中率")
    parser.add_argument("--backend", choices=["link", "semantic"], required=True)
    parser.add_argument("--gold", default=DEFAULT_GOLD)
    parser.add_argument("--k", type=int, default=20)
    args = parser.parse_args()

    entries = json.loads(Path(args.gold).read_text(encoding="utf-8"))
    retrieve = retrieve_semantic if args.backend == "semantic" else retrieve_link
    recalls = []
    hits = []
    for entry in entries:
        got = await retrieve(entry, args.k)
        expected = set(entry["expected_evidence_ids"])
        recall = len(got & expected) / len(expected) if expected else 0.0
        hit = int(bool(got & expected))
        recalls.append(recall)
        hits.append(hit)
        print(f"{entry['query_id']}: Recall@{args.k} = {recall:.2f} hit={hit}")
    print(f"== {args.backend} mean Recall@{args.k} = {sum(recalls) / len(recalls):.3f}")
    print(f"== {args.backend} hit rate@{args.k} = {sum(hits) / len(hits):.3f}")


if __name__ == "__main__":
    asyncio.run(main())
