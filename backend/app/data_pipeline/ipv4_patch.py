"""
IPv4 强制补丁 — 修复上交所互动易（sns.sseinfo.com）IPv6 超时问题。

根因：sns.sseinfo.com 同时解析到 IPv6 和 IPv4，但 IPv6 路由不通，
urllib3 默认优先尝试 IPv6 导致连接超时。

此模块在导入时自动替换 urllib3.util.connection.create_connection，
对 sseinfo.com 域名强制使用 IPv4（AF_INET），其他域名不受影响。
"""

import logging
import socket

import urllib3.util.connection

logger = logging.getLogger(__name__)

# 保存原始 create_connection
_original_create_connection = urllib3.util.connection.create_connection

# 需要强制 IPv4 的域名后缀
_IPV4_FORCE_DOMAINS = ("sseinfo.com",)


def _create_connection_ipv4(address, *args, **kwargs):
    """
    对 sseinfo.com 域名强制使用 IPv4，其他域名走原始逻辑。

    urllib3 create_connection 签名:
        create_connection(address, timeout=..., source_address=None, socket_options=None)
    timeout 可以是位置参数 (args[0]) 或关键字参数 (kwargs['timeout'])。
    """
    host, port = address

    # 提取 timeout 值（兼容位置和关键字两种传参方式）
    if args:
        timeout = args[0]
        remaining_args = args[1:]
    else:
        timeout = kwargs.pop("timeout", socket._GLOBAL_DEFAULT_TIMEOUT)
        remaining_args = ()

    if any(host.endswith(domain) for domain in _IPV4_FORCE_DOMAINS):
        addrs = socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM)
        last_err = None
        for af, socktype, proto, canonname, sa in addrs:
            sock = None
            try:
                sock = socket.socket(af, socktype, proto)
                if timeout is not socket._GLOBAL_DEFAULT_TIMEOUT:
                    sock.settimeout(timeout)
                sock.connect(sa)
                return sock
            except OSError as e:
                last_err = e
                if sock is not None:
                    sock.close()
        if last_err is not None:
            raise last_err

    return _original_create_connection(address, timeout, *remaining_args, **kwargs)


# 安装补丁：替换 urllib3 的 create_connection
urllib3.util.connection.create_connection = _create_connection_ipv4
logger.debug("IPv4 强制补丁已安装：sseinfo.com 将强制使用 IPv4")
