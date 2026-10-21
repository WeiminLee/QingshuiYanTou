/**
 * Same-origin news tape: GET /qingshui/news
 * proxies the latest telegraph items. The API key stays on the host.
 */
import type { IncomingMessage, ServerResponse } from 'node:http'
import type { KnowledgeClient } from './knowledge-client.ts'
import { isLoopbackHostRequest } from './ev-route.ts'
import { shapeNewsFeed } from './news-tape.ts'

export const NEWS_ROUTE_PATH = '/qingshui/news'

export type NewsRouteDeps = {
  client: () => KnowledgeClient | undefined
}

function sendJson(res: ServerResponse, status: number, body: Record<string, unknown>): void {
  res.writeHead(status, {
    'content-type': 'application/json; charset=utf-8',
    'cache-control': 'no-store',
  })
  res.end(JSON.stringify(body))
}

/**
 * Install the news proxy. @param webCtx - web server. @param deps - client accessor.
 * @returns disposer.
 */
export function installNewsRoute(
  webCtx: { webServer: { register: (route: { kind: 'exact' | 'prefix'; path: string; handler: (req: IncomingMessage, res: ServerResponse) => Promise<void> | void }) => () => void } },
  deps: NewsRouteDeps,
): () => void {
  return webCtx.webServer.register({
    kind: 'exact',
    path: NEWS_ROUTE_PATH,
    handler: async (req, res): Promise<void> => {
      if (!isLoopbackHostRequest(req)) {
        sendJson(res, 403, { ok: false, error: 'forbidden' })
        return
      }
      const client = deps.client()
      if (client === undefined) {
        sendJson(res, 503, { ok: false, error: '知识库未配置' })
        return
      }
      try {
        const payload = await client.listRecentEvents(20)
        sendJson(res, 200, { ok: true, items: shapeNewsFeed(payload) })
      } catch (error) {
        const message = error instanceof Error ? error.message : '知识库查询失败'
        sendJson(res, 502, { ok: false, error: message })
      }
    },
  })
}
