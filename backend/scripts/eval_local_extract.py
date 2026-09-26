# backend/scripts/eval_local_extract.py
"""本地抽取 A/B 评估:对照生产 kw_v2 缓存,给"本地 serve 的模型"打字段级 F1。

背景:2026-09-19 §12.1 横评只留了 F1 汇总表,分模型原始输出未归档;
本脚本把口径固化(参照 = 生产缓存、same prompt、same 解析器),一次写入 JSON 留档。

口径:
- 参照(视为"正确答案"): 云上生产 kw_v2 缓存(Qwen3.6-35B-A3B-FP8 抽取结果);
- 待评模型: 本地 OpenAI 兼容服务(如 vllm-metax / llama.cpp server),同 KEYWORD_SYSTEM_PROMPT、
  同 LLM_INPUT_MAX_CHARS 窗口、temperature=0;
- 集合匹配: company/product 按原文表面串(strip 后全等,大小写敏感——"不改写"纪律下
  大小写漂移计 miss);metric 按 name 集合比对;
- 空 vs 空 计 F1=1.0(口径内一致),另报告 both_empty 速率;
- 汇总取宏平均(逐 doc F1 再平均),与 §12.1 汇总口径一致;
- 采样: 默认 sort(evidence_id)+seed 洗牌——注意池子增长会改变洗牌结果,
  跨模型严格同题请用 --ids-file 钉死样本(推荐,可提交进仓库);
- 逐条完即写 .partial,长跑中断零损失。

在 d 集群 pod 上运行(pod 有 127.0.0.1:27018 云库正向隧道 + 本地 vllm/llama-server):
  cd /root/wq/backend && /root/wq/venv/bin/python -m scripts.eval_local_extract \
      --base-url http://127.0.0.1:8001/v1 --model qwen3-32b-awq \
      --ids-file /root/wq/pinned_sample_ids.json \
      --out /root/wq/eval_qwen32b_awq_pinned.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import random
import time
from statistics import mean

from app.config import settings  # noqa: F401  (加载 /root/wq/backend/.env)
from app.core.mongodb import get_mongo_db
from app.knowledge.linklayer.llm_extract import (
    KEYWORD_SYSTEM_PROMPT,
    LLM_INPUT_MAX_CHARS,
    parse_llm_json,
)
from openai import AsyncOpenAI

FIELDS = ("company", "product", "metric")


def _set_prf(pred: list, ref: list) -> dict:
    ref_s = {x for x in ref if x}
    pred_s = {x for x in pred if x}
    tp = len(ref_s & pred_s)
    p = tp / len(pred_s) if pred_s else 1.0
    r = tp / len(ref_s) if ref_s else 1.0
    f = 2 * p * r / (p + r) if (p + r) > 0 else 1.0
    return {
        "p": round(p, 4),
        "r": round(r, 4),
        "f1": round(f, 4),
        "miss": sorted(ref_s - pred_s),
        "extra": sorted(pred_s - ref_s),
    }


def _score_doc(pred: dict | None, ref: dict) -> dict:
    out: dict = {}
    for field in ("company", "product"):
        out[field] = _set_prf((pred or {}).get(field) or [], ref.get(field) or [])
    ref_names = [m.get("name") for m in ref.get("metric") or [] if isinstance(m, dict)]
    pred_names = [m.get("name") for m in ((pred or {}).get("metric") or []) if isinstance(m, dict)]
    out["metric"] = _set_prf(pred_names, ref_names)
    ref_empty = not ref.get("company") and not ref.get("product") and not ref.get("metric")
    pred_empty = pred is None or (
        not pred.get("company") and not pred.get("product") and not pred.get("metric")
    )
    out["both_empty"] = bool(ref_empty and pred_empty)
    return out


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--sample", type=int, default=40)
    ap.add_argument("--concurrency", type=int, default=8)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", default="/root/wq/eval_local_extract.json")
    ap.add_argument("--request-timeout", type=float, default=1800.0, dest="request_timeout")
    ap.add_argument("--ids-file", default=None, help="pinned sample ids (json list); overrides --sample/--seed")
    ap.add_argument(
        "--refs-file",
        default=None,
        help="离线样本文件（含 evidence_id/text_excerpt/ref），用于无 DB 通道的 worker 上评测；"
             "与 --ids-file 互斥，给出时完全跳过 Mongo",
    )
    args = ap.parse_args()

    if args.refs_file:
        # 离线模式：参照答案随样本一起从文件读入（worker 侧无 Mongo 通道）
        with open(args.refs_file, encoding="utf-8") as fh:
            picked = json.load(fh)
        for d in picked:
            d.setdefault("ref", {})
        print(f"offline refs: {len(picked)} docs from {args.refs_file}", flush=True)
    else:
        col = get_mongo_db()["kg_evidence"]
        proj = {"evidence_id": 1, "source_type": 1, "subject_hint": 1,
                "text_excerpt": 1, "keyword_extraction.result": 1}
        if args.ids_file:
            with open(args.ids_file, encoding="utf-8") as fh:
                pinned = json.load(fh)
            picked = await col.find({"evidence_id": {"$in": pinned}}, proj).to_list(len(pinned))
            print(f"pinned ids: requested {len(pinned)}, fetched {len(picked)}", flush=True)
        else:
            q = {"keyword_extraction.version": "kw_v2", "keyword_extraction.result": {"$exists": True}}
            pool = await col.find(q, {"evidence_id": 1, "source_type": 1}).to_list(500_000)
            pool.sort(key=lambda d: d["evidence_id"])
            rng = random.Random(args.seed)
            rng.shuffle(pool)
            irm = [d for d in pool if d["source_type"] == "irm"]
            ann = [d for d in pool if d["source_type"] == "announcement"]
            n_ann = min(len(ann), max(1, args.sample // 4))
            want = [d["evidence_id"] for d in (irm[: args.sample - n_ann] + ann[:n_ann])[: args.sample]]
            picked = await col.find({"evidence_id": {"$in": want}}, proj).to_list(len(want))
            rng.shuffle(picked)
            print(f"sampled: total={len(picked)} (pool {len(pool)})", flush=True)

    client = AsyncOpenAI(base_url=args.base_url, api_key="local", timeout=args.request_timeout)
    sem = asyncio.Semaphore(args.concurrency)
    partial: dict[str, dict] = {}
    partial_lock = asyncio.Lock()

    async def run_one(d: dict) -> dict:
        ref = d.get("ref") or (d.get("keyword_extraction") or {}).get("result") or {}
        text = (d.get("text_excerpt") or "")[:LLM_INPUT_MAX_CHARS]
        t0 = time.perf_counter()
        pred = None
        err = None
        if text.strip():
            try:
                async with sem:
                    resp = await client.chat.completions.create(
                        model=args.model,
                        messages=[{"role": "user", "content": f"{KEYWORD_SYSTEM_PROMPT}\n\n{text}"}],
                        temperature=0.0,
                        max_tokens=2048,
                        extra_body={"chat_template_kwargs": {"enable_thinking": False}},
                    )
                pred = parse_llm_json(resp.choices[0].message.content or "")
            except Exception as exc:  # noqa: BLE001
                err = f"{type(exc).__name__}: {exc}"
        dt = time.perf_counter() - t0
        sc = _score_doc(pred, ref)
        row = {
            "evidence_id": d.get("evidence_id"),
            "source_type": d.get("source_type"),
            "latency_s": round(dt, 2),
            "parse_ok": bool(text.strip()) and pred is not None,
            "error": err,
            **sc,
        }
        async with partial_lock:
            partial[row["evidence_id"]] = row
            with open(args.out + ".partial", "w", encoding="utf-8") as fh:
                json.dump(list(partial.values()), fh, ensure_ascii=False, default=str)
        return row

    t_start = time.perf_counter()
    results = await asyncio.gather(*(run_one(d) for d in picked))
    wall = time.perf_counter() - t_start

    report = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "model": args.model,
        "base_url": args.base_url,
        "reference": "cloud production kw_v2 cache (Qwen3.6-35B-A3B-FP8)"
        if not args.refs_file else f"offline refs file: {args.refs_file}",
        "sample_seed": args.seed,
        "ids_file": args.ids_file,
        "refs_file": args.refs_file,
        "n_docs": len(picked),
        "parse_failures": [r["evidence_id"] for r in results if r["error"]],
        "both_empty_rate": round(sum(1 for r in results if r["both_empty"]) / len(results), 4),
        "wall_s": round(wall, 2),
        "throughput_docs_per_min": round(len(picked) / max(wall / 60, 1e-9), 1),
        "macro_f1": {f: round(mean(r[f]["f1"] for r in results), 4) for f in FIELDS},
        "macro_f1_overall": round(mean(r[f]["f1"] for r in results for f in FIELDS), 4),
        "docs": results,
    }
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1, default=str)
    print(json.dumps({
        "model": args.model,
        "n": len(picked),
        "macro_f1": report["macro_f1"],
        "macro_f1_overall": report["macro_f1_overall"],
        "parse_failures": len(report["parse_failures"]),
        "both_empty_rate": report["both_empty_rate"],
        "throughput_docs_per_min": report["throughput_docs_per_min"],
        "out": args.out,
    }, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    asyncio.run(main())
