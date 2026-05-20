"""
光通信产业链知识图谱数据初始化
来源：2026-03-25_光通信产业链核心赛道全解析.md（乐晴智库）

设计原则：
  - 图谱只存"结构性事实"，不存推理结论
  - 关系必须有方向性（除 COMPETES_WITH 外）
  - 所有边带 valid_from/to + source_type + confidence
  - 边属性化（Reification）：有限边类型 + 无限属性
"""

"""
光通信产业链知识图谱数据初始化（示例数据）

如需为特定股票池初始化 KG 数据，请使用：
  - scripts/sync_kg_from_stockpool.py（每日自动运行）
  - LLM 抽取材料后写入（V1.2 文本挖掘 pipeline）

本脚本仅作示例/测试用途，不针对特定业务场景。
"""

import sys
import os
from datetime import date, datetime
from app.knowledge.entity_service import upsert_entity, generate_entity_id
from app.knowledge.relation_service import upsert_relation

# ============================================================
# 光通信产业链实体数据
# ============================================================

INDUSTRIES = [
    {
        "entity_id": "IND_FIBER",
        "entity_type": "Industry",
        "name": "光纤光缆",
        "properties": {
            "upstream": ["IND_CHIP"],
            "downstream": ["IND_MODULE", "IND_EQUIPMENT"],
            "tech_routes": ["普通光纤", "WDM波分复用", "空芯光纤"],
            "current_stage": "WDM为主，空芯光纤商用起步",
        },
        "source_type": "research_report",
        "source_name": "乐晴智库",
        "valid_from": "2020-01-01",
    },
    {
        "entity_id": "IND_CHIP",
        "entity_type": "Industry",
        "name": "光芯片",
        "properties": {
            "upstream": ["IND_FIBER"],
            "downstream": ["IND_COMPONENT", "IND_MODULE"],
            "tech_routes": ["2.5G/10G低速", "25G/50G高速", "100G EML", "硅光"],
            "current_stage": "25G以上高速化，国产替代加速",
        },
        "source_type": "research_report",
        "source_name": "乐晴智库",
        "valid_from": "2020-01-01",
    },
    {
        "entity_id": "IND_COMPONENT",
        "entity_type": "Industry",
        "name": "光器件",
        "properties": {
            "upstream": ["IND_CHIP"],
            "downstream": ["IND_MODULE"],
            "key_components": ["TOSA", "ROSA", "BOSA", "高速光引擎"],
            "current_stage": "TOSA/ROSA/BOSA国产化率高，高速光引擎快速迭代",
        },
        "source_type": "research_report",
        "source_name": "乐晴智库",
        "valid_from": "2020-01-01",
    },
    {
        "entity_id": "IND_MODULE",
        "entity_type": "Industry",
        "name": "光模块",
        "properties": {
            "upstream": ["IND_CHIP", "IND_COMPONENT"],
            "downstream": ["IND_EQUIPMENT"],
            "tech_evolution": ["400G(出清中)", "800G(量产爬坡)", "1.6T(送样验证)", "3.2T(研发中)"],
            "current_stage": "800G量产爬坡，1.6T送样验证",
        },
        "source_type": "research_report",
        "source_name": "乐晴智库",
        "valid_from": "2020-01-01",
    },
    {
        "entity_id": "IND_CPO",
        "entity_type": "Industry",
        "name": "共封装光学(CPO)",
        "properties": {
            "upstream": ["IND_CHIP"],
            "downstream": ["IND_EQUIPMENT"],
            "tech_evolution": ["NPO", "CPO", "OIO"],
            "current_stage": "送样/小批量，博通2026-H2量产",
        },
        "source_type": "research_report",
        "source_name": "乐晴智库",
        "valid_from": "2024-01-01",
    },
    {
        "entity_id": "IND_OCS",
        "entity_type": "Industry",
        "name": "光电路交换(OCS)",
        "properties": {
            "upstream": ["IND_CHIP"],
            "downstream": ["IND_EQUIPMENT"],
            "current_stage": "谷歌规模导入，OCS交换机定制化生产",
        },
        "source_type": "research_report",
        "source_name": "乐晴智库",
        "valid_from": "2024-01-01",
    },
    {
        "entity_id": "IND_EQUIPMENT",
        "entity_type": "Industry",
        "name": "通信设备",
        "properties": {
            "upstream": ["IND_MODULE", "IND_CPO", "IND_OCS"],
            "downstream": [],
            "key_players": ["华为", "中兴通讯", "烽火通信"],
            "current_stage": "CPO交换机商用前夕",
        },
        "source_type": "research_report",
        "source_name": "乐晴智库",
        "valid_from": "2020-01-01",
    },
    {
        "entity_id": "IND_DATACENTER",
        "entity_type": "Industry",
        "name": "数据中心",
        "properties": {
            "upstream": [],
            "downstream": [],
            "key_players": ["谷歌", "Meta", "亚马逊", "微软"],
            "current_stage": "AI驱动光互联超级周期",
        },
        "source_type": "research_report",
        "source_name": "乐晴智库",
        "valid_from": "2020-01-01",
    },
]

