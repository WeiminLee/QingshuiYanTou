"""tinyshare 客户端。行情只走 mintree 网关，不调用 tushare 官方域名。"""

from __future__ import annotations

from urllib.parse import urlparse

TINYSHARE_GATEWAY = "http://mintree.site:8080"
_FORBIDDEN_HOSTS = ("tushare.pro", "waditu.com")


def assert_tinyshare_gateway(url: str) -> None:
    """拒绝官方 tushare 域名，只允许 tinyshare 的 mintree 网关。"""
    host = urlparse(url).netloc.lower()
    if any(bad in host for bad in _FORBIDDEN_HOSTS):
        raise RuntimeError(f"行情拒绝走官方 tushare：{host or url}")
    if "mintree.site" not in host:
        raise RuntimeError(f"行情必须走 tinyshare 网关 {TINYSHARE_GATEWAY}，当前是 {url or '空'}")


def open_tinyshare_pro(token: str):
    """用 tinyshare 授权码打开 pro 客户端，并钉在 mintree。"""
    if not token:
        raise RuntimeError("TUSHARE_TOKEN 未配置，请填写 tinyshare 授权码")
    import tinyshare as ts

    ts.set_token(token)
    ts.set_url(TINYSHARE_GATEWAY)
    assert_tinyshare_gateway(ts.get_url())
    return ts.pro_api()
