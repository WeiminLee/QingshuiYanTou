/**
 * Same-origin quote strip: GET /qingshui/market-snapshot
 * proxies the latest Shanghai composite. The API key stays on the host.
 */
import type { IncomingMessage, ServerResponse } from 'node:http'
import type { KnowledgeClient } from './knowledge-client.ts'
import { isLoopbackHostRequest } from './ev-route.ts'
import { pickBoardQuotes, pickShanghaiQuote } from './quote-strip.ts'

export const SNAPSHOT_ROUTE_PATH = '/qingshui/market-snapshot'
export const OVERSEAS_ROUTE_PATH = '/qingshui/overseas-snapshot'

export type MarketRouteDeps = {
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
 * Install the snapshot proxy. @param webCtx - web server. @param deps - client accessor.
 * @returns disposer.
 */
export function installMarketRoute(
  webCtx: { webServer: { register: (route: { kind: 'exact' | 'prefix'; path: string; handler: (req: IncomingMessage, res: ServerResponse) => Promise<void> | void }) => () => void } },
  deps: MarketRouteDeps,
): () => void {
  const disposeSnapshot = webCtx.webServer.register({
    kind: 'exact',
    path: SNAPSHOT_ROUTE_PATH,
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
        const payload = await client.getMarketSnapshot()
        const quotes = pickBoardQuotes(payload)
        const quote = pickShanghaiQuote(payload)
        sendJson(res, 200, { ok: true, quotes, ...(quote === null ? {} : { quote }) })
      } catch (error) {
        const message = error instanceof Error ? error.message : '知识库查询失败'
        sendJson(res, 502, { ok: false, error: message })
      }
    },
  })

  const disposeOverseas = webCtx.webServer.register({
    kind: 'exact',
    path: OVERSEAS_ROUTE_PATH,
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
        const payload = await client.getOverseasSnapshot()
        sendJson(res, 200, { ok: true, ...payload })
      } catch (error) {
        const message = error instanceof Error ? error.message : '知识库查询失败'
        sendJson(res, 502, { ok: false, error: message })
      }
    },
  })

  return () => {
    disposeSnapshot()
    disposeOverseas()
  }
}
