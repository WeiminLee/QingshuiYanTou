"""
小批量 KG 抽取测试脚本（增量版）

从 PostgreSQL 采样有 PDF 的公告，增量抽取 KG：
1. 下载 PDF → 计算 SHA256
2. 查询 MongoDB kg_file_index，hash 未变则跳过
3. 抽取 KG → 成功后写入 kg_file_index

用法:
  uv run --directory backend python scripts/sample_kg_extract.py
  uv run --directory backend python scripts/sample_kg_extract.py --resume  # 重新处理失败项
  uv run --directory backend python scripts/sample_kg_extract.py --n 20
"""
import argparse
import asyncio
import hashlib
import logging
import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# 保存原始代理环境变量（必须在导入任何 app 模块之前）
_ORIGINAL_PROXIES = {
    k: os.environ.get(k, "") for k in
    ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy")
}

import requests
from motor.motor_asyncio import AsyncIOMotorClient
from sqlalchemy import select

from app.core.database import async_session
from app.models.models import Announcement
from app.knowledge.kg_extractor import extract_text

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

CLOUD_BASE = "http://124.221.188.38:8080/api/v1"

# MongoDB kg_file_index 配置（从 .env 读取，支持认证）
from dotenv import load_dotenv
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"), verbose=False)
import os as _env_os
_MONGO_URL = _env_os.environ.get("MONGODB_URL", "mongodb://qingshui:qingshui123@localhost:27017/qingshui?authSource=admin")
_MONGO_DB  = "qingshui"
INDEX_COL = "kg_file_index"


def _restore_proxies() -> None:
    """恢复 os.environ 中的代理变量，让 requests 自然读取"""
    for k, v in _ORIGINAL_PROXIES.items():
        os.environ[k] = v


def _compute_bytes_hash(data: bytes) -> str:
    """计算 bytes 的 SHA256（用于云端 PDF 内容指纹）"""
    return hashlib.sha256(data).hexdigest()


def download_pdf(ann_id: str, file_url: str) -> bytes | None:
    """从云端下载 PDF 内容"""
    if file_url.startswith("/api/v1"):
        url = f"http://124.221.188.38:8080{file_url}"
    elif file_url.startswith("http"):
        url = file_url
    else:
        url = f"http://124.221.188.38:8080/api/v1/{file_url.lstrip('/')}"

    _restore_proxies()
    try:
        resp = requests.get(url, timeout=60)
        resp.raise_for_status()
        return resp.content
    except Exception as e:
        logger.warning(f"PDF 下载失败 ann_id={ann_id}: {e}")
        return None


def extract_pdf_text(pdf_bytes: bytes) -> str:
    """从 PDF bytes 提取纯文本"""
    import io
    try:
        import pdfplumber
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            pages = []
            for page in pdf.pages:
                text = page.extract_text() or ""
                if text.strip():
                    pages.append(text)
            return "\n".join(pages)
    except ImportError:
        logger.warning("pdfplumber 未安装，尝试 PyPDF2")
        try:
            from PyPDF2 import PdfReader
            reader = PdfReader(io.BytesIO(pdf_bytes))
            pages = []
            for page in reader.pages:
                text = page.extract_text() or ""
                if text.strip():
                    pages.append(text)
            return "\n".join(pages)
        except Exception as e:
            logger.error(f"PyPDF2 提取失败: {e}")
            return ""


# ── MongoDB kg_file_index 操作 ────────────────────────────────────────────────

async def _get_mongo_collection():
    client = AsyncIOMotorClient(_MONGO_URL)
    db = client[_MONGO_DB]
    col = db[INDEX_COL]
    # 确保索引（ignore_index_errors=True 防止权限不足时报错）
    try:
        await col.create_index("ann_id", unique=True)
        await col.create_index("status")
    except Exception as e:
        logger.warning("索引创建跳过（权限不足或已存在）: %s", e)
    return col


async def _check_duplicate(col, ann_id: str, file_hash: str) -> bool:
    """
    检查 ann_id 是否已抽取且 hash 未变。
    增量关键：同 ann_id + 同 hash → 跳过。
    """
    doc = await col.find_one({"ann_id": ann_id})
    if doc is None:
        return False
    if doc.get("status") == "done" and doc.get("file_hash") == file_hash:
        return True  # 已抽取且内容未变
    return False


async def _upsert_index(
    col,
    ann_id: str,
    file_hash: str,
    status: str,
    ts_code: str,
    title: str,
    entities_count: int = 0,
    relations_count: int = 0,
    error: str = "",
) -> None:
    """Upsert kg_file_index 记录（云端变体，以 ann_id 为主键）"""
    now = datetime.utcnow()
    doc = {
        "ann_id": ann_id,
        "file_hash": file_hash,
        "status": status,
        "ts_code": ts_code,
        "title": (title or "")[:200],
        "entities_count": entities_count,
        "relations_count": relations_count,
        "error": error[:500] if error else "",
        "schema_version": "v1.2",
        "parser_version": "v1.2",
        "updated_at": now,
    }
    if status == "done":
        doc["extracted_at"] = now

    await col.update_one(
        {"ann_id": ann_id},
        {"$set": doc},
        upsert=True,
    )


