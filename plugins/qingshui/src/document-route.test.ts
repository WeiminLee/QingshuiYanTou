import assert from 'node:assert/strict'
import { test } from 'node:test'
import { Writable } from 'node:stream'
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

type Captured = {
  status: number
  headers: Record<string, string>
  chunks: Uint8Array[]
  ended: boolean
  body?: Record<string, unknown>
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

/** JSON-only fake (document route and plain JSON assertions). */
function fakeRes(c: Captured): ServerResponse {
  return {
    writeHead(status: number, headers?: Record<string, string>) {
      c.status = status
      Object.assign(c.headers, headers ?? {})
    },
    write(chunk: Uint8Array): boolean {
      c.chunks.push(chunk)
      return true
    },
    end(payload?: string) {
      c.ended = true
      if (typeof payload === 'string') c.body = JSON.parse(payload) as Record<string, unknown>
    },
  } as unknown as ServerResponse
}

async function call(
  route: Route,
  url: string,
  headers: Record<string, string | undefined> = { host: '127.0.0.1:8399' },
): Promise<Captured> {
  const captured: Captured = { status: 0, headers: {}, chunks: [], ended: false }
  await route.handler({ url, headers } as unknown as IncomingMessage, fakeRes(captured))
  return captured
}

type StreamOptions = {
  highWaterMark?: number
  /** Delay before each write callback (ms), forcing pipeline to wait for 'drain'. */
  writeDelayMs?: number | ((index: number) => number | undefined)
}

/** A real Writable, so `pipeline()` drives it exactly as it drives a ServerResponse. */
function streamRes(c: Captured, options: StreamOptions = {}): { res: ServerResponse; stream: Writable } {
  let writes = 0
  const stream = new Writable({
    highWaterMark: options.highWaterMark ?? 64 * 1024,
    write(chunk: Buffer, _encoding, callback) {
      c.chunks.push(new Uint8Array(chunk))
      const delay = typeof options.writeDelayMs === 'function'
        ? options.writeDelayMs(writes)
        : options.writeDelayMs
      writes += 1
      if (delay === undefined) callback()
      else setTimeout(callback, delay)
    },
    final(callback) {
      c.ended = true
      callback()
    },
  })
  ;(stream as unknown as { writeHead: (status: number, headers?: Record<string, string>) => void }).writeHead = (status, headers) => {
    c.status = status
    Object.assign(c.headers, headers ?? {})
  }
  return { res: stream as unknown as ServerResponse, stream }
}

async function callStream(
  route: Route,
  url: string,
  headers: Record<string, string | undefined> = { host: '127.0.0.1:8399' },
  options: StreamOptions = {},
): Promise<Captured> {
  const captured: Captured = { status: 0, headers: {}, chunks: [], ended: false }
  const { res } = streamRes(captured, options)
  await route.handler({ url, headers } as unknown as IncomingMessage, res)
  return captured
}

function bytesOf(captured: Captured): Buffer {
  return Buffer.concat(captured.chunks)
}

function jsonOf(captured: Captured): unknown {
  return JSON.parse(bytesOf(captured).toString('utf8'))
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

test('document route rejects path-like ann_ids without calling the client', async () => {
  const { routes, webServer } = capture()
  let called = 0
  installDocumentRoute({ webServer }, {
    client: () => ({
      fetchDocument: async () => { called += 1; return DOC },
    }) as unknown as KnowledgeClient,
  })
  // ``%2E%2E`` is normalized away by URL parsing before the id is read; the
  // encoded-slash form is the one that reaches the validator.
  for (const bad of ['a%2Fb', 'a%5Cb', 'a%2F..%2Fb', 'a%2E%2Eb']) {
    const rejected = await call(routes[0]!, `${DOCUMENT_ROUTE_PATH}/${bad}`)
    assert.equal(rejected.status, 400, bad)
    assert.deepEqual(rejected.body, { ok: false, error: 'bad ann_id' }, bad)
  }
  assert.equal(called, 0)
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

function pdfRoute(respond: (annId: string, range?: string) => Promise<Response>, log?: (message: string) => void): Route {
  const { routes, webServer } = capture()
  installPdfRoute({ webServer }, {
    client: () => ({ openDocumentPdf: respond }) as unknown as KnowledgeClient,
    ...(log === undefined ? {} : { log }),
  })
  return routes[0]!
}

test('pdf route forwards Range and passes 206 headers and bytes through', async () => {
  let requested: { annId: string; range?: string } | undefined
  const route = pdfRoute(async (annId, range) => {
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
        'content-disposition': 'inline',
        'x-api-key': 'host-secret',
      },
    })
  })
  assert.equal(route.kind, 'prefix')
  assert.equal(route.path, PDF_ROUTE_PATH)

  const partial = await callStream(route, `${PDF_ROUTE_PATH}/1225468566`, {
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
  assert.equal(partial.headers['content-disposition'], 'inline')
  assert.equal(partial.headers['x-api-key'], undefined)
  assert.deepEqual(bytesOf(partial), Buffer.from(PDF_BYTES))
  assert.equal(partial.ended, true)
})

test('pdf route passes a full 200 response through without a Range header', async () => {
  let requested: { annId: string; range?: string } | undefined
  const route = pdfRoute(async (annId, range) => {
    requested = { annId, range }
    return new Response(PDF_BYTES, {
      status: 200,
      headers: { 'content-type': 'application/pdf', 'content-length': String(PDF_BYTES.byteLength) },
    })
  })
  const ok = await callStream(route, `${PDF_ROUTE_PATH}/1225468566`)
  assert.deepEqual(requested, { annId: '1225468566', range: undefined })
  assert.equal(ok.status, 200)
  assert.equal(ok.headers['content-type'], 'application/pdf')
  assert.deepEqual(bytesOf(ok), Buffer.from(PDF_BYTES))
})

test('pdf route preserves upstream 404 and 416 statuses and their bodies', async () => {
  const missing = pdfRoute(async () => new Response(JSON.stringify({ detail: { code: 'pdf_missing' } }), {
    status: 404,
    headers: { 'content-type': 'application/json' },
  }))
  const miss = await callStream(missing, `${PDF_ROUTE_PATH}/404404`)
  assert.equal(miss.status, 404)
  assert.equal(miss.headers['content-type'], 'application/json')
  assert.deepEqual(jsonOf(miss), { detail: { code: 'pdf_missing' } })

  const unsat = pdfRoute(async () => new Response(JSON.stringify({ detail: { code: 'range_not_satisfiable' } }), {
    status: 416,
    headers: { 'content-type': 'application/json', 'content-range': 'bytes */6', 'accept-ranges': 'bytes' },
  }))
  const rangeMiss = await callStream(unsat, `${PDF_ROUTE_PATH}/1225468566`, {
    host: '127.0.0.1:8399',
    range: 'bytes=99-200',
  })
  assert.equal(rangeMiss.status, 416)
  assert.equal(rangeMiss.headers['content-range'], 'bytes */6')
  assert.equal(rangeMiss.headers['accept-ranges'], 'bytes')
})

test('pdf route preserves a bodiless 304', async () => {
  const route = pdfRoute(async () => new Response(null, {
    status: 304,
    headers: { etag: '"abc123"', 'cache-control': 'private, max-age=86400' },
  }))
  const cached = await callStream(route, `${PDF_ROUTE_PATH}/1225468566`, {
    host: '127.0.0.1:8399',
    range: 'bytes=0-5',
  })
  assert.equal(cached.status, 304)
  assert.equal(cached.headers.etag, '"abc123"')
  assert.equal(cached.chunks.length, 0)
  assert.equal(cached.ended, true)
})

test('pdf route streams a multi-chunk body without coalescing or loss', async () => {
  const chunks = [new Uint8Array([1]), new Uint8Array([2, 3]), new Uint8Array([4, 5, 6])]
  const route = pdfRoute(async () => new Response(new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(chunk)
      controller.close()
    },
  }), { status: 200, headers: { 'content-type': 'application/pdf' } }))
  const ok = await callStream(route, `${PDF_ROUTE_PATH}/1225468566`)
  assert.equal(ok.status, 200)
  assert.equal(ok.chunks.length, chunks.length)
  assert.deepEqual(bytesOf(ok), Buffer.concat(chunks.map(chunk => Buffer.from(chunk))))
  assert.equal(ok.ended, true)
})

