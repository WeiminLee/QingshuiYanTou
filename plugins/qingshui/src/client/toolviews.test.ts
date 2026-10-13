import assert from 'node:assert/strict'
import { test } from 'node:test'
import {
  asEvidenceDoc,
  asHistoryPayload,
  asKlinePayload,
  asSearchResult,
  blockArgs,
  blockState,
  blockText,
  extractResultJson,
  formatDate,
  formatKlineTooltip,
  formatTradeDate,
  formatVolume,
  freqLabel,
  groupHistoryByDate,
  isSettled,
  sourceTypeLabel,
  type SettledBlock,
} from './toolviews/model.ts'

function settled(over: Partial<SettledBlock>): SettledBlock {
  return {
    kind: 'tool-result',
    callId: 'c1',
    call: { name: 'get_kline', argsRaw: '{"ts_code":"300308.SZ"}' },
    content: [],
    isError: false,
    ...over,
  }
}

test('blockState discriminates running/error/ok', () => {
  assert.equal(blockState({ callId: 'c', name: 'get_kline', argsRaw: '' }), 'running')
  assert.equal(blockState(settled({ isError: true })), 'error')
  assert.equal(blockState(settled({})), 'ok')
  assert.ok(isSettled(settled({})))
})

test('blockArgs parses argsRaw from running and settled blocks', () => {
  assert.deepEqual(blockArgs({ callId: 'c', name: 't', argsRaw: '{"a":1}' }), { a: 1 })
  assert.deepEqual(blockArgs(settled({})), { ts_code: '300308.SZ' })
  assert.deepEqual(blockArgs({ callId: 'c', name: 't', argsRaw: 'not json' }), {})
  assert.deepEqual(blockArgs(settled({ call: null })), {})
})

test('blockText flattens text blocks and falls back to error name/code', () => {
  const text = blockText(settled({
    content: [{ type: 'text', text: 'a' }, { type: 'image', data: 'x' }],
  }))
  assert.ok(text.includes('a'))
  assert.ok(text.includes('"image"'))
  assert.equal(
    blockText(settled({ content: [], isError: true, error: { name: 'ToolError', code: 'timeout' } })),
    'ToolError: timeout',
  )
})

test('extractResultJson prefers meta, then parses text, else undefined', () => {
  const meta = { count: 1 }
  assert.equal(extractResultJson(settled({ meta, content: [{ type: 'text', text: 'ignored' }] })), meta)
  assert.deepEqual(
    extractResultJson(settled({ content: [{ type: 'text', text: '{"count":2}' }] })),
    { count: 2 },
  )
  assert.equal(extractResultJson(settled({ content: [{ type: 'text', text: '证据 ID: EV:1\n非 JSON' }] })), undefined)
  assert.equal(extractResultJson(settled({ content: [] })), undefined)
})

test('asKlinePayload validates and coerces items', () => {
  const payload = asKlinePayload({
    ts_code: '300308.SZ',
    start_date: '20260416',
    end_date: '20261013',
    freq: 'D',
    count: 2,
    items: [
      { trade_date: '20260511', open: 889.06, high: 946.79, low: 870, close: 940.13, volume: 32265543, pct_chg: 6.1095 },
      { trade_date: '20261012', open: '762.41', high: 770.9, low: 723, close: 724.47, volume: 210483.01 },
      { trade_date: 'bad', open: 'x' },
    ],
    text: '摘要',
  })
  assert.ok(payload)
  assert.equal(payload.items.length, 2)
  assert.equal(payload.items[1]?.open, 762.41)
  assert.equal(payload.count, 2)
  assert.equal(payload.text, '摘要')
  assert.equal(asKlinePayload({ items: 'nope' }), undefined)
  assert.equal(asKlinePayload('text'), undefined)
  const empty = asKlinePayload({ ts_code: 'x', items: [], count: 0 })
  assert.ok(empty)
  assert.equal(empty.items.length, 0)
})

test('formatTradeDate and formatDate normalize date shapes', () => {
  assert.equal(formatTradeDate('20260511'), '2026-05-11')
  assert.equal(formatTradeDate('2026-05-11'), '2026-05-11')
  assert.equal(formatDate('2025-04-28 16:00:00+00:00'), '2025-04-28')
  assert.equal(formatDate('20260416'), '2026-04-16')
  assert.equal(formatDate(undefined), '')
})

test('asEvidenceDoc extracts doc fields with fallbacks', () => {
  const doc = asEvidenceDoc({
    evidence_id: 'EV:1',
    source_type: 'announcement',
    source_name: '公告:301629.SZ',
    publish_date: '2025-04-29',
    confidence: '0.95',
    text_excerpt: '正文',
    subject_hint: { ts_code: '301629.SZ', title: '2024年年度报告' },
    source_ref: { pdf_url: 'http://example.com/x.pdf' },
    metadata: { title: '备用标题' },
  })
  assert.ok(doc)
  assert.equal(doc.title, '2024年年度报告')
  assert.equal(doc.ts_code, '301629.SZ')
  assert.equal(doc.confidence, 0.95)
  assert.equal(doc.pdf_url, 'http://example.com/x.pdf')
  const metaTitle = asEvidenceDoc({ evidence_id: 'EV:2', metadata: { title: '仅元数据标题' } })
  assert.equal(metaTitle?.title, '仅元数据标题')
  assert.equal(asEvidenceDoc({ error: '证据查询失败: boom' }), undefined)
  assert.equal(asEvidenceDoc('证据 ID: EV:1\n来源类型: announcement'), undefined)
  assert.equal(asEvidenceDoc(undefined), undefined)
})

