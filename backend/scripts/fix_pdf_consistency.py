#!/usr/bin/env python3
"""
修复本地 PDF 与数据库的一致性问题

策略：
1. 如果本地 PDF 能匹配到数据库记录（通过 cninfo_id），更新 file_path
2. 如果本地 PDF 在数据库中完全不存在，回补数据库记录并复用本地 PDF
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from urllib.parse import unquote, urlparse

import psycopg2

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def get_db_config():
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url:
        return {
            "host": "localhost",
            "port": 5433,
            "database": "qingshui",
            "user": "qingshui",
            "password": "qingshui123",
        }
    parsed = urlparse(database_url)
    return {
        "host": parsed.hostname or "localhost",
        "port": parsed.port or 5432,
        "database": parsed.path.lstrip("/") or "qingshui",
        "user": parsed.username or "qingshui",
        "password": parsed.password or "",
    }


def extract_ann_info(filename: str) -> dict | None:
    """从文件名解析公告信息。

    格式: ann_TS_CODE_YYYYMMDD_id_title.pdf
    返回: {"ts_code": ..., "ann_date": ..., "cninfo_id_prefix": ..., "title": ...}
    """
    try:
        # 去掉 .pdf 后缀
        name = filename.replace(".pdf", "")
        parts = name.split("_", 4)
        if len(parts) < 5:
            return None

        ts_code = parts[1]
        ann_date_str = parts[2]
        ann_id = parts[3]
        title = unquote(parts[4]) if "%" in parts[4] else parts[4]

        # 解析日期
        if len(ann_date_str) == 8 and ann_date_str.isdigit():
            ann_date = f"{ann_date_str[:4]}-{ann_date_str[4:6]}-{ann_date_str[6:8]}"
        else:
            return None

        return {
            "ts_code": ts_code,
            "ann_date": ann_date,
            "ann_id": ann_id,
            "title": title,
            "cninfo_id_prefix": f"ann_{ts_code}_{ann_date_str}_{ann_id}",
        }
    except Exception:
        return None


def fix_pdf_consistency():
    """修复 PDF 与数据库一致性"""
    db_config = get_db_config()
    notices_dir = Path("/run/media/lwm/0E27099B0E27099B/qingshui_data/notices")

    conn = psycopg2.connect(**db_config)
    cursor = conn.cursor()

    target_types = (
        "annual_report",
        "half_report",
        "quarter_report",
        "research_survey",
        "ma_activity",
        "investment",
    )

    print("=" * 70)
    print("  修复 PDF 与数据库一致性")
    print("=" * 70)
    print()

    # 1. 获取数据库所有 file_path
    cursor.execute("SELECT file_path FROM announcements WHERE file_path IS NOT NULL AND file_path != ''")
    db_paths = set(row[0] for row in cursor.fetchall() if row[0])

    # 2. 获取数据库所有公告（用于匹配）
    cursor.execute(
        """
        SELECT cninfo_id, ts_code, ann_date, title, file_path
        FROM announcements
        WHERE announcement_type IN %s AND source_type = 'minishare'
    """,
        (target_types,),
    )
    db_anns = {
        row[0]: {
            "cninfo_id": row[0],
            "ts_code": row[1],
            "ann_date": str(row[2]),
            "title": row[3],
            "file_path": row[4],
        }
        for row in cursor.fetchall()
    }

    # 构建 title 索引（用于非标准文件名匹配）
    db_anns_by_title = {}
    for ann in db_anns.values():
        if ann["title"]:
            # 精确匹配
            db_anns_by_title[ann["title"]] = ann
            # 部分匹配（title 包含关系）
            short_title = ann["title"][:20] if len(ann["title"]) > 20 else ann["title"]
            if short_title not in db_anns_by_title:
                db_anns_by_title[short_title] = ann

    print(f"  数据库公告总数: {len(db_anns)}")
    print(f"  数据库有 file_path: {len(db_paths)}")

    # 3. 扫描本地 PDF
    local_pdfs = list(notices_dir.rglob("*.pdf"))
    print(f"  本地 PDF 总数: {len(local_pdfs)}")

    # 4. 分类处理
    already_synced = []  # 本地有，数据库也有且 file_path 正确
    need_update_by_cninfo = []  # 通过 cninfo_id 匹配
    need_update_by_title = []  # 通过 title 匹配
    need_insert = []  # 完全新记录

    for pdf in local_pdfs:
        pdf_str = str(pdf)
        filename = Path(pdf).stem

        # 检查是否已同步
        if pdf_str in db_paths:
            already_synced.append(pdf)
            continue

        # 尝试解析标准格式
        info = extract_ann_info(filename)
        if info:
            # 在数据库中查找 cninfo_id 匹配
            matched = None
            for cninfo_id, ann in db_anns.items():
                if info["cninfo_id_prefix"] in cninfo_id:
                    matched = ann
                    break

            if matched:
                need_update_by_cninfo.append((pdf, matched))
            else:
                # 用 ts_code + date + title 匹配
                matched = None
                for ann in db_anns.values():
                    if (
                        ann["ts_code"] == info["ts_code"]
                        and ann["ann_date"][:10] == info["ann_date"]
                        and ann["title"]
                        and info["title"] in ann["title"]
                    ):
                        matched = ann
                        break
                if matched:
                    need_update_by_title.append((pdf, matched))
                else:
                    need_insert.append((pdf, info))
        else:
            # 非标准格式，尝试用 title 匹配
            parts = filename.split("_", 1)
            if len(parts) >= 2:
                title = unquote(parts[1]) if "%" in parts[1] else parts[1]
                if title in db_anns_by_title:
                    need_update_by_title.append((pdf, db_anns_by_title[title]))
                else:
                    # 尝试部分匹配
                    for db_title, ann in db_anns_by_title.items():
                        if db_title and title and (db_title in title or title in db_title):
                            need_update_by_title.append((pdf, ann))
                            break
                    else:
                        need_insert.append((pdf, {"title": title}))

    print()
    print("  状态分析:")
    print(f"    已同步（无需处理）: {len(already_synced)}")
    print(f"    需要更新 file_path (cninfo_id): {len(need_update_by_cninfo)}")
    print(f"    需要更新 file_path (title): {len(need_update_by_title)}")
    print(f"    需要新增记录: {len(need_insert)}")
    print()

    # 5. 执行修复

    # 5.1 更新 file_path (cninfo_id)
    if need_update_by_cninfo:
        print("  更新 file_path (cninfo_id 匹配)...")
        updated = 0
        for pdf, ann in need_update_by_cninfo:
            try:
                cursor.execute(
                    """
                    UPDATE announcements
                    SET file_path = %s
                    WHERE cninfo_id = %s
                """,
                    (str(pdf), ann["cninfo_id"]),
                )
                if cursor.rowcount > 0:
                    updated += 1
            except Exception as e:
                logger.warning(f"更新失败 {ann['cninfo_id']}: {e}")
        conn.commit()
        print(f"    已更新: {updated}")

    # 5.2 更新 file_path (title)
    if need_update_by_title:
        print("  更新 file_path (title 匹配)...")
        updated = 0
        for pdf, ann in need_update_by_title:
            try:
                cursor.execute(
                    """
                    UPDATE announcements
                    SET file_path = %s
                    WHERE cninfo_id = %s
                """,
                    (str(pdf), ann["cninfo_id"]),
                )
                if cursor.rowcount > 0:
                    updated += 1
            except Exception as e:
                logger.warning(f"更新失败 {ann['cninfo_id']}: {e}")
        conn.commit()
        print(f"    已更新: {updated}")

    # 5.3 插入新记录
    if need_insert:
        print("  插入新记录...")
        inserted = 0
        from datetime import datetime

        for pdf, info in need_insert:
            try:
                title = info.get("title", Path(pdf).stem)
                # 从标题推断 announcement_type
                ann_type = "other"
                if "年度报告" in title:
                    ann_type = "annual_report"
                elif "半年度报告" in title:
                    ann_type = "half_report"
                elif "季度报告" in title or "一季报" in title or "三季报" in title:
                    ann_type = "quarter_report"
                elif "投资者" in title or "调研" in title:
                    ann_type = "research_survey"
                elif "重大资产重组" in title or "资产重组" in title:
                    ann_type = "ma_activity"
                elif "对外投资" in title or "收购" in title or "增资" in title:
                    ann_type = "investment"

                # 尝试从路径提取 ts_code 和日期
                ts_code = ""
                ann_date = datetime.now().strftime("%Y-%m-%d")
                parts = pdf.parts
                for part in parts:
                    if part.endswith(".SZ") or part.endswith(".SH"):
                        ts_code = part
                    if len(part) == 7 and part[4] == "-":
                        ann_date = f"{part}-01"

                # 生成 cninfo_id
                cninfo_id = f"ann_local_{Path(pdf).stem[:40]}"

                cursor.execute(
                    """
                    INSERT INTO announcements (
                        ann_date, ts_code, name, title, type,
                        cninfo_id, announcement_type, source_type,
                        source_name, confidence_tier, file_path
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (ts_code, ann_date, title) DO UPDATE
                    SET file_path = EXCLUDED.file_path
                """,
                    (
                        ann_date,
                        ts_code,
                        "",
                        title,
                        None,
                        cninfo_id,
                        ann_type,
                        "minishare",
                        "minishare_local_fix",
                        "Tier2",
                        str(pdf),
                    ),
                )
                if cursor.rowcount > 0:
                    inserted += 1
            except Exception as e:
                logger.warning(f"插入失败: {e}")
        conn.commit()
        print(f"    已插入: {inserted}")

    cursor.close()
    conn.close()

    print()
    print("=" * 70)
    print("  修复完成")
    print("=" * 70)

    # 6. 再次校验
    print()
    print("  最终校验...")

    conn = psycopg2.connect(**db_config)
    cursor = conn.cursor()

    cursor.execute("SELECT file_path FROM announcements WHERE file_path IS NOT NULL AND file_path != ''")
    db_paths_final = set(row[0] for row in cursor.fetchall() if row[0])

    local_pdfs_final = set(str(p) for p in notices_dir.rglob("*.pdf"))

    diff = len(local_pdfs_final) - len(db_paths_final)

    print(f"    数据库有 file_path: {len(db_paths_final):,}")
    print(f"    本地 PDF: {len(local_pdfs_final):,}")

    if diff == 0:
        print()
        print("  ✅ 完全一致！")
    elif diff > 0:
        print(f"    ⚠️  本地比数据库多 {diff} 个文件")
    else:
        print(f"    ⚠️  数据库比本地多 {abs(diff)} 个文件")

    cursor.close()
    conn.close()


if __name__ == "__main__":
    fix_pdf_consistency()
