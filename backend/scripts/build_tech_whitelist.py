#!/usr/bin/env python3
"""
基于 Tushare 同花顺概念数据生成核心科技股白名单

分类策略:
1. AUTO_INCLUDE: 只要命中就是科技股（AI/算力/芯片等）
2. PAN_TECH: 泛科技概念（智能硬件/新能源/材料等）
3. EXCLUDE: 完全排除（金融/农业/消费/传统能源/区域概念）

最终白名单 = (AUTO_INCLUDE | PAN_TECH) - EXCLUDE
一只股票可同时属于多个类别
"""

import json
from collections import defaultdict
from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).parent.parent / "data" / "board_concept"

# ── 读取数据 ──────────────────────────────────────────────
df = pd.read_csv(DATA_DIR / "ths_tushare_members.csv")
print(f"原始数据: {len(df)} 条, {df['concept_code'].nunique()} 个概念, {df['stock_code'].nunique()} 只股票")


def clean_ts_code(code):
    code = str(code).strip()
    if "." in code:
        return code
    if len(code) != 6 or not code.isdigit():
        return None
    if code.startswith(("60", "68")):
        return f"{code}.SH"
    if code.startswith(("00", "30", "20")):
        return f"{code}.SZ"
    if code.startswith(("43", "83", "87", "88", "89", "92")):
        return f"{code}.BJ"
    return None


# ── 排除规则 ──────────────────────────────────────────────
EXCLUDE_KEYWORDS = [
    "参股",
    "融资融券",
    "券商重仓",
    "社保重仓",
    "保险重仓",
    "证金",
    "期货",
    "猪肉",
    "养鸡",
    "鸡肉",
    "大豆",
    "玉米",
    "农业种植",
    "生态农业",
    "人造肉",
    "农机",
    "粮食",
    "乳业",
    "青蒿素",
    "白酒",
    "啤酒",
    "体育",
    "冰雪",
    "露营",
    "预制菜",
    "宠物经济",
    "自贸区",
    "成渝",
    "京津冀",
    "雄安",
    "海南",
    "长三角",
    "西部大开发",
    "横琴新区",
    "房地产",
    "物业",
    "装修",
    "装配",
    "煤炭",
    "石油",
    "燃气",
    "天然气",
    "ST",
    "摘帽",
    "高送转",
    "举牌",
    "恒大",
    "供销社",
    "冷链",
    "污水处理",
    "固废",
    "土壤修复",
    "垃圾分类",
    "赛马概念",
    "共享单车",
]


def is_excluded(name):
    if not name:
        return True
    return any(kw in name for kw in EXCLUDE_KEYWORDS)


# ── 分类规则 ──────────────────────────────────────────────
AUTO_INCLUDE_KEYWORDS = [
    # AI / 大模型
    "AI",
    "DeepSeek",
    "ChatGPT",
    "AIGC",
    "Sora",
    "多模态AI",
    "AI智能体",
    "AI应用",
    "AI眼镜",
    "AI PC",
    "AI手机",
    "AI语料",
    "人工智能",
    "智谱AI",
    "中国AI 50",
    "MLOps",
    "AI视频",
    # 算力 / 数据中心
    "算力",
    "数据中心",
    "东数西算",
    "液冷",
    "英伟达",
    "算力租赁",
    "云计算",
    "云办公",
    "云游戏",
    "国资云",
    # 半导体 / 芯片
    "芯片",
    "半导",
    "光刻",
    "封测",
    "存储芯片",
    "MCU",
    "汽车芯片",
    "先进封装",
    "中芯国际",
    "大基金",
    "光刻机",
    # 光通信 / CPO
    "共封装光学",
    "CPO",
    "光通信",
    "光纤",
    "铜缆",
    # 华为生态
    "华为",
    "鸿蒙",
    "昇腾",
    "鲲鹏",
    "欧拉",
    "海思",
    "盘古",
    # 机器人 / 自动化
    "机器人",
    "人形机器人",
    "机器视觉",
    "减速器",
    "工业母机",
    # 智能驾驶
    "无人驾驶",
    "智能驾驶",
    "智能座舱",
    "汽车电子",
    "毫米波雷达",
    "激光雷达",
    # 新兴科技
    "脑机接口",
    "量子",
    "元宇宙",
    "虚拟现实",
    "数字孪生",
    "空间计算",
    "MR",
    "VR",
    "AR",
    "XR",
    "虚拟数字人",
    "Web3",
    "数字水印",
    # 消费电子
    "OLED",
    "MiniLED",
    "柔性屏",
    "折叠屏",
    "PCB",
    "触摸屏",
    "电子纸",
    "MicroLED",
    "消费电子",
    # 软件 / 信创
    "信创",
    "操作系统",
    "数字安全",
    "数字货币",
    "财税数字化",
    "数字乡村",
    # 低空 / 航天
    "低空",
    "飞行汽车",
    "eVTOL",
    "无人机",
    "商业航天",
    "卫星导航",
    # 传感器 / 物联网
    "传感器",
    "物联网",
    "智能电网",
    "车联网",
    "工业互联网",
]

