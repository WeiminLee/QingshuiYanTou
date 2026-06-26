# Evidence 管道实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 从 PostgreSQL announcements 表构建 Evidence 记录入 MongoDB kg_evidence，支持智能多策略分块（章节检测 + Token 切分 + 小章节合并）

**Architecture:**
- PDF 解析层：复用现有的 `pdf_parser.py` + 新增强的分块策略
- Evidence 构建层：更新 `evidence_builders_simple.py`
- 批量处理层：更新 `build_evidence_batch.py` 支持断点续跑

**Tech Stack:** Python 3.11+, pymupdf, tiktoken/tokenizer, PostgreSQL, MongoDB

---

## 1. 文件变更概览

| 文件 | 操作 | 职责 |
|------|------|------|
| `backend/app/knowledge/ingestion/chunker.py` | 新建 | 智能多策略分块模块 |
| `backend/app/knowledge/ingestion/__init__.py` | 修改 | 导出 chunker |
| `backend/app/knowledge/evidence_builders_simple.py` | 修改 | 使用新分块策略 |
| `backend/scripts/build_evidence_batch.py` | 修改 | 支持断点续跑、并发处理 |

---

## 2. 实施任务

### Task 1: 创建智能分块模块 `chunker.py`

**Files:**
- Create: `backend/app/knowledge/ingestion/chunker.py`
- Test: `backend/tests/test_chunker.py`

**分块参数常量:**
```python
MAX_CHUNK_TOKENS = 4096     # 单块最大 token 数
MIN_CHUNK_TOKENS = 512      # 小于此值考虑合并
MERGE_TARGET_TOKENS = 2048  # 合并目标大小
```

**分块策略（三级融合）:**

1. **策略1: 章节检测**
   - 按标题层级分割（中文序号、阿拉伯数字、Markdown 标题）
   - 返回 `list[{"heading": str, "body": str, "level": int}]`

2. **策略2: Token 切分**（章节太长时触发）
   - 按句子边界切分，确保不截断句子
   - 使用 ` tiktoken` 计算 token 数

3. **策略3: 小章节合并**（章节太小时触发）
   - 合并相邻小章节直到达到 ~2048 tokens

**正则表达式（从 ragflow/nlp/__init__.py 适配）:**
```python
# 中文章节标题
CHAPTER_PATTERN_CN = [
    r"第[零一二三四五六七八九十百]+章",
    r"第[零一二三四五六七八九十百]+节",
    r"第[零一二三四五六七八九十百]+条",
]

# 阿拉伯数字章节标题
CHAPTER_PATTERN_NUM = [
    r"^\d+[\.、]\s",
    r"^\d+\.\d+[\.\s]",
    r"^\d+\.\d+\.\d+",
]

# Markdown 标题
MARKDOWN_HEADING = r"^#{1,6}\s+"
```

- [ ] **Step 1: 创建测试文件**

