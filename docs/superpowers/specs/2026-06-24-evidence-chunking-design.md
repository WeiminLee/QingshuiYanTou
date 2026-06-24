# Evidence 分块逻辑完善设计

> 日期：2026-06-24
> 状态：Approved

## 1. 目标

整合已有的 SmartChunker 到 Evidence 构建流程，确保：
- 分块语义完整
- 支持多种标题格式
- Token 限制 4096
- 表格独立成块

## 2. 现状分析

### 2.1 当前分块逻辑

`evidence_builders_simple.py` 使用 `announcement_parser.split_by_chapters`：

```python
from app.knowledge.ingestion.announcement_parser import (
    parse_pdf_text,
    split_by_chapters,  # 只支持中文序号，无 token 限制
)
```

### 2.2 SmartChunker 能力

`chunker.py` 已实现完整分块逻辑：

| 能力 | 支持格式 | Token 限制 |
|------|----------|-----------|
| 中文序号 | `一、公司简介`、`第一节 业务`、`第一章 总则` | ✅ 4096 |
| 阿拉伯数字 | `1. 公司概况`、`1.1 业务`、`1.1.1 产品` | ✅ 4096 |
| Markdown 标题 | `# 标题`、`## 副标题` | ✅ 4096 |
| 小章节合并 | <512 tokens 合并到 ~2048 | ✅ |
| 表格保留 | `\| 表格 \|` 独立成块 | ✅ |
| 句子边界切分 | 按 `。！？；\n` 切分 | ✅ |

## 3. 实施方案

### 3.1 修改 `evidence_builders_simple.py`

**文件**: `backend/app/knowledge/evidence_builders_simple.py`

**改动 1**: 更新导入
```python
# 旧
from app.knowledge.ingestion.announcement_parser import (
    parse_pdf_text,
    split_by_chapters,
)

# 新
from app.knowledge.ingestion.pdf_parser import extract_text_from_pdf
from app.knowledge.ingestion.chunker import SmartChunker
```

**改动 2**: 修改 `_split_pdf_chapters` 函数
```python
def _split_pdf_chapters(file_path: str) -> list[dict] | None:
    """解析本地 PDF 并按章节切分，返回分块列表"""
    try:
        text = extract_text_from_pdf(file_path)
        if not text.strip():
            return None

        # 使用 SmartChunker
        chunker = SmartChunker(max_tokens=4096)
        chunks = chunker.chunk(text)

        return [
            {
                "heading": c.heading,
                "body": c.text,
                "tokens": c.tokens,
                "source": c.source,
            }
            for c in chunks
        ]
    except Exception as e:
        logger.warning(f"PDF 解析失败 [{file_path}]: {e}")
        return None
```

### 3.2 清理废弃代码

**文件**: `backend/app/knowledge/ingestion/announcement_parser.py`

移除 `split_by_chapters` 函数（已由 SmartChunker 替代）。

### 3.3 保留 `parse_pdf_text`

`parse_pdf_text` 保留用于兼容性（其他模块可能依赖）。

## 4. 分块参数

| 参数 | 值 | 说明 |
|------|-----|------|
| MAX_CHUNK_TOKENS | 4096 | 单块最大 token 数 |
| MIN_CHUNK_TOKENS | 512 | 小于此值考虑合并 |
| MERGE_TARGET_TOKENS | 2048 | 合并目标大小 |

## 5. 分块效果预期

| 指标 | 当前 | 优化后 |
|------|------|--------|
| 支持标题格式 | 中文序号 | 全部 |
| 最大 chunk | 9286 tokens | 4096 tokens |
| 表格处理 | 内联 | 独立成块 |
| 小章节合并 | 无 | ✅ |

## 6. 测试验证

1. **单元测试**: 已有 `tests/test_chunker.py` 覆盖 SmartChunker
2. **集成测试**: 运行 `build_evidence_batch --limit 100` 验证 MongoDB 输出
3. **分块统计**: 检查 max_tokens <= 4096

## 7. 风险与缓解

| 风险 | 缓解 |
|------|------|
| 分块逻辑变化导致已有 evidence 重建 | 全量重建 evidence（已有脚本支持） |
| PDF 解析失败 | 保留 title 作为 fallback |
