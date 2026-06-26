"""
讯飞 Embedding 服务测试

用法：
    cd /home/10241671/code/LocalProjects/QingShuiTouYan
    uv run --directory backend python -c "
    from app.knowledge.vector_client import XunfeiEmbedding
    emb = XunfeiEmbedding(
        appid='33a813c2',
        apikey='16e6220d647dcfeae2016bdc4dc8bd12',
        apisecret='N2IzYzdjZWYzOTgzMTlmOGNjMzk1Njlm',
    )
    vec = emb.embed('中际旭创的光模块业务分析')
    print(f'dim={len(vec)}, 前5维={vec[:5]}')
    "
"""

import sys

sys.path.insert(0, "/home/10241671/code/LocalProjects/QingShuiTouYan/backend")

from app.config import settings
from app.knowledge.vector_client import XunfeiEmbedding

emb = XunfeiEmbedding(
    appid=settings.xunfei_emb_appid,
    apikey=settings.xunfei_emb_apikey,
    apisecret=settings.xunfei_emb_apisecret,
)
print(f"APPID: {settings.xunfei_emb_appid}, APIKEY: {settings.xunfei_emb_apikey[:8]}...")

print("测试 1: 短文本（query domain）")
vec1 = emb.embed("中际旭创的光模块业务")
print(f"  dim={len(vec1)}, 前5维={vec1[:5]}")

print("测试 2: 长文本（para domain）")
vec2 = emb.embed(
    "中际旭创主要从事光通信收发模块的研发、生产和销售，产品覆盖100G/400G/800G高速光模块，广泛应用于数据中心和电信网络。受益于AI算力建设带来的光互联需求爆发，公司2024年业绩高速增长。"
)
print(f"  dim={len(vec2)}, 前5维={vec2[:5]}")

print("测试 3: 批量")
vecs = emb.embed_batch(["文本一", "文本二", "文本三"])
print(f"  批量结果: {len(vecs)} 条, dim={len(vecs[0])}")