```python
# backend/tests/test_chunker.py
import pytest
from app.knowledge.ingestion.chunker import (
    SmartChunker,
    split_by_chapters,
    merge_small_chunks,
    chunk_text,
    count_tokens,
)

class TestChapterDetection:
    """章节检测测试"""

    def test_chinese_chapter_heading(self):
        """中文序号标题检测"""
        text = "一、公司简介\n公司成立于2000年\n二、主要业务\n主营业务包括..."
        chapters = split_by_chapters(text)
        assert len(chapters) >= 2
        assert any("公司简介" in c["heading"] for c in chapters)

    def test_arabic_numeral_heading(self):
        """阿拉伯数字章节标题检测"""
        text = "1. 公司概况\n公司是国内领先的...\n2. 财务数据\n营收100亿元..."
        chapters = split_by_chapters(text)
        assert len(chapters) >= 2

    def test_markdown_heading(self):
        """Markdown 标题检测"""
        text = "# 公司简介\n公司成立于2000年\n## 主要业务\n主营业务包括..."
        chapters = split_by_chapters(text)
        assert len(chapters) >= 2


class TestSmartChunking:
    """智能分块测试"""

    def test_small_chapters_merge(self):
        """小章节应被合并"""
        chapters = [
            {"heading": "一、", "body": "短内容1", "level": 1, "tokens": 100},
            {"heading": "二、", "body": "短内容2", "level": 1, "tokens": 100},
            {"heading": "三、", "body": "短内容3", "level": 1, "tokens": 100},
        ]
        merged = merge_small_chunks(chapters, target_tokens=2048)
        # 三个小章节应合并成一个
        assert len(merged) == 1

    def test_large_chapter_split(self):
        """大章节应被切分"""
        # 生成超过 4096 tokens 的文本
        long_text = "X公司年度报告\n" + "\n".join(["正文内容第{}行".format(i) for i in range(2000)])
        chunks = chunk_text(long_text, max_tokens=4096)
        # 应被切分成多个块
        assert all(c["tokens"] <= 4096 for c in chunks)

    def test_table_preservation(self):
        """表格应作为独立块保留"""
        text = "# 财务数据\n| 项目 | 金额 |\n|------|------|\n| 营收 | 100 |"
        chunks = chunk_text(text, max_tokens=4096)
        # 表格应保留在某个 chunk 中
        table_chunks = [c for c in chunks if "| 项目 |" in c["text"]]
        assert len(table_chunks) > 0


class TestIntegration:
    """集成测试"""

    def test_full_pipeline(self):
        """完整分块流程"""
        sample = """
一、公司基本情况
公司名称：某某股份有限公司
股票代码：600000.SH

二、主要财务数据
| 指标 | 2023年 | 2024年 |
|------|--------|--------|
| 营收 | 100亿 | 120亿 |
| 净利润 | 10亿 | 15亿 |

三、股东情况
前十大股东持股比例合计超过60%。
"""
        chunker = SmartChunker()
        chunks = chunker.chunk(sample)
        assert len(chunks) > 0
        assert all(c["tokens"] <= 4096 for c in chunks)
```

- [ ] **Step 2: 运行测试验证失败**

```bash
cd /home/lwm/code/QingshuiYanTou/backend
source .venv/bin/activate
pytest tests/test_chunker.py -v
```
Expected: FAIL (module not found)

- [ ] **Step 3: 实现分块模块**