test('pdf route honours write backpressure and still delivers every chunk', { timeout: 5000 }, async () => {
  const chunks = [new Uint8Array([1, 1]), new Uint8Array([2, 2]), new Uint8Array([3, 3])]
  const route = pdfRoute(async () => new Response(new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(chunk)
      controller.close()
    },
  }), { status: 200 }))
  // highWaterMark 1 with a delayed callback makes the first write return false,
  // so pipeline has to wait for 'drain' before the rest flow.
  const ok = await callStream(route, `${PDF_ROUTE_PATH}/1225468566`, { host: '127.0.0.1:8399' }, {
    highWaterMark: 1,
    writeDelayMs: 5,
  })
  assert.equal(ok.chunks.length, chunks.length)
  assert.deepEqual(bytesOf(ok), Buffer.concat(chunks.map(chunk => Buffer.from(chunk))))
  assert.equal(ok.ended, true)
})

test('pdf route settles and stops reading upstream when the body errors mid-stream', { timeout: 5000 }, async () => {
  let pulls = 0
  const logs: string[] = []
  const route = pdfRoute(async () => new Response(new ReadableStream<Uint8Array>({
    pull(controller) {
      pulls += 1
      if (pulls === 1) {
        controller.enqueue(new Uint8Array([1, 2, 3]))
        return
      }
      controller.error(new Error('upstream body failed at /data/qingshui/pdf/x.pdf'))
    },
  }), { status: 200 }), message => logs.push(message))

  const ok = await callStream(route, `${PDF_ROUTE_PATH}/1225468566`)
  assert.equal(ok.status, 200)
  assert.equal(logs.length, 1)
  assert.doesNotMatch(logs[0]!, /\/data|\.pdf|qingshui\/pdf|ann_id|1225468566/)
  assert.match(logs[0]!, /qingshui: pdf proxy stream failed/)
  // The handler settled and no further reads are issued against the errored stream.
  const settledPulls = pulls
  await new Promise(resolve => setTimeout(resolve, 20))
  assert.equal(pulls, settledPulls)
})

