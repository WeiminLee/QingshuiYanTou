"""关键字变体归并工具（词表治理，spec §4.2「LLM 提议、词典裁决」闭环）。

用法:
  python -m scripts.merge_keyword --layer scope "抛光硅片产品" "半导体硅片、单晶硅片" --to "硅片"

语义：把若干 surface 变体（同 layer 同义）合并到目标规范键。
- 变体 keyword 行标记 status=merged、merged_into=目标；
- 变体的 link 行移动到目标 keyword_id（PK 冲突 do-nothing，span 重复安全）；
- 目标不存在时按 layer 以 dictionary 源创建（理应已存在）。
生产影响可逆：merge 不删除任何数据（链接被移动而非删除，keyword 行标记 merged 保留）。
"""
from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import text

from app.core.database import async_session
from app.knowledge.linklayer.models import make_keyword_id


async def run(layer: str, variants: list[str], target: str, dry_run: bool) -> None:
    assert layer in ("subject", "dimension", "stage", "scope"), layer
    target_id = make_keyword_id(layer, target)
    variant_ids = [make_keyword_id(layer, v) for v in variants]

    async with async_session() as session:
        target_row = (
            await session.execute(
                text("SELECT keyword_id, norm_text, status FROM link_keywords WHERE keyword_id=:i"),
                {"i": target_id},
            )
        ).first()
        print(f"[目标] {target}: {target_row if target_row else '不存在'}")
        for kw_id, disp in zip(variant_ids, variants):
            row = (
                await session.execute(
                    text("SELECT status FROM link_keywords WHERE keyword_id=:i"), {"i": kw_id}
                )
            ).first()
            print(f"[变体] {disp}: {row if row else '不存在'}")

        stat = (
            await session.execute(
                text(
                    "SELECT count(*) FROM link_links WHERE keyword_id = ANY(:vids)"
                ),
                {"vids": variant_ids},
            )
        ).scalar()
        print(f"待迁移链接数: {stat}")
        if dry_run:
            await session.rollback()
            return

        # 目标缺失则创建；目标若处于 merged 状态则复活为 active
        if target_row is None:
            await session.execute(
                text(
                    "INSERT INTO link_keywords (keyword_id, layer, norm_text, display_text, status)"
                    " VALUES (:i, :l, :n, :n, 'active')"
                ),
                {"i": target_id, "l": layer, "n": target},
            )
        elif target_row.status != "active":
            await session.execute(
                text(
                    "UPDATE link_keywords SET status='active', merged_into=NULL WHERE keyword_id=:i"
                ),
                {"i": target_id},
            )

        # 移动链接（PK 冲突 do-nothing 后删除源行）
        await session.execute(
            text(
                "INSERT INTO link_links (keyword_id, evidence_id, span_start, span_end,"
                " published_at, source, created_at)"
                " SELECT :tid, evidence_id, span_start, span_end, published_at, source, created_at"
                " FROM link_links WHERE keyword_id = ANY(:vids)"
                " ON CONFLICT DO NOTHING"
            ),
            {"tid": target_id, "vids": variant_ids},
        )
        await session.execute(
            text("DELETE FROM link_links WHERE keyword_id = ANY(:vids)"),
            {"vids": variant_ids},
        )
        for kw_id in variant_ids:
            await session.execute(
                text(
                    "UPDATE link_keywords SET status='merged', merged_into=:tid WHERE keyword_id=:kid"
                ),
                {"tid": target_id, "kid": kw_id},
            )
        await session.commit()
        after = (
            await session.execute(
                text("SELECT count(*) FROM link_links WHERE keyword_id=:i"), {"i": target_id}
            )
        ).scalar()
        print(f"完成：{len(variants)} 个变体并入 {layer}/{target}，目标现有链接 {after} 条")


def main() -> None:
    parser = argparse.ArgumentParser(description="关键字变体归并（词表治理）")
    parser.add_argument("--layer", required=True, choices=["subject", "dimension", "stage", "scope"])
    parser.add_argument("variants", nargs="+", help="要归并的变体 norm_text")
    parser.add_argument("--to", required=True, help="目标规范键 norm_text")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    asyncio.run(run(args.layer, args.variants, args.to, args.dry_run))


if __name__ == "__main__":
    main()
