"""
API 鉴权工具

用法：
1. 标准路由（POST/GET JSON）: x_api_key: str = Depends(verify_api_key)
2. SSE/EventSource（不支持 Header）: api_key: str = Depends(verify_api_key_query)
3. 健康检查等公开端点: _ = Depends(verify_api_key_optional)
"""
from fastapi import Header, HTTPException, Depends, Query


def verify_api_key(x_api_key: str = Header(..., description="API 访问密钥")) -> str:
    """验证 API 密钥（Header 方式，适合 POST/GET JSON 请求）"""
    from app.config import settings
    if x_api_key != settings.api_key:
        raise HTTPException(status_code=401, detail="无效 API 密钥")
    return x_api_key


def verify_api_key_query(api_key: str = Query(..., description="API 访问密钥")) -> str:
    """验证 API 密钥（Query 参数方式，适合 SSE/EventSource 等不支持 Header 的场景）"""
    from app.config import settings
    if api_key != settings.api_key:
        raise HTTPException(status_code=401, detail="无效 API 密钥")
    return api_key


def verify_api_key_optional(
    x_api_key: str = Header(default=None, description="API 访问密钥（可选）")
) -> str | None:
    """可选验证：有密钥时验证，无密钥时放行（用于健康检查等）"""
    from app.config import settings
    if x_api_key is not None and x_api_key != settings.api_key:
        raise HTTPException(status_code=401, detail="无效 API 密钥")
    return x_api_key