test('pdf route settles and cancels upstream when the client closes before drain', { timeout: 5000 }, async () => {
  let cancelled = false
  const body = new ReadableStream<Uint8Array>({
    pull(controller) { controller.enqueue(new Uint8Array(1024)) },
    cancel() { cancelled = true },
  })
  const logs: string[] = []
  const route = pdfRoute(async () => new Response(body, { status: 200 }), message => logs.push(message))

  const captured: Captured = { status: 0, headers: {}, chunks: [], ended: false }
  const { res, stream } = streamRes(captured, { highWaterMark: 1, writeDelayMs: 50 })
  const pending = route.handler(
    { url: `${PDF_ROUTE_PATH}/1225468566`, headers: { host: '127.0.0.1:8399' } } as unknown as IncomingMessage,
    res,
  )
  // The client drops while a write is still pending: 'drain' will never fire.
  setTimeout(() => stream.destroy(), 10)
  await pending
  assert.equal(cancelled, true)
  assert.equal(captured.ended, false)
  assert.equal(logs.length, 1)
  assert.match(logs[0]!, /qingshui: pdf proxy stream failed/)
})

test('pdf route fences non-loopback hosts, path-like ids, and reports a missing client', async () => {
  let called = 0
  const route = pdfRoute(async () => {
    called += 1
    return new Response(PDF_BYTES, { status: 200 })
  })
  const forbidden = await callStream(route, `${PDF_ROUTE_PATH}/1225468566`, { host: 'evil.example' })
  assert.equal(forbidden.status, 403)
  assert.deepEqual(jsonOf(forbidden), { ok: false, error: 'forbidden' })

  const blank = await callStream(route, `${PDF_ROUTE_PATH}/`)
  assert.equal(blank.status, 400)

  for (const bad of ['a%2Fb', 'a%5Cb', 'a%2F..%2Fb']) {
    const rejected = await callStream(route, `${PDF_ROUTE_PATH}/${bad}`)
    assert.equal(rejected.status, 400, bad)
    assert.deepEqual(jsonOf(rejected), { ok: false, error: 'bad ann_id' }, bad)
  }
  assert.equal(called, 0)

  const { routes, webServer } = capture()
  installPdfRoute({ webServer }, { client: () => undefined })
  const notConfigured = await callStream(routes[0]!, `${PDF_ROUTE_PATH}/1225468566`)
  assert.equal(notConfigured.status, 503)
  assert.equal((jsonOf(notConfigured) as { ok?: unknown }).ok, false)
})

test('pdf route wraps client failures as 502', async () => {
  const route = pdfRoute(async () => { throw new Error('Knowledge API unreachable') })
  const fail = await callStream(route, `${PDF_ROUTE_PATH}/1225468566`)
  assert.equal(fail.status, 502)
  const body = jsonOf(fail) as { ok?: unknown; error?: unknown }
  assert.equal(body.ok, false)
  assert.match(String(body.error), /unreachable/)
})
