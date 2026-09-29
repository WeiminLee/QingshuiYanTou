"""退役 legacy combined 抽取任务（架构迁移收尾）。

背景：H 集群迁移后 worker 只跑 link/vector（combined 是旧的 link+vector 一体
模式，已被拆分取代）。云侧 combined 处理随云侧 legacy worker 下线而停摆，
遗留一批 pending combined 长期滞留（最老可追到 2026-09-02，实测 1454 条）。

安全性：仅退役「对应 evidence 的 link 与 vector 均已 done/skipped」的
pending combined —— 抽取成果不缺，job 只是冗余台账。未覆盖的一律不动并打印
（交人工确认），绝不误弃未抽取数据。

幂等：第二遍无匹配即无操作。规则机械（无 LLM）。

用法（云端容器）：
  python -m scripts.retire_legacy_combined --dry-run
  python -m scripts.retire_legacy_combined --apply
"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

DONE_STATES = ("done", "skipped")


async def main() -> None:
    dry_run = "--dry-run" in sys.argv or "--apply" not in sys.argv

    from app.core.mongodb import get_mongo_db

    db = get_mongo_db()
    jobs = db["kg_extraction_jobs"]

    pending = await jobs.find(
        {"status": "pending", "job_type": "combined"},
        {"_id": 0, "job_id": 1, "evidence_id": 1},
    ).to_list(length=None)
    print(f"pending combined = {len(pending)}  (dry_run={dry_run})")

    now = datetime.now(UTC)
    retired = 0
    uncovered: list[str] = []

    for job in pending:
        evid = job.get("evidence_id") or ""
        # 覆盖判定：同 evidence 的 link 与 vector 均已成（done/skipped）
        link_ok = await jobs.count_documents(
            {"evidence_id": evid, "job_type": "link", "status": {"$in": DONE_STATES}},
            limit=1,
        )
        vector_ok = await jobs.count_documents(
            {"evidence_id": evid, "job_type": "vector", "status": {"$in": DONE_STATES}},
            limit=1,
        )
        if not (link_ok and vector_ok):
            uncovered.append(evid)
            continue
        if dry_run:
            retired += 1
            continue
        await jobs.update_one(
            {"job_id": job["job_id"], "status": "pending"},
            {
                "$set": {
                    "status": "skipped",
                    "error": "superseded by link+vector (combined 已退役)",
                    "finished_at": now,
                    "updated_at": now,
                }
            },
        )
        await db["kg_evidence"].update_one(
            {"evidence_id": evid},
            {"$set": {"extraction_status.combined": "skipped", "updated_at": now}},
        )
        retired += 1

    print(f"retired / to-retire = {retired}")
    print(f"uncovered (未动) = {len(uncovered)}")
    for evid in uncovered[:20]:
        print("  UNCOVERED", evid)


if __name__ == "__main__":
    asyncio.run(main())
