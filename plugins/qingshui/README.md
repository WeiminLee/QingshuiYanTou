# qingshui

清水投研 dsh Cordis 插件。Tools 经 Knowledge HTTP（X-API-Key），不直连 DB。

## Install

```sh
pnpm run build:plugin
pnpm dsh plugin --profile headless add ./plugins/qingshui
set -a; source .env.dsh.local; set +a
KNOWLEDGE_API_KEY=… pnpm dsh --profile headless "对硅片板块做预期差分析"
```

LLM: pjlab Gateway `https://token.pjlab.org.cn/v1`（模型如 `glm-5.3`,
`OPENAI_API_KEY`；实际 provider/model 配置以 `cordis.patch.yml` 为准）。

## Skills

`skills/divergence-mining` is mounted via nested `@deepseek-ai/dsh-skill-filesystem`
(provider `qingshui-local`, MatDiscovery pattern). Frontmatter `description` must be
YAML-safe (quote strings that contain `:`).

```sh
pnpm run check:skills
```

## Model overlay

If `~/.dsh/settings.yaml` still pins another provider, pass the checkout overlay:

```sh
pnpm dsh --profile headless --patch patches/qingshui.yml "…"
```
