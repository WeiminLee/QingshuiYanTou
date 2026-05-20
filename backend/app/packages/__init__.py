"""
情报包生成器 - 业务层

数据来源：data_pipeline.services（DB 查询）
"""
from app.packages.stock_package import build_stock_package, build_stock_package_json
from app.packages.stock_scorer import compute_stock_score
from app.packages.material_package import build_material_package

__all__ = [
    "build_stock_package",
    "build_stock_package_json",
    "compute_stock_score",
    "build_material_package",
]
