import assert from 'node:assert/strict'
import { test } from 'node:test'
import type { IncomingMessage, ServerResponse } from 'node:http'
import {
  DOCUMENT_ROUTE_PATH,
  PDF_ROUTE_PATH,
  installDocumentRoute,
  installPdfRoute,
} from './document-route.ts'
import type { KnowledgeClient } from './knowledge-client.ts'

type Route = {
  kind: string
  path: string
  handler: (req: IncomingMessage, res: ServerResponse) => Promise<void> | void
}

function capture() {
  const routes: Route[] = []
  const webServer = {
    register(route: Route) {
      routes.push(route)
      return () => { routes.splice(routes.indexOf(route), 1) }
    },
  }
  return { routes, webServer }
}

type FakeRes = {
  status: number
  headers: Record<string, string>
  chunks: Uint8Array[]
  ended: boolean
  body?: Record<string, unknown>
}

function fakeRes(capture: FakeRes): ServerResponse {
  return {
    writeHead(status: number, headers?: Record<string, string>) {
      capture.status = status
      Object.assign(capture.headers, headers ?? {})
    },
    write(chunk: Uint8Array): boolean {
      capture.chunks.push(chunk)
      return true
    },
    end(payload?: string) {
      capture.ended = true
      if (typeof payload === 'string') capture.body = JSON.parse(payload) as Record<string, unknown>
    },
  } as unknown as ServerResponse
}

async function call(
  route: Route,
  url: string,
  headers: Record<string, string | undefined> = { host: '127.0.0.1:8399' },
): Promise<FakeRes> {
  const captured: FakeRes = { status: 0, headers: {}, chunks: [], ended: false }
  await route.handler({ url, headers } as unknown as IncomingMessage, fakeRes(captured))
  return captured
}

function bytesOf(captured: FakeRes): Uint8Array {
  return Buffer.concat(captured.chunks)
}

const DOC = {
  ann_id: '1225468566',
  title: '关于签订日常经营重大合同的公告',
  chapters: [{ evidence_id: 'EV:3fe7ff02', chapter_index: 0, heading: '一、合同概况', chars: 42 }],
  pdf: { exists: true, sha256: null, size: 4 },
}

test('document route registers a prefix and proxies the aggregate', async () => {
  const { routes, webServer } = capture()
  let requested = ''
  installDocumentRoute({ webServer }, {
    client: () => ({
      fetchDocument: async (annId: string) => { requested = annId; return DOC },
    }) as unknown as KnowledgeClient,
  })
  assert.equal(routes[0]?.kind, 'prefix')
  assert.equal(routes[0]?.path, DOCUMENT_ROUTE_PATH)

  const ok = await call(routes[0]!, `${DOCUMENT_ROUTE_PATH}/1225468566`)
  assert.equal(ok.status, 200)
  assert.deepEqual(ok.body, { ok: true, doc: DOC })
  assert.equal(requested, '1225468566')
  assert.equal(ok.headers['content-type'], 'application/json; charset=utf-8')
})

test('document route decodes a percent-encoded ann_id', async () => {
  const { routes, webServer } = capture()
  let requested = ''
  installDocumentRoute({ webServer }, {
    client: () => ({
      fetchDocument: async (annId: string) => { requested = annId; return DOC },
    }) as unknown as KnowledgeClient,
  })
  const ok = await call(routes[0]!, `${DOCUMENT_ROUTE_PATH}/1225%2D468566`)
  assert.equal(ok.status, 200)
  assert.equal(requested, '1225-468566')
})

test('document route fences non-loopback hosts and missing ids', async () => {
  const { routes, webServer } = capture()
  installDocumentRoute({ webServer }, {
    client: () => ({
      fetchDocument: async () => DOC,
    }) as unknown as KnowledgeClient,
  })
  const forbidden = await call(routes[0]!, `${DOCUMENT_ROUTE_PATH}/1225468566`, { host: 'evil.example' })
  assert.equal(forbidden.status, 403)
  assert.equal(forbidden.body?.ok, false)

  const blank = await call(routes[0]!, DOCUMENT_ROUTE_PATH)
  assert.equal(blank.status, 400)
  assert.equal(blank.body?.ok, false)

  const trailing = await call(routes[0]!, `${DOCUMENT_ROUTE_PATH}/`)
  assert.equal(trailing.status, 400)
})

