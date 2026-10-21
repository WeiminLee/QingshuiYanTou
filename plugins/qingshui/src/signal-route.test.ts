import assert from 'node:assert/strict'
import { test } from 'node:test'
import type { IncomingMessage, ServerResponse } from 'node:http'
import { installSignalRoute, SIGNAL_ROUTE_PATH } from './signal-route.ts'
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

test('signal route groups processed rows into four lanes', async () => {
  const seen: string[] = []
  const { routes, webServer } = capture()
  installSignalRoute({ webServer }, {
    client: () => ({
      listSignals: async (input: { sourceType: string }) => {
        seen.push(input.sourceType)
        if (input.sourceType !== 'announcement:llm') return { items: [] }
        return { items: [{ signal_id: 'LLM:1', summary: '营收上台阶', subject_name: '德明利', polarity: 'positive', value_score: 8 }] }
      },
    }) as unknown as KnowledgeClient,
  })
  assert.equal(routes[0]?.path, SIGNAL_ROUTE_PATH)
  const ok = await call(routes[0]!)
  assert.equal(ok.status, 200)
  const lanes = ok.body?.lanes as Array<{ id: string; items: Array<{ summary: string }> }>
  assert.deepEqual(lanes.map(lane => lane.id), ['news', 'announcement', 'event', 'mapping'])
  assert.equal(lanes[1]?.items[0]?.summary, '营收上台阶')
  assert.ok(seen.includes('us_map:llm'))
  assert.ok(seen.includes('tw_map:llm'))
  assert.ok(seen.includes('irm'))
  assert.ok(seen.includes('irm:llm'))
})

test('signal route refuses a non-loopback host', async () => {
  const { routes, webServer } = capture()
  installSignalRoute({ webServer }, {
    client: () => ({ listSignals: async () => ({ items: [] }) }) as unknown as KnowledgeClient,
  })
  const denied = await call(routes[0]!, 'evil.example')
  assert.equal(denied.status, 403)
})