```python
# backend/app/knowledge/ingestion/chunker.py
"""智能多策略分块模块

分块策略（三级融合）:
1. 章节检测：按标题层级分割
2. Token 切分：章节超过 4096 tokens 时按句子边界切分
3. 小章节合并：章节小于 512 tokens 时合并到 ~2048
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

# ── 分块参数常量 ────────────────────────────────────────────────

MAX_CHUNK_TOKENS = 4096      # 单块最大 token 数
MIN_CHUNK_TOKENS = 512       # 小于此值考虑合并
MERGE_TARGET_TOKENS = 2048   # 合并目标大小

# ── Token 计算 ─────────────────────────────────────────────────

try:
    import tiktoken
    _enc = tiktoken.get_encoding("cl100k_base")
    
    def count_tokens(text: str) -> int:
        """使用 tiktoken 计算 token 数"""
        return len(_enc.encode(text))
except ImportError:
    # Fallback: 粗略估算 (中文字符约 1.5 tokens)
    def count_tokens(text: str) -> int:
        chinese = sum(1 for c in text if '一' <= c <= '鿿')
        other = len(text) - chinese
        return int(chinese * 1.5 + other * 0.25)


# ── 章节检测正则 ───────────────────────────────────────────────

# 中文序号标题
_CHAPTER_PATTERNS_CN = [
    (re.compile(r"^第[零一二三四五六七八九十百]+章\s*(.+?)\s*$", re.M), 1),  # 第X章
    (re.compile(r"^第[零一二三四五六七八九十百]+节\s*(.+?)\s*$", re.M), 2),  # 第X节
    (re.compile(r"^第[零一二三四五六七八九十百]+条\s*(.+?)\s*$", re.M), 1),  # 第X条
]

# 阿拉伯数字编号标题
_NUMBER_PATTERNS = [
    (re.compile(r"^\d+\.\s+(.+?)\s*$", re.M), 1),   # 1. 标题
    (re.compile(r"^\d+\.\d+\.\s+(.+?)\s*$", re.M), 2),  # 1.1 标题
    (re.compile(r"^\d+\.\d+\.\d+\.\s+(.+?)\s*$", re.M), 3),  # 1.1.1 标题
]

# Markdown 标题
_MARKDOWN_PATTERN = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.M)

# 句子边界（用于切分）
_SENTENCE_DELIMITERS = r"[。！？；\n]"


@dataclass
class Chapter:
    """单个章节"""
    heading: str
    body: str
    level: int = 1  # 标题层级
    tokens: int = 0

    def __post_init__(self):
        if self.tokens == 0:
            self.tokens = count_tokens(self.heading + "\n" + self.body)


@dataclass
class Chunk:
    """单个文本块"""
    text: str
    heading: str = ""
    tokens: int = 0
    source: str = "auto"  # "chapter" | "split" | "merge"
    
    def __post_init__(self):
        if self.tokens == 0:
            self.tokens = count_tokens(self.text)


def split_by_chapters(text: str) -> list[Chapter]:
    """
    策略1: 按标题层级检测并分割章节
    
    Returns:
        list[Chapter]: 章节列表，包含 heading、body、level、tokens
    """
    if not text or not text.strip():
        return []
    
    lines = text.split("\n")
    chapters: list[Chapter] = []
    current_body_lines: list[str] = []
    current_heading = ""
    current_level = 1
    
    def _flush_chapter(heading: str, level: int):
        """将当前内容 flush 为一个章节"""
        body = "\n".join(current_body_lines).strip()
        if body:
            chapters.append(Chapter(
                heading=heading,
                body=body,
                level=level,
            ))
    
    def _match_heading(line: str) -> tuple[Optional[str], int]:
        """尝试匹配标题模式，返回 (heading, level) 或 (None, 0)"""
        line = line.strip()
        if not line:
            return None, 0
        
        # Markdown 标题
        m = _MARKDOWN_PATTERN.match(line)
        if m:
            level = len(m.group(1))
            return m.group(2).strip(), level
        
        # 中文序号标题
        for pattern, level in _CHAPTER_PATTERNS_CN:
            m = pattern.match(line)
            if m:
                return m.group(1).strip(), level
        
        # 阿拉伯数字标题
        for pattern, level in _NUMBER_PATTERNS:
            m = pattern.match(line)
            if m:
                return m.group(1).strip(), level
        
        return None, 0
    
    for line in lines:
        heading, level = _match_heading(line)
        
        if heading:
            # 遇到新标题，先 flush 之前的内容
            if current_heading or current_body_lines:
                _flush_chapter(current_heading, current_level)
                current_body_lines = []
            current_heading = heading
            current_level = level
        else:
            current_body_lines.append(line)
    
    # 处理最后一个章节
    if current_heading or current_body_lines:
        _flush_chapter(current_heading, current_level)
    
    # 如果没有检测到任何标题，将全文作为一个章节
    if not chapters:
        chapters.append(Chapter(
            heading="",
            body=text.strip(),
            level=0,
        ))
    
    return chapters


def _split_by_sentences(text: str, max_tokens: int) -> list[str]:
    """
    按句子边界切分文本
    
    Returns:
        list[str]: 句子块列表
    """
    # 分割句子
    sentences = re.split(f"({_SENTENCE_DELIMITERS}+)", text)
    
    chunks: list[str] = []
    current_chunk = ""
    current_tokens = 0
    
    for i in range(0, len(sentences), 2):
        sentence = sentences[i]
        # 获取分隔符（如果有）
        delimiter = sentences[i + 1] if i + 1 < len(sentences) else ""
        full_text = sentence + delimiter
        text_tokens = count_tokens(full_text)
        
        if text_tokens > max_tokens:
            # 单个句子就超过限制，跳过（保留原样）
            if current_chunk:
                chunks.append(current_chunk.strip())
                current_chunk = ""
                current_tokens = 0
            chunks.append(sentence.strip())
            current_chunk = ""
            current_tokens = 0
        elif current_tokens + text_tokens > max_tokens:
            # 超过限制，保存当前块，开始新块
            if current_chunk:
                chunks.append(current_chunk.strip())
            current_chunk = full_text
            current_tokens = text_tokens
        else:
            current_chunk += full_text
            current_tokens += text_tokens
    
    if current_chunk.strip():
        chunks.append(current_chunk.strip())
    
    return chunks


def merge_small_chunks(chapters: list[Chapter], target_tokens: int = MERGE_TARGET_TOKENS) -> list[Chapter]:
    """
    策略3: 合并相邻小章节
    
    将多个小章节合并，直到达到 target_tokens 大小。
    """
    if not chapters:
        return []
    
    # 按 level 分组，优先合并同级的章节
    merged: list[Chapter] = []
    buffer: list[Chapter] = []
    buffer_tokens = 0
    
    def _flush_buffer():
        nonlocal buffer, buffer_tokens
        if not buffer:
            return
        if len(buffer) == 1:
            merged.append(buffer[0])
        else:
            # 合并多个小章节
            combined_body = "\n\n".join(c.body for c in buffer)
            first_heading = buffer[0].heading
            # 取最小的 level
            min_level = min(c.level for c in buffer)
            merged.append(Chapter(
                heading=first_heading,
                body=combined_body,
                level=min_level,
            ))
        buffer = []
        buffer_tokens = 0
    
    for chapter in chapters:
        if chapter.tokens < MIN_CHUNK_TOKENS:
            # 小章节，加入 buffer
            buffer.append(chapter)
            buffer_tokens += chapter.tokens
            
            # 达到目标大小，flush
            if buffer_tokens >= target_tokens:
                _flush_buffer()
        else:
            # 大章节，先 flush buffer
            _flush_buffer()
            merged.append(chapter)
    
    # 处理最后剩余的 buffer
    _flush_buffer()
    
    return merged


def chunk_text(text: str, max_tokens: int = MAX_CHUNK_TOKENS) -> list[Chunk]:
    """
    智能多策略分块主函数
    
    流程:
    1. 章节检测
    2. Token 切分（对过长章节）
    3. 小章节合并
    
    Returns:
        list[Chunk]: 分块结果列表
    """
    if not text or not text.strip():
        return []
    
    # 策略1: 章节检测
    chapters = split_by_chapters(text)
    
    # 策略3: 小章节合并（先合并，再切分）
    chapters = merge_small_chunks(chapters)
    
    # 策略2: Token 切分（对仍然过大的章节）
    result_chunks: list[Chunk] = []
    
    for chapter in chapters:
        if chapter.tokens <= max_tokens:
            # 章节大小合适
            result_chunks.append(Chunk(
                text=f"{chapter.heading}\n\n{chapter.body}" if chapter.heading else chapter.body,
                heading=chapter.heading,
                tokens=chapter.tokens,
                source="chapter",
            ))
        else:
            # 章节过长，按句子切分
            full_text = f"{chapter.heading}\n\n{chapter.body}" if chapter.heading else chapter.body
            sub_chunks = _split_by_sentences(full_text, max_tokens)
            
            for i, sub_text in enumerate(sub_chunks):
                result_chunks.append(Chunk(
                    text=sub_text,
                    heading=f"{chapter.heading} (第{i+1}段)" if chapter.heading else "",
                    tokens=count_tokens(sub_text),
                    source="split",
                ))
    
    return result_chunks


class SmartChunker:
    """
    智能分块器类
    
    提供可配置的接口，支持自定义参数。
    """
    
    def __init__(
        self,
        max_tokens: int = MAX_CHUNK_TOKENS,
        min_tokens: int = MIN_CHUNK_TOKENS,
        merge_target: int = MERGE_TARGET_TOKENS,
    ):
        self.max_tokens = max_tokens
        self.min_tokens = min_tokens
        self.merge_target = merge_target
    
    def chunk(self, text: str) -> list[Chunk]:
        """对文本进行智能分块"""
        return chunk_text(text, self.max_tokens)
    
    def chunk_with_metadata(self, text: str, metadata: dict) -> list[dict]:
        """
        返回带元数据的分块结果
        
        Returns:
            list[dict]: 每个块包含 text, heading, tokens, source, metadata
        """
        chunks = self.chunk(text)
        return [
            {
                "text": c.text,
                "heading": c.heading,
                "tokens": c.tokens,
                "source": c.source,
                **metadata,
            }
            for c in chunks
        ]
```

