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
import { pipeline } from 'node:stream/promises'
import type { IncomingMessage, ServerResponse } from 'node:http'
import type { KnowledgeClient } from './knowledge-client.ts'
import { isLoopbackHostRequest } from './ev-route.ts'

export const DOCUMENT_ROUTE_PATH = '/qingshui/document'
export const PDF_ROUTE_PATH = '/qingshui/pdf'

export type DocumentRouteDeps = {
  client: () => KnowledgeClient | undefined
  /**
   * Host-side diagnostics sink (defaults to console.warn). Messages never carry
   * a path, ann_id, or body content — only an error code/name.
   */
  log?: (message: string) => void
}

/** Upstream response headers the browser is allowed to see, verbatim. */
const PDF_PASSTHROUGH_HEADERS = [
  'content-type',
  'content-length',
  'content-range',
  'accept-ranges',
  'etag',
  'cache-control',
  'content-disposition',
] as const

/** Defense in depth: an ann_id is a flat key, never a path fragment. */
const BAD_ANN_ID_RE = /[/\\]|\.\./

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

/** Send the 400 for an unusable id. @returns true when the request was answered. */
function rejectBadAnnId(res: ServerResponse, annId: string): boolean {
  if (annId === '') {
    sendJson(res, 400, { ok: false, error: 'missing ann_id' })
    return true
  }
  if (BAD_ANN_ID_RE.test(annId)) {
    sendJson(res, 400, { ok: false, error: 'bad ann_id' })
    return true
  }
  return false
}

/** A log-safe error label: code when present, else the class name. */
function errorLabel(error: unknown): string {
  const code = (error as { code?: unknown } | null)?.code
  if (typeof code === 'string' && code !== '') return code
  return error instanceof Error && error.name !== '' ? error.name : 'unknown'
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
      if (rejectBadAnnId(res, annId)) return
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
      if (rejectBadAnnId(res, annId)) return
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

      const log = deps.log ?? ((message: string): void => { console.warn(message) })
      try {
        res.writeHead(upstream.status, headers)
        if (upstream.body === null) {
          res.end()
          return
        }
        // pipeline owns both ends from here: it honours backpressure, and on
        // any failure (upstream error, client 'close' before 'drain') it
        // destroys the transformed stream and the destination, which in turn
        // cancels the undici body. No backend connection is left dangling.
        await pipeline(Readable.fromWeb(upstream.body as Parameters<typeof Readable.fromWeb>[0]), res)
      } catch (error: unknown) {
        // The browser went away mid-stream (or the upstream aborted): there is
        // no status left to report. Diagnostics stay host-side and carry no
        // path or body content.
        await upstream.body?.cancel().catch(() => {})
        log(`qingshui: pdf proxy stream failed (${errorLabel(error)})`)
        if (!res.writableEnded && !res.destroyed) res.end()
      }
    },
  })
}