test('document route reports 503 when the client is not configured', async () => {
  const { routes, webServer } = capture()
  installDocumentRoute({ webServer }, { client: () => undefined })
  const notConfigured = await call(routes[0]!, `${DOCUMENT_ROUTE_PATH}/1225468566`)
  assert.equal(notConfigured.status, 503)
  assert.equal(notConfigured.body?.ok, false)
})

test('document route maps upstream 404 to 404 and other failures to 502', async () => {
  const missing = capture()
  installDocumentRoute({ webServer: missing.webServer }, {
    client: () => ({
      fetchDocument: async () => { throw new Error('Knowledge API 404: {"detail":{"code":"document_not_found"}}') },
    }) as unknown as KnowledgeClient,
  })
  const miss = await call(missing.routes[0]!, `${DOCUMENT_ROUTE_PATH}/404404`)
  assert.equal(miss.status, 404)
  assert.equal(miss.body?.ok, false)
  assert.match(String(miss.body?.error), /文档未命中/)

  const down = capture()
  installDocumentRoute({ webServer: down.webServer }, {
    client: () => ({
      fetchDocument: async () => { throw new Error('Knowledge API 503: document_unavailable') },
    }) as unknown as KnowledgeClient,
  })
  const fail = await call(down.routes[0]!, `${DOCUMENT_ROUTE_PATH}/1225468566`)
  assert.equal(fail.status, 502)
  assert.equal(fail.body?.ok, false)
  assert.match(String(fail.body?.error), /document_unavailable/)
})

const PDF_BYTES = new Uint8Array([0x25, 0x50, 0x44, 0x46, 0x2d, 0x31])

test('pdf route forwards Range and passes 206 headers and bytes through', async () => {
  const { routes, webServer } = capture()
  let requested: { annId: string; range?: string } | undefined
  installPdfRoute({ webServer }, {
    client: () => ({
      openDocumentPdf: async (annId: string, range?: string) => {
        requested = { annId, range }
        return new Response(PDF_BYTES, {
          status: 206,
          headers: {
            'content-type': 'application/pdf',
            'content-length': String(PDF_BYTES.byteLength),
            'content-range': `bytes 0-${PDF_BYTES.byteLength - 1}/${PDF_BYTES.byteLength}`,
            'accept-ranges': 'bytes',
            etag: '"abc123"',
            'cache-control': 'private, max-age=86400',
            'x-api-key': 'host-secret',
          },
        })
      },
    }) as unknown as KnowledgeClient,
  })
  assert.equal(routes[0]?.kind, 'prefix')
  assert.equal(routes[0]?.path, PDF_ROUTE_PATH)

  const partial = await call(routes[0]!, `${PDF_ROUTE_PATH}/1225468566`, {
    host: '127.0.0.1:8399',
    range: 'bytes=0-5',
  })
  assert.deepEqual(requested, { annId: '1225468566', range: 'bytes=0-5' })
  assert.equal(partial.status, 206)
  assert.equal(partial.headers['content-type'], 'application/pdf')
  assert.equal(partial.headers['content-range'], `bytes 0-5/${PDF_BYTES.byteLength}`)
  assert.equal(partial.headers['accept-ranges'], 'bytes')
  assert.equal(partial.headers.etag, '"abc123"')
  assert.equal(partial.headers['cache-control'], 'private, max-age=86400')
  assert.equal(partial.headers['content-length'], String(PDF_BYTES.byteLength))
  assert.equal(partial.headers['x-api-key'], undefined)
  assert.deepEqual(bytesOf(partial), Buffer.from(PDF_BYTES))
  assert.equal(partial.ended, true)
})

test('pdf route passes a full 200 response through without a Range header', async () => {
  const { routes, webServer } = capture()
  let requested: { annId: string; range?: string } | undefined
  installPdfRoute({ webServer }, {
    client: () => ({
      openDocumentPdf: async (annId: string, range?: string) => {
        requested = { annId, range }
        return new Response(PDF_BYTES, {
          status: 200,
          headers: { 'content-type': 'application/pdf', 'content-length': String(PDF_BYTES.byteLength) },
        })
      },
    }) as unknown as KnowledgeClient,
  })
  const ok = await call(routes[0]!, `${PDF_ROUTE_PATH}/1225468566`)
  assert.deepEqual(requested, { annId: '1225468566', range: undefined })
  assert.equal(ok.status, 200)
  assert.equal(ok.headers['content-type'], 'application/pdf')
  assert.deepEqual(bytesOf(ok), Buffer.from(PDF_BYTES))
})

