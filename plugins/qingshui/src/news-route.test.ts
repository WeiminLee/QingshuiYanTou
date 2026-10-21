import assert from 'node:assert/strict'
import { test } from 'node:test'
import type { IncomingMessage, ServerResponse } from 'node:http'
import { installNewsRoute, NEWS_ROUTE_PATH } from './news-route.ts'
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

test('news route returns shaped telegraph rows', async () => {
  const { routes, webServer } = capture()
  installNewsRoute({ webServer }, {
    client: () => ({
      listRecentEvents: async () => ({
        items: [{ event_id: 'EV:abc', title: '存储芯片局部异动', source: 'tushare', publish_at: '2026-10-19 01:41:00+00:00' }],
      }),
    }) as unknown as KnowledgeClient,
  })
  assert.equal(routes[0]?.path, NEWS_ROUTE_PATH)
  const ok = await call(routes[0]!)
  assert.equal(ok.status, 200)
  const items = ok.body?.items as Array<{ source: string; title: string }>
  assert.equal(items[0]?.source, '财联社')
  assert.equal(items[0]?.title, '存储芯片局部异动')
})

test('news route refuses a non-loopback host', async () => {
  const { routes, webServer } = capture()
  installNewsRoute({ webServer }, {
    client: () => ({ listRecentEvents: async () => ({ items: [] }) }) as unknown as KnowledgeClient,
  })
  const denied = await call(routes[0]!, 'evil.example')
  assert.equal(denied.status, 403)
})