COMPANIES = [
    # 光模块
    {
        "entity_id": "CO_300308",
        "entity_type": "Company",
        "name": "中际旭创",
        "ts_code": "300308.SZ",
        "properties": {
            "listing_board": "创业板",
            "industry_tags": ["光模块", "数据中心"],
            "main_products": ["800G光模块", "1.6T OSFP-XD硅光光模块"],
            "customer_base": ["北美CSP", "谷歌", "Meta"],
            "tech_route": "EML+硅光双路线",
            "is_idm": False,
        },
        "source_type": "research_report",
        "source_name": "乐晴智库",
        "valid_from": "2023-01-01",
    },
    {
        "entity_id": "CO_300502",
        "entity_type": "Company",
        "name": "新易盛",
        "ts_code": "300502.SZ",
        "properties": {
            "listing_board": "创业板",
            "industry_tags": ["光模块"],
            "main_products": ["800G光模块"],
            "customer_base": ["北美CSP"],
            "tech_route": "传统EML",
            "is_idm": False,
        },
        "source_type": "research_report",
        "source_name": "乐晴智库",
        "valid_from": "2023-01-01",
    },
    {
        "entity_id": "CO_002281",
        "entity_type": "Company",
        "name": "光迅科技",
        "ts_code": "002281.SZ",
        "properties": {
            "listing_board": "主板",
            "industry_tags": ["光模块", "光器件"],
            "main_products": ["800G硅光光模块", "400G硅光光模块"],
            "customer_base": ["国内CSP", "华为"],
            "tech_route": "硅光",
            "is_idm": True,
        },
        "source_type": "research_report",
        "source_name": "乐晴智库",
        "valid_from": "2023-01-01",
    },
    {
        "entity_id": "CO_603083",
        "entity_type": "Company",
        "name": "剑桥科技",
        "ts_code": "603083.SH",
        "properties": {
            "listing_board": "主板",
            "industry_tags": ["光模块"],
            "main_products": ["800G光模块"],
            "customer_base": ["北美CSP"],
            "tech_route": "传统EML",
            "is_idm": False,
        },
        "source_type": "research_report",
        "source_name": "乐晴智库",
        "valid_from": "2023-01-01",
    },
    # 光器件
    {
        "entity_id": "CO_300394",
        "entity_type": "Company",
        "name": "天孚通信",
        "ts_code": "300394.SZ",
        "properties": {
            "listing_board": "创业板",
            "industry_tags": ["光器件"],
            "main_products": ["TOSA发射组件", "ROSA接收组件", "高速光引擎", "FAU封装", "ELS光源"],
            "customer_base": ["光模块厂商"],
            "tech_route": "垂直整合",
            "is_idm": False,
        },
        "source_type": "research_report",
        "source_name": "乐晴智库",
        "valid_from": "2023-01-01",
    },
    # 光芯片
    {
        "entity_id": "CO_688498",
        "entity_type": "Company",
        "name": "源杰科技",
        "ts_code": "688498.SH",
        "properties": {
            "listing_board": "科创板",
            "industry_tags": ["光芯片"],
            "main_products": ["100G EML芯片", "25G DFB激光器", "CW激光器（兼容800G/1.6T）"],
            "customer_base": ["国内CSP", "光模块厂商"],
            "tech_route": "IDM",
            "is_idm": True,
        },
        "source_type": "research_report",
        "source_name": "乐晴智库",
        "valid_from": "2023-01-01",
    },
    {
        "entity_id": "CO_688048",
        "entity_type": "Company",
        "name": "长光华芯",
        "ts_code": "688048.SH",
        "properties": {
            "listing_board": "科创板",
            "industry_tags": ["光芯片"],
            "main_products": ["100mW CW DFB激光器芯片", "VCSEL激光芯片"],
            "customer_base": ["光模块厂商"],
            "tech_route": "VCSEL",
            "is_idm": True,
        },
        "source_type": "research_report",
        "source_name": "乐晴智库",
        "valid_from": "2023-01-01",
    },
    {
        "entity_id": "CO_688313",
        "entity_type": "Company",
        "name": "仕佳光子",
        "ts_code": "688313.SH",
        "properties": {
            "listing_board": "科创板",
            "industry_tags": ["光芯片"],
            "main_products": ["CW光源", "CWDFB激光器", "PLC光分路器芯片", "AWG芯片"],
            "customer_base": ["博通", "国内CSP"],
            "tech_route": "PLC/AWG",
            "is_idm": True,
        },
        "source_type": "research_report",
        "source_name": "乐晴智库",
        "valid_from": "2023-01-01",
    },
    # CPO
    {
        "entity_id": "CO_300757",
        "entity_type": "Company",
        "name": "罗博特科",
        "ts_code": "300757.SZ",
        "properties": {
            "listing_board": "创业板",
            "industry_tags": ["CPO设备"],
            "main_products": ["硅光/CPO设备"],
            "customer_base": ["光模块厂商"],
            "tech_route": "设备商",
            "is_idm": False,
        },
        "source_type": "research_report",
        "source_name": "乐晴智库",
        "valid_from": "2024-01-01",
    },
    # OCS
    {
        "entity_id": "CO_688205",
        "entity_type": "Company",
        "name": "德科立",
        "ts_code": "688205.SH",
        "properties": {
            "listing_board": "科创板",
            "industry_tags": ["OCS"],
            "main_products": ["OCS整机（谷歌定制）"],
            "customer_base": ["谷歌"],
            "tech_route": "硅光+商用光电模组",
            "is_idm": False,
        },
        "source_type": "research_report",
        "source_name": "乐晴智库",
        "valid_from": "2023-01-01",
    },
    {
        "entity_id": "CO_688195",
        "entity_type": "Company",
        "name": "腾景科技",
        "ts_code": "688195.SH",
        "properties": {
            "listing_board": "科创板",
            "industry_tags": ["OCS"],
            "main_products": ["钒酸钇晶体（全球领先）", "透镜阵列"],
            "customer_base": ["OCS厂商"],
            "tech_route": "晶体",
            "is_idm": False,
        },
        "source_type": "research_report",
        "source_name": "乐晴智库",
        "valid_from": "2023-01-01",
    },
    {
        "entity_id": "CO_300620",
        "entity_type": "Company",
        "name": "光库科技",
        "ts_code": "300620.SZ",
        "properties": {
            "listing_board": "创业板",
            "industry_tags": ["OCS", "光器件"],
            "main_products": ["铌酸锂调制器", "薄膜铌酸锂调制器", "MEMS产品"],
            "customer_base": ["谷歌（OCS代工）", "光模块厂商"],
            "tech_route": "薄膜铌酸锂",
            "is_idm": False,
        },
        "source_type": "research_report",
        "source_name": "乐晴智库",
        "valid_from": "2023-01-01",
    },
    # 光纤光缆
    {
        "entity_id": "CO_601869",
        "entity_type": "Company",
        "name": "长飞光纤",
        "ts_code": "601869.SH",
        "properties": {
            "listing_board": "主板",
            "industry_tags": ["光纤光缆"],
            "main_products": ["空芯光纤", "WDM波分复用器"],
            "customer_base": ["运营商", "数据中心"],
            "tech_route": "光纤",
            "is_idm": True,
        },
        "source_type": "research_report",
        "source_name": "乐晴智库",
        "valid_from": "2023-01-01",
    },
    {
        "entity_id": "CO_600487",
        "entity_type": "Company",
        "name": "亨通光电",
        "ts_code": "600487.SH",
        "properties": {
            "listing_board": "主板",
            "industry_tags": ["光纤光缆"],
            "main_products": ["空芯光纤", "海缆"],
            "customer_base": ["运营商", "数据中心"],
            "tech_route": "光纤",
            "is_idm": True,
        },
        "source_type": "research_report",
        "source_name": "乐晴智库",
        "valid_from": "2023-01-01",
    },
    {
        "entity_id": "CO_600105",
        "entity_type": "Company",
        "name": "永鼎股份",
        "ts_code": "600105.SH",
        "properties": {
            "listing_board": "主板",
            "industry_tags": ["光纤光缆", "光芯片"],
            "main_products": ["WDM滤光片", "ELS光源", "IDM激光器芯片"],
            "customer_base": ["光模块厂商"],
            "tech_route": "IDM",
            "is_idm": True,
        },
        "source_type": "research_report",
        "source_name": "乐晴智库",
        "valid_from": "2023-01-01",
    },
    # 通信设备
    {
        "entity_id": "CO_000063",
        "entity_type": "Company",
        "name": "中兴通讯",
        "ts_code": "000063.SZ",
        "properties": {
            "listing_board": "主板",
            "industry_tags": ["通信设备"],
            "main_products": ["光通信设备", "运营商网络设备"],
            "customer_base": ["运营商"],
            "tech_route": "设备商",
            "is_idm": True,
        },
        "source_type": "research_report",
        "source_name": "乐晴智库",
        "valid_from": "2023-01-01",
    },
    # 海外公司
    {
        "entity_id": "CO_GOOGLE",
        "entity_type": "Company",
        "name": "谷歌",
        "ts_code": None,
        "properties": {
            "listing_board": "海外",
            "industry_tags": ["数据中心"],
            "main_products": ["TPU集群", "OCS交换机"],
            "customer_base": [],
            "tech_route": "自研",
            "is_idm": False,
        },
        "source_type": "research_report",
        "source_name": "乐晴智库",
        "valid_from": "2023-01-01",
    },
    {
        "entity_id": "CO_BROADCOM",
        "entity_type": "Company",
        "name": "博通",
        "ts_code": None,
        "properties": {
            "listing_board": "海外",
            "industry_tags": ["CPO", "光芯片"],
            "main_products": ["CPO交换机", "硅光芯片", "PAM4 DSP"],
            "customer_base": ["数据中心"],
            "tech_route": "硅光+CPO",
            "is_idm": True,
        },
        "source_type": "research_report",
        "source_name": "乐晴智库",
        "valid_from": "2024-01-01",
    },
]

