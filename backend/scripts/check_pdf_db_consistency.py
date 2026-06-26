#!/usr/bin/env python3
"""
PDF 与数据库记录一致性校验脚本（独立版）

使用 psycopg2 直接查询 PostgreSQL，避免循环导入问题。
"""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse


def get_db_config():
    """从环境变量获取数据库配置"""
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url:
        # 默认值
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


def check_consistency():
    """校验数据库记录数与本地 PDF 文件数的一致性"""
    import psycopg2

    db_config = get_db_config()

    # 连接数据库
    conn = psycopg2.connect(**db_config)
    cursor = conn.cursor()

    # 目标类型（与 sync_minishare_ann_history.py 保持一致）
    target_types = (
        "annual_report",
        "half_report",
        "quarter_report",
        "research_survey",
        "ma_activity",
        "investment",
    )

    print("=" * 70)
    print("  PDF 与数据库一致性校验")
    print("=" * 70)
    print()

    # 1. 数据库统计
    # 总记录数
    cursor.execute(
        """
        SELECT COUNT(*) FROM announcements
        WHERE announcement_type IN %s
          AND source_type = 'minishare'
    """,
        (target_types,),
    )
    total_count = cursor.fetchone()[0]

    # 有 file_path 的记录数
    cursor.execute(
        """
        SELECT COUNT(*) FROM announcements
        WHERE announcement_type IN %s
          AND source_type = 'minishare'
          AND file_path IS NOT NULL
          AND file_path != ''
    """,
        (target_types,),
    )
    with_path_count = cursor.fetchone()[0]

    # 待下载（无 file_path 但有 pdf_url）
    cursor.execute(
        """
        SELECT COUNT(*) FROM announcements
        WHERE announcement_type IN %s
          AND source_type = 'minishare'
          AND file_path IS NULL
          AND pdf_url IS NOT NULL
    """,
        (target_types,),
    )
    pending_count = cursor.fetchone()[0]

    # 无 URL（无法下载）
    cursor.execute(
        """
        SELECT COUNT(*) FROM announcements
        WHERE announcement_type IN %s
          AND source_type = 'minishare'
          AND (file_path IS NULL OR file_path = '')
          AND (pdf_url IS NULL OR pdf_url = '')
    """,
        (target_types,),
    )
    no_url_count = cursor.fetchone()[0]

    # 获取所有有 file_path 的记录用于检查文件是否存在
    cursor.execute(
        """
        SELECT cninfo_id, file_path, title
        FROM announcements
        WHERE announcement_type IN %s
          AND source_type = 'minishare'
          AND file_path IS NOT NULL
          AND file_path != ''
    """,
        (target_types,),
    )
    file_path_records = cursor.fetchall()

    print(f"  目标类型: {target_types}")
    print()
    print("  数据库统计:")
    print(f"    有 file_path 记录数: {with_path_count:,}")
    print(f"    待下载 (无 file_path): {pending_count:,}")
    print(f"    无 URL (无法下载): {no_url_count:,}")
    print(f"    总计: {total_count:,}")
    print()

    # 2. 本地 PDF 文件统计
    print("  正在扫描本地 PDF 文件...")

    # 从环境变量或默认值获取存储路径
    storage_paths = [
        "/run/media/lwm/0E27099B0E27099B/qingshui_data/notices",  # 外部硬盘
        os.environ.get("MINISHARE_DATA_ROOT", "/home/lwm/qingshui_data"),
    ]

    local_pdfs: dict[str, int] = {}
    total_local = 0

    for base_path in storage_paths:
        base_dir = Path(base_path)
        if base_dir.exists():
            pdf_files = list(base_dir.rglob("*.pdf"))
            count = len(pdf_files)
            if count > 0:
                local_pdfs[base_path] = count
                total_local += count
                print(f"    {base_path}: {count:,} PDFs")

    if not local_pdfs:
        # 尝试常见的存储位置
        common_paths = [
            "/home/lwm/qingshui_data/notices",
            "/home/lwm/qingshui_data/notices",
            "/data/notices",
        ]
        for path in common_paths:
            base_dir = Path(path)
            if base_dir.exists():
                pdf_files = list(base_dir.rglob("*.pdf"))
                count = len(pdf_files)
                if count > 0:
                    local_pdfs[path] = count
                    total_local += count
                    print(f"    {path}: {count:,} PDFs")

    print(f"    本地 PDF 总计: {total_local:,}")
    print()

    # 3. 检查 file_path 记录的文件是否存在
    print("  检查 file_path 有效性...")
    valid_count = 0
    invalid_count = 0
    invalid_examples = []

    for rec in file_path_records:
        cninfo_id, file_path, title = rec
        if file_path:
            p = Path(file_path)
            if p.exists():
                valid_count += 1
            else:
                invalid_count += 1
                if len(invalid_examples) < 5:
                    invalid_examples.append(rec)

    print(f"    file_path 有效: {valid_count:,}")
    print(f"    file_path 无效: {invalid_count:,}")
    if invalid_examples:
        print()
        print("  无效 file_path 示例（前 5 条）:")
        for cninfo_id, file_path, title in invalid_examples:
            print(f"    cninfo_id: {cninfo_id}")
            print(f"    file_path: {file_path}")
            title_str = title[:50] if title else "N/A"
            print(f"    title:     {title_str}...")
            print()

    # 4. 汇总差异
    print("=" * 70)
    print("  一致性检查结果:")
    print("=" * 70)

    diff = with_path_count - total_local
    if diff == 0 and invalid_count == 0:
        print("  ✅ 一致：数据库有 file_path 记录数 = 本地 PDF 文件数")
    elif diff > 0:
        print(f"  ⚠️  数据库比本地多 {diff:,} 个 file_path 记录")
    elif diff < 0:
        print(f"  ⚠️  本地 PDF 比数据库多 {abs(diff):,} 个文件")

    if invalid_count > 0:
        print(f"  ❌ {invalid_count:,} 条 file_path 指向不存在的文件")

    print()

    # 5. 按月份统计待下载数量
    print("  按月份统计待下载数量...")
    cursor.execute(
        """
        SELECT
            TO_CHAR(ann_date, 'YYYY-MM') as month,
            COUNT(*) as cnt
        FROM announcements
        WHERE announcement_type IN %s
          AND source_type = 'minishare'
          AND file_path IS NULL
          AND pdf_url IS NOT NULL
        GROUP BY TO_CHAR(ann_date, 'YYYY-MM')
        ORDER BY month DESC
        LIMIT 20
    """,
        (target_types,),
    )
    monthly = cursor.fetchall()

    if monthly:
        print()
        print("  月份        待下载数")
        print("  " + "-" * 25)
        for month, cnt in monthly:
            print(f"  {month}    {cnt:,}")

    print()

    cursor.close()
    conn.close()

    return {
        "total_db": with_path_count,
        "total_local": total_local,
        "pending": pending_count,
        "invalid_file_path": invalid_count,
        "diff": diff,
    }


if __name__ == "__main__":
    check_consistency()
