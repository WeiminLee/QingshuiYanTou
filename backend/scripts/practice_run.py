"""实战试跑：预期差三工具 + 图传递，在真实标的上走一遍分析流程。

场景：投资者问「硅片/光伏产业链现在谁最赚、谁的预期差最大？」
"""
import asyncio


def show(title: str, data: dict, keys: list[str], n: int = 6):
    print(f"\n=== {title} ===")
    for k in keys:
        print(f"  {k}: {data.get(k)}")


async def main():
    from app.reasoning.tools.knowledge.graph_walk import related_nodes, propagate_along
    from app.reasoning.tools.knowledge.metric_ops import (
        compare_metric,
        metric_trend,
        rollup_metric,
    )

    # 1) 图传递：硅片产业链公司面
    r = await propagate_along.ainvoke({"start": "硅片", "max_hops": 1, "min_cooccur": 5, "top_k": 12})
    companies = [x for x in r.get("reachable", []) if x["layer"] == "subject"][:6]
    print("\n[1] 硅片 → 关联公司（共现≥5）:", [c["name"] for c in companies])

    rn = await related_nodes.ainvoke({"keyword": "硅片", "layer": "subject", "top_k": 6})
    print("[1b] related_nodes 一跳公司:", [x["name"] for x in rn.get("neighbors", [])][:6])

    # 2) 横向：硅片公司毛利率谁高谁低
    r2 = await compare_metric.ainvoke({"dimension": "毛利率", "scope": "硅片"})
    rows = r2.get("rows") or r2.get("items") or []
    print("\n[2] compare_metric(毛利率 × 硅片): count =", len(rows))
    for x in rows[:6]:
        print("    %s = %s %s (%s)" % (
            (x.get("subject") or "?")[:16], x.get("value"),
            x.get("unit") or "", (x.get("period") or "")[:8],
        ))

    # 3) 纵向：单公司时间线
    ts = (rows[0].get("subject") if rows else None) or "300962.SZ"
    r3 = await metric_trend.ainvoke({"subject": ts, "dimension": "毛利率"})
    series = r3.get("series") or r3.get("items") or []
    print(f"\n[3] metric_trend({ts}, 毛利率): points =", len(series))
    for x in series[:5]:
        print("    %s = %s %s" % ((x.get("period") or "?")[:10], x.get("value"), x.get("unit") or ""))

    # 4) 层次：营收细分
    r4 = await rollup_metric.ainvoke({"parent": "营收"})
    kids = r4.get("children") or r4.get("items") or []
    print("\n[4] rollup_metric(营收): children =", len(kids))
    for x in kids[:6]:
        print("    ", x if isinstance(x, str) else (x.get("name") or x.get("norm_text") or x))

    # 5) scan_dimension 由 compare_metric 内部覆盖，这里省略


asyncio.run(main())
