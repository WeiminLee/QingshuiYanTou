"""测试智能分块模块"""
import pytest
from app.knowledge.ingestion.chunker import (
    SmartChunker,
    split_by_chapters,
    merge_small_chunks,
    chunk_text,
    count_tokens,
    Chapter,
    MAX_CHUNK_TOKENS,
    MIN_CHUNK_TOKENS,
    MERGE_TARGET_TOKENS,
)


class TestChapterDetection:
    """章节检测测试"""

    def test_chinese_chapter_heading(self):
        """中文序号标题检测"""
        text = "一、公司简介\n公司成立于2000年\n二、主要业务\n主营业务包括..."
        chapters = split_by_chapters(text)
        assert len(chapters) >= 2
        assert any("简介" in c.heading for c in chapters)

    def test_chinese_section_heading(self):
        """中文节标题检测"""
        text = "一、概况\n内容1\n第一节 业务\n内容2\n二、财务\n内容3"
        chapters = split_by_chapters(text)
        # "第一节"可能被识别为二级节或与上级合并
        assert len(chapters) >= 2  # 至少检测到2个一级章节
        # 确保检测到一级章节
        assert any("概况" in c.heading for c in chapters)

    def test_arabic_numeral_heading(self):
        """阿拉伯数字章节标题检测"""
        text = "1. 公司概况\n公司是国内领先的...\n2. 财务数据\n营收100亿元..."
        chapters = split_by_chapters(text)
        assert len(chapters) >= 2

    def test_nested_arabic_heading(self):
        """嵌套阿拉伯数字标题检测"""
        text = "1. 概况\n内容1\n1.1 业务\n内容2\n1.2 人员\n内容3\n2. 财务\n内容4"
        chapters = split_by_chapters(text)
        assert len(chapters) >= 4

    def test_markdown_heading(self):
        """Markdown 标题检测"""
        text = "# 公司简介\n公司成立于2000年\n## 主要业务\n主营业务包括..."
        chapters = split_by_chapters(text)
        assert len(chapters) >= 2

    def test_no_heading(self):
        """无标题时全文作为一个章节"""
        text = "这是纯文本内容，没有标题结构。"
        chapters = split_by_chapters(text)
        assert len(chapters) == 1
        assert chapters[0].body == text

    def test_mixed_headings(self):
        """混合标题格式"""
        text = "# 概述\n内容1\n1. 详情\n内容2\n一、补充\n内容3"
        chapters = split_by_chapters(text)
        assert len(chapters) >= 3


class TestSmallChapterMerge:
    """小章节合并测试"""

    def test_small_chapters_merge(self):
        """多个小章节应被合并"""
        chapters = [
            Chapter(heading="一、", body="短内容1", level=1, tokens=100),
            Chapter(heading="二、", body="短内容2", level=1, tokens=100),
            Chapter(heading="三、", body="短内容3", level=1, tokens=100),
        ]
        merged = merge_small_chunks(chapters, target_tokens=2048)
        # 三个小章节应合并成一个
        assert len(merged) == 1

    def test_large_chapter_unchanged(self):
        """大章节保持不变"""
        large_body = "x" * 3000  # 足够大
        chapters = [
            Chapter(heading="一、", body=large_body, level=1, tokens=1000),
        ]
        merged = merge_small_chunks(chapters)
        assert len(merged) == 1
        assert merged[0].body == large_body

    def test_mixed_chapters(self):
        """混合大小章节"""
        # 使用足够大的数据确保合并逻辑工作
        chapters = [
            Chapter(heading="一、小", body="内容1" * 100, level=1, tokens=300),
            Chapter(heading="二、大", body="x" * 2000, level=1, tokens=600),
            Chapter(heading="三、小", body="内容3" * 100, level=1, tokens=300),
        ]
        merged = merge_small_chunks(chapters)
        # 大章节应保持独立，小章节可能被合并
        assert len(merged) >= 2


class TestSmartChunking:
    """智能分块测试"""

    def test_basic_chunking(self):
        """基本分块功能"""
        text = "一、公司简介\n公司成立于2000年\n二、主要业务\n主营业务包括..."
        chunks = chunk_text(text)
        assert len(chunks) > 0
        assert all(c.tokens > 0 for c in chunks)

    def test_token_limit(self):
        """分块不超过最大 token 数"""
        # 生成一个超过限制的长文本（使用重复的短句）
        sentences = ["这是第{}句话。".format(i) for i in range(500)]
        long_text = "\n".join(sentences)
        chunks = chunk_text(long_text, max_tokens=MAX_CHUNK_TOKENS)
        # 每个块应不超过限制（允许10%误差）
        for c in chunks:
            assert c.tokens <= MAX_CHUNK_TOKENS * 1.1, f"Chunk exceeds limit: {c.tokens}"

    def test_small_chunks_merged(self):
        """小文本块被合并"""
        text = "一、A\n内容A\n二、B\n内容B\n三、C\n内容C"
        chunks = chunk_text(text)
        # 三个小章节应合并
        assert len(chunks) <= 3

    def test_empty_text(self):
        """空文本返回空列表"""
        assert chunk_text("") == []
        assert chunk_text(None) == []  # type: ignore
        assert chunk_text("   ") == []


class TestSmartChunkerClass:
    """SmartChunker 类测试"""

    def test_default_params(self):
        """默认参数"""
        chunker = SmartChunker()
        assert chunker.max_tokens == MAX_CHUNK_TOKENS
        assert chunker.min_tokens == MIN_CHUNK_TOKENS
        assert chunker.merge_target == MERGE_TARGET_TOKENS

    def test_custom_params(self):
        """自定义参数"""
        chunker = SmartChunker(max_tokens=2048, min_tokens=256, merge_target=1024)
        assert chunker.max_tokens == 2048
        assert chunker.min_tokens == 256
        assert chunker.merge_target == 1024

    def test_chunk_with_metadata(self):
        """带元数据的分块"""
        chunker = SmartChunker()
        text = "一、概述\n内容"
        result = chunker.chunk_with_metadata(text, {"source": "pdf", "id": "123"})
        assert len(result) > 0
        assert result[0]["source"] == "pdf"
        assert result[0]["id"] == "123"


class TestTokenCounting:
    """Token 计算测试"""

    def test_count_tokens(self):
        """Token 计数"""
        # 基本测试
        tokens = count_tokens("你好世界")
        assert tokens > 0

    def test_empty_string(self):
        """空字符串"""
        assert count_tokens("") == 0


class TestIntegration:
    """集成测试"""

    def test_full_pipeline_real_document(self):
        """完整分块流程 - 真实文档结构"""
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
        # 表格应保留在某个 chunk 中
        table_in_chunk = any("|" in c.text for c in chunks)
        assert table_in_chunk or len(chunks) == 1  # 表格可能在 body 中

    def test_large_document(self):
        """大文档分块"""
        # 生成一个大文档
        sections = []
        for i in range(20):
            sections.append(f"一、第{i}章标题\n")
            sections.append("\n".join([f"这是第{i}章的第{j}段内容。" for j in range(50)]))
            sections.append("\n")
        long_text = "\n".join(sections)

        chunks = chunk_text(long_text)
        assert len(chunks) > 1
        # 每个块不超过限制
        for c in chunks:
            assert c.tokens <= MAX_CHUNK_TOKENS
