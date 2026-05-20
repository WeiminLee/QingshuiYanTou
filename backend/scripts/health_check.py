#!/usr/bin/env python3
"""
系统自检脚本

在 uvicorn 启动前检查以下依赖：
1. 云端 API 是否可达（走 proxyhk 代理）
2. PostgreSQL 数据库是否正常（asyncpg）
3. LLM（LiteLLM）是否正常
4. Embedding 服务是否正常（直连）

任意一项失败 → 输出警告，不启动后端。
"""
from __future__ import annotations

import asyncio
import json
import sys
import os

# 确保 backend 在路径中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def check(label: str, ok: bool, detail: str = "") -> bool:
    symbol = "✓" if ok else "✗"
    print(f"  {symbol} {label}" + (f" — {detail}" if detail else ""))
    return ok


async def main() -> int:
    print("\n" + "=" * 50)
    print("  清水投研系统 · 启动前自检")
    print("=" * 50 + "\n")

    import requests
    import asyncpg
    from app.config import settings

    all_ok = True

    # ── 1. 云端 API（走 proxyhk 代理）───────────────────────
    print("[1/4] 云端 API (http://124.221.188.38:8080)")
    cloud_base = "http://124.221.188.38:8080/api/v1"
    try:
        proxies = {
            "http": "http://proxyhk.zte.com.cn:80",
            "https": "http://proxyhk.zte.com.cn:80",
        }
        r = requests.get(
            f"{cloud_base}/ann_ids",
            params={"page": 1, "page_size": 3},
            proxies=proxies,
            timeout=15,
        )
        if r.ok:
            data = r.json()
            count = len(data.get("data", []))
            all_ok &= check("云端 API", True, f"HTTP {r.status_code}, 返回 {count} 条数据")
        else:
            all_ok &= check("云端 API", False, f"HTTP {r.status_code}")
            print("  ⚠ 警告：云端 API 不可用，研报/公告查询将失败")
    except Exception as e:
        all_ok &= check("云端 API", False, str(e))
        print("  ⚠ 警告：云端 API 不可用，研报/公告查询将失败")

    # ── 2. PostgreSQL（asyncpg）─────────────────────────────
    print("\n[2/4] PostgreSQL 数据库")
    try:
        raw_url = settings.database_url
        # asyncpg 不支持 postgresql+asyncpg:// 格式，转为 postgres://
        url = raw_url.replace("postgresql+asyncpg://", "postgres://").replace(
            "postgresql://", "postgres://"
        )
        conn = await asyncpg.connect(url, timeout=5)
        # 测试真实查询
        result = await conn.fetchval("SELECT 1")
        await conn.close()
        if result == 1:
            all_ok &= check("PostgreSQL", True, "查询测试成功")
        else:
            all_ok &= check("PostgreSQL", False, "查询返回异常结果")
            print("  ✗ 致命：数据库查询异常，后端无法启动")
            all_ok = False
    except Exception as e:
        all_ok &= check("PostgreSQL", False, str(e))
        print("  ✗ 致命：数据库不可用，后端无法启动")
        all_ok = False

    # ── 3. LLM（LiteLLM）───────────────────────────────────
    print("\n[3/4] LLM (LiteLLM @ localhost:4000)")
    try:
        # 使用真实的 API key 和模型名称
        api_key = settings.llm_api_key
        model_name = settings.llm_model  # 从配置读取模型名称

        if not api_key:
            all_ok &= check("LLM", False, "LLM_API_KEY 未配置")
            print("  ✗ 致命：LLM_API_KEY 未配置，Agent 无法分析")
            all_ok = False
        elif not model_name:
            all_ok &= check("LLM", False, "LLM_MODEL 未配置")
            print("  ✗ 致命：LLM_MODEL 未配置，Agent 无法分析")
            all_ok = False
        else:
            # 测试真实的 API 调用
            r = requests.post(
                "http://localhost:4000/v1/chat/completions",
                json={
                    "model": model_name,  # 使用配置中的模型名称
                    "messages": [{"role": "user", "content": "hi"}],
                    "max_tokens": 5,
                },
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=30,
            )

            if r.status_code == 200:
                data = r.json()
                model = data.get("model", "?")
                # 检查是否有有效的响应内容
                choices = data.get("choices", [])
                if choices and len(choices) > 0:
                    content = choices[0].get("message", {}).get("content", "")
                    all_ok &= check(f"LLM ({model_name})", True, f"model={model}, 响应正常")
                else:
                    all_ok &= check("LLM", False, "响应无内容")
                    print("  ✗ 致命：LLM 响应异常，Agent 无法分析")
                    all_ok = False
            else:
                error_msg = r.json().get("error", {}).get("message", r.text) if r.headers.get("content-type", "").startswith("application/json") else r.text
                all_ok &= check("LLM", False, f"HTTP {r.status_code}: {error_msg[:100]}")
                print("  ✗ 致命：LLM API 调用失败，Agent 无法分析")
                print(f"     错误详情: {error_msg[:200]}")
                all_ok = False
    except Exception as e:
        all_ok &= check("LLM", False, str(e))
        print("  ✗ 致命：LLM 不可用，Agent 无法分析")
        all_ok = False

    # ── 4. Embedding 服务（直连 10.57.230.169）───────────────
    print("\n[4/4] Embedding 服务 (http://10.57.230.169:8000)")
    try:
        r = requests.post(
            "http://10.57.230.169:8000/v1/embeddings",
            json={"texts": ["test"]},
            timeout=8,
        )
        if r.status_code == 200:
            data = r.json()
            embs = data.get("embeddings", [])
            if embs and len(embs) > 0:
                dim = len(embs[0]) if embs else 0
                if dim > 0:
                    all_ok &= check("Embedding 服务", True, f"向量维度={dim}, 响应正常")
                else:
                    all_ok &= check("Embedding 服务", False, "向量维度为 0")
                    print("  ⚠ 警告：Embedding 服务返回异常向量")
            else:
                all_ok &= check("Embedding 服务", False, "无嵌入向量返回")
                print("  ⚠ 警告：Embedding 服务不可用，向量检索将使用占位实现")
        else:
            all_ok &= check("Embedding 服务", False, f"HTTP {r.status_code}")
            print("  ⚠ 警告：Embedding 服务不可用，向量检索将使用占位实现")
    except Exception as e:
        all_ok &= check("Embedding 服务", False, str(e))
        print("  ⚠ 警告：Embedding 服务不可用，向量检索将使用占位实现")

    # ── 结果 ────────────────────────────────────────────────
    print("\n" + "=" * 50)
    if all_ok:
        print("  ✓ 自检全部通过，系统可以启动")
        print("=" * 50 + "\n")
        return 0
    else:
        print("  ✗ 自检未通过，请修复上述问题后再启动")
        print("=" * 50 + "\n")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
