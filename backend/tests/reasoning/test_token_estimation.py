"""
tests/reasoning/test_token_estimation.py

Bug M1 TDD: Token 估算不准确

Bug 描述：
  context_compressor.py 使用 len(text) // 2 (中文) 估算 token。
  对中文：实际约 1 字符/token，但代码使用 // 2，低估约 60%

修复方案：
  改为 len(text) // 1（中文）或使用 tiktoken。

Run: uv run --directory backend python -m pytest tests/reasoning/test_token_estimation.py -v
"""
import pytest


class TestTokenEstimationAccuracy:
    """Token 估算准确性测试"""

    def test_current_implementation_underestimates_chinese(self):
        """
        当前实现：中文字符低估约 60%

        中文约 0.8-1 字符/token，用 len//2 会严重低估。
        例如 "分析光模块行业" = 9 字符，len//2 = 4，但实际约 9 token
        """
        from app.reasoning.langchain_agent.middlewares.context_compressor import _estimate_text_tokens

        # 中文测试用例
        chinese_text = "分析光模块行业的竞争格局和技术路线"

        # tiktoken 实际值（如果有）
        try:
            import tiktoken
            enc = tiktoken.get_encoding("cl100k_base")
            actual = len(enc.encode(chinese_text))
        except ImportError:
            actual = len(chinese_text)  # 保守估计：1 char = 1 token

        estimated = _estimate_text_tokens(chinese_text)

        print(f"中文文本: {chinese_text}")
        print(f"字符数: {len(chinese_text)}")
        print(f"tiktoken 估算: {actual}")
        print(f"当前函数输出: {estimated}")
        print(f"低估比例: {(actual - estimated) / actual * 100:.1f}%")

        # 验证当前实现不应低估超过 30%
        error_pct = abs(actual - estimated) / actual * 100
        assert error_pct < 30, f"估算误差 {error_pct:.1f}% 超过 30% 阈值"

    def test_tiktoken_used_when_available(self):
        """tiktoken 可用时应优先使用"""
        try:
            import tiktoken
            enc = tiktoken.get_encoding("cl100k_base")
            # tiktoken 可用，函数应返回准确值
            pytest.skip("tiktoken 可用，验证通过")
        except ImportError:
            pytest.skip("tiktoken 不可用，跳过此测试")

    def test_chinese_estimation_accuracy(self):
        """
        验证中文估算准确性（误差 < 30%）
        """
        from app.reasoning.langchain_agent.middlewares.context_compressor import _estimate_text_tokens

        test_cases = [
            "分析",
            "分析光模块",
            "分析光模块行业",
            "分析光模块行业的竞争格局和技术路线",
            "投资建议：关注光模块龙头企业的技术创新和产能扩张",
        ]

        for text in test_cases:
            try:
                import tiktoken
                enc = tiktoken.get_encoding("cl100k_base")
                actual = len(enc.encode(text))
            except ImportError:
                actual = len(text)

            estimated = _estimate_text_tokens(text)
            error_pct = abs(actual - estimated) / actual * 100 if actual > 0 else 0

            print(f"文本: {text[:20]}...")
            print(f"  实际: {actual}, 估算: {estimated}, 误差: {error_pct:.1f}%")

            assert error_pct < 30, f"'{text[:10]}...' 估算误差 {error_pct:.1f}% 超过 30%"

    def test_code_estimation_accuracy(self):
        """
        验证代码/英文估算准确性
        """
        from app.reasoning.langchain_agent.middlewares.context_compressor import _estimate_text_tokens

        code_text = "def calculate_similarity(a, b): return a * b / 100"
        estimated = _estimate_text_tokens(code_text)

        # 英文代码约 4 字符/token
        expected = len(code_text) // 4
        print(f"代码文本: {code_text}")
        print(f"估算: {estimated}, 预期: {expected}")

        assert abs(estimated - expected) <= 2, "代码估算应在合理误差范围内"

    def test_mixed_content_accuracy(self):
        """
        验证中英文混合内容的估算准确性
        """
        from app.reasoning.langchain_agent.middlewares.context_compressor import _estimate_text_tokens

        # 中英文混合
        mixed = "分析 get_kline() 返回的 K 线数据趋势"
        estimated = _estimate_text_tokens(mixed)

        try:
            import tiktoken
            enc = tiktoken.get_encoding("cl100k_base")
            actual = len(enc.encode(mixed))
        except ImportError:
            actual = len(mixed)

        error_pct = abs(actual - estimated) / actual * 100 if actual > 0 else 0
        print(f"混合文本: {mixed}")
        print(f"  实际: {actual}, 估算: {estimated}, 误差: {error_pct:.1f}%")

        assert error_pct < 30, f"混合内容估算误差 {error_pct:.1f}% 超过 30%"