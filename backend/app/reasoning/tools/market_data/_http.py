"""
共享 HTTP Session 配置

提供带代理支持的 requests.Session 实例，供所有云端 API 工具使用。
"""
import logging
import threading

import requests
import requests.adapters

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = (10, 30)

# 懒加载全局 session（按 proxy 地址缓存，线程安全）
_cached_session: requests.Session | None = None
_cached_proxy: str | None = None
_session_lock = threading.Lock()


def _build_session(
    proxy: str | None = None,
    timeout: tuple[int, int] | None = None,
    pool_size: int = 10,
) -> requests.Session:
    """
    构建配置好的 requests.Session。

    - 不使用系统代理（trust_env=False）
    - 可选指定代理地址（来自 settings.http_proxy）
    - 连接池复用避免频繁建联
    """
    session = requests.Session()
    session.trust_env = False

    if proxy:
        session.proxies = {
            "http": proxy,
            "https": proxy,
        }
        logger.debug(f"[HTTP] 使用代理: {proxy}")
    else:
        session.proxies = {}
        logger.debug("[HTTP] 不使用代理")

    # 连接池
    adapter = requests.adapters.HTTPAdapter(
        pool_connections=pool_size,
        pool_maxsize=pool_size,
        max_retries=0,
    )
    session.mount("http://", adapter)
    session.mount("https://", adapter)

    session.timeout = timeout or _DEFAULT_TIMEOUT
    return session


def get_http_session(
    proxy: str | None = None,
    timeout: tuple[int, int] | None = None,
) -> requests.Session:
    """
    获取配置好的 HTTP session（懒加载，按 proxy 地址缓存，线程安全）。
    调用方负责 session 的生命周期管理。
    """
    global _cached_session, _cached_proxy
    with _session_lock:
        if _cached_session is None or _cached_proxy != proxy:
            _cached_session = _build_session(proxy=proxy, timeout=timeout)
            _cached_proxy = proxy
            logger.info(f"[HTTP] 初始化 session，proxy={proxy}")
        return _cached_session


def _get_proxy_from_settings() -> str | None:
    """从 settings 读取代理地址，失败时返回 None"""
    try:
        from app.config import settings
        return settings.http_proxy or None
    except Exception:
        return None