async def sample_and_extract(
    n: int = 5,
    dry_run: bool = False,
    resume: bool = False,
) -> dict:
    """采样公告，下载 PDF，增量 KG 抽取"""
    col = await _get_mongo_collection()

    # 1. 从 PG 采样（resume 模式：优先取失败/pending 的）
    async with async_session() as db:
        if resume:
            # resume：取所有有 PDF 的，不查 index（直接走覆盖逻辑）
            query = (
                select(Announcement)
                .where(Announcement.pdf_url.isnot(None))
                .where(Announcement.pdf_url != "")
                .where(Announcement.ts_code != "")
            )
        else:
            query = (
                select(Announcement)
                .where(Announcement.pdf_url.isnot(None))
                .where(Announcement.pdf_url != "")
                .where(Announcement.ts_code != "")
            )
        result = await db.execute(query.limit(n))
        rows = result.scalars().all()

    logger.info(f"采样到 {len(rows)} 条公告（resume={resume}）")
    if not rows:
        return {"status": "no_data", "processed": 0}

    results = []
    total_entities = 0
    total_relations = 0
    skipped_hash = 0

    for i, ann in enumerate(rows):
        logger.info(f"[{i+1}/{len(rows)}] {ann.ts_code} | {ann.title[:40] if ann.title else 'N/A'}")

        # 2. 下载 PDF
        pdf_bytes = download_pdf(ann.cninfo_id, ann.pdf_url)
        if not pdf_bytes:
            logger.warning("  PDF 下载失败，跳过")
            await _upsert_index(col, ann.cninfo_id, "", "pdf_failed",
                                ann.ts_code, ann.title, error="PDF download failed")
            results.append({"ann_id": ann.cninfo_id, "status": "pdf_failed"})
            continue

        file_hash = _compute_bytes_hash(pdf_bytes)
        file_size_kb = len(pdf_bytes) / 1024
        logger.info(f"  PDF 大小: {file_size_kb:.1f} KB | hash: {file_hash[:12]}...")

        # 3. 增量检查：hash 未变则跳过
        is_dup = await _check_duplicate(col, ann.cninfo_id, file_hash)
        if is_dup:
            logger.info("  [SKIP] ann_id=%s hash 未变，已抽取，跳过", ann.cninfo_id)
            skipped_hash += 1
            results.append({"ann_id": ann.cninfo_id, "status": "skipped_hash"})
            continue

        # 4. 提取文本
        text = extract_pdf_text(pdf_bytes)
        if not text or len(text) < 100:
            logger.warning(f"  文本提取失败或内容过少（{len(text)} 字符），跳过")
            await _upsert_index(col, ann.cninfo_id, file_hash, "text_empty",
                                ann.ts_code, ann.title, error=f"Text too short: {len(text)}")
            results.append({"ann_id": ann.cninfo_id, "status": "text_empty"})
            continue

        logger.info(f"  提取文本 {len(text)} 字符")

        # 5. KG 抽取
        if dry_run:
            logger.info("  [DRY-RUN] 跳过 KG 抽取")
            results.append({"ann_id": ann.cninfo_id, "status": "dry_run", "text_len": len(text)})
            continue

        try:
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                None,
                lambda: extract_text(
                    text=text,
                    ts_code=ann.ts_code,
                    source_name=ann.title or "cloud_pdf",
                    source_type="cninfo_announcement",
                    article_ref=ann.pdf_url,
                ),
            )
            ents = result.get("entities", [])
            rels = result.get("relations", [])
            total_entities += len(ents)
            total_relations += len(rels)

            # 成功后写入 index
            await _upsert_index(
                col, ann.cninfo_id, file_hash, "done",
                ann.ts_code, ann.title,
                entities_count=len(ents),
                relations_count=len(rels),
            )
            logger.info(f"  KG 结果: {len(ents)} 实体, {len(rels)} 关系 → indexed")
            results.append({
                "ann_id": ann.cninfo_id,
                "ts_code": ann.ts_code,
                "status": "success",
                "entities": len(ents),
                "relations": len(rels),
                "text_len": len(text),
                "file_hash": file_hash[:16],
            })
        except Exception as e:
            logger.exception(f"  KG 抽取失败: {e}")
            await _upsert_index(col, ann.cninfo_id, file_hash, "kg_failed",
                                ann.ts_code, ann.title, error=str(e))
            results.append({"ann_id": ann.cninfo_id, "status": "kg_failed", "error": str(e)})

    success = sum(1 for r in results if r.get("status") == "success")
    logger.info(
        f"\n完成：成功 {success}/{len(rows)} 条 | "
        f"实体 {total_entities} | 关系 {total_relations} | "
        f"hash跳过 {skipped_hash}"
    )
    return {
        "status": "done",
        "total": len(rows),
        "success": success,
        "skipped_hash": skipped_hash,
        "total_entities": total_entities,
        "total_relations": total_relations,
        "results": results,
    }


async def main():
    parser = argparse.ArgumentParser(description="小批量 KG 抽取测试（增量版）")
    parser.add_argument("--n", type=int, default=5, help="采样数量（默认 5）")
    parser.add_argument("--dry-run", action="store_true", help="仅采样不抽取")
    parser.add_argument("--resume", action="store_true",
                        help="重新处理（包括之前失败的，跳过已成功且 hash 未变的）")
    args = parser.parse_args()

    result = await sample_and_extract(
        n=args.n,
        dry_run=args.dry_run,
        resume=args.resume,
    )
    print("\n最终结果:")
    for k, v in result.items():
        if k != "results":
            print(f"  {k}: {v}")


if __name__ == "__main__":
    asyncio.run(main())
