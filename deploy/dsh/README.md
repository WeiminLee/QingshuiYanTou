# Cloud handoff — dsh vertical slice + 硅片预期差

Host: `root@124.221.188.38` path `/home/lwm/code/QingShuiTouYan` (see ops docs).

## One-shot headless 预期差（今晚验收）

```bash
ssh root@124.221.188.38
cd /home/lwm/code/QingShuiTouYan
git fetch && git checkout feat/dsh-vertical-slice && git pull
# Node 24 via nvm
export NVM_DIR=/home/lwm/.nvm; . "$NVM_DIR/nvm.sh"; nvm use 24
# env (gitignored): OPENAI_API_KEY, LLM_*, KNOWLEDGE_API_KEY or API_KEY from backend/.env
set -a; source .env.dsh; set +a
pnpm install
# dsh submodule pin stays at b150a551; apply Qingshui-local HTTP mintRpcId fix (not upstream)
./deploy/dsh/apply-mint-rpc-id-patch.sh
cd dsh && CI=true pnpm_config_verify_deps_before_run=false pnpm install && pnpm run build:lib:host && pnpm run build:lib:client && pnpm run build:web && cd ..
pnpm run build:plugin
pnpm dsh plugin --profile headless add ./plugins/qingshui
# May stop data-acquisition processes for test
pnpm run check:skills
pnpm dsh --profile headless --patch patches/qingshui.yml "对硅片板块做预期差分析" | tee /tmp/silicon-wafer-divergence-dsh.md
```

Rollback: leave submodule/plugin in git; stop any dsh unit; Vue/LangChain untouched.

## Durable dsh patch: insecure-HTTP `mintRpcId`

Public web is served over **HTTP** (`http://124.221.188.38/`). Upstream
`WebApiClient` uses `crypto.randomUUID()`, which browsers reject outside a
secure context, so the composer never becomes editable.

**Qingshui-local fix** (do **not** push to `deepseek-ai/deepseek-harness`):

- Patch: `patches/dsh-web-api-mint-rpc-id.patch`
- Overrides `WebApiClient.mintRpcId` to use `randomUuid()` from
  `./random-uuid.ts` (`crypto.getRandomValues`, works on insecure origins).
- Apply + rebuild after clean submodule checkout:

```bash
# from Qingshui repo root (gitlink pin remains b150a551)
./deploy/dsh/apply-mint-rpc-id-patch.sh --rebuild
# or: apply only, then follow the build:lib:client / build:web steps above
systemctl restart qingshui-dsh
```

`lib/` under the connection package is gitignored — always rebuild after apply;
do not vendor `packages/client/connection/lib/client.js` in Qingshui.

## Prod web + public Host trust

Cloud nginx (`deploy/nginx/dsh-web.conf.example` → `/etc/nginx/conf.d/dsh-web.conf`)
proxies `:80` → `127.0.0.1:3080` with basic auth and **`proxy_set_header Host $host`**.

dsh refuses `/api` (and WS upgrades) unless `Host` is loopback or listed in
`trustedHosts`. The public IP must be declared — otherwise the HTML shell loads
but API/WS return **403**.

**Intended knob:** `qingshui-dsh.service` ExecStart adds
`--trusted-host 124.221.188.38` (flows `webStartup` → `webRuntime` →
`connection.trustedHosts`). See `deploy/dsh/qingshui-dsh.service.example`.

**Do not** rewrite nginx `Host` to `127.0.0.1:3080`. That would make every
proxied request look loopback and unlock PRIVILEGED methods (`host.pickDirectory`,
settings/credentials plane, etc.). Keep `$host` + explicit `trustedHosts`.

**Host FS:** cordis patch `name` is a match-guard (cannot rename the row).
`plugins/qingshui/cordis.patch.yml` therefore **disables** `directory-picker`
(auto) and **inserts** native, so `host.listDirectory` / `createDirectory`
return `directory-picker-unavailable` instead of listings. auto→browse would
list the host filesystem for any trusted Host. `host.pickDirectory` /
settings / credentials remain loopback-only via dsh PRIVILEGED_METHODS.

After pull: apply mintRpcId patch if submodule was reset, then
`systemctl daemon-reload && systemctl restart qingshui-dsh`
(nginx unchanged unless conf edited).
