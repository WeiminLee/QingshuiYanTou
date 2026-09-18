# backend/scripts/backfill_keyword_links.py
"""全量回填链接层：遍历 kg_evidence，逐条建链。支持 --limit / --dry-run / --sample。

断点续跑：只处理尚无 keyword_extraction 缓存的 evidence（LLM 浅提取成功后会写回
该缓存，见 app/knowledge/linklayer/llm_extract.py），已处理的条目自动跳过；
幂等：link PK 冲突 do nothing，重复执行无新增。

用法：
  cd backend && uv run python -m scripts.backfill_keyword_links --limit 100 --dry-run
  cd backend && uv run python -m scripts.backfill_keyword_links --limit 20
"""

from __future__ import annotations

import argparse
import asyncio
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
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip())


_load_env()


async def _collect_evidence_ids(svc, limit: int) -> list[str]:
    """收集待回填的 evidence_id：无 keyword_extraction 缓存 = 尚未回填。"""
    # EvidenceService 未暴露公开集合句柄，直接取其内部 evidence 集合（构造时已连好 db）
    query = {"keyword_extraction": {"$exists": False}}
    cursor = svc._evidence.find(query, {"evidence_id": 1}).limit(limit or 0)
    return [doc["evidence_id"] async for doc in cursor]


async def main() -> None:
    parser = argparse.ArgumentParser(description="全量回填链接层 link_links")
    parser.add_argument("--limit", type=int, default=0, help="最多处理条数，0=全部")
    parser.add_argument("--dry-run", action="store_true", help="只列出将回填的 evidence_id，不写入")
    parser.add_argument("--sample", type=int, default=0, help="dry-run 时最多打印的 evidence_id 条数，0=全部")
    args = parser.parse_args()

    from app.core.database import async_session
    from app.knowledge.evidence_service import EvidenceService
    from app.knowledge.linklayer.ingest import ingest_evidence

    svc = EvidenceService()
    evidence_ids = await _collect_evidence_ids(svc, args.limit)

    if args.dry_run:
        shown = evidence_ids[: args.sample] if args.sample > 0 else evidence_ids
        for evidence_id in shown:
            print(f"[dry-run] {evidence_id}")
        print(f"[dry-run] 待回填共 {len(evidence_ids)} 条（示例 {len(shown)} 条）")
        return

    done = failed = 0
    async with async_session() as session:
        for evidence_id in evidence_ids:
            try:
                result = await ingest_evidence(evidence_id, _session=session)
                done += 1
                print(f"{evidence_id}: {result}")
            except Exception as exc:  # 单条失败不中断
                failed += 1
                print(f"FAIL {evidence_id}: {exc}")
    print(f"done={done} failed={failed}")


if __name__ == "__main__":
    asyncio.run(main())