PAN_TECH_CATEGORIES = {
    "通信": ["5G", "6G", "F5G", "WiFi", "移动支付"],
    "新能源/储能": [
        "光伏",
        "风电",
        "储能",
        "充电桩",
        "换电",
        "虚拟电厂",
        "固态电池",
        "钠离子",
        "钙钛矿",
        "TOPCon",
        "HJT",
        "BC电池",
        "新能源汽车",
        "锂电",
        "氢能源",
        "燃料电池",
        "动力电池",
    ],
    "智能硬件": [
        "苹果概念",
        "小米",
        "手机游戏",
        "智能穿戴",
        "智能家居",
        "智能音箱",
        "无线充电",
        "无线耳机",
        "智能医疗",
        "智能交通",
        "智慧灯杆",
    ],
    "高端制造": ["高端装备", "海工装备", "特高压", "电网", "水利"],
    "材料化工": [
        "碳纤维",
        "氟化工",
        "磷化工",
        "硅能源",
        "钒电池",
        "可降解塑料",
        "POE胶膜",
        "PET铜箔",
        "PEEK材料",
        "石墨烯",
        "超级电容",
        "新型工业化",
        "页岩气",
        "可燃冰",
    ],
    "生物医药": [
        "创新药",
        "合成生物",
        "仿制药",
        "基因测序",
        "细胞免疫",
        "医疗器械",
        "疫苗",
        "减肥药",
        "维生素",
        "NMN",
    ],
    "软件互联网": [
        "网络安全",
        "数字经济",
        "数据要素",
        "数据确权",
        "智慧城市",
        "智慧政务",
        "在线教育",
        "职业教育",
    ],
    "泛科技指数": [
        "专精特新",
        "宁德时代",
        "比亚迪概念",
        "特斯拉概念",
        "苹果概念",
        "独角兽",
        "人形机器人",
        "长安汽车",
    ],
    "新能源产业链": [
        "稀土永磁",
        "盐湖提锂",
        "金属",
        "石墨电极",
        "环氧丙烷",
        "碳中和",
        "碳交易",
        "碳纤维",
        "抽水蓄能",
    ],
}


def get_categories(name):
    """返回概念命中的所有类别列表"""
    cats = []
    if any(kw in name for kw in AUTO_INCLUDE_KEYWORDS):
        cats.append("核心科技")
    for cat, keywords in PAN_TECH_CATEGORIES.items():
        if any(kw in name for kw in keywords):
            cats.append(cat)
    if not cats:
        cats.append("泛科技")
    return cats


# ── 过滤 & 分类 ──────────────────────────────────────────────
df["is_excluded"] = df["concept_name"].apply(is_excluded)
df["ts_code"] = df["stock_code"].apply(clean_ts_code)
df = df[df["ts_code"].notna() & ~df["is_excluded"]].copy()

# 为每行计算 categories（逗号分隔）
df["categories"] = df["concept_name"].apply(get_categories)

