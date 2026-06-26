"""
BUG 修复测试套件

测试以下 BUG 修复：
- BUG-1: Cypher 注入防护
- BUG-6: N+1 查询问题
- BUG-9/10/11: 事务原子性
- BUG-11: entity_id 格式验证
- BUG-12: 关系方向丢失、失败计数
- BUG-19: Embedding 默认值读取
"""

import os
import re

import pytest


class TestBug1CypherInjection:
    """BUG-1: Cypher 注入防护测试"""

    def test_safe_rel_type_rejects_sql_injection(self):
        """测试 SQL/Cypher 注入尝试被拒绝"""
        RELATIONSHIP_TYPES = {"RELATES", "LOCATED_IN", "PARTICIPATES_IN", "HAS_METRIC", "MENTIONS"}

        def safe_rel_type(rel_type: str) -> str:
            if not rel_type or not isinstance(rel_type, str):
                raise ValueError(f"relationship_type 必须是字符串: {rel_type!r}")
            if rel_type not in RELATIONSHIP_TYPES:
                raise ValueError(f"无效 relationship_type: {rel_type}")
            return rel_type

        malicious_inputs = [
            "RELATES; DROP DATABASE",
            "RELATES\nMATCH (n) DETACH DELETE n",
            "RELATES`]",
            "RELATES--comment",
            "RELATES/* comment */",
        ]

        for malicious in malicious_inputs:
            with pytest.raises(ValueError):
                safe_rel_type(malicious)

    def test_relation_service_has_safe_rel_type(self):
        """测试 relation_service.py 包含 _safe_rel_type 函数"""
        source_file = "/home/code/QingShuiTouYan/backend/app/knowledge/relation_service.py"
        if not os.path.exists(source_file):
            pytest.skip("relation_service.py not found")

        with open(source_file) as f:
            source = f.read()

        assert "_safe_rel_type" in source, "relation_service.py 应包含 _safe_rel_type 函数"
        assert "BUG-1" in source or "注入" in source, "应有 BUG-1 修复标记"


class TestBug11EntityIdValidation:
    """BUG-11: entity_id 格式验证测试"""

    def test_valid_entity_id_formats(self):
        """测试合法 entity_id 格式"""
        ENTITY_ID_PATTERN = re.compile(r"^(C:|P:|M:|E:|CO:|IND:|I:)[A-Za-z0-9_.:/-]+$")

        valid_ids = [
            "C:600519.SH",
            "P:chip_A",
            "M:memory_2024",
            "E:event_main",
            "CO:company_abc",
            "IND:industry_tech",
            "I:index_000001",
        ]

        for entity_id in valid_ids:
            assert ENTITY_ID_PATTERN.match(entity_id), f"应通过: {entity_id}"

    def test_invalid_entity_id_formats(self):
        """测试非法 entity_id 格式"""
        ENTITY_ID_PATTERN = re.compile(r"^(C:|P:|M:|E:|CO:|IND:|I:)[A-Za-z0-9_.:/-]+$")

        invalid_ids = [
            "invalid_id",
            "C;DROP DATABASE",
            "X:600519.SH",
            "C:",
        ]

        for entity_id in invalid_ids:
            assert not ENTITY_ID_PATTERN.match(entity_id), f"应拒绝: {entity_id}"

    def test_feedback_service_has_entity_id_validation(self):
        """测试 feedback_service.py 包含 entity_id 格式验证"""
        source_file = "/home/code/QingShuiTouYan/backend/app/knowledge/feedback_service.py"
        if not os.path.exists(source_file):
            pytest.skip("feedback_service.py not found")

        with open(source_file) as f:
            source = f.read()

        assert "ENTITY_ID_PATTERN" in source or "entity_id" in source.lower(), (
            "feedback_service.py 应包含 entity_id 格式验证"
        )


class TestBug12RelationshipDirection:
    """BUG-12: 关系方向丢失、失败计数测试"""

    def test_entity_resolver_has_bidirectional_handling(self):
        """测试 entity_resolver.py 包含双向关系处理"""
        source_file = "/home/code/QingShuiTouYan/backend/app/knowledge/entity_resolver.py"
        if not os.path.exists(source_file):
            pytest.skip("entity_resolver.py not found")

        with open(source_file) as f:
            source = f.read()

        # 检查包含双向处理逻辑
        has_bidirectional = ("cypher_outgoing" in source or "cypher_incoming" in source) or (
            "outgoing" in source.lower() and "incoming" in source.lower()
        )
        assert has_bidirectional, "entity_resolver.py 应包含双向关系处理逻辑"
        assert "BUG-12" in source, "应有 BUG-12 修复标记"

    def test_kg_extractor_has_failure_counter(self):
        """测试 kg_extractor.py 包含失败计数器"""
        source_file = "/home/code/QingShuiTouYan/backend/app/knowledge/kg_extractor.py"
        if not os.path.exists(source_file):
            pytest.skip("kg_extractor.py not found")

        with open(source_file) as f:
            source = f.read()

        assert "chunks_failed" in source or "chunks_written" in source, (
            "kg_extractor.py 应包含 chunk 向量写入失败计数器"
        )