test('pdf route preserves upstream 404 and 416 statuses and their bodies', async () => {
  const missing = capture()
  installPdfRoute({ webServer: missing.webServer }, {
    client: () => ({
      openDocumentPdf: async () => new Response(JSON.stringify({ detail: { code: 'pdf_missing' } }), {
        status: 404,
        headers: { 'content-type': 'application/json' },
      }),
    }) as unknown as KnowledgeClient,
  })
  const miss = await call(missing.routes[0]!, `${PDF_ROUTE_PATH}/404404`)
  assert.equal(miss.status, 404)
  assert.equal(miss.headers['content-type'], 'application/json')
  assert.deepEqual(JSON.parse(Buffer.from(bytesOf(miss)).toString()), { detail: { code: 'pdf_missing' } })

  const unsat = capture()
  installPdfRoute({ webServer: unsat.webServer }, {
    client: () => ({
      openDocumentPdf: async () => new Response(JSON.stringify({ detail: { code: 'range_not_satisfiable' } }), {
        status: 416,
        headers: { 'content-type': 'application/json', 'content-range': 'bytes */6', 'accept-ranges': 'bytes' },
      }),
    }) as unknown as KnowledgeClient,
  })
  const rangeMiss = await call(unsat.routes[0]!, `${PDF_ROUTE_PATH}/1225468566`, {
    host: '127.0.0.1:8399',
    range: 'bytes=99-200',
  })
  assert.equal(rangeMiss.status, 416)
  assert.equal(rangeMiss.headers['content-range'], 'bytes */6')
  assert.equal(rangeMiss.headers['accept-ranges'], 'bytes')
})

test('pdf route preserves a bodiless 304', async () => {
  const { routes, webServer } = capture()
  installPdfRoute({ webServer }, {
    client: () => ({
      openDocumentPdf: async () => new Response(null, {
        status: 304,
        headers: { etag: '"abc123"', 'cache-control': 'private, max-age=86400' },
      }),
    }) as unknown as KnowledgeClient,
  })
  const cached = await call(routes[0]!, `${PDF_ROUTE_PATH}/1225468566`, {
    host: '127.0.0.1:8399',
    range: 'bytes=0-5',
  })
  assert.equal(cached.status, 304)
  assert.equal(cached.headers.etag, '"abc123"')
  assert.equal(cached.chunks.length, 0)
  assert.equal(cached.ended, true)
})

test('pdf route fences non-loopback hosts and reports a missing client', async () => {
  const { routes, webServer } = capture()
  installPdfRoute({ webServer }, {
    client: () => ({
      openDocumentPdf: async () => new Response(PDF_BYTES, { status: 200 }),
    }) as unknown as KnowledgeClient,
  })
  const forbidden = await call(routes[0]!, `${PDF_ROUTE_PATH}/1225468566`, { host: 'evil.example' })
  assert.equal(forbidden.status, 403)
  assert.equal(forbidden.body?.ok, false)

  const blank = await call(routes[0]!, `${PDF_ROUTE_PATH}/`)
  assert.equal(blank.status, 400)

  const unconfigured = capture()
  installPdfRoute({ webServer: unconfigured.webServer }, { client: () => undefined })
  const notConfigured = await call(unconfigured.routes[0]!, `${PDF_ROUTE_PATH}/1225468566`)
  assert.equal(notConfigured.status, 503)
  assert.equal(notConfigured.body?.ok, false)
})

test('pdf route wraps client failures as 502', async () => {
  const { routes, webServer } = capture()
  installPdfRoute({ webServer }, {
    client: () => ({
      openDocumentPdf: async () => { throw new Error('Knowledge API unreachable') },
    }) as unknown as KnowledgeClient,
  })
  const fail = await call(routes[0]!, `${PDF_ROUTE_PATH}/1225468566`)
  assert.equal(fail.status, 502)
  assert.equal(fail.body?.ok, false)
  assert.match(String(fail.body?.error), /unreachable/)
})
