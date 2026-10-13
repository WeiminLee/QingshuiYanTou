# Qingshui Data MCP（只读）

云端与 Knowledge API **同机**跑只读 Data MCP；本机/云端 dsh harness 用同一套 `plugins/qingshui`，经 `mcpBaseUrl` 连接。

## Profiles

| Profile | MCP bind | Knowledge | 备注 |
|---|---|---|---|
| `prod`（云） | `127.0.0.1:8100` | 同机 `127.0.0.1:8000`/`8080` | **禁止**依赖本机 Mac 隧道 |
| `dev-eval`（本机） | 指向云端 MCP（HTTPS/内网）或本机旁路 `127.0.0.1:8100` | 云端 Knowledge | 仅评测/开发；默认 CI 不真连生产库 |

## 启动（云上，用户执行）

```bash
cd /path/to/QingshuiYanTou/backend
export KNOWLEDGE_API_KEY=...          # 与 Knowledge HTTP 同源
export KNOWLEDGE_BASE_URL=http://127.0.0.1:8000
.venv/bin/python -m app.mcp_data.server --transport streamable-http --host 127.0.0.1 --port 8100
```

## 探活

```bash
# 无 key 也可（/health 开放）
curl -s http://127.0.0.1:8100/health

# 带 key（与 MCP 工具调用相同头）
curl -s -H "X-API-Key: $KNOWLEDGE_API_KEY" http://127.0.0.1:8100/health
```

期望 JSON：`{"ok":true,"service":"qingshui-data-mcp","tools":[...P0...]}`。

MCP endpoint：`http://127.0.0.1:8100/mcp`（Streamable HTTP）。对外请经 nginx 终止 TLS，并继续要求 `X-API-Key`；**不要**默认把 MCP bind 到 `0.0.0.0`。

## systemd

见同目录 `qingshui-data-mcp.service.example`。改路径与 Environment 后由用户 `systemctl enable --now`（本计划不在云上不可逆操作）。

## P0 tools

`fetch_evidence` `semantic_search` `compare_metric` `pull_history` `lookup_players` `lookup_products` `get_kline` `get_stock_profile` `data_readiness`

无 write / claim / upsert / enqueue。