PRODUCTS = [
    {
        "entity_id": "PROD_400G_MODULE",
        "entity_type": "Product",
        "name": "400G光模块",
        "properties": {
            "category": "光模块",
            "tech_generation": "Gen3",
            "mass_production_status": "出清中",
            "key_players": ["中际旭创", "新易盛", "光迅科技"],
            "price_trend": "降价",
        },
        "source_type": "research_report",
        "source_name": "乐晴智库",
        "valid_from": "2022-01-01",
    },
    {
        "entity_id": "PROD_800G_MODULE",
        "entity_type": "Product",
        "name": "800G光模块",
        "properties": {
            "category": "光模块",
            "tech_generation": "Gen4",
            "mass_production_status": "量产爬坡",
            "key_players": ["中际旭创", "新易盛", "光迅科技", "剑桥科技", "华工科技"],
            "price_usd_range": "400-600",
        },
        "source_type": "research_report",
        "source_name": "乐晴智库",
        "valid_from": "2024-01-01",
    },
    {
        "entity_id": "PROD_1P6T_MODULE",
        "entity_type": "Product",
        "name": "1.6T光模块",
        "properties": {
            "category": "光模块",
            "tech_generation": "Gen5",
            "mass_production_status": "送样验证",
            "key_players": ["中际旭创（联合思科）", "新易盛"],
            "evidence": "OFC2026展出",
        },
        "source_type": "research_report",
        "source_name": "乐晴智库",
        "valid_from": "2025-01-01",
    },
    {
        "entity_id": "PROD_EML_100G",
        "entity_type": "Product",
        "name": "100G EML芯片",
        "properties": {
            "category": "光芯片",
            "tech_generation": "Gen3",
            "mass_production_status": "送样验证",
            "key_players": ["源杰科技（国内领先）", "长光华芯"],
            "overseas_players": ["Coherent", "Lumentum"],
            "market_share_overseas": "80%+",
        },
        "source_type": "research_report",
        "source_name": "乐晴智库",
        "valid_from": "2024-01-01",
    },
    {
        "entity_id": "PROD_EML_25G",
        "entity_type": "Product",
        "name": "25G激光器芯片",
        "properties": {
            "category": "光芯片",
            "tech_generation": "Gen2",
            "mass_production_status": "量产",
            "key_players": ["源杰科技", "云岭光电", "长光华芯", "中科光芯"],
            "domestic_market_share": "加速突破",
        },
        "source_type": "research_report",
        "source_name": "乐晴智库",
        "valid_from": "2023-01-01",
    },
    {
        "entity_id": "PROD_CW_LASER",
        "entity_type": "Product",
        "name": "CW激光器",
        "properties": {
            "category": "光芯片",
            "tech_generation": "Gen3",
            "mass_production_status": "小批量",
            "key_players": ["仕佳光子", "源杰科技", "长光华芯"],
            "application": "硅光光源",
        },
        "source_type": "research_report",
        "source_name": "乐晴智库",
        "valid_from": "2024-01-01",
    },
    {
        "entity_id": "PROD_SIP_CHIP",
        "entity_type": "Product",
        "name": "硅光芯片",
        "properties": {
            "category": "光芯片",
            "tech_generation": "Gen4",
            "mass_production_status": "送样验证",
            "key_players": ["英特尔", "博通", "Marvell", "光迅科技", "仕佳光子"],
        },
        "source_type": "research_report",
        "source_name": "乐晴智库",
        "valid_from": "2024-01-01",
    },
    {
        "entity_id": "PROD_CPO_SWITCH",
        "entity_type": "Product",
        "name": "CPO以太网交换机",
        "properties": {
            "category": "CPO",
            "tech_generation": "Gen1",
            "mass_production_status": "送样/小批量",
            "key_players": ["博通", "英伟达", "英特尔"],
            "evidence": "博通2026-H2量产，第四季度月产能千级",
        },
        "source_type": "research_report",
        "source_name": "乐晴智库",
        "valid_from": "2025-01-01",
    },
    {
        "entity_id": "PROD_OCS_SWITCH",
        "entity_type": "Product",
        "name": "OCS光交换机",
        "properties": {
            "category": "OCS",
            "tech_generation": "Gen1",
            "mass_production_status": "规模导入",
            "key_players": ["德科立（谷歌定制）"],
            "evidence": "谷歌Ironwood集群配置2000+台OCS交换机",
        },
        "source_type": "research_report",
        "source_name": "乐晴智库",
        "valid_from": "2024-01-01",
    },
    {
        "entity_id": "PROD_LN_MODULATOR",
        "entity_type": "Product",
        "name": "铌酸锂调制器",
        "properties": {
            "category": "光器件",
            "tech_generation": "Gen2",
            "mass_production_status": "小批量",
            "key_players": ["光库科技"],
            "tech_advantage": "薄膜铌酸锂",
        },
        "source_type": "research_report",
        "source_name": "乐晴智库",
        "valid_from": "2023-01-01",
    },
    {
        "entity_id": "PROD_HCF",
        "entity_type": "Product",
        "name": "空芯光纤",
        "properties": {
            "category": "光纤",
            "tech_generation": "Gen2",
            "mass_production_status": "商用部署起步",
            "key_players": ["长飞光纤", "亨通光电", "中天科技"],
            "application": "数据中心/海缆",
        },
        "source_type": "research_report",
        "source_name": "乐晴智库",
        "valid_from": "2024-01-01",
    },
    {
        "entity_id": "PROD_TOSA",
        "entity_type": "Product",
        "name": "TOSA发射组件",
        "properties": {
            "category": "光器件",
            "mass_production_status": "量产",
            "key_players": ["天孚通信（垂直整合）"],
        },
        "source_type": "research_report",
        "source_name": "乐晴智库",
        "valid_from": "2022-01-01",
    },
]

