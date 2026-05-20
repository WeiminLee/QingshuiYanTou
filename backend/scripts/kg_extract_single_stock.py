"""
针对单个股票的知识图谱抽取测试

用法:
  # 针对新雷能抽取 3 条
  python scripts/kg_extract_single_stock.py --ts-code 300593.SZ --n 3

  # 仅获取公告列表（dry-run）
  python scripts/kg_extract_single_stock.py --ts-code 300593.SZ --dry-run
"""
import argparse
import asyncio
import hashlib
import io
import logging
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"), verbose=False)

import requests
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import settings
from app.knowledge.kg_extractor import extract_text

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

CLOUD_BASE = "http://124.221.188.38:8080/api/v1"


def download_pdf(cninfo_id: str, file_url: str) -> bytes | None:
    """从云端下载 PDF 内容"""
    if file_url.startswith("/api/v1"):
        url = f"http://124.221.188.38:8080{file_url}"
    elif file_url.startswith("http"):
        url = file_url
    else:
        url = f"http://124.221.188.38:8080/api/v1/{file_url.lstrip('/')}"

    # 临时清除代理
    orig = {k: os.environ.get(k, "") for k in ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy")}
    for k in orig:
        os.environ[k] = ""
    try:
        resp = requests.get(url, timeout=60)
        resp.raise_for_status()
        return resp.content
    except Exception as e:
        logger.warning(f"PDF 下载失败 cninfo_id={cninfo_id}: {e}")
        return None
    finally:
        for k, v in orig.items():
            os.environ[k] = v


def extract_pdf_text(pdf_bytes: bytes, cninfo_id: str = "") -> str:
    """从 PDF bytes 提取纯文本"""
    # 调试：检查文件头
    if len(pdf_bytes) < 4:
        logger.warning(f"[{cninfo_id}] PDF bytes 太短: {len(pdf_bytes)}")
        return ""
    header = pdf_bytes[:4]
    logger.info(f"[{cninfo_id}] 文件头: {header} (预期 b'%PDF')")

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


async def extract_stock_kg(
    ts_code: str,
    n: int = 3,
    dry_run: bool = False,
) -> dict:
    """针对单个股票抽取 KG"""
    engine = create_async_engine(settings.database_url)

    # 1. 获取公告列表
    async with engine.connect() as conn:
        result = await conn.execute(
            text("""
                SELECT cninfo_id, title, pdf_url, announcement_type
                FROM announcements
                WHERE ts_code = :ts_code AND pdf_url IS NOT NULL AND pdf_url != ''
                LIMIT :n
            """),
            {"ts_code": ts_code, "n": n}
        )
        announcements = result.fetchall()

    logger.info(f"获取到 {len(announcements)} 条 {ts_code} 公告")

    results = []
    total_entities = 0
    total_relations = 0

    for i, (cninfo_id, title, pdf_url, ann_type) in enumerate(announcements):
        logger.info(f"[{i+1}/{len(announcements)}] {title[:50] if title else 'N/A'}...")

        # 2. 下载 PDF
        pdf_bytes = download_pdf(cninfo_id, pdf_url)
        if not pdf_bytes:
            logger.warning("  PDF 下载失败，跳过")
            results.append({"cninfo_id": cninfo_id, "status": "pdf_failed"})
            continue

        file_hash = hashlib.sha256(pdf_bytes).hexdigest()
        file_size_kb = len(pdf_bytes) / 1024
        logger.info(f"  PDF: {file_size_kb:.1f} KB | hash: {file_hash[:12]}...")

        # 3. 提取文本
        extracted_text = extract_pdf_text(pdf_bytes, cninfo_id)
        if not extracted_text or len(extracted_text) < 100:
            logger.warning(f"  文本提取失败（{len(extracted_text)} 字符），跳过")
            results.append({"cninfo_id": cninfo_id, "status": "text_empty"})
            continue

        logger.info(f"  提取文本 {len(extracted_text)} 字符")

        if dry_run:
            logger.info("  [DRY-RUN] 跳过 KG 抽取")
            results.append({"cninfo_id": cninfo_id, "status": "dry_run", "text_len": len(extracted_text)})
            continue

        # 4. KG 抽取
        try:
            loop = asyncio.get_event_loop()
            kg_result = await loop.run_in_executor(
                None,
                lambda: extract_text(
                    text=extracted_text,
                    ts_code=ts_code,
                    source_name=title or "pdf",
                    source_type="cninfo_announcement",
                    article_ref=pdf_url,
                ),
            )
            ents = kg_result.get("entities", [])
            rels = kg_result.get("relations", [])
            total_entities += len(ents)
            total_relations += len(rels)

            logger.info(f"  ✅ KG 结果: {len(ents)} 实体, {len(rels)} 关系")
            results.append({
                "cninfo_id": cninfo_id,
                "title": title[:50],
                "status": "success",
                "entities": len(ents),
                "relations": len(rels),
                "text_len": len(extracted_text),
            })
        except Exception as e:
            logger.exception(f"  ❌ KG 抽取失败: {e}")
            results.append({"cninfo_id": cninfo_id, "status": "kg_failed", "error": str(e)})

    success = sum(1 for r in results if r.get("status") == "success")
    logger.info(
        f"\n完成：成功 {success}/{len(announcements)} 条 | "
        f"实体 {total_entities} | 关系 {total_relations}"
    )

    await engine.dispose()
    return {
        "status": "done",
        "ts_code": ts_code,
        "total": len(announcements),
        "success": success,
        "total_entities": total_entities,
        "total_relations": total_relations,
        "results": results,
    }


async def main():
    parser = argparse.ArgumentParser(description="针对单个股票的知识图谱抽取测试")
    parser.add_argument("--ts-code", default="300593.SZ", help="股票代码（默认 300593.SZ 新雷能）")
    parser.add_argument("--n", type=int, default=3, help="抽取数量（默认 3）")
    parser.add_argument("--dry-run", action="store_true", help="仅获取公告列表，不抽取 KG")
    args = parser.parse_args()

    result = await extract_stock_kg(
        ts_code=args.ts_code,
        n=args.n,
        dry_run=args.dry_run,
    )

    print("\n" + "="*50)
    print(f"股票: {result['ts_code']}")
    print(f"抽取: {result['success']}/{result['total']} 条")
    print(f"实体: {result['total_entities']} | 关系: {result['total_relations']}")


if __name__ == "__main__":
    asyncio.run(main())
