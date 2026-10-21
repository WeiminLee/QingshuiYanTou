import assert from 'node:assert/strict'
import { test } from 'node:test'
import type { IncomingMessage, ServerResponse } from 'node:http'
import { installHealthRoute, HEALTH_ROUTE_PATH } from './health-route.ts'
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

test('health route reports ok when the Knowledge API /health answers', async () => {
  const { routes, webServer } = capture()
  let probed = 0
  installHealthRoute({ webServer }, {
    client: () => ({ health: async () => { probed += 1; return { status: 'ok' } } }) as unknown as KnowledgeClient,
  })
  assert.equal(routes[0]?.path, HEALTH_ROUTE_PATH)
  const ok = await call(routes[0]!)
  assert.equal(ok.status, 200)
  assert.equal(ok.body?.ok, true)
  assert.equal(probed, 1)
})

test('health route reports 503 when the client is not configured', async () => {
  const { routes, webServer } = capture()
  installHealthRoute({ webServer }, { client: () => undefined })
  const notConfigured = await call(routes[0]!)
  assert.equal(notConfigured.status, 503)
  assert.equal(notConfigured.body?.ok, false)
})

test('health route reports 502 when the probe fails', async () => {
  const { routes, webServer } = capture()
  installHealthRoute({ webServer }, {
    client: () => ({ health: async () => { throw new Error('Knowledge API 500: down') } }) as unknown as KnowledgeClient,
  })
  const down = await call(routes[0]!)
  assert.equal(down.status, 502)
  assert.equal(down.body?.ok, false)
  assert.ok(String(down.body?.error).includes('down'))
})

test('health route refuses a non-loopback host', async () => {
  const { routes, webServer } = capture()
  installHealthRoute({ webServer }, {
    client: () => ({ health: async () => ({ status: 'ok' }) }) as unknown as KnowledgeClient,
  })
  const denied = await call(routes[0]!, 'evil.example')
  assert.equal(denied.status, 403)
})
