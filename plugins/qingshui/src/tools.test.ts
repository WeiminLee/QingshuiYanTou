import assert from 'node:assert/strict'
import { test } from 'node:test'
import { accelerationFromTimeline, formatEvidenceText, installQingshuiTools, withSeriesAcceleration } from './tools.ts'
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
    async searchStocks() { return {} },
    async getMarketSnapshot() { return {} },
  }
  installQingshuiTools(fakeCtx as never, { client: () => client })
  for (const name of [
    'compare_metric', 'metric_trend', 'rollup_metric', 'fetch_evidence', 'semantic_search',
    'related_nodes', 'propagate_along', 'get_kline', 'get_stock_profile', 'search_stock',
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
    async searchStocks() { return {} },
    async getMarketSnapshot() { return {} },
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
    async searchStocks() { return {} },
    async getMarketSnapshot() { return {} },
  }
  installQingshuiTools(fakeCtx as never, { client: () => client })
  const tool = tools.get('get_kline')
  assert.ok(tool)
  const value = await tool.execute({ ts_code: '300308.SZ', start_date: '20250901', freq: 'W' })
  assert.deepEqual(value, payload)
  assert.deepEqual(calls[0], { ts_code: '300308.SZ', start_date: '20250901', end_date: null, freq: 'W' })
  assert.equal(tool.output.presentationMeta?.({}, value), payload)
})

test('search_stock looks up the local name index and rejects an empty query', async () => {
  const tools = new Map<string, {
    description?: string
    execute: (args: Record<string, unknown>) => Promise<unknown>
  }>()
  const fakeCtx = {
    inject(_deps: string[], fn: (c: { tools: { register: (t: { name: string } & object) => void } }) => void) {
      fn({ tools: { register(tool) { tools.set(tool.name, tool as never) } } })
    },
  }
  const calls: Array<Record<string, unknown>> = []
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
    async searchStocks(input) {
      calls.push(input as Record<string, unknown>)
      return { items: [{ ts_code: '301666.SZ', name: '大普微' }] }
    },
    async getMarketSnapshot() { return {} },
  }
  installQingshuiTools(fakeCtx as never, { client: () => client })
  const tool = tools.get('search_stock')
  assert.ok(tool)
  assert.match(tool.description ?? '', /不要猜代码/)
  const value = await tool.execute({ q: '大普微', limit: 5 })
  assert.deepEqual(value, { items: [{ ts_code: '301666.SZ', name: '大普微' }] })
  assert.deepEqual(calls[0], { q: '大普微', limit: 5 })
  const empty = await tool.execute({ q: '  ' })
  assert.deepEqual(empty, { error: 'search_stock 需要 q' })
  await tool.execute({ q: '大普微', limit: 99 })
  assert.deepEqual(calls[1], { q: '大普微', limit: 10 })
  const kline = tools.get('get_kline') as { description?: string } | undefined
  assert.match(kline?.description ?? '', /amount 单位是千元，10 万千元 = 1 亿元/)
})

