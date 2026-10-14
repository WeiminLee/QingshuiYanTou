import { strict as assert } from 'node:assert'
import { test } from 'node:test'
import type { IncomingMessage, ServerResponse } from 'node:http'
import { EVIDENCE_ROUTE_PATH, installEvidenceRoute, isLoopbackHostRequest, isValidEvidenceId } from './ev-route.ts'
import type { KnowledgeClient } from './knowledge-client.ts'

type FakeReq = IncomingMessage & { url: string; headers: Record<string, string | string[] | undefined> }
type FakeRes = { status: number; body: Record<string, unknown> | undefined }

function fakeRes(capture: FakeRes): ServerResponse {
  const res = {
    writeHead(status: number) { capture.status = status },
    end(payload?: string) {
      capture.body = payload === undefined ? undefined : JSON.parse(payload) as Record<string, unknown>
    },
    headersSent: false,
  }
  return res as unknown as ServerResponse
}

function fakeClient(doc: Record<string, unknown> | Error): () => KnowledgeClient {
  return () => ({
    async fetchEvidence(): Promise<Record<string, unknown>> {
      if (doc instanceof Error) throw doc
      return doc
    },
  }) as unknown as () => KnowledgeClient
}

async function callRoute(
  handler: { kind: string; path: string; handler: (req: FakeReq, res: ServerResponse) => Promise<void> | void },
  url: string,
  headers: Record<string, string> = { host: '127.0.0.1:8399' },
): Promise<FakeRes> {
  const capture: FakeRes = { status: 0, body: undefined }
  const req = { url, headers } as FakeReq
  await handler.handler(req, fakeRes(capture))
  return capture
}

function captureRegister(): { routes: Array<ReturnType<typeof makeRoute>>; webServer: object } {
  const routes: Array<ReturnType<typeof makeRoute>> = []
  function makeRoute(route: { kind: 'exact' | 'prefix'; path: string; handler: (req: FakeReq, res: ServerResponse) => Promise<void> | void }): { kind: 'exact' | 'prefix'; path: string; handler: (req: FakeReq, res: ServerResponse) => Promise<void> | void } {
    return route
  }
  return {
    routes,
    webServer: {
      register(route: ReturnType<typeof makeRoute>): () => void {
        routes.push(route)
        return () => { const idx = routes.indexOf(route); if (idx >= 0) routes.splice(idx, 1) }
      },
    },
  }
}

const DOC = { evidence_id: 'EV:c2162ae848cc32706670f57a4af482e73b7518901ef522833b03248babb8c422', text_excerpt: '隆基绿能2025年年报' }

test('isValidEvidenceId accepts EV hex ids, rejects others', () => {
  assert.equal(isValidEvidenceId('EV:3fe7ff02'), true)
  assert.equal(isValidEvidenceId('EV:c2162ae848cc32706670f57a4af482e73b7518901ef522833b03248babb8c422'), true)
  assert.equal(isValidEvidenceId('EV:abc'), false)
  assert.equal(isValidEvidenceId('../../etc/passwd'), false)
  assert.equal(isValidEvidenceId('FD:abcdef'), false)
})

test('isLoopbackHostRequest enforces loopback Host and same-site fetch', () => {
  assert.equal(isLoopbackHostRequest({ headers: { host: '127.0.0.1:8399' } } as IncomingMessage), true)
  assert.equal(isLoopbackHostRequest({ headers: { host: 'localhost:8399' } } as IncomingMessage), true)
  assert.equal(isLoopbackHostRequest({ headers: { host: 'evil.example.com' } } as IncomingMessage), false)
  assert.equal(isLoopbackHostRequest({ headers: { host: '127.0.0.1:8399', 'sec-fetch-site': 'cross-site' } } as IncomingMessage), false)
  assert.equal(isLoopbackHostRequest({ headers: { host: '127.0.0.1:8399', origin: 'http://evil.example' } } as IncomingMessage), false)
  assert.equal(isLoopbackHostRequest({ headers: { host: '127.0.0.1:8399', origin: 'http://127.0.0.1:8399' } } as IncomingMessage), true)
})

test('installEvidenceRoute registers a prefix route and answers lookups', async () => {
  const { routes, webServer } = captureRegister()
  const dispose = installEvidenceRoute({ webServer }, { client: fakeClient(DOC) })
  assert.equal(routes.length, 1)
  assert.equal(routes[0]?.kind, 'prefix')
  assert.equal(routes[0]?.path, EVIDENCE_ROUTE_PATH)

  const ok = await callRoute(routes[0]!, `${EVIDENCE_ROUTE_PATH}/EV:3fe7ff02`)
  assert.equal(ok.status, 200)
  assert.equal(ok.body?.ok, true)
  assert.deepEqual(ok.body?.doc, DOC)
  dispose()
  assert.equal(routes.length, 0)
})

test('route refuses non-loopback, bad ids, and missing client', async () => {
  const { routes, webServer } = captureRegister()
  installEvidenceRoute({ webServer }, { client: fakeClient(DOC) })
  const route = routes[0]!

  const forbidden = await callRoute(route, `${EVIDENCE_ROUTE_PATH}/EV:3fe7ff02`, { host: 'evil.example' })
  assert.equal(forbidden.status, 403)

  const bad = await callRoute(route, `${EVIDENCE_ROUTE_PATH}/not-an-id`)
  assert.equal(bad.status, 400)

  const { webServer: ws2, routes: routes2 } = captureRegister()
  installEvidenceRoute({ webServer: ws2 }, { client: () => undefined })
  const unconfigured = await callRoute(routes2[0]!, `${EVIDENCE_ROUTE_PATH}/EV:3fe7ff02`)
  assert.equal(unconfigured.status, 503)
})

test('route maps 404 knowledge misses and upstream failures', async () => {
  const { routes, webServer } = captureRegister()
  installEvidenceRoute({ webServer }, {
    client: fakeClient(new Error('Knowledge API 404: missing')),
  })
  const miss = await callRoute(routes[0]!, `${EVIDENCE_ROUTE_PATH}/EV:3fe7ff02`)
  assert.equal(miss.status, 404)
  assert.match(String(miss.body?.error), /证据未命中/)

  const { webServer: ws2, routes: routes2 } = captureRegister()
  installEvidenceRoute({ webServer: ws2 }, {
    client: fakeClient(new Error('Knowledge API 500: boom')),
  })
  const fail = await callRoute(routes2[0]!, `${EVIDENCE_ROUTE_PATH}/EV:3fe7ff02`)
  assert.equal(fail.status, 502)
  assert.match(String(fail.body?.error), /知识库查询失败/)
})