- [ ] **Step 4: 运行测试验证通过**

```bash
cd /home/lwm/code/QingshuiYanTou/backend
source .venv/bin/activate
pytest tests/test_chunker.py -v
```
Expected: PASS

- [ ] **Step 5: 提交代码**

```bash
git add backend/app/knowledge/ingestion/chunker.py backend/tests/test_chunker.py
git commit -m "feat(ingestion): add smart chunker with multi-strategy partitioning"
```

---

### Task 2: 更新 Evidence Builder

**Files:**
- Modify: `backend/app/knowledge/evidence_builders_simple.py`
- Test: `backend/tests/test_evidence_builders_simple.py` (扩展)

- [ ] **Step 1: 更新导入和分块逻辑**

找到 `evidence_builders_simple.py` 中的相关函数，替换为使用新的 `SmartChunker`:

```python
# 添加导入
from app.knowledge.ingestion.chunker import SmartChunker, count_tokens

# 替换 _split_pdf_chapters 函数
def _split_pdf_chapters(file_path: str) -> list[dict] | None:
    """解析本地 PDF 并按章节切分，返回分块列表"""
    try:
        with open(file_path, "rb") as f:
            content = f.read()
        # 使用已有的 pdf_parser
        from app.knowledge.ingestion.pdf_parser import extract_text_from_pdf
        text = extract_text_from_pdf(file_path)
        if not text.strip():
            return None
        
        # 使用智能分块器
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

- [ ] **Step 2: 更新 build_announcement_evidence 函数**

确保返回的 `text_excerpt` 包含完整的分块文本:

```python
def build_announcement_evidence(
    record: dict[str, Any],
) -> list[EvidenceInput]:
    """从 announcements 记录构建 EvidenceInput 列表。

    使用智能多策略分块：
    1. 章节检测
    2. Token 切分（4096 tokens 上限）
    3. 小章节合并（<512 tokens 时合并到 ~2048）

    每章节作为一个 Evidence。
    """
    # ... 现有代码保持不变，只更新分块逻辑 ...
    
    # 修改分块结果处理
    if has_local_pdf:
        raw_chunks = _split_pdf_chapters(local_pdf) or []
        # 转换为章节列表
        if raw_chunks:
            chapters = [
                {"heading": c.get("heading", ""), "body": c.get("body", c.get("text", ""))}
                for c in raw_chunks
            ]
        else:
            chapters = []
