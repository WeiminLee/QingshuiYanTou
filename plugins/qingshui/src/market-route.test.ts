import assert from 'node:assert/strict'
import { test } from 'node:test'
import type { IncomingMessage, ServerResponse } from 'node:http'
import { installMarketRoute, OVERSEAS_ROUTE_PATH, SNAPSHOT_ROUTE_PATH } from './market-route.ts'
import type { KnowledgeClient } from './knowledge-client.ts'

const SNAPSHOT = {
  trade_date: '20261016',
  indices: [{ ts_code: '000001.SH', name: '上证综合指数', close: 3716.2842, pct_chg: 0.2376 }],
}

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

async function call(handler: typeof capture extends never ? never : { handler: (req: IncomingMessage, res: ServerResponse) => Promise<void> | void }, host = '127.0.0.1:8399') {
  const captureBody: { status: number; body?: Record<string, unknown> } = { status: 0 }
  const res = {
    writeHead(status: number) { captureBody.status = status },
    end(payload?: string) { captureBody.body = payload === undefined ? undefined : JSON.parse(payload) as Record<string, unknown> },
  }
  await handler.handler({ headers: { host } } as IncomingMessage, res as unknown as ServerResponse)
  return captureBody
}

test('market route returns the Shanghai quote', async () => {
  const { routes, webServer } = capture()
  installMarketRoute({ webServer }, {
    client: () => ({ getMarketSnapshot: async () => SNAPSHOT }) as unknown as KnowledgeClient,
  })
  assert.equal(routes[0]?.path, SNAPSHOT_ROUTE_PATH)
  const ok = await call(routes[0]!)
  assert.equal(ok.status, 200)
  assert.equal((ok.body?.quote as { close: string }).close, '3716.28')
  const quotes = ok.body?.quotes as Array<{ label: string; direction: string }>
  assert.equal(quotes.length, 4)
  assert.equal(quotes[0]?.label, '上证')
  assert.equal(quotes[2]?.direction, 'absent')
})

test('market route refuses a non-loopback host', async () => {
  const { routes, webServer } = capture()
  installMarketRoute({ webServer }, {
    client: () => ({ getMarketSnapshot: async () => SNAPSHOT }) as unknown as KnowledgeClient,
  })
  const denied = await call(routes[0]!, 'evil.example')
  assert.equal(denied.status, 403)
})

test('overseas route proxies the overseas snapshot', async () => {
  const { routes, webServer } = capture()
  const payload = { as_of: '20261030', markets: [{ market: 'US', name: '美股', pct_chg: 0.8, symbols: [] }] }
  installMarketRoute({ webServer }, {
    client: () => ({
      getMarketSnapshot: async () => SNAPSHOT,
      getOverseasSnapshot: async () => payload,
    }) as unknown as KnowledgeClient,
  })
  const route = routes.find(item => item.path === OVERSEAS_ROUTE_PATH)
  assert.ok(route)
  const ok = await call(route!)
  assert.equal(ok.status, 200)
  assert.equal(ok.body?.ok, true)
  assert.equal((ok.body?.markets as Array<{ market: string }>)[0]?.market, 'US')
})
