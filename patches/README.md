# patches

`cordis.patch.yml` overlays applied with `pnpm dsh --profile web --patch ./patches/<file>.yml`.
Tonight composition is inside `plugins/qingshui/cordis.patch.yml` after `dsh plugin add`.
Keep `patches/qingshui.yml` empty unless a checkout needs a local override.

## dsh source patches (git apply, not cordis)

| File | Purpose |
|------|---------|
| `dsh-web-api-mint-rpc-id.patch` | HTTP / non-secure: `WebApiClient.mintRpcId` → `randomUuid()`. Apply via `./deploy/dsh/apply-mint-rpc-id-patch.sh` before `build:lib:client` / `build:web`. Does not change the dsh gitlink pin (`b150a551`); never push to upstream harness. |