print(f"过滤后: {len(df)} 条")

# ── 去重 + 汇总 ──────────────────────────────────────────────
# 按 (stock_code, concept_name) 去重
df_unique = df.drop_duplicates(subset=["stock_code", "concept_name"])
print(f"去重后: {len(df_unique)} 条, {df_unique['stock_code'].nunique()} 只股票")

# 汇总每只股票的信息
stock_infos = {}
for _, row in df_unique.iterrows():
    ts = row["ts_code"]
    cats = row["categories"]
    if ts not in stock_infos:
        stock_infos[ts] = {
            "name": row["stock_name"],
            "categories": set(),
            "concepts": set(),
        }
    stock_infos[ts]["categories"].update(cats)
    stock_infos[ts]["concepts"].add(row["concept_name"])

whitelist = sorted(stock_infos.keys())
print(f"最终白名单: {len(whitelist)} 只")

# ── 统计 ──────────────────────────────────────────────
cat_total = defaultdict(int)
for info in stock_infos.values():
    for cat in info["categories"]:
        cat_total[cat] += 1

print("\n=== 股票类别分布 ===")
for cat, cnt in sorted(cat_total.items(), key=lambda x: -x[1]):
    print(f"  {cat:20s} {cnt:>5}")

# ── 写入文件 ──────────────────────────────────────────────
DATA_DIR.mkdir(parents=True, exist_ok=True)

# 1. 白名单
wl_file = DATA_DIR / "tech_ts_codes.txt"
wl_file.write_text("\n".join(whitelist) + "\n")
print(f"\n已写入: {wl_file} ({len(whitelist)} 只)")

# 2. 概念映射
concept_map = df_unique.groupby("concept_name")["stock_code"].apply(lambda x: sorted(x.unique())).to_dict()
with open(DATA_DIR / "tech_concepts.json", "w", encoding="utf-8") as f:
    json.dump(concept_map, f, ensure_ascii=False, indent=2)
print(f"已写入: {DATA_DIR / 'tech_concepts.json'} ({len(concept_map)} 个概念)")

# 3. 类别 -> 股票
cat_map = defaultdict(list)
for ts, info in stock_infos.items():
    for cat in info["categories"]:
        cat_map[cat].append(ts)
for cat in cat_map:
    cat_map[cat] = sorted(cat_map[cat])
with open(DATA_DIR / "tech_categories.json", "w", encoding="utf-8") as f:
    json.dump(dict(sorted(cat_map.items())), f, ensure_ascii=False, indent=2)
print(f"已写入: {DATA_DIR / 'tech_categories.json'} ({len(cat_map)} 个类别)")

# 4. 股票详情
stock_detail = {}
for ts, info in stock_infos.items():
    stock_detail[ts] = {
        "name": info["name"],
        "categories": sorted(list(info["categories"])),
        "concepts": sorted(list(info["concepts"])),
    }
with open(DATA_DIR / "tech_stocks_detail.json", "w", encoding="utf-8") as f:
    json.dump(stock_detail, f, ensure_ascii=False, indent=2)
print(f"已写入: {DATA_DIR / 'tech_stocks_detail.json'} ({len(stock_detail)} 只)")

# 5. 概念-类别映射
concept_cat_map = {}
for _, row in df_unique.drop_duplicates(subset="concept_name").iterrows():
    cats = get_categories(row["concept_name"])
    concept_cat_map[row["concept_name"]] = cats
with open(DATA_DIR / "concept_categories.json", "w", encoding="utf-8") as f:
    json.dump(concept_cat_map, f, ensure_ascii=False, indent=2)
print(f"已写入: {DATA_DIR / 'concept_categories.json'} ({len(concept_cat_map)} 个概念)")

# 交易所分布
sh = len([s for s in whitelist if s.endswith(".SH")])
sz = len([s for s in whitelist if s.endswith(".SZ")])
bj = len([s for s in whitelist if s.endswith(".BJ")])
print(f"\n上交所: {sh}, 深交所: {sz}, 北交所: {bj}")
