"""
补充光通信产业链核心标的进 StockPool（手动指定，非爬虫）
仅补充文章中明确提及的核心标的

已在 StockPool：永鼎股份、中兴通讯、华工科技、风华高科、超声电子、
               青山纸业、上海贝岭、生益科技、特发信息、汇源通信、
               新能泰山、京东方Ａ、中广核技、法尔胜
"""

import asyncio
from datetime import date
from sqlalchemy import text
from app.core.database import async_session

# 文章明确提及的核心标的（ts_code, name, 环节标签, 关联概念名)
OPTICAL_STOCKS = [
    ("300308.SZ", "中际旭创", "光模块", "光模块"),
    ("300502.SZ", "新易盛", "光模块", "光模块"),
    ("002281.SZ", "光迅科技", "光模块", "光模块"),
    ("603083.SH", "剑桥科技", "光模块", "光模块"),
    ("300394.SZ", "天孚通信", "光器件", "光器件"),
    ("688498.SH", "源杰科技", "光芯片", "光芯片"),
    ("688048.SH", "长光华芯", "光芯片", "光芯片"),
    ("688313.SH", "仕佳光子", "光芯片", "光芯片"),
    ("300757.SZ", "罗博特科", "CPO", "共封装光学(CPO)"),
    ("688205.SH", "德科立", "OCS", "光电路交换(OCS)"),
    ("688195.SH", "腾景科技", "OCS", "光电路交换(OCS)"),
    ("300620.SZ", "光库科技", "OCS", "光电路交换(OCS)"),
]


async def main():
    async with async_session() as sess:
        today = date.today().isoformat()

        for ts_code, name, link, concept in OPTICAL_STOCKS:
            # 检查是否已在 StockPool
            exists = await sess.execute(
                text("SELECT 1 FROM stock_pool WHERE ts_code = :ts_code"),
                {"ts_code": ts_code}
            )
            if exists.scalar():
                print(f"⏭  {name}({ts_code}) 已在 StockPool，跳过")
                continue

            await sess.execute(
                text("""
                    INSERT INTO stock_pool (ts_code, concept_code, concept_name, in_date, out_date, pct_chg_5d, score, updated_at)
                    VALUES (:ts_code, :concept_code, :concept_name, :in_date, NULL, 0.0, 0.0, NOW())
                    ON CONFLICT (ts_code) DO UPDATE SET
                        concept_name = EXCLUDED.concept_name,
                        in_date = EXCLUDED.in_date,
                        updated_at = NOW()
                """),
                {
                    "ts_code": ts_code,
                    "concept_code": f"optical_{link}",
                    "concept_name": f"光通信-{concept}",
                    "in_date": today,
                }
            )
            print(f"✅ {name}({ts_code}) 已加入 StockPool -> 光通信-{concept}")

        await sess.commit()
        print(f"\n共处理 {len(OPTICAL_STOCKS)} 只光通信核心标的")


if __name__ == "__main__":
    asyncio.run(main())
