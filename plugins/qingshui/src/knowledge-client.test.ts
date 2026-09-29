import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createKnowledgeClient } from './knowledge-client.ts'

test('compareMetric posts to agent endpoint with X-API-Key', async () => {
  const calls: Array<{ url: string; init: RequestInit }> = []
  const fetchImpl: typeof fetch = async (url, init) => {
    calls.push({ url: String(url), init: init ?? {} })
    return new Response(JSON.stringify({ count: 0, items: [] }), { status: 200 })
  }
  const client = createKnowledgeClient({
    baseUrl: 'http://knowledge.test',
    apiKey: 'k',
    timeoutMs: 5000,
    fetchImpl,
  })
  await client.compareMetric({ dimension: '毛利率', scope: '硅片' })
  assert.equal(calls.length, 1)
  assert.equal(calls[0].url, 'http://knowledge.test/api/v1/knowledge/agent/compare_metric')
  assert.equal((calls[0].init.headers as Record<string, string>)['X-API-Key'], 'k')
  assert.equal(calls[0].init.method, 'POST')
})

test('metricTrend and rollupMetric hit correct paths', async () => {
  const urls: string[] = []
  const fetchImpl: typeof fetch = async (url) => {
    urls.push(String(url))
    return new Response(JSON.stringify({}), { status: 200 })
  }
  const client = createKnowledgeClient({
    baseUrl: 'http://knowledge.test/',
    apiKey: 'k',
    timeoutMs: 5000,
    fetchImpl,
  })
  await client.metricTrend({ subject: '600962.SH', dimension: '营业收入' })
  await client.rollupMetric({ parent: '营收' })
  await client.fetchEvidence('EV:1')
  assert.equal(urls[0], 'http://knowledge.test/api/v1/knowledge/agent/metric_trend')
  assert.equal(urls[1], 'http://knowledge.test/api/v1/knowledge/agent/rollup_metric')
  assert.equal(urls[2], 'http://knowledge.test/api/v1/knowledge/evidence/EV%3A1')
})

test('non-2xx throws with status', async () => {
  const fetchImpl: typeof fetch = async () => new Response('nope', { status: 401 })
  const client = createKnowledgeClient({
    baseUrl: 'http://knowledge.test',
    apiKey: 'bad',
    timeoutMs: 5000,
    fetchImpl,
  })
  await assert.rejects(() => client.compareMetric({ dimension: 'x' }), /401/)
})
