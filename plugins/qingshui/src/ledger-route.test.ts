import assert from 'node:assert/strict'
import { test } from 'node:test'
import type { IncomingMessage, ServerResponse } from 'node:http'
import { installLedgerRoute, LEDGER_ROUTE_PATH } from './ledger-route.ts'
import type { KnowledgeClient } from './knowledge-client.ts'

function capture() {
  const routes: Array<{ kind: string; path: string; handler: (req: IncomingMessage, res: ServerResponse) => Promise<void> | void }> = []
  const webServer = {
    register(route: typeof routes[number]) {
      routes.push(route)
      return () => { routes.splice(routes.indexOf(route), 1) }
    },
  }
  return { routes, webServer }
}

async function call(handler: { handler: (req: IncomingMessage, res: ServerResponse) => Promise<void> | void }, host = '127.0.0.1:8399') {
  const captureBody: { status: number; body?: Record<string, unknown> } = { status: 0 }
  const res = {
    writeHead(status: number) { captureBody.status = status },
    end(payload?: string) { captureBody.body = payload === undefined ? undefined : JSON.parse(payload) as Record<string, unknown> },
  }
  await handler.handler({ headers: { host } } as IncomingMessage, res as unknown as ServerResponse)
  return captureBody
}

test('ledger route returns findings through the ledger search', async () => {
  const { routes, webServer } = capture()
  let requested: { limit?: number } | undefined
  installLedgerRoute({ webServer }, {
    client: () => ({
      searchFindings: async (input?: { limit?: number }) => { requested = input; return { items: [{ finding_id: 'f1' }], count: 1 } },
    }) as unknown as KnowledgeClient,
  })
  assert.equal(routes[0]?.path, LEDGER_ROUTE_PATH)
  const ok = await call(routes[0]!)
  assert.equal(ok.status, 200)
  assert.equal(ok.body?.ok, true)
  assert.equal(ok.body?.count, 1)
})

test('ledger route reports 503 when the client is not configured', async () => {
  const { routes, webServer } = capture()
  installLedgerRoute({ webServer }, { client: () => undefined })
  const notConfigured = await call(routes[0]!)
  assert.equal(notConfigured.status, 503)
  assert.equal(notConfigured.body?.ok, false)
})

test('ledger route reports 502 when the search fails', async () => {
  const { routes, webServer } = capture()
  installLedgerRoute({ webServer }, {
    client: () => ({ searchFindings: async () => { throw new Error('Knowledge API 500: down') } }) as unknown as KnowledgeClient,
  })
  const down = await call(routes[0]!)
  assert.equal(down.status, 502)
  assert.equal(down.body?.ok, false)
  assert.ok(String(down.body?.error).includes('down'))
})

test('ledger route refuses a non-loopback host', async () => {
  const { routes, webServer } = capture()
  installLedgerRoute({ webServer }, {
    client: () => ({ searchFindings: async () => ({ items: [], count: 0 }) }) as unknown as KnowledgeClient,
  })
  const denied = await call(routes[0]!, 'evil.example')
  assert.equal(denied.status, 403)
})
