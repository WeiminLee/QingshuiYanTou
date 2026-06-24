# Evidence 分块逻辑完善实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 SmartChunker 整合到 Evidence 构建流程，替代 announcement_parser 的简单分块

**Architecture:** 修改 `evidence_builders_simple.py` 的导入和 `_split_pdf_chapters` 函数，调用 SmartChunker

**Tech Stack:** Python, pymupdf, tiktoken, MongoDB

---

## 文件变更概览

| 文件 | 操作 | 职责 |
|------|------|------|
| `backend/app/knowledge/evidence_builders_simple.py` | 修改 | 改用 SmartChunker |
| `backend/app/knowledge/ingestion/announcement_parser.py` | 修改 | 移除 split_by_chapters |

---

## Task 1: 修改 evidence_builders_simple.py 导入

**Files:**
- Modify: `backend/app/knowledge/evidence_builders_simple.py:1-18`

- [ ] **Step 1: 更新导入语句**

将:
```python
from app.knowledge.ingestion.announcement_parser import (
    parse_pdf_text,
    split_by_chapters,
)
```

改为:
```python
from app.knowledge.ingestion.pdf_parser import extract_text_from_pdf
from app.knowledge.ingestion.chunker import SmartChunker
```

验证: `grep -n "from app.knowledge.ingestion" evidence_builders_simple.py`

- [ ] **Step 2: 验证导入可用**

Run: `cd /home/lwm/code/QingshuiYanTou/backend && source .venv/bin/activate && python -c "from app.knowledge.ingestion.pdf_parser import extract_text_from_pdf; from app.knowledge.ingestion.chunker import SmartChunker; print('OK')"`
Expected: `OK`

- [ ] **Step 3: 提交**

```bash
git add backend/app/knowledge/evidence_builders_simple.py
git commit -m "refactor(evidence): update imports for SmartChunker integration"
```

---

## Task 2: 修改 _split_pdf_chapters 函数

**Files:**
- Modify: `backend/app/knowledge/evidence_builders_simple.py:46-57`

- [ ] **Step 1: 替换函数实现**

将 `_split_pdf_chapters` 函数替换为:

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

- [ ] **Step 2: 验证语法正确**

Run: `cd /home/lwm/code/QingshuiYanTou/backend && source .venv/bin/activate && python -c "from app.knowledge.evidence_builders_simple import _split_pdf_chapters; print('OK')"`
Expected: `OK`

- [ ] **Step 3: 提交**

```bash
git add backend/app/knowledge/evidence_builders_simple.py
git commit -m "feat(evidence): use SmartChunker for PDF chunking with 4096 token limit"
```

---

## Task 3: 清理 announcement_parser.py

**Files:**
- Modify: `backend/app/knowledge/ingestion/announcement_parser.py`

- [ ] **Step 1: 检查 split_by_chapters 使用情况**

Run: `grep -rn "split_by_chapters" backend/app/ backend/scripts/`
Expected: 只在 `evidence_builders_simple.py` 中有导入（已移除）

- [ ] **Step 2: 移除 split_by_chapters 函数**

在 `announcement_parser.py` 中删除 `split_by_chapters` 函数（约第 69-106 行）。

保留 `parse_pdf_text` 和 `download_announcement_pdf` 函数。

- [ ] **Step 3: 验证语法正确**

Run: `cd /home/lwm/code/QingshuiYanTou/backend && source .venv/bin/activate && python -c "from app.knowledge.ingestion.announcement_parser import parse_pdf_text, download_announcement_pdf; print('OK')"`
Expected: `OK`

- [ ] **Step 4: 提交**

```bash
git add backend/app/knowledge/ingestion/announcement_parser.py
git commit -m "refactor(ingestion): remove split_by_chapters (replaced by SmartChunker)"
```

---

## Task 4: 集成测试

**Files:**
- Test: `backend/scripts/build_evidence_batch.py`

- [ ] **Step 1: 清空 MongoDB 测试数据**

Run:
```bash
docker exec qingshui_mongo mongosh qingshui --quiet --eval "
db = db.getSiblingDB('qingshui');
db.kg_evidence.deleteMany({});
db.kg_extraction_jobs.deleteMany({});
print('Cleaned kg_evidence and kg_extraction_jobs');
"
```

- [ ] **Step 2: 运行小规模测试**

Run: `cd /home/lwm/code/QingshuiYanTou/backend && source .venv/bin/activate && python -m scripts.build_evidence_batch --type announcement --limit 100`
Expected: 构建成功，无错误

- [ ] **Step 3: 验证分块效果**

Run:
```bash
docker exec qingshui_mongo mongosh qingshui --quiet --eval "
db = db.getSiblingDB('qingshui');
print('=== 分块统计 ===');
db.kg_evidence.aggregate([
    {\$project: {len: {\$strLenCP: '\$text_excerpt'}}},
    {\$group: {_id: null, max_len: {\$max: '\$len'}, count: {\$sum: 1}}}
]).forEach(r => print('max chars:', r.max_len, 'count:', r.count));
"
```
Expected: max_len <= 约 12000（4096 tokens × 3 字符）

- [ ] **Step 4: 验证章节标题分布**

Run:
```bash
docker exec qingshui_mongo mongosh qingshui --quiet --eval "
db = db.getSiblingDB('qingshui');
print('=== chapter_heading 分布 ===');
db.kg_evidence.distinct('source_ref.chapter_heading').slice(0, 10).forEach(h => print('  - ' + h));
"
```
Expected: 包含中文序号、阿拉伯数字等多种格式

---

## Task 5: 清理并提交

- [ ] **Step 1: 确认 git 状态**

Run: `git status`
Expected: 只修改了 `evidence_builders_simple.py` 和 `announcement_parser.py`

- [ ] **Step 2: 提交所有更改**

```bash
git add -A
git commit -m "feat: integrate SmartChunker into evidence pipeline
- Replace announcement_parser.split_by_chapters with SmartChunker
- Add 4096 token limit per chunk
- Support Chinese numerals, Arabic numbers, Markdown headings
- Tables preserved as separate chunks"
```

---

## 自检清单

- [ ] SmartChunker 替代了 announcement_parser 的分块逻辑
- [ ] 单块 token 数不超过 4096
- [ ] 表格作为独立块保留
- [ ] 支持中文序号、阿拉伯数字、Markdown 标题
- [ ] 小章节合并生效（<512 tokens）
- [ ] MongoDB 测试验证通过