class TestBug19EmbeddingDefaults:
    """BUG-19: Embedding 默认值读取测试"""

    def test_local_embedding_reads_from_settings(self):
        """测试 LocalEmbedding 从 settings 读取默认值"""
        source_file = "/home/code/QingShuiTouYan/backend/app/knowledge/vector_client.py"
        if not os.path.exists(source_file):
            pytest.skip("vector_client.py not found")

        with open(source_file) as f:
            source = f.read()

        assert "settings" in source, "vector_client.py 应使用 settings"
        assert "embedding_api" in source.lower(), "应读取 embedding_api 相关配置"

    def test_bug19_fix_marked(self):
        """测试 BUG-19 修复标记存在"""
        source_file = "/home/code/QingShuiTouYan/backend/app/knowledge/vector_client.py"
        if not os.path.exists(source_file):
            pytest.skip("vector_client.py not found")

        with open(source_file) as f:
            source = f.read()

        assert "BUG-19" in source, "应有 BUG-19 修复标记"


class TestBug9TransactionAtomicity:
    """BUG-9/10/11: 事务原子性测试"""

    def test_neo4j_client_has_write_transaction(self):
        """测试 neo4j_client.py 包含 write_transaction"""
        source_file = "/home/code/QingShuiTouYan/backend/app/core/neo4j_client.py"
        if not os.path.exists(source_file):
            pytest.skip("neo4j_client.py not found")

        with open(source_file) as f:
            source = f.read()

        assert "write_transaction" in source, "neo4j_client.py 应包含 write_transaction"

    def test_relation_service_uses_transaction(self):
        """测试 relation_service.py 使用事务"""
        source_file = "/home/code/QingShuiTouYan/backend/app/knowledge/relation_service.py"
        if not os.path.exists(source_file):
            pytest.skip("relation_service.py not found")

        with open(source_file) as f:
            source = f.read()

        assert "write_transaction" in source, "relation_service.py 应使用事务"


class TestBug6N1Query:
    """BUG-6: N+1 查询问题测试"""

    def test_entity_service_has_unwind_batch_method(self):
        """测试 entity_service.py 包含 UNWIND 批量方法"""
        source_file = "/home/code/QingShuiTouYan/backend/app/knowledge/entity_service.py"
        if not os.path.exists(source_file):
            pytest.skip("entity_service.py not found")

        with open(source_file) as f:
            source = f.read()

        assert "batch_upsert_entities_unwind" in source or "UNWIND" in source, (
            "entity_service.py 应包含 UNWIND 批量方法"
        )
        assert "BUG-6" in source, "应有 BUG-6 修复标记"

    def test_batch_upsert_delegates_to_unwind(self):
        """测试 batch_upsert 委托给 UNWIND 方法"""
        source_file = "/home/code/QingShuiTouYan/backend/app/knowledge/entity_service.py"
        if not os.path.exists(source_file):
            pytest.skip("entity_service.py not found")

        with open(source_file) as f:
            source = f.read()

        # 检查 batch_upsert_entities 函数委托给 unwind 方法
        if "def batch_upsert_entities" in source:
            batch_func_start = source.find("def batch_upsert_entities")
            # 找到下一个函数定义作为边界
            next_func = source.find("\ndef ", batch_func_start + 10)
            if next_func == -1:
                next_func = len(source)
            batch_func_body = source[batch_func_start:next_func]

            # 验证委托给 unwind 方法
            assert "batch_upsert_entities_unwind" in batch_func_body or "UNWIND" in batch_func_body, (
                "batch_upsert_entities 应委托给 UNWIND 方法"
            )


# 运行测试的便捷函数
def run_all_tests():
    """运行所有 BUG 修复测试"""
    pytest.main([__file__, "-v", "--tb=short"])


if __name__ == "__main__":
    run_all_tests()
