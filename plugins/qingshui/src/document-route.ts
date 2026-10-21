/**
 * Same-origin artifact routes for the browser:
 *   GET /qingshui/document/<ann_id> — aggregate document view (chapters, no bodies)
 *   GET /qingshui/pdf/<ann_id>      — the retained PDF, byte-for-byte
 * Both proxy the Knowledge API with the host-side API key, so the browser never
 * sees it. Loopback-fenced like the other /qingshui routes. The PDF route
 * forwards Range and copies the upstream status/headers through untouched, so
 * pdf.js sees 200/206/304/404/416 exactly as the backend produced them.
 */
import { Readable } from 'node:stream'
import { once } from 'node:events'
import type { IncomingMessage, ServerResponse } from 'node:http'
import type { KnowledgeClient } from './knowledge-client.ts'
import { isLoopbackHostRequest } from './ev-route.ts'

export const DOCUMENT_ROUTE_PATH = '/qingshui/document'
export const PDF_ROUTE_PATH = '/qingshui/pdf'

export type DocumentRouteDeps = {
  client: () => KnowledgeClient | undefined
}

/** Upstream response headers the browser is allowed to see, verbatim. */
const PDF_PASSTHROUGH_HEADERS = [
  'content-type',
  'content-length',
  'content-range',
  'accept-ranges',
  'etag',
  'cache-control',
] as const

function sendJson(res: ServerResponse, status: number, body: Record<string, unknown>): void {
  res.writeHead(status, {
    'content-type': 'application/json; charset=utf-8',
    'cache-control': 'no-store',
  })
  res.end(JSON.stringify(body))
}

/** @returns the decoded ann_id tail of a prefix path, or '' when absent/malformed. */
function annIdFrom(url: string, prefix: string): string {
  try {
    const path = decodeURIComponent(new URL(url, 'http://x').pathname)
    return path.slice(prefix.length).replace(/^\//, '')
  } catch {
    return ''
  }
}

function requestRange(req: IncomingMessage): string | undefined {
  const range = req.headers.range
  const value = Array.isArray(range) ? range[0] : range
  return typeof value === 'string' && value !== '' ? value : undefined
}

/**
 * Install the document aggregate proxy. @param webCtx - web server. @param deps - client accessor.
 * @returns disposer.
 */
export function installDocumentRoute(
  webCtx: { webServer: { register: (route: { kind: 'exact' | 'prefix'; path: string; handler: (req: IncomingMessage, res: ServerResponse) => Promise<void> | void }) => () => void } },
  deps: DocumentRouteDeps,
): () => void {
  return webCtx.webServer.register({
    kind: 'prefix',
    path: DOCUMENT_ROUTE_PATH,
    handler: async (req, res): Promise<void> => {
      if (!isLoopbackHostRequest(req)) {
        sendJson(res, 403, { ok: false, error: 'forbidden' })
        return
      }
      const annId = annIdFrom(req.url ?? '/', DOCUMENT_ROUTE_PATH)
      if (annId === '') {
        sendJson(res, 400, { ok: false, error: 'missing ann_id' })
        return
      }
      const client = deps.client()
      if (client === undefined) {
        sendJson(res, 503, { ok: false, error: 'knowledge client not configured (missing API key)' })
        return
      }
      try {
        const doc = await client.fetchDocument(annId)
        sendJson(res, 200, { ok: true, doc })
      } catch (error: unknown) {
        const message = error instanceof Error ? error.message : String(error)
        const missing = /Knowledge API 404/.test(message)
        sendJson(res, missing ? 404 : 502, {
          ok: false,
          error: missing ? '文档未命中：该 ann_id 不存在' : `文档查询失败：${message.slice(0, 200)}`,
        })
      }
    },
  })
}

/**
 * Install the PDF streaming proxy. @param webCtx - web server. @param deps - client accessor.
 * @returns disposer.
 */
export function installPdfRoute(
  webCtx: { webServer: { register: (route: { kind: 'exact' | 'prefix'; path: string; handler: (req: IncomingMessage, res: ServerResponse) => Promise<void> | void }) => () => void } },
  deps: DocumentRouteDeps,
): () => void {
  return webCtx.webServer.register({
    kind: 'prefix',
    path: PDF_ROUTE_PATH,
    handler: async (req, res): Promise<void> => {
      if (!isLoopbackHostRequest(req)) {
        sendJson(res, 403, { ok: false, error: 'forbidden' })
        return
      }
      const annId = annIdFrom(req.url ?? '/', PDF_ROUTE_PATH)
      if (annId === '') {
        sendJson(res, 400, { ok: false, error: 'missing ann_id' })
        return
      }
      const client = deps.client()
      if (client === undefined) {
        sendJson(res, 503, { ok: false, error: 'knowledge client not configured (missing API key)' })
        return
      }

      let upstream: Response
      try {
        upstream = await client.openDocumentPdf(annId, requestRange(req))
      } catch (error: unknown) {
        const message = error instanceof Error ? error.message : String(error)
        sendJson(res, 502, { ok: false, error: `PDF 获取失败：${message.slice(0, 200)}` })
        return
      }

      const headers: Record<string, string> = {}
      for (const name of PDF_PASSTHROUGH_HEADERS) {
        const value = upstream.headers.get(name)
        if (value !== null) headers[name] = value
      }
      res.writeHead(upstream.status, headers)

      if (upstream.body === null) {
        res.end()
        return
      }
      try {
        const stream = Readable.fromWeb(upstream.body as Parameters<typeof Readable.fromWeb>[0])
        for await (const chunk of stream) {
          if (res.write(chunk as Uint8Array) === false) await once(res, 'drain')
        }
      } catch {
        // The browser went away mid-stream (or the upstream aborted): there is
        // no status left to report, only the truncated response to close.
      }
      if (!res.writableEnded && !res.destroyed) res.end()
    },
  })
}
