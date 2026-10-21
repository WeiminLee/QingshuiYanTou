/**
 * Same-origin data-plane liveness: GET /qingshui/health probes the Knowledge
 * API /health through the host (SSH tunnel), so the browser can surface a
 * silent tunnel drop without ever seeing the API key. Loopback-fenced like
 * the other /qingshui/* routes.
 */
import type { IncomingMessage, ServerResponse } from 'node:http'
import type { KnowledgeClient } from './knowledge-client.ts'
import { isLoopbackHostRequest } from './ev-route.ts'

export const HEALTH_ROUTE_PATH = '/qingshui/health'

export type HealthRouteDeps = {
  client: () => KnowledgeClient | undefined
}

function sendJson(res: ServerResponse, status: number, body: Record<string, unknown>): void {
  res.writeHead(status, {
    'content-type': 'application/json; charset=utf-8',
    'cache-control': 'no-store',
  })
  res.end(JSON.stringify(body))
}

export function installHealthRoute(
  webCtx: { webServer: { register: (route: { kind: 'exact' | 'prefix'; path: string; handler: (req: IncomingMessage, res: ServerResponse) => Promise<void> | void }) => () => void } },
  deps: HealthRouteDeps,
): () => void {
  return webCtx.webServer.register({
    kind: 'exact',
    path: HEALTH_ROUTE_PATH,
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
        await client.health()
        sendJson(res, 200, { ok: true })
      } catch (error) {
        const message = error instanceof Error ? error.message : '知识库不可达'
        sendJson(res, 502, { ok: false, error: message })
      }
    },
  })
}
