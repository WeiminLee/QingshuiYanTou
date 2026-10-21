import assert from 'node:assert/strict'
import { test } from 'node:test'
import {
  asEvidenceDoc,
  asFindingDoc,
  asFindingListPayload,
  asHistoryPayload,
  asKlinePayload,
  asSearchResult,
  blockArgs,
  blockState,
  blockText,
  evidenceAnnId,
  extractResultJson,
  findingKindLabel,
  findingStatusLabel,
  formatConfidence,
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

test('evidenceAnnId reads the parent announcement id, absent for parentless evidence', () => {
  assert.equal(evidenceAnnId({ source_ref: { ann_id: '880123' } }), '880123')
  assert.equal(evidenceAnnId({ source_ref: { ann_id: 880123 } }), '880123')
  assert.equal(evidenceAnnId({ source_ref: { ann_id: '' } }), undefined)
  assert.equal(evidenceAnnId({ source_ref: { pdf_url: 'http://x' } }), undefined)
  assert.equal(evidenceAnnId({ evidence_id: 'EV:1' }), undefined)
  assert.equal(evidenceAnnId(undefined), undefined)
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

test('asFindingDoc parses fields and falls back support_count from supports', () => {
  const doc = asFindingDoc({
    finding_id: 'FD:abc123',
    kind: 'divergence',
    subject_ts_code: '300308.SZ',
    dimension: 'pricing',
    dimension_scope: 'HBM',
    judgment: '市场预期低估了涨价传导幅度',
    confidence: 0.72,
    supports: [{ obs_id: 'o1', evidence_id: 'EV:1' }, { obs_id: 'o2', evidence_id: 'EV:2' }],
    contradicts: [{ evidence_id: 'EV:3' }],
    status: 'candidate',
    supersedes: null,
    created_at: '2026-10-20T08:00:00+00:00',
  })
  assert.ok(doc)
  assert.equal(doc.kind, 'divergence')
  assert.equal(doc.support_count, 2)
  assert.equal(doc.contradicts, 1)
  assert.equal(doc.confidence, 0.72)
  assert.equal(doc.dimension_scope, 'HBM')
  assert.equal(doc.judgment, '市场预期低估了涨价传导幅度')
  const explicit = asFindingDoc({ finding_id: 'FD:x', support_count: 5, supports: [{}] })
  assert.equal(explicit?.support_count, 5)
  assert.equal(asFindingDoc({ finding_id: 'FD:y' })?.support_count, 0)
  assert.equal(asFindingDoc('not-an-object'), undefined)
  assert.equal(asFindingDoc({}), undefined)
})

test('asFindingDoc keeps well-formed supports and drops dirty anchors', () => {
  const doc = asFindingDoc({
    finding_id: 'FD:spans',
    judgment: '供给收缩已传导到报价',
    supports: [
      { obs_id: 'o1', evidence_id: 'EV:aaaa', span_start: 0, span_end: 12 },
      { obs_id: 'o2', evidence_id: 'EV:bbbb', span_start: 20, span_end: 44 },
      { obs_id: 'o3', evidence_id: '', span_start: 0, span_end: 4 },
      { obs_id: 'o4', evidence_id: 'EV:cccc', span_start: 1.5, span_end: 8 },
      { obs_id: 'o5', evidence_id: 'EV:dddd', span_start: 0, span_end: '9' },
      { obs_id: 'o6', evidence_id: 'EV:eeee' },
      { obs_id: 'o7', evidence_id: 'EV:ffff', span_start: -4, span_end: 3 },
      { obs_id: 'o8', evidence_id: 'EV:gggg', span_start: 9, span_end: 4 },
      { evidence_id: 7, span_start: 0, span_end: 1 },
      null,
    ],
  })
  assert.ok(doc)
  assert.deepEqual(doc.supports, [
    { evidence_id: 'EV:aaaa', span_start: 0, span_end: 12 },
    { evidence_id: 'EV:bbbb', span_start: 20, span_end: 44 },
  ])
  assert.deepEqual(asFindingDoc({ finding_id: 'FD:none' })?.supports, [])
  assert.deepEqual(asFindingDoc({ finding_id: 'FD:bad', supports: 'nope' })?.supports, [])
})

test('asFindingListPayload reads search_findings items and history_findings findings', () => {
  const viaItems = asFindingListPayload({
    count: 1,
    items: [{ finding_id: 'FD:1', kind: 'progression', judgment: 'a' }],
  })
  assert.ok(viaItems)
  assert.equal(viaItems.findings.length, 1)
  assert.equal(viaItems.observationCount, 0)
  const viaFindings = asFindingListPayload({
    subject_ts_code: '300308.SZ',
    observations: [{ obs_id: 'o1' }, { obs_id: 'o2' }],
    findings: [{ finding_id: 'FD:2', kind: 'regression', judgment: 'b' }],
  })
  assert.ok(viaFindings)
  assert.equal(viaFindings.findings.length, 1)
  assert.equal(viaFindings.observationCount, 2)
  assert.equal(asFindingListPayload({}), undefined)
  assert.equal(asFindingListPayload('text'), undefined)
})

test('findingKindLabel / findingStatusLabel map known values and pass through', () => {
  assert.equal(findingKindLabel('divergence'), '预期差')
  assert.equal(findingKindLabel('progression'), '递进')
  assert.equal(findingKindLabel('regression'), '恶化')
  assert.equal(findingKindLabel('new_event'), '新增事件')
  assert.equal(findingKindLabel('association'), '关联传导')
  assert.equal(findingKindLabel('weird'), 'weird')
  assert.equal(findingKindLabel(undefined), '未知')
  assert.equal(findingStatusLabel('candidate'), '候选')
  assert.equal(findingStatusLabel('superseded'), '已被取代')
  assert.equal(findingStatusLabel('dismissed'), '已驳回')
  assert.equal(findingStatusLabel(undefined), '')
})

test('formatConfidence scales 0..1 to percent and leaves >1 as-is', () => {
  assert.equal(formatConfidence(0.72), '72%')
  assert.equal(formatConfidence(0.5), '50%')
  assert.equal(formatConfidence(0.85), '85%')
  assert.equal(formatConfidence(85), '85%')
  assert.equal(formatConfidence(undefined), '')
  assert.equal(formatConfidence(Number.NaN), '')
})