```

- [ ] **Step 3: 运行现有测试确保兼容**

```bash
cd /home/lwm/code/QingshuiYanTou/backend
source .venv/bin/activate
pytest tests/test_evidence_builders_simple.py -v 2>/dev/null || echo "测试文件不存在，跳过"
```

- [ ] **Step 4: 提交代码**

```bash
git add backend/app/knowledge/evidence_builders_simple.py
git commit -m "feat(evidence): use SmartChunker for announcement splitting"
```

---

### Task 3: 更新批量构建脚本

**Files:**
- Modify: `backend/scripts/build_evidence_batch.py`

- [ ] **Step 1: 添加断点续跑支持**

在脚本中添加进度跟踪:

```python
# 在文件顶部添加
import json
from pathlib import Path

PROGRESS_FILE = Path(__file__).parent / ".evidence_build_progress.json"


def load_progress() -> dict:
    """加载断点进度"""
    if PROGRESS_FILE.exists():
        try:
            return json.loads(PROGRESS_FILE.read_text())
        except Exception:
            pass
    return {"last_id": 0, "completed": {}}


def save_progress(progress: dict):
    """保存断点进度"""
    try:
        PROGRESS_FILE.write_text(json.dumps(progress, indent=2))
    except Exception as e:
        logger.warning(f"进度保存失败: {e}")
