"""
快速验证脚本：状态机 + 向量库模块

运行方式：
  uv run --directory backend python -c "
  exec(open('scripts/verify_modules.py').read())
  "
"""

import sys

sys.path.insert(0, ".")

# ── 状态机验证 ───────────────────────────────────────────────────────────
print("=" * 60)
print("1. 状态机模块验证")
print("=" * 60)

from app.knowledge.state_machine import (
    IndustryState,
    describe_state,
    get_all_states,
    infer_state_from_text,
    validate_transition,
)

test_texts = [
    ("公司已实现规模量产，产能正在爬坡，预计明年大规模释放", "GROWTH"),
    ("目前处于中试阶段，已向头部客户送样验证", "PILOT"),
    ("公司处于研发阶段，工艺尚在定型过程中，性能验证中", "RND"),
    ("行业已进入成熟期，龙头企业稳居市场主导地位", "MATURITY"),
    ("目前仍属实验室理论研究阶段，尚无商业化前景，无营收", "LAB"),
]

all_pass = True
for text, expected in test_texts:
    inferred = infer_state_from_text(text)
    status = "✓" if inferred and inferred.value == expected else "✗"
    if status == "✗":
        all_pass = False
    print(f"  {status} [{expected:16s}] 推断={inferred.value if inferred else 'None':16s}  文本={text[:30]}...")

# 转换校验
print()
print("  转换校验:")
transitions = [
    (IndustryState.PILOT, IndustryState.GROWTH, True),
    (IndustryState.GROWTH, IndustryState.LAB, False),
    (IndustryState.GROWTH, IndustryState.MATURITY, True),
    (IndustryState.DECLINE, IndustryState.GROWTH, True),  # 可逆
    (IndustryState.LAB, IndustryState.GROWTH, False),  # 跳级
]
for from_s, to_s, expected in transitions:
    ok = validate_transition(from_s, to_s)
    status = "✓" if ok == expected else "✗"
    if status == "✗":
        all_pass = False
    print(
        f"  {status} {from_s.value} → {to_s.value}: {'允许' if ok else '禁止'} (期望:{'允许' if expected else '禁止'})"
    )

print()
print("  状态描述:")
for s in get_all_states():
    print(f"    {s.value:16s} = {describe_state(s)}")


# ── 向量库验证 ───────────────────────────────────────────────────────────
print()
print("=" * 60)
print("2. 向量库模块验证（占位实现）")
print("=" * 60)

from app.knowledge.vector_client import (
    COLLECTION_ENTITIES,
    PlaceholderEmbedding,
    QdrantClient,
    SearchResult,
    VectorRecord,
)

# Embedding 占位实现
emb = PlaceholderEmbedding(dimension=1536)
vec = emb.embed("中际旭创是全球领先的光模块制造商")
print(f"  ✓ PlaceholderEmbedding: dim={emb.dimension()}, vec[0]={vec[0]:.4f}")

vecs = emb.embed_batch(["文本A", "文本B"])
print(f"  ✓ Batch embed: {len(vecs)} 条")

# VectorRecord
rec = VectorRecord(id="test:001", vector=vec, payload={"name": "测试实体"})
print(f"  ✓ VectorRecord: id={rec.id}, payload={rec.payload}")

# SearchResult
res = SearchResult(id="result:1", score=0.95, payload={"name": "结果"})
print(f"  ✓ SearchResult: id={res.id}, score={res.score}")

# Qdrant 客户端实例化（不实际连接）
qc = QdrantClient(url="http://localhost:6333")
print("  ✓ QdrantClient 实例化成功")

# Collection 常量
print(f"  ✓ Collection 常量: entities={COLLECTION_ENTITIES}")


# ── 总结 ────────────────────────────────────────────────────────────────
print()
print("=" * 60)
if all_pass:
    print("✓ 所有状态机测试通过")
else:
    print("✗ 部分状态机测试失败，请检查")
print("✓ 向量库模块验证完成（embedding 占位，模型待接入）")
print("=" * 60)
