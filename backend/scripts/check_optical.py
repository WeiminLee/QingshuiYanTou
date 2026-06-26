import asyncio

from sqlalchemy import text

from app.core.database import async_session


async def check():
    async with async_session() as sess:
        # 光通信核心个股（用 ts_code 直接查）
        result = await sess.execute(
            text("""
            SELECT s.ts_code, st.name, s.total_score, s.momentum_score,
                   s.capital_score, s.concept_bonus, s.trend_score
            FROM stock_scores s
            JOIN stocks st ON st.ts_code = s.ts_code
            WHERE st.name IN ('中际旭创','新易盛','光迅科技','天孚通信','源杰科技',
                              '仕佳光子','长光华芯','德科立','光库科技','剑桥科技',
                              '华工科技','亨通光电','长飞光纤','永鼎股份','中天科技',
                              '烽火通信','罗博特科','华懋科技','腾景科技','太辰光',
                              '凌云光','大族激光','中兴通讯')
            ORDER BY s.total_score DESC NULLS LAST
        """)
        )
        rows = result.fetchall()
        print("=== 光通信核心个股评分 ===")
        for r in rows:
            print(
                f"{r[1]:10s} | 总分={str(r[2]):6s} | 动量={str(r[3]):5s} | 资金={str(r[4]):5s} | 概念溢价={str(r[5]):5s} | 趋势={str(r[6]):5s} | {r[0]}"
            )

        # 光通信相关概念评分
        result2 = await sess.execute(
            text("""
            SELECT concept_ts_code, name, score, momentum_1d, breadth, relative_strength
            FROM concept_scores
            WHERE name LIKE '%光%' OR name LIKE '%CPO%' OR name LIKE '%OCS%'
               OR name LIKE '%光通信%' OR name LIKE '%光模块%' OR name LIKE '%光纤%'
            ORDER BY score DESC
            LIMIT 20
        """)
        )
        rows2 = result2.fetchall()
        print()
        print("=== 光通信相关概念评分 ===")
        for r in rows2:
            print(
                f"{r[1]:15s} | score={r[2]:5.2f} | 1日={r[3]:5.2f}% | 广度={r[4]:.3f} | 相对强度={r[5]:5.2f} | {r[0]}"
            )

        # StockPool
        result3 = await sess.execute(
            text("""
            SELECT st.ts_code, st.name, sp.concept_name, sp.score
            FROM stock_pool sp
            JOIN stocks st ON st.ts_code = sp.ts_code
            ORDER BY sp.score DESC NULLS LAST
            LIMIT 80
        """)
        )
        rows3 = result3.fetchall()
        print()
        print(f"=== StockPool (总数={len(rows3)}) ===")
        for r in rows3:
            print(f"score={str(r[3]):6s} | {r[1]:10s} | {str(r[2]):20s} | {r[0]}")

        # 光通信个股是否在 StockPool
        optical_names = [
            "中际旭创",
            "新易盛",
            "光迅科技",
            "天孚通信",
            "源杰科技",
            "仕佳光子",
            "长光华芯",
            "德科立",
            "光库科技",
            "剑桥科技",
            "华工科技",
            "亨通光电",
            "长飞光纤",
            "永鼎股份",
            "中天科技",
            "烽火通信",
            "罗博特科",
            "华懋科技",
            "腾景科技",
            "太辰光",
            "凌云光",
            "大族激光",
            "中兴通讯",
        ]
        result4 = await sess.execute(
            text("""
            SELECT st.name, sp.concept_name
            FROM stock_pool sp
            JOIN stocks st ON st.ts_code = sp.ts_code
            WHERE st.name = ANY(:names)
        """)
        )
        in_pool = {r[0]: r[1] for r in result4.fetchall()}
        print()
        print("=== 光通信个股在 StockPool 情况 ===")
        for name in optical_names:
            if name in in_pool:
                print(f"✅ {name} -> {in_pool[name]}")
            else:
                print(f"❌ {name} 不在 StockPool")


asyncio.run(check())
