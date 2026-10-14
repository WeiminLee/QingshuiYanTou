/**
 * Same-origin evidence route for the browser: GET /qingshui/evidence/<id>
 * proxies to the Knowledge API by exact evidence_id. The API key stays in
 * this host process; the browser never sees it. Requests are refused unless
 * the Host header names this loopback authority (DNS-rebinding fence, same
 * posture as the /api RPC channel) and the browser labels the initiator
 * same-site.
 */
import type { IncomingMessage, ServerResponse } from 'node:http'
import type { KnowledgeClient } from './knowledge-client.ts'

export const EVIDENCE_ROUTE_PATH = '/qingshui/evidence'

const EV_ID_RE = /^EV:[0-9a-fA-F]{6,64}$/

export type EvidenceRouteDeps = {
  client: () => KnowledgeClient | undefined
}

/** Minimal Host/Origin fence mirroring the /api channel's trust posture. */
export function isLoopbackHostRequest(req: IncomingMessage): boolean {
  const host = req.headers.host
  if (typeof host !== 'string' || host === '') return false
  const hostname = host.split(':')[0]?.toLowerCase() ?? ''
  const port = host.includes(':') ? host.slice(host.indexOf(':') + 1) : ''
  // Port sanity: absent, or a plain numeric suffix (bracketed IPv6 forms do
  // not reach loopback hostnames anyway).
  if (port !== '' && !/^\d*$/.test(port)) return false
  if (hostname !== '127.0.0.1' && hostname !== 'localhost' && hostname !== '::1') return false
  const site = req.headers['sec-fetch-site']
  if (typeof site === 'string' && site === 'cross-site') return false
  const origin = req.headers.origin
  if (origin === undefined) return true
  try {
    const parsed = new URL(origin)
    return parsed.host === host
  } catch {
    return false
  }
}

/** @param id - candidate evidence id. @returns whether it is a well-formed EV id. */
export function isValidEvidenceId(id: string): boolean {
  return EV_ID_RE.test(id)
}

function sendJson(res: ServerResponse, status: number, body: Record<string, unknown>): void {
  const payload = JSON.stringify(body)
  res.writeHead(status, {
    'content-type': 'application/json; charset=utf-8',
    'cache-control': 'no-store',
  })
  res.end(payload)
}

/**
 * Install the evidence proxy route on the web server when it is available.
 * @param webCtx - context carrying the webServer service
 * @param deps - knowledge client accessor
 * @returns disposer
 */
export function installEvidenceRoute(
  webCtx: { webServer: { register: (route: { kind: 'exact' | 'prefix'; path: string; handler: (req: IncomingMessage, res: ServerResponse) => Promise<void> | void }) => () => void } },
  deps: EvidenceRouteDeps,
): () => void {
  return webCtx.webServer.register({
    kind: 'prefix',
    path: EVIDENCE_ROUTE_PATH,
    handler: async (req, res): Promise<void> => {
      if (!isLoopbackHostRequest(req)) {
        sendJson(res, 403, { ok: false, error: 'forbidden' })
        return
      }
      const url = req.url ?? '/'
      let id = ''
      try {
        const path = decodeURIComponent(new URL(url, 'http://x').pathname)
        id = path.slice(EVIDENCE_ROUTE_PATH.length).replace(/^\//, '')
      } catch {
        id = ''
      }
      if (!isValidEvidenceId(id)) {
        sendJson(res, 400, { ok: false, error: 'bad evidence id (expected EV:<hex>)' })
        return
      }
      const client = deps.client()
      if (client === undefined) {
        sendJson(res, 503, { ok: false, error: 'knowledge client not configured (missing API key)' })
        return
      }
      try {
        const doc = await client.fetchEvidence(id)
        sendJson(res, 200, { ok: true, doc })
      } catch (error: unknown) {
        const message = error instanceof Error ? error.message : String(error)
        const missing = /Knowledge API 404/.test(message)
        sendJson(res, missing ? 404 : 502, {
          ok: false,
          error: missing ? '证据未命中：该 evidence_id 不存在（短 ID 需以完整 64 位十六进制核验）' : `知识库查询失败：${message.slice(0, 200)}`,
        })
      }
    },
  })
}