EVENTS = [
    {
        "entity_id": "EVT_GTC2026",
        "entity_type": "Event",
        "name": "英伟达GTC 2026",
        "properties": {
            "event_type": "产业大会",
            "date": "2026-03",
            "affected_industries": ["IND_CPO", "IND_MODULE"],
            "affected_companies": ["博通", "中际旭创"],
            "signal_direction": "bullish",
            "key_content": "展示CPO技术Spectrum-6以太网交换机，Vera Rubin平台采用",
        },
        "source_type": "cls_news",
        "source_name": "乐晴智库",
        "valid_from": "2026-03-01",
    },
    {
        "entity_id": "EVT_OFC2026",
        "entity_type": "Event",
        "name": "OFC 2026全球光通信大会",
        "properties": {
            "event_type": "产业大会",
            "date": "2026-03",
            "affected_industries": ["IND_CHIP", "IND_MODULE", "IND_CPO", "IND_OCS"],
            "affected_companies": ["中际旭创", "光迅科技", "仕佳光子"],
            "signal_direction": "bullish",
            "key_content": "1.6T OSFP-XD硅光光模块展出，多项新技术落地",
        },
        "source_type": "research_report",
        "source_name": "乐晴智库",
        "valid_from": "2026-03-01",
    },
    {
        "entity_id": "EVT_BROADCOM_CPO",
        "entity_type": "Event",
        "name": "博通CPO 2026H2量产声明",
        "properties": {
            "event_type": "产能指引",
            "date": "2026-03",
            "affected_industries": ["IND_CPO"],
            "affected_companies": ["博通"],
            "signal_direction": "bullish",
            "key_content": "2026年下半年进入关键量产阶段，Q4月产能千级",
        },
        "source_type": "research_report",
        "source_name": "乐晴智库",
        "valid_from": "2026-03-01",
    },
    {
        "entity_id": "EVT_GOOGLE_IRONWOOD",
        "entity_type": "Event",
        "name": "谷歌Ironwood TPU集群",
        "properties": {
            "event_type": "产品发布",
            "date": "2026-03",
            "affected_industries": ["IND_OCS", "IND_DATACENTER"],
            "affected_companies": ["德科立"],
            "signal_direction": "bullish",
            "key_content": "单集群集成数万颗TPU，配置2000+台OCS交换机",
        },
        "source_type": "research_report",
        "source_name": "乐晴智库",
        "valid_from": "2026-03-01",
    },
    {
        "entity_id": "EVT_LUMENTUM_EXPAND",
        "entity_type": "Event",
        "name": "Lumentum扩产指引",
        "properties": {
            "event_type": "产能指引",
            "date": "2026-03",
            "affected_industries": ["IND_CHIP"],
            "affected_companies": ["Lumentum"],
            "signal_direction": "bullish",
            "key_content": "EML/CW/UHP高功率产能26-30年CAGR 85%，远超AI算力增速",
        },
        "source_type": "research_report",
        "source_name": "乐晴智库",
        "valid_from": "2026-03-01",
    },
    {
        "entity_id": "EVT_CHIP_SUPPLY_SHORTAGE",
        "entity_type": "Event",
        "name": "光芯片供应紧张",
        "properties": {
            "event_type": "供需变化",
            "date": "2026-03",
            "affected_industries": ["IND_CHIP", "IND_CPO"],
            "signal_direction": "neutral",
            "key_content": "CPO和OIO离不开光芯片，行业供需缺口持续扩大",
        },
        "source_type": "research_report",
        "source_name": "乐晴智库",
        "valid_from": "2026-01-01",
    },
]

