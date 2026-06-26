#!/usr/bin/env python3
"""
清理 2024 年以前的公告数据和本地 PDF 文件

确保本地 PDF 与数据库记录在 2024 年及以后保持一致。
"""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse

import psycopg2


def get_db_config():
    """从环境变量获取数据库配置"""
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


def cleanup_old_data():
    """清理 2024 年以前的公告数据"""
    import argparse

    parser = argparse.ArgumentParser(description="清理 2024 年以前的公告数据")
    parser.add_argument("--force", "-f", action="store_true", help="跳过确认直接执行")
    parser.add_argument("--dry-run", "-n", action="store_true", help="只显示不删除")
    args = parser.parse_args()

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
    print("  清理 2024 年以前的数据")
    print("=" * 70)
    print()

    # 1. 统计数据库中 2024 年以前的数据
    cursor.execute(
        """
        SELECT COUNT(*) FROM announcements
        WHERE announcement_type IN %s
          AND source_type = 'minishare'
          AND ann_date < '2024-01-01'
    """,
        (target_types,),
    )
    db_old_count = cursor.fetchone()[0]
    print(f"  数据库中 2024 年前的公告数: {db_old_count:,}")

    # 2. 统计本地 2024 年以前的 PDF
    local_old_pdfs = []
    if notices_dir.exists():
        for pdf in notices_dir.rglob("*.pdf"):
            # 检查年份目录
            parts = pdf.parts
            for part in parts:
                if len(part) == 7 and part[4] == "-":
                    year = int(part[:4])
                    if year < 2024:
                        local_old_pdfs.append(pdf)
                        break

    print(f"  本地 2024 年前的 PDF 数: {len(local_old_pdfs):,}")
    print()

    # 3. Dry-run 模式
    if args.dry_run:
        print("  [Dry-run] 以下文件将被删除:")
        for pdf in local_old_pdfs[:20]:
            print(f"    {pdf}")
        if len(local_old_pdfs) > 20:
            print(f"    ... 还有 {len(local_old_pdfs) - 20} 个文件")
        return

    # 4. 确认清理
    if not args.force:
        confirm = input("确认清理这些数据？(y/N): ").strip().lower()
        if confirm != "y":
            print("取消清理")
            return

    # 5. 删除数据库记录
    print()
    print("  删除数据库记录...")
    if db_old_count > 0:
        cursor.execute(
            """
            DELETE FROM announcements
            WHERE announcement_type IN %s
              AND source_type = 'minishare'
              AND ann_date < '2024-01-01'
        """,
            (target_types,),
        )
        deleted_db = cursor.rowcount
        conn.commit()
        print(f"  已删除数据库记录: {deleted_db:,}")
    else:
        print("  数据库无旧记录需要删除")

    # 6. 删除本地 PDF
    print()
    print("  删除本地 PDF 文件...")
    deleted_local = 0
    for pdf in local_old_pdfs:
        try:
            pdf.unlink()
            deleted_local += 1
        except Exception as e:
            print(f"    删除失败: {pdf} - {e}")
    print(f"  已删除本地 PDF: {deleted_local:,}")

    cursor.close()
    conn.close()

    print()
    print("=" * 70)
    print("  清理完成")
    print("=" * 70)


if __name__ == "__main__":
    cleanup_old_data()
