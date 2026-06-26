"""
对重置为 pending 的文件执行 KG 抽取（单次运行）

用法:
  uv run --directory backend python scripts/run_extraction.py

说明:
  读取 kg_file_index 中所有 status=pending 的文件，逐个执行抽取。
  抽取完成后更新 kg_file_index 状态为 done/failed。
"""

import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from motor.motor_asyncio import AsyncIOMotorClient

from app.knowledge.kg_extractor import extract_document_async

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def _load_env() -> dict:
    env = {}
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.exists():
        raw = env_path.read_bytes().decode("utf-8", errors="replace")
        for line in raw.splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip()
    return env


async def run_extraction():
    env = _load_env()
    mongo_url = env.get("MONGODB_URL", "")
    client = AsyncIOMotorClient(mongo_url)
    db = client.get_database()
    coll = db["kg_file_index"]

    pending = []
    async for doc in coll.find({"status": "pending"}, {"file_path": 1, "file_name": 1, "ts_code": 1}):
        pending.append(doc)

    if not pending:
        print("没有 pending 文件，跳过")
        client.close()
        return

    print(f"找到 {len(pending)} 个待抽取文件：")
    for p in pending:
        print(f"  {p['file_name']}")

    for doc in pending:
        fp = doc["file_path"]
        fname = doc["file_name"]
        ts_code = doc.get("ts_code") or "INDUSTRY"
        print(f"\n>>> 抽取: {fname}")

        try:
            p = Path(fp)
            if not p.exists():
                raise FileNotFoundError(f"文件不存在: {fp}")

            await coll.update_one({"file_path": fp}, {"$set": {"status": "extracting"}})
            result = await extract_document_async(
                file_path=str(p),
                ts_code=ts_code,
                source_name=fname,
                source_type="uploaded_doc",
            )
            n_ent = result.get("entities_created", 0) + result.get("entities_updated", 0)
            n_rel = result.get("relations_created", 0) + result.get("relations_updated", 0)
            await coll.update_one(
                {"file_path": fp},
                {
                    "$set": {
                        "status": "done",
                        "entities_count": n_ent,
                        "relations_count": n_rel,
                    }
                },
            )
            print(f"  ✓ 完成: {n_ent} 实体, {n_rel} 关系")

        except Exception as e:
            await coll.update_one({"file_path": fp}, {"$set": {"status": "failed", "error": str(e)[:500]}})
            print(f"  ✗ 失败: {e}")

    stats = coll.aggregate([{"$group": {"_id": "$status", "count": {"$sum": 1}}}])
    print("\n最终状态：")
    async for r in stats:
        print(f"  {r['_id']}: {r['count']}")

    client.close()
    print("\n✓ 全部完成")


if __name__ == "__main__":
    asyncio.run(run_extraction())