test('metric_trend returns acceleration and does not recompute inside the test', async () => {
  const shrinking = accelerationFromTimeline([
    { metric: '毛利率', value: 10, unit: '%', period: '2024', evidence_id: 'EV:1' },
    { metric: '毛利率', value: 14, unit: '%', period: '2025', evidence_id: 'EV:2' },
    { metric: '毛利率', value: 15, unit: '%', period: '2026', evidence_id: 'EV:3' },
  ])
  assert.equal(shrinking.status, 'ok')
  assert.equal(shrinking.d1, 4)
  assert.equal(shrinking.d2, 1)
  assert.equal(shrinking.a, -3)
  assert.match(shrinking.note, /不要/)

  const lastThree = accelerationFromTimeline([
    { metric: '毛利率', value: '1', unit: '%', period: '2022' },
    { metric: '毛利率', value: '2', unit: '%', period: '2023' },
    { metric: '毛利率', value: '10', unit: '%', period: '2024' },
    { metric: '毛利率', value: '14', unit: '%', period: '2025' },
    { metric: '营业收入', value: 100, unit: '元', period: '2024' },
    { metric: '营业收入', value: 200, unit: '元', period: '2025' },
    { metric: '毛利率', value: '15', unit: '%', period: '2026' },
  ])
  assert.equal(lastThree.a, -3)
  assert.deepEqual(lastThree.points.map((point) => point.value), [10, 14, 15])

  const short = accelerationFromTimeline([
    { metric: '毛利率', value: 28, unit: '%', period: '2024' },
    { metric: '毛利率', value: 32, unit: '%', period: '2025' },
  ])
  assert.equal(short.status, 'insufficient_points')
  assert.equal(short.d1, null)
  assert.equal(short.d2, null)
  assert.equal(short.a, null)
  assert.match(short.note, /二阶导不可计算/)
  assert.match(short.note, /点数不足只说明加速度算不出/)

  const errorPayload = { error: 'upstream', timeline: [{ value: 1 }, { value: 2 }, { value: 3 }] }
  assert.equal(withSeriesAcceleration(errorPayload), errorPayload)
  assert.deepEqual(withSeriesAcceleration({ subject: '600962.SH' }), { subject: '600962.SH' })

  const tools = new Map<string, {
    description?: string
    execute: (args: Record<string, unknown>) => Promise<unknown>
  }>()
  const calls: Array<Record<string, unknown>> = []
  const client: KnowledgeClient = {
    async semanticSearch() { return {} },
    async fetchEvidence() { return {} },
    async compareMetric() { return {} },
    async metricTrend(input) {
      calls.push(input as Record<string, unknown>)
      return {
        subject: '600962.SH',
        dimension: '毛利率',
        count: 3,
        timeline: [
          { metric: '毛利率', value: 10, unit: '%', period: '2024', evidence_id: 'EV:1' },
          { metric: '毛利率', value: 14, unit: '%', period: '2025', evidence_id: 'EV:2' },
          { metric: '毛利率', value: 15, unit: '%', period: '2026', evidence_id: 'EV:3' },
        ],
      }
    },
    async rollupMetric() { return {} },
    async relatedNodes() { return {} },
    async propagateAlong() { return {} },
    async getKline() { return {} },
    async getStockProfile() { return {} },
    async searchStocks() { return {} },
    async getMarketSnapshot() { return {} },
  }
  installQingshuiTools({
    inject(_deps: string[], fn: (c: { tools: { register: (t: { name: string } & object) => void } }) => void) {
      fn({ tools: { register(tool) { tools.set(tool.name, tool as never) } } })
    },
  } as never, { client: () => client })
  const tool = tools.get('metric_trend')
  assert.ok(tool)
  assert.match(tool.description ?? '', /acceleration/)
  assert.match(tool.description ?? '', /不要对 timeline 再做减法/)
  const value = await tool.execute({ subject: '600962.SH', dimension: '毛利率', limit: 50 }) as {
    acceleration: { status: string; d1: number; d2: number; a: number }
    timeline: unknown[]
  }
  assert.equal(value.acceleration.status, 'ok')
  assert.equal(value.acceleration.d1, 4)
  assert.equal(value.acceleration.d2, 1)
  assert.equal(value.acceleration.a, -3)
  assert.equal(value.timeline.length, 3)
  assert.deepEqual(calls[0], { subject: '600962.SH', dimension: '毛利率', limit: 50 })

  const stored = accelerationFromTimeline([
    { metric: '营业收入', value: '100,000', unit: '元', period: '2024', evidence_id: 'EV:a' },
    { metric: '营业收入', value: '110,000', unit: '元', period: '2025', evidence_id: 'EV:b' },
    { metric: '营业收入', value: '130,000', unit: '元', period: '2026', evidence_id: 'EV:c' },
  ])
  assert.equal(stored.status, 'ok')
  assert.equal(stored.d1, 10000)
  assert.equal(stored.d2, 20000)
  assert.equal(stored.a, 10000)
  assert.equal(JSON.stringify(stored.a), '10000')

  const samePeriod = accelerationFromTimeline([
    { metric: '毛利率', value: 28.1, unit: '%', period: '2024', evidence_id: 'EV:p1' },
    { metric: '毛利率', value: 28.2, unit: '%', period: '2024', evidence_id: 'EV:p2' },
    { metric: '毛利率', value: 28.5, unit: '%', period: '2024', evidence_id: 'EV:p3' },
  ])
  assert.equal(samePeriod.status, 'insufficient_points')
  assert.equal(samePeriod.d1, null)
  assert.equal(samePeriod.d2, null)
  assert.equal(samePeriod.a, null)
  assert.equal(samePeriod.points.length, 1)
  assert.equal(samePeriod.points[0]?.value, 28.5)

  const restated = accelerationFromTimeline([
    { metric: '毛利率', value: 30, unit: '%', period: '2026', evidence_id: 'EV:6' },
    { metric: '毛利率', value: 10, unit: '%', period: '2024', evidence_id: 'EV:4' },
    { metric: '毛利率', value: 20, unit: '%', period: '2025', evidence_id: 'EV:5' },
    { metric: '毛利率', value: 12, unit: '%', period: '2024', evidence_id: 'EV:4b' },
  ])
  assert.equal(restated.status, 'ok')
  assert.deepEqual(restated.points.map((point) => point.period), ['2024', '2025', '2026'])
  assert.deepEqual(restated.points.map((point) => point.value), [12, 20, 30])
  assert.equal(restated.points[0]?.evidence_id, 'EV:4b')
  assert.equal(restated.d1, 8)
  assert.equal(restated.d2, 10)
  assert.equal(restated.a, 2)

  const decimals = accelerationFromTimeline([
    { metric: '毛利率', value: 28.1, unit: '%', period: '2024' },
    { metric: '毛利率', value: 28.2, unit: '%', period: '2025' },
    { metric: '毛利率', value: 28.5, unit: '%', period: '2026' },
  ])
  assert.equal(decimals.status, 'ok')
  assert.equal(decimals.d1, 0.1)
  assert.equal(decimals.d2, 0.3)
  assert.equal(decimals.a, 0.2)
  assert.equal(JSON.stringify(decimals.d1), '0.1')
  assert.equal(JSON.stringify(decimals.d2), '0.3')
  assert.equal(JSON.stringify(decimals.a), '0.2')

  const storedDecimals = accelerationFromTimeline([
    { metric: '毛利率', value: '28.1', unit: '%', period: '2024' },
    { metric: '毛利率', value: '28.2', unit: '%', period: '2025' },
    { metric: '毛利率', value: '28.5', unit: '%', period: '2026' },
  ])
  assert.equal(storedDecimals.d1, 0.1)
  assert.equal(storedDecimals.d2, 0.3)
  assert.equal(storedDecimals.a, 0.2)
  assert.equal(JSON.stringify(storedDecimals.d1), '0.1')
  assert.equal(JSON.stringify(storedDecimals.d2), '0.3')
  assert.equal(JSON.stringify(storedDecimals.a), '0.2')

  const commaDecimal = accelerationFromTimeline([
    { metric: '营业收入', value: '343,339.41', unit: '元', period: '2024' },
    { metric: '营业收入', value: '343,449.41', unit: '元', period: '2025' },
    { metric: '营业收入', value: '343,669.41', unit: '元', period: '2026' },
  ])
  assert.equal(commaDecimal.status, 'ok')
  assert.equal(commaDecimal.d1, 110)
  assert.equal(commaDecimal.d2, 220)
  assert.equal(commaDecimal.a, 110)
  assert.equal(JSON.stringify(commaDecimal.d1), '110')

  const commaPayload = {
    subject: '600962.SH',
    timeline: [
      { metric: '营业收入', value: '100,000', unit: '元', period: '2024' },
      { metric: '营业收入', value: '110,000', unit: '元', period: '2025' },
      { metric: '营业收入', value: '130,000', unit: '元', period: '2026' },
    ],
  }
  const wrapped = withSeriesAcceleration(commaPayload) as { acceleration: { a: number; status: string } }
  assert.equal(wrapped.acceleration.status, 'ok')
  assert.equal(wrapped.acceleration.a, 10000)

  const mixedCadence = accelerationFromTimeline([
    { metric: '营业收入', value: '1', unit: '元', period: '2024A' },
    { metric: '营业收入', value: '2', unit: '元', period: '2025Q1' },
    { metric: '营业收入', value: '3', unit: '元', period: '2025Q2' },
    { metric: '营业收入', value: '4', unit: '元', period: '2025Q3' },
  ])
  assert.equal(mixedCadence.status, 'ok')
  assert.deepEqual(mixedCadence.points.map((point) => point.period), ['2025Q1', '2025Q2', '2025Q3'])
  assert.equal(mixedCadence.d1, 1)
  assert.equal(mixedCadence.d2, 1)
  assert.equal(mixedCadence.a, 0)

  const toolsComma = new Map<string, { execute: (args: Record<string, unknown>) => Promise<unknown> }>()
  installQingshuiTools({
    inject(_deps: string[], fn: (c: { tools: { register: (t: { name: string } & object) => void } }) => void) {
      fn({ tools: { register(tool) { toolsComma.set(tool.name, tool as never) } } })
    },
  } as never, {
    client: () => ({
      ...client,
      async metricTrend() { return commaPayload },
    }),
  })
  const commaTool = toolsComma.get('metric_trend')
  assert.ok(commaTool)
  const commaValue = await commaTool.execute({ subject: '600962.SH', dimension: '营业收入' }) as {
    acceleration: { status: string; d1: number; d2: number; a: number }
  }
  assert.equal(commaValue.acceleration.status, 'ok')
  assert.equal(commaValue.acceleration.d1, 10000)
  assert.equal(commaValue.acceleration.d2, 20000)
  assert.equal(commaValue.acceleration.a, 10000)

  const storedQuarters = accelerationFromTimeline([
    { metric: '营业收入', value: 10, unit: '元', period: 'Q1 2024' },
    { metric: '营业收入', value: 20, unit: '元', period: 'Q2 2024' },
    { metric: '营业收入', value: 30, unit: '元', period: 'Q3 2024' },
    { metric: '营业收入', value: 100, unit: '元', period: 'Q4 2024' },
    { metric: '营业收入', value: 40, unit: '元', period: 'Q1 2025' },
  ])
  assert.equal(storedQuarters.status, 'ok')
  assert.deepEqual(storedQuarters.points.map((point) => point.period), ['Q3 2024', 'Q4 2024', 'Q1 2025'])
  assert.deepEqual(storedQuarters.points.map((point) => point.value), [30, 100, 40])
  assert.equal(storedQuarters.d1, 70)
  assert.equal(storedQuarters.d2, -60)
  assert.equal(storedQuarters.a, -130)

  const storedHalves = accelerationFromTimeline([
    { metric: '营业收入', value: 10, unit: '元', period: 'H1 2023' },
    { metric: '营业收入', value: 20, unit: '元', period: 'H2 2023' },
    { metric: '营业收入', value: 30, unit: '元', period: 'H1 2024' },
  ])
  assert.equal(storedHalves.status, 'ok')
  assert.deepEqual(storedHalves.points.map((point) => point.period), ['H1 2023', 'H2 2023', 'H1 2024'])
  assert.equal(storedHalves.d1, 10)
  assert.equal(storedHalves.d2, 10)
  assert.equal(storedHalves.a, 0)

  const storedYtd = accelerationFromTimeline([
    { metric: '营业收入', value: 30, unit: '元', period: 'Q1-Q3 2025' },
    { metric: '营业收入', value: 10, unit: '元', period: 'Q1-Q3 2023' },
    { metric: '营业收入', value: 20, unit: '元', period: 'Q1-Q3 2024' },
  ])
  assert.equal(storedYtd.status, 'ok')
  assert.deepEqual(storedYtd.points.map((point) => point.period), ['Q1-Q3 2023', 'Q1-Q3 2024', 'Q1-Q3 2025'])
  assert.equal(storedYtd.a, 0)

  const storedDays = accelerationFromTimeline([
    { metric: '营业收入', value: 10, unit: '元', period: '2024-11-02' },
    { metric: '营业收入', value: 20, unit: '元', period: '2024-12-01' },
    { metric: '营业收入', value: 30, unit: '元', period: '2024-12-15' },
    { metric: '营业收入', value: 999, unit: '元', period: '2024-01-12' },
  ])
  assert.equal(storedDays.status, 'ok')
  assert.deepEqual(storedDays.points.map((point) => point.period), ['2024-11-02', '2024-12-01', '2024-12-15'])
  assert.deepEqual(storedDays.points.map((point) => point.value), [10, 20, 30])
  assert.equal(storedDays.d1, 10)
  assert.equal(storedDays.d2, 10)
  assert.equal(storedDays.a, 0)
})
