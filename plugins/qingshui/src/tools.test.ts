import assert from 'node:assert/strict'
import { test } from 'node:test'
import { formatEvidenceText, installQingshuiTools } from './tools.ts'
import type { KnowledgeClient } from './knowledge-client.ts'

test('formatEvidenceText truncates long excerpt', () => {
  const text = formatEvidenceText({
    evidence_id: 'EV:1',
    source_type: 'announcement',
    source_name: 'x',
    publish_date: '2024-01-01',
    confidence: 0.9,
    text_excerpt: 'a'.repeat(9000),
  })
  assert.match(text, /EV:1/)
  assert.match(text, /原文过长已截断/)
  assert.ok(text.length < 9500)
})

test('installQingshuiTools registers divergence tool set', () => {
  const registered: string[] = []
  const fakeCtx = {
    inject(_deps: string[], fn: (c: { tools: { register: (t: { name: string }) => void } }) => void) {
      fn({
        tools: {
          register(tool) {
            registered.push(tool.name)
          },
        },
      })
    },
  }
  const client: KnowledgeClient = {
    async semanticSearch() { return {} },
    async fetchEvidence() { return {} },
    async compareMetric() { return {} },
    async metricTrend() { return {} },
    async rollupMetric() { return {} },
    async relatedNodes() { return {} },
    async propagateAlong() { return {} },
    async getKline() { return {} },
    async getStockProfile() { return {} },
  }
  installQingshuiTools(fakeCtx as never, { client: () => client })
  for (const name of [
    'compare_metric', 'metric_trend', 'rollup_metric', 'fetch_evidence', 'semantic_search',
    'related_nodes', 'propagate_along', 'get_kline', 'get_stock_profile',
  ]) {
    assert.ok(registered.includes(name), `missing ${name}`)
  }
})

test('fetch_evidence keeps model text render while meta carries the raw doc', async () => {
  const tools = new Map<string, {
    output: {
      render: (args: unknown, value: unknown) => Array<{ type: string; text: string }>
      presentationMeta?: (args: unknown, value: unknown) => unknown
    }
    execute: (args: Record<string, unknown>) => Promise<unknown>
  }>()
  const fakeCtx = {
    inject(_deps: string[], fn: (c: { tools: { register: (t: { name: string } & object) => void } }) => void) {
      fn({
        tools: {
          register(tool) {
            tools.set(tool.name, tool as never)
          },
        },
      })
    },
  }
  const doc = {
    evidence_id: 'EV:1',
    source_type: 'announcement',
    source_name: '公告:301629.SZ',
    publish_date: '2025-04-29',
    confidence: 0.95,
    text_excerpt: '正文',
  }
  const client: KnowledgeClient = {
    async semanticSearch() { return {} },
    async fetchEvidence() { return doc },
    async compareMetric() { return {} },
    async metricTrend() { return {} },
    async rollupMetric() { return {} },
    async relatedNodes() { return {} },
    async propagateAlong() { return {} },
    async getKline() { return {} },
    async getStockProfile() { return {} },
  }
  installQingshuiTools(fakeCtx as never, { client: () => client })
  const tool = tools.get('fetch_evidence')
  assert.ok(tool)
  const value = await tool.execute({ evidence_id: 'EV:1' })
  assert.deepEqual(value, doc)
  const rendered = tool.output.render({ evidence_id: 'EV:1' }, value)
  assert.equal(rendered.length, 1)
  const firstBlock = rendered[0]
  assert.ok(firstBlock)
  assert.match(firstBlock.text, /证据 ID: EV:1/)
  assert.match(firstBlock.text, /正文/)
  assert.equal(tool.output.presentationMeta?.({ evidence_id: 'EV:1' }, value), doc)
  const failure = await (async () => {
    const failing = { ...client, async fetchEvidence(): Promise<Record<string, unknown>> { throw new Error('boom') } }
    const tools2 = new Map<string, typeof tool>()
    installQingshuiTools({
      inject(_deps: string[], fn: (c: { tools: { register: (t: { name: string } & object) => void } }) => void) {
        fn({ tools: { register(t) { tools2.set(t.name, t as never) } } })
      },
    } as never, { client: () => failing })
    const t2 = tools2.get('fetch_evidence')
    assert.ok(t2)
    return t2.execute({ evidence_id: 'EV:x' })
  })()
  assert.deepEqual(failure, { error: '证据查询失败: boom' })
  const errorRender = tool.output.render({}, { error: '证据查询失败: boom' })
  assert.equal(errorRender[0]?.text, '证据查询失败: boom')
})

test('get_kline forwards params and meta carries the payload', async () => {
  const tools = new Map<string, {
    output: { presentationMeta?: (args: unknown, value: unknown) => unknown }
    execute: (args: Record<string, unknown>) => Promise<unknown>
  }>()
  const fakeCtx = {
    inject(_deps: string[], fn: (c: { tools: { register: (t: { name: string } & object) => void } }) => void) {
      fn({ tools: { register(tool) { tools.set(tool.name, tool as never) } } })
    },
  }
  const calls: Array<Record<string, unknown>> = []
  const payload = { ts_code: '300308.SZ', count: 1, items: [{ trade_date: '20261012', open: 1, close: 2, low: 1, high: 2 }] }
  const client: KnowledgeClient = {
    async semanticSearch() { return {} },
    async fetchEvidence() { return {} },
    async compareMetric() { return {} },
    async metricTrend() { return {} },
    async rollupMetric() { return {} },
    async relatedNodes() { return {} },
    async propagateAlong() { return {} },
    async getKline(input) { calls.push(input as Record<string, unknown>); return payload },
    async getStockProfile() { return {} },
  }
  installQingshuiTools(fakeCtx as never, { client: () => client })
  const tool = tools.get('get_kline')
  assert.ok(tool)
  const value = await tool.execute({ ts_code: '300308.SZ', start_date: '20250901', freq: 'W' })
  assert.deepEqual(value, payload)
  assert.deepEqual(calls[0], { ts_code: '300308.SZ', start_date: '20250901', end_date: null, freq: 'W' })
  assert.equal(tool.output.presentationMeta?.({}, value), payload)
})
