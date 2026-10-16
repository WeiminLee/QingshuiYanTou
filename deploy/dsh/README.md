# dsh 部署辅助（本地 Mac 交互层）

dsh web + `plugins/qingshui` 在本地 Mac 运行（入口 `scripts/start-local-dsh-web.sh`，
详见 AGENTS.md 角色分工条目 2）。本目录只保留 dsh submodule 的本地补丁与其应用脚本。

## Durable dsh patch: insecure-HTTP `mintRpcId`

Upstream `WebApiClient` uses `crypto.randomUUID()`, which browsers reject outside a
secure context, so the composer never becomes editable.

**Qingshui-local fix** (do **not** push to `deepseek-ai/deepseek-harness`):

- Patch: `patches/dsh-web-api-mint-rpc-id.patch`
- Overrides `WebApiClient.mintRpcId` to use `randomUuid()` from
  `./random-uuid.ts` (`crypto.getRandomValues`, works on insecure origins).
- Apply + rebuild after clean submodule checkout:

```bash
# from Qingshui repo root (gitlink pin remains b150a551)
./deploy/dsh/apply-mint-rpc-id-patch.sh --rebuild
# or: apply only, then rebuild lib:client / web manually
```

`lib/` under the connection package is gitignored — always rebuild after apply;
do not vendor `packages/client/connection/lib/client.js` in Qingshui.

## Data MCP（harness 唯一运行时）

插件默认 `mcpBaseUrl=http://127.0.0.1:8100/mcp`（见 `plugins/qingshui/cordis.patch.yml`）。
MCP 服务跑在 chemagent（`deploy/chemagent/docker-compose.yml` 的 `data-mcp`），
本机经 SSH 端口转发访问（`scripts/tunnel_chemagent.sh`），
双轨评测细则见 [`deploy/mcp/DUAL_TRACK_RUNBOOK.md`](../mcp/DUAL_TRACK_RUNBOOK.md)。
