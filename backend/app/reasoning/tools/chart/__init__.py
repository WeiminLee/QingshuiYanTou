"""
Chart Tool — 可视化图表渲染

将数据渲染为 ECharts HTML 图表，供前端展示。
支持：K线图 / 板块热度图 / 置信度雷达图 / 供应链桑基图
"""

import json
import logging
import uuid
from pathlib import Path
from typing import Annotated

from langchain_core.tools import tool

logger = logging.getLogger(__name__)

_CHART_DIR = Path(__file__).resolve().parent.parent.parent.parent.parent / "static" / "charts"


@tool("present_chart")
def present_chart(
    chart_type: Annotated[str, "图表类型：kline/concept_heatmap/confidence_radar/sankey"],
    data: Annotated[dict, "图表数据（结构因类型而异）"],
    title: Annotated[str, "图表标题"] = "",
) -> str:
    """渲染交互式 ECharts 图表（K线/板块热度/置信度雷达/供应链桑基图）。输入图表类型和数据，输出HTML文件并返回访问URL。"""
    generators = {
        "kline": _render_kline,
        "concept_heatmap": _render_concept_heatmap,
        "confidence_radar": _render_confidence_radar,
        "sankey": _render_sankey,
    }
    generator = generators.get(chart_type)
    if not generator:
        return f"未知图表类型：{chart_type}。可用：{', '.join(generators.keys())}"
    try:
        html = generator(data, title)
        return _save_and_get_url(html, chart_type)
    except Exception as e:
        logger.warning(f"[ChartTool] render failed: {e}")
        return f"图表渲染失败：{e}"


def _render_kline(data: dict, title: str) -> str:
    candles = data.get("candles", [])
    if not candles:
        return "<p>无K线数据</p>"
    dates = [c["date"] for c in candles]
    kdata = [[c["open"], c["close"], c["low"], c["high"]] for c in candles]
    volumes = [c.get("vol", 0) for c in candles]
    ma5 = data.get("ma5", [])
    ma10 = data.get("ma10", [])
    ts_code = data.get("ts_code", "")
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<script src="https://cdn.jsdelivr.net/npm/echarts@5.5.1/dist/echarts.min.js"></script></head>
<body><div id="c" style="width:100%;height:500px;"></div>
<script>
const c=echarts.init(document.getElementById('c'));
c.setOption({{
  title:{{text:"{title or ts_code + " K线"}"}},
  tooltip:{{trigger:'axis',axisPointer:{{type:'cross'}}}},
  legend:{{data: ['K线','MA5','MA10','成交量']}},
  grid:[{{left:'10%',right:'8%',top:'10%',height:'55%'}},{{left:'10%',right:'8%',top:'72%',height:'15%'}}],
  xAxis:[{{type:'category',data:{json.dumps(dates)},gridIndex:0,boundaryGap:false}},
         {{type:'category',data:{json.dumps(dates)},gridIndex:1,boundaryGap:false}}],
  yAxis:[{{scale:true,gridIndex:0}},{{scale:true,gridIndex:1}}],
  dataZoom:[{{type:'inside',xAxisIndex:[0,1],start:60,end:100}}],
  series:[
    {{name:'K线',type:'candlestick',xAxisIndex:0,yAxisIndex:0,
      data:{json.dumps(kdata)},
      itemStyle:{{color:'#ef5350',color0:'#26a69a',borderColor:'#ef5350',borderColor0:'#26a69a'}}}},
    {{name:'MA5',type:'line',xAxisIndex:0,yAxisIndex:0,data:{json.dumps(ma5)},smooth:true,showSymbol:false}},
    {{name:'MA10',type:'line',xAxisIndex:0,yAxisIndex:0,data:{json.dumps(ma10)},smooth:true,showSymbol:false}},
    {{name:'成交量',type:'bar',xAxisIndex:1,yAxisIndex:1,data:{json.dumps(volumes)}}}
  ]
}});
</script></body></html>"""


def _render_concept_heatmap(data: dict, title: str) -> str:
    heatmap_data = data.get("data", [])
    names = [h["name"] for h in heatmap_data]
    values = [h.get("change_pct", 0) for h in heatmap_data]
    items = [[0, i, v] for i, v in enumerate(values)]
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<script src="https://cdn.jsdelivr.net/npm/echarts@5.5.1/dist/echarts.min.js"></script></head>
<body><div id="c" style="width:100%;height:600px;"></div>
<script>
const c=echarts.init(document.getElementById('c'));
c.setOption({{
  title:{{text:"{title or "板块热度"}"}},
  tooltip:{{formatter:p=>{{const d={json.dumps(names)}[p.data[1]];return d+'<br/>'+p.data[2]+'%'}}}},
  xAxis:{{type:'category',data:['热度'],axisLabel:{{show:false}}}},
  yAxis:{{type:'category',data:{json.dumps(names)},inverse:true}},
  visualMap:{{min:-10,max:10,calculable:true,inRange:{{color:['#ef5350','#fff','#26a69a']}}}},
  series:[{{type:'heatmap',data:{json.dumps(items)},
    label:{{show:true,formatter:p=>{{const d={json.dumps(names)}[p.data[1]];return d+' '+p.data[2]+'%'}}}},
    emphasis:{{itemStyle:{{shadowBlur:10}}}}]
}});
</script></body></html>"""


def _render_confidence_radar(data: dict, title: str) -> str:
    indicators = data.get("indicators", [])
    if not indicators:
        return "<p>无置信度数据</p>"
    ind_json = json.dumps(indicators)
    values = [i["value"] for i in indicators]
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<script src="https://cdn.jsdelivr.net/npm/echarts@5.5.1/dist/echarts.min.js"></script></head>
<body><div id="c" style="width:100%;height:500px;"></div>
<script>
const c=echarts.init(document.getElementById('c'));
c.setOption({{
  title:{{text:"{title or "置信度雷达"}",left:'center'}},
  tooltip:{{}},
  legend:{{data:['置信度'],bottom:10}},
  radar:{{indicator:{ind_json}}},
  series:[{{
    type:'radar',
    data:[{{name:'置信度',value:{json.dumps(values)},
      areaStyle:{{color:'rgba(54,162,235,0.3)'}},
      lineStyle:{{color:'#36a2ef'}}]]
  }}]
}});
</script></body></html>"""


def _render_sankey(data: dict, title: str) -> str:
    nodes = data.get("nodes", [])
    links = data.get("links", [])
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<script src="https://cdn.jsdelivr.net/npm/echarts@5.5.1/dist/echarts.min.js"></script></head>
<body><div id="c" style="width:100%;height:600px;"></div>
<script>
const c=echarts.init(document.getElementById('c'));
c.setOption({{
  title:{{text:"{title or "供应链桑基"}"}},
  tooltip:{{trigger:'item',triggerOn:'mousemove'}},
  series:[{{
    type:'sankey',layout:'none',
    data:{json.dumps(nodes)},
    links:{json.dumps(links)},
    lineStyle:{{curveness:0.5}},
    emphasis:{{itemStyle:{{shadowBlur:10}}}}
  }}]
}});
</script></body></html>"""


def _save_and_get_url(html: str, chart_type: str) -> str:
    _CHART_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{chart_type}_{uuid.uuid4().hex[:8]}.html"
    (_CHART_DIR / filename).write_text(html, encoding="utf-8")
    return f"图表已生成：/static/charts/{filename}"