test('asSearchResult reads entities and chunks with optional fields', () => {
  const result = asSearchResult({
    entities: [{ entity_id: 'e1', name: '硅片', type: 'product', ts_code: '', score: 0.9 }],
    chunks: [
      { evidence_id: 'EV:1', snippet: '片段', source_type: 'news', source_name: '快讯', score: 0.81234 },
      { evidence_id: 'EV:2', snippet: '片段2', source_type: 'announcement', source_name: '公告', publish_date: '2025-01-01', title: '标题', pdf_url: 'http://x' },
    ],
  })
  assert.ok(result)
  assert.equal(result.entities.length, 1)
  assert.equal(result.entities[0]?.name, '硅片')
  assert.equal(result.chunks[0]?.publish_date, undefined)
  assert.equal(result.chunks[1]?.title, '标题')
  assert.equal(result.chunks[0]?.score?.toFixed(3), '0.812')
  assert.equal(asSearchResult({}), undefined)
  const chunksOnly = asSearchResult({ chunks: [] })
  assert.ok(chunksOnly)
  assert.equal(chunksOnly.entities.length, 0)
})

test('asHistoryPayload reads items; groupHistoryByDate buckets by day in order', () => {
  const payload = asHistoryPayload({
    count: 3,
    items: [
      { evidence_id: 'EV:1', published_at: '2025-04-28 16:00:00+00:00', source_type: 'announcement', source_name: '公告:A', text_excerpt: 'a', matched_keywords: ['硅片', '涨价'] },
      { evidence_id: 'EV:2', published_at: '2025-04-28 01:00:00+00:00', source_type: 'news', source_name: '新闻:B', text_excerpt: 'b' },
      { evidence_id: 'EV:3', published_at: '2025-04-01 10:00:00+00:00', source_type: 'irm', source_name: '互动易:C', text_excerpt: 'c', matched_keywords: 'bad' },
    ],
  })
  assert.ok(payload)
  assert.equal(payload.count, 3)
  assert.deepEqual(payload.items[1]?.matched_keywords, [])
  assert.deepEqual(payload.items[2]?.matched_keywords, [])
  const groups = groupHistoryByDate(payload.items)
  assert.equal(groups.length, 2)
  assert.equal(groups[0]?.date, '2025-04-28')
  assert.equal(groups[0]?.items.length, 2)
  assert.equal(groups[1]?.date, '2025-04-01')
  assert.equal(asHistoryPayload({}), undefined)
})

test('sourceTypeLabel maps known types and passes through unknown', () => {
  assert.equal(sourceTypeLabel('announcement'), '公告')
  assert.equal(sourceTypeLabel('irm'), '互动易')
  assert.equal(sourceTypeLabel('something_else'), 'something_else')
  assert.equal(sourceTypeLabel(undefined), '未知')
})

test('freqLabel maps D/W/M to 日K/周K/月K case-insensitively', () => {
  assert.equal(freqLabel('D'), '日K')
  assert.equal(freqLabel('W'), '周K')
  assert.equal(freqLabel('M'), '月K')
  assert.equal(freqLabel('d'), '日K')
  assert.equal(freqLabel('Q'), 'Q')
})

test('formatVolume scales with 万/亿', () => {
  assert.equal(formatVolume(28551616), '2855.2万')
  assert.equal(formatVolume(32265543), '3226.6万')
  assert.equal(formatVolume(29399331289.46), '293.99亿')
  assert.equal(formatVolume(1e8), '1.00亿')
  assert.equal(formatVolume(9999), '9999')
  assert.equal(formatVolume(0), '0')
})

test('formatKlineTooltip renders Chinese OHLC + scaled volume rows', () => {
  const items = [{
    trade_date: '20260511',
    open: 889.06,
    high: 946.79,
    low: 870,
    close: 940.13,
    volume: 32265543,
  }]
  const html = formatKlineTooltip(items, [{ dataIndex: 0, axisValue: '2026-05-11' }])
  for (const part of ['2026-05-11', '开盘：889.06', '收盘：940.13', '最低：870.00', '最高：946.79', '成交量：3226.6万']) {
    assert.ok(html.includes(part), `missing ${part}`)
  }
  assert.equal(formatKlineTooltip(items, [{ dataIndex: 1 }]), '')
  assert.equal(formatKlineTooltip(items, []), '')
  const fallback = formatKlineTooltip(items, [{ dataIndex: 0 }])
  assert.ok(fallback.includes('2026-05-11'), 'falls back to formatted trade_date')
})