# ============================================================
# 光通信产业链关系数据
# ============================================================

RELATIONSHIPS = [
    # === 公司 BELONGS_TO 产业 ===
    ("CO_300308", "IND_MODULE", "BELONGS_TO", 0.85, "2023-01-01", {},
     "Company→Industry", "research_report", "乐晴智库",
     "2026-03-25_光通信产业链核心赛道全解析.md", "光模块龙头"),
    ("CO_300502", "IND_MODULE", "BELONGS_TO", 0.85, "2023-01-01", {},
     "Company→Industry", "research_report", "乐晴智库",
     "2026-03-25_光通信产业链核心赛道全解析.md", "光模块龙头"),
    ("CO_002281", "IND_MODULE", "BELONGS_TO", 0.85, "2023-01-01", {},
     "Company→Industry", "research_report", "乐晴智库",
     "2026-03-25_光通信产业链核心赛道全解析.md", "光模块龙头"),
    ("CO_603083", "IND_MODULE", "BELONGS_TO", 0.85, "2023-01-01", {},
     "Company→Industry", "research_report", "乐晴智库",
     "2026-03-25_光通信产业链核心赛道全解析.md", ""),
    ("CO_300394", "IND_COMPONENT", "BELONGS_TO", 0.85, "2023-01-01", {},
     "Company→Industry", "research_report", "乐晴智库",
     "2026-03-25_光通信产业链核心赛道全解析.md", ""),
    ("CO_688498", "IND_CHIP", "BELONGS_TO", 0.85, "2023-01-01", {},
     "Company→Industry", "research_report", "乐晴智库",
     "2026-03-25_光通信产业链核心赛道全解析.md", "国内100G EML领先"),
    ("CO_688048", "IND_CHIP", "BELONGS_TO", 0.85, "2023-01-01", {},
     "Company→Industry", "research_report", "乐晴智库",
     "2026-03-25_光通信产业链核心赛道全解析.md", ""),
    ("CO_688313", "IND_CHIP", "BELONGS_TO", 0.85, "2023-01-01", {},
     "Company→Industry", "research_report", "乐晴智库",
     "2026-03-25_光通信产业链核心赛道全解析.md", "CW光源在博通验证"),
    ("CO_300757", "IND_CPO", "BELONGS_TO", 0.85, "2024-01-01", {},
     "Company→Industry", "research_report", "乐晴智库",
     "2026-03-25_光通信产业链核心赛道全解析.md", ""),
    ("CO_688205", "IND_OCS", "BELONGS_TO", 0.85, "2023-01-01", {},
     "Company→Industry", "research_report", "乐晴智库",
     "2026-03-25_光通信产业链核心赛道全解析.md", "谷歌OCS核心供应商"),
    ("CO_688195", "IND_OCS", "BELONGS_TO", 0.85, "2023-01-01", {},
     "Company→Industry", "research_report", "乐晴智库",
     "2026-03-25_光通信产业链核心赛道全解析.md", ""),
    ("CO_300620", "IND_OCS", "BELONGS_TO", 0.85, "2023-01-01", {},
     "Company→Industry", "research_report", "乐晴智库",
     "2026-03-25_光通信产业链核心赛道全解析.md", ""),
    ("CO_300620", "IND_COMPONENT", "BELONGS_TO", 0.85, "2023-01-01", {},
     "Company→Industry", "research_report", "乐晴智库",
     "2026-03-25_光通信产业链核心赛道全解析.md", ""),
    ("CO_601869", "IND_FIBER", "BELONGS_TO", 0.85, "2023-01-01", {},
     "Company→Industry", "research_report", "乐晴智库",
     "2026-03-25_光通信产业链核心赛道全解析.md", ""),
    ("CO_600487", "IND_FIBER", "BELONGS_TO", 0.85, "2023-01-01", {},
     "Company→Industry", "research_report", "乐晴智库",
     "2026-03-25_光通信产业链核心赛道全解析.md", ""),
    ("CO_600105", "IND_FIBER", "BELONGS_TO", 0.85, "2023-01-01", {},
     "Company→Industry", "research_report", "乐晴智库",
     "2026-03-25_光通信产业链核心赛道全解析.md", ""),
    ("CO_600105", "IND_CHIP", "BELONGS_TO", 0.85, "2023-01-01", {},
     "Company→Industry", "research_report", "乐晴智库",
     "2026-03-25_光通信产业链核心赛道全解析.md", ""),
    ("CO_000063", "IND_EQUIPMENT", "BELONGS_TO", 0.85, "2023-01-01", {},
     "Company→Industry", "research_report", "乐晴智库",
     "2026-03-25_光通信产业链核心赛道全解析.md", ""),
    ("CO_GOOGLE", "IND_DATACENTER", "BELONGS_TO", 0.85, "2023-01-01", {},
     "Company→Industry", "research_report", "乐晴智库",
     "2026-03-25_光通信产业链核心赛道全解析.md", ""),
    ("CO_BROADCOM", "IND_CPO", "BELONGS_TO", 0.85, "2024-01-01", {},
     "Company→Industry", "research_report", "乐晴智库",
     "2026-03-25_光通信产业链核心赛道全解析.md", ""),

    # === 公司 PRODUCES 产品 ===
    ("CO_300308", "PROD_800G_MODULE", "PRODUCES", 0.85, "2024-01-01", {},
     "Company→Product", "research_report", "乐晴智库",
     "2026-03-25_光通信产业链核心赛道全解析.md", "800G量产"),
    ("CO_300308", "PROD_1P6T_MODULE", "PRODUCES", 0.70, "2025-01-01", {},
     "Company→Product", "research_report", "乐晴智库",
     "2026-03-25_光通信产业链核心赛道全解析.md", "1.6T送样，OFC展出"),
    ("CO_300502", "PROD_800G_MODULE", "PRODUCES", 0.85, "2024-01-01", {},
     "Company→Product", "research_report", "乐晴智库",
     "2026-03-25_光通信产业链核心赛道全解析.md", ""),
    ("CO_002281", "PROD_800G_MODULE", "PRODUCES", 0.85, "2024-01-01", {},
     "Company→Product", "research_report", "乐晴智库",
     "2026-03-25_光通信产业链核心赛道全解析.md", "硅光路线"),
    ("CO_002281", "PROD_1P6T_MODULE", "PRODUCES", 0.70, "2025-01-01", {},
     "Company→Product", "research_report", "乐晴智库",
     "2026-03-25_光通信产业链核心赛道全解析.md", "联合思科"),
    ("CO_603083", "PROD_800G_MODULE", "PRODUCES", 0.85, "2024-01-01", {},
     "Company→Product", "research_report", "乐晴智库",
     "2026-03-25_光通信产业链核心赛道全解析.md", ""),
    ("CO_688498", "PROD_EML_100G", "PRODUCES", 0.75, "2024-01-01", {},
     "Company→Product", "research_report", "乐晴智库",
     "2026-03-25_光通信产业链核心赛道全解析.md", "国内100G EML领先"),
    ("CO_688498", "PROD_EML_25G", "PRODUCES", 0.85, "2023-01-01", {},
     "Company→Product", "research_report", "乐晴智库",
     "2026-03-25_光通信产业链核心赛道全解析.md", ""),
    ("CO_688498", "PROD_CW_LASER", "PRODUCES", 0.80, "2024-01-01", {},
     "Company→Product", "research_report", "乐晴智库",
     "2026-03-25_光通信产业链核心赛道全解析.md", "兼容800G/1.6T"),
    ("CO_688048", "PROD_EML_25G", "PRODUCES", 0.85, "2023-01-01", {},
     "Company→Product", "research_report", "乐晴智库",
     "2026-03-25_光通信产业链核心赛道全解析.md", "VCSEL"),
    ("CO_688313", "PROD_CW_LASER", "PRODUCES", 0.80, "2024-01-01", {},
     "Company→Product", "research_report", "乐晴智库",
     "2026-03-25_光通信产业链核心赛道全解析.md", "博通硅光验证"),
    ("CO_688205", "PROD_OCS_SWITCH", "PRODUCES", 0.85, "2024-01-01", {},
     "Company→Product", "research_report", "乐晴智库",
     "2026-03-25_光通信产业链核心赛道全解析.md", "谷歌定制"),
    ("CO_300620", "PROD_LN_MODULATOR", "PRODUCES", 0.85, "2023-01-01", {},
     "Company→Product", "research_report", "乐晴智库",
     "2026-03-25_光通信产业链核心赛道全解析.md", "薄膜铌酸锂"),
    ("CO_300394", "PROD_TOSA", "PRODUCES", 0.85, "2022-01-01", {},
     "Company→Product", "research_report", "乐晴智库",
     "2026-03-25_光通信产业链核心赛道全解析.md", "TOSA垂直整合"),
    ("CO_601869", "PROD_HCF", "PRODUCES", 0.85, "2024-01-01", {},
     "Company→Product", "research_report", "乐晴智库",
     "2026-03-25_光通信产业链核心赛道全解析.md", ""),
    ("CO_600487", "PROD_HCF", "PRODUCES", 0.85, "2024-01-01", {},
     "Company→Product", "research_report", "乐晴智库",
     "2026-03-25_光通信产业链核心赛道全解析.md", ""),

    # === 公司 SUPPLIES_TO 公司（通过产品） ===
    ("CO_688498", "CO_300308", "SUPPLIES_TO", 0.65, "2024-01-01",
     {"product": "100G EML芯片", "spec": "EML, 50G/100G", "contract_type": "长协"},
     "Company→Company", "research_report", "乐晴智库",
     "2026-03-25_光通信产业链核心赛道全解析.md", "光芯片→光模块"),
    ("CO_688313", "CO_BROADCOM", "SUPPLIES_TO", 0.65, "2024-01-01",
     {"product": "CW光源", "spec": "CWDFB, 50℃>1000mW", "tech_route": "硅光"},
     "Company→Company", "research_report", "乐晴智库",
     "2026-03-25_光通信产业链核心赛道全解析.md", "仕佳CW光源在博通硅光验证"),
    ("CO_688205", "CO_GOOGLE", "SUPPLIES_TO", 0.75, "2023-01-01",
     {"product": "OCS整机", "spec": "硅光芯片+商用光电模组", "contract_type": "定制"},
     "Company→Company", "research_report", "乐晴智库",
     "2026-03-25_光通信产业链核心赛道全解析.md", "谷歌OCS核心供应商"),
    ("CO_300620", "CO_GOOGLE", "SUPPLIES_TO", 0.65, "2024-01-01",
     {"product": "铌酸锂调制器/MEMS", "contract_type": "代工"},
     "Company→Company", "research_report", "乐晴智库",
     "2026-03-25_光通信产业链核心赛道全解析.md", "谷歌OCS代工"),
    ("CO_300394", "CO_300308", "SUPPLIES_TO", 0.65, "2024-01-01",
     {"product": "TOSA/高速光引擎", "spec": "FAU/ELS封装"},
     "Company→Company", "research_report", "乐晴智库",
     "2026-03-25_光通信产业链核心赛道全解析.md", "光器件→光模块"),

    # === 公司 COMPETES_WITH 公司 ===
    ("CO_300308", "CO_300502", "COMPETES_WITH", 0.90, "2023-01-01",
     {"market": "800G光模块", "tech_route": "EML"},
     "Company↔Company", "research_report", "乐晴智库",
     "2026-03-25_光通信产业链核心赛道全解析.md", "800G光模块正面竞争"),
    ("CO_300308", "CO_002281", "COMPETES_WITH", 0.90, "2023-01-01",
     {"market": "800G光模块", "tech_route": "硅光"},
     "Company↔Company", "research_report", "乐晴智库",
     "2026-03-25_光通信产业链核心赛道全解析.md", "800G硅光路线竞争"),
    ("CO_300502", "CO_603083", "COMPETES_WITH", 0.90, "2023-01-01",
     {"market": "800G光模块"},
     "Company↔Company", "research_report", "乐晴智库",
     "2026-03-25_光通信产业链核心赛道全解析.md", ""),
    ("CO_688498", "CO_688048", "COMPETES_WITH", 0.90, "2023-01-01",
     {"market": "25G以上高速光芯片"},
     "Company↔Company", "research_report", "乐晴智库",
     "2026-03-25_光通信产业链核心赛道全解析.md", "光芯片国产替代竞争"),
    ("CO_688498", "CO_688313", "COMPETES_WITH", 0.85, "2024-01-01",
     {"market": "CW光源（硅光配套）"},
     "Company↔Company", "research_report", "乐晴智库",
     "2026-03-25_光通信产业链核心赛道全解析.md", "CW光源硅光配套竞争"),

    # === 产品 SUBSTITUTES 产品 ===
    ("PROD_800G_MODULE", "PROD_400G_MODULE", "SUBSTITUTES", 0.85, "2024-01-01",
     {"substitute_prob": 0.9, "cost_delta": -0.3, "tech_gap": "1代"},
     "Product→Product", "research_report", "乐晴智库",
     "2026-03-25_光通信产业链核心赛道全解析.md", "800G替代400G"),
    ("PROD_1P6T_MODULE", "PROD_800G_MODULE", "SUBSTITUTES", 0.60, "2025-01-01",
     {"substitute_prob": 0.5, "cost_delta": None, "tech_gap": "1代"},
     "Product→Product", "research_report", "乐晴智库",
     "2026-03-25_光通信产业链核心赛道全解析.md", "1.6T送样中"),
    ("PROD_EML_100G", "PROD_EML_25G", "SUBSTITUTES", 0.80, "2024-01-01",
     {"substitute_prob": 0.7, "cost_delta": None, "tech_gap": "1代"},
     "Product→Product", "research_report", "乐晴智库",
     "2026-03-25_光通信产业链核心赛道全解析.md", "100G替代25G"),

    # === 产品 APPLIES_TO 产业 ===
    ("PROD_800G_MODULE", "IND_DATACENTER", "APPLIES_TO", 0.90, "2024-01-01",
     {"渗透率": "快速提升", "认证状态": "已认证"},
     "Product→Industry", "research_report", "乐晴智库",
     "2026-03-25_光通信产业链核心赛道全解析.md", "数据中心为主要市场"),
    ("PROD_CPO_SWITCH", "IND_DATACENTER", "APPLIES_TO", 0.85, "2025-01-01",
     {"渗透率": "起步", "认证状态": "送样中"},
     "Product→Industry", "research_report", "乐晴智库",
     "2026-03-25_光通信产业链核心赛道全解析.md", "AI集群交换机"),
    ("PROD_OCS_SWITCH", "IND_DATACENTER", "APPLIES_TO", 0.85, "2024-01-01",
     {"渗透率": "规模导入", "认证状态": "已认证"},
     "Product→Industry", "research_report", "乐晴智库",
     "2026-03-25_光通信产业链核心赛道全解析.md", "谷歌TPU集群"),

    # === 事件 CATALYZES / CONSTRAINS ===
    ("EVT_GTC2026", "IND_CPO", "CATALYZES", 0.75, "2026-03-01",
     {"lag_period": 6, "intensity": "高", "affected_scope": "全行业"},
     "Event→Industry", "cls_news", "乐晴智库",
     "2026-03-25_光通信产业链核心赛道全解析.md", "英伟达GTC CPO展示催化CPO"),
    ("EVT_GTC2026", "IND_MODULE", "CATALYZES", 0.75, "2026-03-01",
     {"lag_period": 3, "intensity": "高", "affected_scope": "光模块"},
     "Event→Industry", "cls_news", "乐晴智库",
     "2026-03-25_光通信产业链核心赛道全解析.md", ""),
    ("EVT_BROADCOM_CPO", "IND_CPO", "CATALYZES", 0.80, "2026-03-01",
     {"lag_period": 12, "intensity": "高", "affected_scope": "CPO全链条"},
     "Event→Industry", "research_report", "乐晴智库",
     "2026-03-25_光通信产业链核心赛道全解析.md", "博通量产声明"),
    ("EVT_GOOGLE_IRONWOOD", "IND_OCS", "CATALYZES", 0.80, "2026-03-01",
     {"lag_period": 3, "intensity": "高", "affected_scope": "OCS全链条"},
     "Event→Industry", "research_report", "乐晴智库",
     "2026-03-25_光通信产业链核心赛道全解析.md", "谷歌Ironwood TPU导入OCS"),
    ("EVT_LUMENTUM_EXPAND", "IND_CHIP", "CATALYZES", 0.70, "2026-03-01",
     {"lag_period": 6, "intensity": "中", "affected_scope": "光芯片供需"},
     "Event→Industry", "research_report", "乐晴智库",
     "2026-03-25_光通信产业链核心赛道全解析.md", "海外扩产加速"),
    ("EVT_CHIP_SUPPLY_SHORTAGE", "IND_CPO", "CONSTRAINS", 0.75, "2026-01-01",
     {"reason": "上游光芯片短缺", "duration": "未知"},
     "Event→Industry", "research_report", "乐晴智库",
     "2026-03-25_光通信产业链核心赛道全解析.md", "CPO规模化的制约因素"),
]


