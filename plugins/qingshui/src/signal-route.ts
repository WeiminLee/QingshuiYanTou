/**
 * Same-origin signal desk: GET /qingshui/signals
 * proxies four processed-signal lanes. The API key stays on the host.
 */
import type { IncomingMessage, ServerResponse } from 'node:http'
import type { KnowledgeClient } from './knowledge-client.ts'
import { isLoopbackHostRequest } from './ev-route.ts'
import { loadSignalBoard } from './signal-board.ts'

export const SIGNAL_ROUTE_PATH = '/qingshui/signals'

export type SignalRouteDeps = {
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
 * Install the signal proxy. @param webCtx - web server. @param deps - client accessor.
 * @returns disposer.
 */
export function installSignalRoute(
  webCtx: { webServer: { register: (route: { kind: 'exact' | 'prefix'; path: string; handler: (req: IncomingMessage, res: ServerResponse) => Promise<void> | void }) => () => void } },
  deps: SignalRouteDeps,
): () => void {
  return webCtx.webServer.register({
    kind: 'exact',
    path: SIGNAL_ROUTE_PATH,
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
        const lanes = await loadSignalBoard((sourceType, limit) => client.listSignals({ sourceType, limit }))
        sendJson(res, 200, { ok: true, lanes })
      } catch (error) {
        const message = error instanceof Error ? error.message : '知识库查询失败'
        sendJson(res, 502, { ok: false, error: message })
      }
    },
  })
}
