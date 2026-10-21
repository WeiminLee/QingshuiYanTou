# Routes

The product is one local page. There is no client router.

| URL | What renders | Layout |
|---|---|---|
| `http://127.0.0.1:8399/` | Research shell: sidebar + conversation | SidebarRoot + ResearchConversationRoot |

Settings is a modal on the same page, not a route. Evidence and kline cards render inside the transcript, not on their own routes.

Entry scripts: `scripts/start-local-dsh-web.sh` launches `node scripts/dsh.mjs --profile web` with patches `patches/qingshui.yml`, `patches/local-pjlab-retry.yml`, `patches/local-mac.yml`. The browser plugin is `plugins/qingshui` (`cordis.patch.yml` + `src/client/index.ts`).