# ============================================================
# 入库函数
# ============================================================

def init_kg():
    """同步入库（调用 Neo4j 服务层）"""
    node_count = 0
    rel_count = 0
    today_str = date.today().isoformat()

    # ---- 入库实体 ----
    all_entities = INDUSTRIES + COMPANIES + PRODUCTS + EVENTS
    for e in all_entities:
        entity_id = e.get("entity_id") or generate_entity_id(
            entity_type=e["entity_type"],
            name=e["name"],
            ts_code=e.get("ts_code"),
        )
        valid_from_str = e.get("valid_from", "1900-01-01")
        valid_from_date = valid_from_str if isinstance(valid_from_str, date) else \
            datetime.strptime(valid_from_str, "%Y-%m-%d").date()

        try:
            upsert_entity(
                entity_id=entity_id,
                entity_type=e["entity_type"],
                name=e["name"],
                ts_code=e.get("ts_code"),
                properties=e.get("properties"),
                confidence=e.get("confidence", 0.80),
                source_type=e.get("source_type", "research_report"),
                source_name=e.get("source_name", "乐晴智库"),
                valid_from=valid_from_date,
            )
            node_count += 1
            print(f"  ✅ {e['entity_type']:10s} {entity_id} ({e['name']})")
        except Exception as ex:
            print(f"  ❌ {entity_id}: {ex}")

    # ---- 入库关系 ----
    for (from_e, to_e, rel_type, conf, valid_from_str, props,
         context_tag, source_type, source_name, article, notes) in RELATIONSHIPS:
        valid_from_date = valid_from_str if isinstance(valid_from_str, date) else \
            datetime.strptime(valid_from_str, "%Y-%m-%d").date()

        try:
            upsert_relation(
                from_entity=from_e,
                to_entity=to_e,
                relationship_type=rel_type,
                properties=props,
                confidence=conf,
                source_type=source_type,
                source_name=source_name,
                article_ref=article,
                notes=notes,
                valid_from=valid_from_date,
            )
            rel_count += 1
            print(f"  ✅ {from_e} → [{rel_type}] → {to_e}")
        except Exception as ex:
            print(f"  ❌ {from_e} → [{rel_type}] → {to_e}: {ex}")

    print(f"\n入库完成：{node_count} 个实体，{rel_count} 条关系")


async def init_kg_async():
    """异步入口（用线程池运行同步入库）"""
    await asyncio.to_thread(init_kg)


if __name__ == "__main__":
    init_kg()
