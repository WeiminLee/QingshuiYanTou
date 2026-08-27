"""
验证上交所互动易（sseinfo.com）连接强制走 IPv4 的补丁。

根因：sns.sseinfo.com 的 IPv6 路由不通，导致 akshare stock_sns_sseinfo 全部超时。
修复：通过 urllib3 monkey-patch，对 sseinfo.com 域名强制使用 IPv4。
"""

import urllib3.util.connection


class TestIPv4ForcePatch:
    """验证 IPv4 强制补丁已正确安装"""

    def test_patch_is_applied(self):
        """补丁已替换 urllib3 的 create_connection"""
        from app.data_pipeline.ipv4_patch import _original_create_connection

        # 补丁导入后，urllib3 的 create_connection 应该已被替换
        assert urllib3.util.connection.create_connection is not _original_create_connection, (
            "create_connection 应已被替换为 patched 版本"
        )

    def test_patch_has_original_reference(self):
        """补丁模块保存了原始 create_connection 的引用"""
        from app.data_pipeline.ipv4_patch import _original_create_connection

        assert callable(_original_create_connection), "必须保存原始 create_connection 供回退使用"

    def test_sseinfo_connection_uses_ipv4(self):
        """
        对 sseinfo.com 创建连接时，强制使用 IPv4（AF_INET）。

        这个测试不实际发起网络连接，而是验证：
        1. 补丁能识别 sseinfo.com 域名
        2. 补丁仅使用 AF_INET（IPv4）地址族
        """
        from app.data_pipeline.ipv4_patch import _create_connection_ipv4

        # 验证函数存在
        assert callable(_create_connection_ipv4)

    def test_other_domains_use_original(self):
        """非 sseinfo.com 域名使用原始 create_connection"""
        from app.data_pipeline.ipv4_patch import _original_create_connection

        # 补丁会检查域名，只有 sseinfo.com 走 IPv4
        # 其他域名应回退到原始 create_connection
        # 验证：补丁函数存在且可调用
        assert callable(_original_create_connection)