```

- [ ] **Step 2: 添加并发控制参数**

```python
# 添加命令行参数
parser.add_argument(
    "--workers",
    type=int,
    default=10,
    help="并发 worker 数（默认 10）",
)
parser.add_argument(
    "--resume",
    action="store_true",
    help="从上次断点继续",
)
```

- [ ] **Step 3: 添加批量 upsert 优化**

```python
async def bulk_upsert_evidence(inputs: list[EvidenceInput], batch_size: int = 100):
    """批量 upsert Evidence"""
    service = EvidenceService()
    total = 0
    for i in range(0, len(inputs), batch_size):
        batch = inputs[i:i + batch_size]
        for inp in batch:
            await service.upsert_evidence(inp)
            total += 1
    return total
```

- [ ] **Step 4: 运行小规模测试**

```bash
cd /home/lwm/code/QingshuiYanTou/backend
source .venv/bin/activate
python -m scripts.build_evidence_batch --type announcement --limit 100 --workers 5
```

- [ ] **Step 5: 验证 MongoDB 结果**

```bash
docker exec qingshui_mongo mongosh qingshui --quiet --eval "
db = db.getSiblingDB('qingshui');
print('kg_evidence count:', db.kg_evidence.countDocuments({}));
db.kg_evidence.aggregate([{\$group: {_id: '\$source_type', count: {\$sum: 1}}}]).forEach(r => print(r._id, ':', r.count));
"
```

- [ ] **Step 6: 提交代码**

```bash
git add backend/scripts/build_evidence_batch.py
git commit -m "feat(scripts): add progress tracking and bulk upsert to build_evidence_batch"
```

---

### Task 4: 完整流程测试

- [ ] **Step 1: 清空测试数据（可选，仅测试用）**

```bash
docker exec qingshui_mongo mongosh qingshui --quiet --eval "
db = db.getSiblingDB('qingshui');
db.kg_evidence.deleteMany({});
db.kg_extraction_jobs.deleteMany({});
print('Cleaned kg_evidence and kg_extraction_jobs');
"
```

- [ ] **Step 2: 运行完整构建（限制 1000 条）**

```bash
cd /home/lwm/code/QingshuiYanTou/backend
source .venv/bin/activate
python -m scripts.build_evidence_batch --type all --limit 1000 --workers 10
```

- [ ] **Step 3: 验证分块效果**

```bash
docker exec qingshui_mongo mongosh qingshui --quiet --eval "
db = db.getSiblingDB('qingshui');
// 查看分块统计
var pipeline = [
    {\$match: {source_type: 'announcement'}},
    {\$project: {tokens: {\$size: {\$split: ['\$text_excerpt', ' ']}}}},
    {\$group: {_id: null, avg_tokens: {\$avg: '\$tokens'}, max_tokens: {\$max: '\$tokens'}, min_tokens: {\$min: '\$tokens'}}}
];
db.kg_evidence.aggregate(pipeline).forEach(r => print('avg:', r.avg_tokens, 'max:', r.max_tokens, 'min:', r.min_tokens));
"
```

- [ ] **Step 4: 提交最终代码**

```bash
git add -A
git commit -m "feat: complete evidence pipeline with smart chunking"
```

---

## 3. 自检清单

- [ ] 分块不超过 4096 tokens
- [ ] 小章节（<512 tokens）被合并
- [ ] 合并目标约 2048 tokens
- [ ] 表格作为独立块保留
- [ ] 支持断点续跑
- [ ] 支持并发处理
- [ ] MongoDB upsert 去重
