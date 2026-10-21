/**
 * Pure extraction/validation helpers for qingshui toolviews.
 * No react import: this module is unit-tested under plain node (tsx).
 *
 * A toolview receives the frozen call block: a running call (no `kind`) or a
 * settled tool-result node (`kind: 'tool-result'`, content/isError/meta).
 * Structured data reaches the card through, in preference order:
 *   1. settled `block.meta` (native tools' presentationMeta payload);
 *   2. JSON.parse of the settled block's flattened text (MCP twins return a
 *      JSON string; native json-schema tools render pretty JSON);
 *   3. undefined — the card falls back to raw text.
 * fetch_evidence is the case where (2) fails for the native tool: its text
 * render is a formatted string, so only (1) carries the doc.
 */

export interface RunningBlock {
  callId: string
  name: string
  argsRaw: string
}

export interface SettledBlock {
  kind: 'tool-result'
  callId: string
  call: { name: string; argsRaw: string } | null
  content: readonly unknown[]
  isError: boolean
  error?: { name: string; code: string } | undefined
  meta?: unknown
}

export type ToolviewBlock = RunningBlock | SettledBlock

export type ToolviewState = 'running' | 'ok' | 'error'

export function isSettled(block: ToolviewBlock): block is SettledBlock {
  return 'kind' in block
}

export function blockState(block: ToolviewBlock): ToolviewState {
  if (!isSettled(block)) return 'running'
  return block.isError ? 'error' : 'ok'
}

/** Parse the call args (running: block.argsRaw; settled: block.call.argsRaw). */
export function blockArgs(block: ToolviewBlock): Record<string, unknown> {
  const raw = isSettled(block) ? block.call?.argsRaw ?? '' : block.argsRaw
  if (raw === '') return {}
  try {
    const value: unknown = JSON.parse(raw)
    return typeof value === 'object' && value !== null && !Array.isArray(value)
      ? value as Record<string, unknown>
      : {}
  } catch {
    return {}
  }
}

/** Flatten a settled block's content to display text (text blocks verbatim, others as JSON). */
export function blockText(block: SettledBlock): string {
  const parts: string[] = []
  for (const item of block.content) {
    if (
      typeof item === 'object' && item !== null
      && (item as { type?: unknown }).type === 'text'
      && typeof (item as { text?: unknown }).text === 'string'
    ) {
      parts.push((item as { text: string }).text)
    } else {
      parts.push(JSON.stringify(item, null, 2))
    }
  }
  if (parts.length === 0 && block.error !== undefined) {
    parts.push(`${block.error.name}: ${block.error.code}`)
  }
  return parts.join('\n')
}

/** Structured result: persisted meta first, then JSON.parse of the flattened text. */
export function extractResultJson(block: SettledBlock): unknown {
  if (block.meta !== undefined && block.meta !== null) return block.meta
  const text = blockText(block).trim()
  if (text === '') return undefined
  try {
    return JSON.parse(text) as unknown
  } catch {
    return undefined
  }
}

function asRecord(value: unknown): Record<string, unknown> | undefined {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : undefined
}

function asString(value: unknown): string | undefined {
  return typeof value === 'string' && value !== '' ? value : undefined
}

function asNumber(value: unknown): number | undefined {
  const n = typeof value === 'number' ? value : typeof value === 'string' ? Number(value) : NaN
  return Number.isFinite(n) ? n : undefined
}

// ── get_kline ────────────────────────────────────────────────────────────────

export interface KlineItem {
  trade_date: string
  open: number
  high: number
  low: number
  close: number
  volume: number
  amount?: number | undefined
  pct_chg?: number | undefined
}

export interface KlinePayload {
  ts_code: string
  start_date: string
  end_date: string
  freq: string
  count: number
  items: KlineItem[]
  text?: string | undefined
}

export function asKlinePayload(value: unknown): KlinePayload | undefined {
  const o = asRecord(value)
  if (o === undefined || !Array.isArray(o.items)) return undefined
  const items: KlineItem[] = []
  for (const raw of o.items) {
    const item = asRecord(raw)
    if (item === undefined) continue
    const open = asNumber(item.open)
    const high = asNumber(item.high)
    const low = asNumber(item.low)
    const close = asNumber(item.close)
    if (open === undefined || high === undefined || low === undefined || close === undefined) continue
    items.push({
      trade_date: asString(item.trade_date) ?? '',
      open,
      high,
      low,
      close,
      volume: asNumber(item.volume) ?? 0,
      amount: asNumber(item.amount),
      pct_chg: asNumber(item.pct_chg),
    })
  }
  return {
    ts_code: asString(o.ts_code) ?? '',
    start_date: asString(o.start_date) ?? '',
    end_date: asString(o.end_date) ?? '',
    freq: asString(o.freq) ?? 'D',
    count: asNumber(o.count) ?? items.length,
    items,
    text: asString(o.text),
  }
}

/** '20260511' → '2026-05-11'; other shapes pass through. */
export function formatTradeDate(raw: string): string {
  return /^\d{8}$/.test(raw) ? `${raw.slice(0, 4)}-${raw.slice(4, 6)}-${raw.slice(6, 8)}` : raw
}

/** K 线周期中文标签：D→日K，W→周K，M→月K；其他原样返回。 */
export function freqLabel(freq: string): string {
  const labels: Record<string, string> = { D: '日K', W: '周K', M: '月K' }
  return labels[freq.toUpperCase()] ?? freq
}

/** 成交量万/亿缩写：32265543 → 3226.6万；2.5e8 → 2.50亿。 */
export function formatVolume(volume: number): string {
  const abs = Math.abs(volume)
  if (abs >= 1e8) return `${(volume / 1e8).toFixed(2)}亿`
  if (abs >= 1e4) return `${(volume / 1e4).toFixed(1)}万`
  return String(Math.round(volume))
}

function formatPrice(value: number): string {
  return value.toFixed(2)
}

export interface KlineTooltipParam {
  dataIndex: number
  axisValue?: string | number | undefined
}

/** Axis-trigger tooltip rows: date + 开/收/低/高 + 成交量（万/亿）。 */
export function formatKlineTooltip(items: readonly KlineItem[], params: readonly KlineTooltipParam[]): string {
  const first = params[0]
  if (first === undefined) return ''
  const item = items[first.dataIndex]
  if (item === undefined) return ''
  const date = first.axisValue !== undefined && first.axisValue !== ''
    ? String(first.axisValue)
    : formatTradeDate(item.trade_date)
  return [
    date,
    `开盘：${formatPrice(item.open)}`,
    `收盘：${formatPrice(item.close)}`,
    `最低：${formatPrice(item.low)}`,
    `最高：${formatPrice(item.high)}`,
    `成交量：${formatVolume(item.volume)}`,
  ].join('<br/>')
}

// ── source_type badges ───────────────────────────────────────────────────────

export const SOURCE_TYPE_LABELS: Record<string, string> = {
  announcement: '公告',
  annual_report: '年报',
  research_report: '研报',
  irm: '互动易',
  news: '新闻',
  market: '行情',
  upload: '上传',
}

export function sourceTypeLabel(sourceType: string | undefined): string {
  if (sourceType === undefined || sourceType === '') return '未知'
  return SOURCE_TYPE_LABELS[sourceType] ?? sourceType
}

// ── fetch_evidence ───────────────────────────────────────────────────────────

export interface EvidenceDoc {
  evidence_id: string
  source_type: string
  source_name: string
  publish_date?: string | undefined
  confidence?: number | undefined
  text_excerpt: string
  title?: string | undefined
  ts_code?: string | undefined
  pdf_url?: string | undefined
}

export function asEvidenceDoc(value: unknown): EvidenceDoc | undefined {
  const o = asRecord(value)
  if (o === undefined) return undefined
  if (typeof o.error === 'string') return undefined
  const evidenceId = asString(o.evidence_id)
  const sourceName = asString(o.source_name)
  const excerpt = typeof o.text_excerpt === 'string' ? o.text_excerpt : undefined
  if (evidenceId === undefined && sourceName === undefined && excerpt === undefined) return undefined
  const subject = asRecord(o.subject_hint)
  const sourceRef = asRecord(o.source_ref)
  const metadata = asRecord(o.metadata)
  return {
    evidence_id: evidenceId ?? '',
    source_type: asString(o.source_type) ?? '',
    source_name: sourceName ?? '',
    publish_date: asString(o.publish_date),
    confidence: asNumber(o.confidence),
    text_excerpt: excerpt ?? '',
    title: asString(subject?.title) ?? asString(metadata?.title),
    ts_code: asString(subject?.ts_code),
    pdf_url: asString(sourceRef?.pdf_url),
  }
}

/**
 * Parent announcement id carried by an evidence row (`source_ref.ann_id`).
 * Absent for IRM / research report / upload evidence, which is exactly when
 * the reader falls back to the single-evidence view. Mongo stores announcement
 * ids as ints, so both shapes are read.
 * @param value - raw evidence document.
 * @returns the announcement id, or undefined when the evidence has none.
 */
export function evidenceAnnId(value: unknown): string | undefined {
  const ref = asRecord(asRecord(value)?.source_ref)
  if (ref === undefined) return undefined
  const raw = ref.ann_id
  if (typeof raw === 'string' && raw !== '') return raw
  if (typeof raw === 'number' && Number.isFinite(raw)) return String(raw)
  return undefined
}

/** '2025-04-28 16:00:00+00:00' → '2025-04-28'; '20260416' → '2026-04-16'. */
export function formatDate(value: string | undefined): string {
  if (value === undefined || value === '') return ''
  const head = value.slice(0, 10)
  if (/^\d{4}-\d{2}-\d{2}$/.test(head)) return head
  return formatTradeDate(value)
}

// ── semantic_search ──────────────────────────────────────────────────────────

export interface SearchEntity {
  entity_id: string
  name: string
  type: string
  ts_code?: string | undefined
  score?: number | undefined
}

export interface SearchChunk {
  evidence_id: string
  snippet: string
  source_type: string
  source_name: string
  score?: number | undefined
  publish_date?: string | undefined
  title?: string | undefined
  pdf_url?: string | undefined
}

export interface SearchResultPayload {
  entities: SearchEntity[]
  chunks: SearchChunk[]
}

export function asSearchResult(value: unknown): SearchResultPayload | undefined {
  const o = asRecord(value)
  if (o === undefined) return undefined
  if (!Array.isArray(o.entities) && !Array.isArray(o.chunks)) return undefined
  const entities: SearchEntity[] = []
  for (const raw of Array.isArray(o.entities) ? o.entities : []) {
    const e = asRecord(raw)
    if (e === undefined) continue
    entities.push({
      entity_id: asString(e.entity_id) ?? '',
      name: asString(e.name) ?? '',
      type: asString(e.type) ?? '',
      ts_code: asString(e.ts_code),
      score: asNumber(e.score),
    })
  }
  const chunks: SearchChunk[] = []
  for (const raw of Array.isArray(o.chunks) ? o.chunks : []) {
    const c = asRecord(raw)
    if (c === undefined) continue
    chunks.push({
      evidence_id: asString(c.evidence_id) ?? '',
      snippet: typeof c.snippet === 'string' ? c.snippet : '',
      source_type: asString(c.source_type) ?? '',
      source_name: asString(c.source_name) ?? '',
      score: asNumber(c.score),
      publish_date: asString(c.publish_date),
      title: asString(c.title),
      pdf_url: asString(c.pdf_url),
    })
  }
  return { entities, chunks }
}

// ── pull_history ─────────────────────────────────────────────────────────────

export interface HistoryItem {
  evidence_id: string
  published_at?: string | undefined
  source_type: string
  source_name: string
  text_excerpt: string
  matched_keywords: string[]
}

export interface HistoryPayload {
  items: HistoryItem[]
  count: number
}

export function asHistoryPayload(value: unknown): HistoryPayload | undefined {
  const o = asRecord(value)
  if (o === undefined || !Array.isArray(o.items)) return undefined
  const items: HistoryItem[] = []
  for (const raw of o.items) {
    const item = asRecord(raw)
    if (item === undefined) continue
    items.push({
      evidence_id: asString(item.evidence_id) ?? '',
      published_at: asString(item.published_at),
      source_type: asString(item.source_type) ?? '',
      source_name: asString(item.source_name) ?? '',
      text_excerpt: typeof item.text_excerpt === 'string' ? item.text_excerpt : '',
      matched_keywords: Array.isArray(item.matched_keywords)
        ? item.matched_keywords.filter((k): k is string => typeof k === 'string' && k !== '')
        : [],
    })
  }
  return { items, count: asNumber(o.count) ?? items.length }
}

export interface HistoryGroup {
  date: string
  items: HistoryItem[]
}

/** Group items by calendar day of published_at, preserving arrival order. */
export function groupHistoryByDate(items: readonly HistoryItem[]): HistoryGroup[] {
  const groups: HistoryGroup[] = []
  const byDate = new Map<string, HistoryItem[]>()
  for (const item of items) {
    const date = formatDate(item.published_at) || '未知日期'
    const bucket = byDate.get(date)
    if (bucket === undefined) {
      byDate.set(date, [item])
      groups.push({ date, items: byDate.get(date) as HistoryItem[] })
    } else {
      bucket.push(item)
    }
  }
  return groups
}

// ── findings ledger (history_findings / search_findings) ─────────────────────

export const FINDING_KINDS = ['progression', 'regression', 'new_event', 'association', 'divergence'] as const

export const FINDING_KIND_LABELS: Record<string, string> = {
  progression: '递进',
  regression: '恶化',
  new_event: '新增事件',
  association: '关联传导',
  divergence: '预期差',
}

export function findingKindLabel(kind: string | undefined): string {
  if (kind === undefined || kind === '') return '未知'
  return FINDING_KIND_LABELS[kind] ?? kind
}

export const FINDING_STATUS_LABELS: Record<string, string> = {
  candidate: '候选',
  active: '在用',
  superseded: '已被取代',
  dismissed: '已驳回',
}

export function findingStatusLabel(status: string | undefined): string {
  if (status === undefined || status === '') return ''
  return FINDING_STATUS_LABELS[status] ?? status
}

/** One sentence-level anchor: `[span_start, span_end)` into that evidence body. */
export interface FindingSupport {
  evidence_id: string
  span_start: number
  span_end: number
}

/**
 * Ledger `supports` are `[{obs_id, evidence_id, span_start, span_end}]`, but
 * only the three fields the reader can act on survive. An entry without a
 * usable evidence id or with non-integer offsets cannot be opened or marked,
 * so it is dropped instead of rendered as a dead anchor.
 * @param value - raw `supports` value from a finding row.
 * @returns well-formed supports, in row order.
 */
function asFindingSupports(value: unknown): FindingSupport[] {
  if (!Array.isArray(value)) return []
  const supports: FindingSupport[] = []
  for (const raw of value) {
    const support = asRecord(raw)
    if (support === undefined) continue
    const evidenceId = asString(support.evidence_id)
    if (evidenceId === undefined) continue
    const start = support.span_start
    const end = support.span_end
    if (!Number.isInteger(start) || !Number.isInteger(end)) continue
    supports.push({ evidence_id: evidenceId, span_start: start as number, span_end: end as number })
  }
  return supports
}

export interface FindingDoc {
  finding_id: string
  kind: string
  subject_ts_code: string
  dimension: string
  dimension_scope?: string | undefined
  judgment: string
  confidence?: number | undefined
  support_count: number
  supports: FindingSupport[]
  contradicts: number
  status: string
  supersedes?: string | undefined
  created_at?: string | undefined
}

/** Defensive single-finding parse; supports 恒为 [{obs_id,evidence_id,span…}]，脏锚点丢弃。 */
export function asFindingDoc(value: unknown): FindingDoc | undefined {
  const o = asRecord(value)
  if (o === undefined) return undefined
  const findingId = asString(o.finding_id)
  const judgment = typeof o.judgment === 'string' ? o.judgment : undefined
  if (findingId === undefined && judgment === undefined) return undefined
  return {
    finding_id: findingId ?? '',
    kind: asString(o.kind) ?? '',
    subject_ts_code: asString(o.subject_ts_code) ?? '',
    dimension: asString(o.dimension) ?? '',
    dimension_scope: asString(o.dimension_scope),
    judgment: judgment ?? '',
    confidence: asNumber(o.confidence),
    support_count: asNumber(o.support_count)
      ?? (Array.isArray(o.supports) ? o.supports.length : 0),
    supports: asFindingSupports(o.supports),
    contradicts: Array.isArray(o.contradicts) ? o.contradicts.length : 0,
    status: asString(o.status) ?? '',
    supersedes: asString(o.supersedes),
    created_at: asString(o.created_at),
  }
}

export interface FindingListPayload {
  findings: FindingDoc[]
  observationCount: number
}

/** Reads both ledger shapes: search_findings {items} and history_findings {findings}. */
export function asFindingListPayload(value: unknown): FindingListPayload | undefined {
  const o = asRecord(value)
  if (o === undefined) return undefined
  const raw = Array.isArray(o.items) ? o.items : Array.isArray(o.findings) ? o.findings : undefined
  if (raw === undefined) return undefined
  const findings: FindingDoc[] = []
  for (const item of raw) {
    const doc = asFindingDoc(item)
    if (doc !== undefined) findings.push(doc)
  }
  const observations = Array.isArray(o.observations) ? o.observations : []
  return { findings, observationCount: observations.length }
}

/** confidence 0..1 → '72%'；已是百分数(>1)按原值；缺失 → ''。 */
export function formatConfidence(value: number | undefined): string {
  if (value === undefined || Number.isNaN(value)) return ''
  const pct = Math.abs(value) <= 1 ? value * 100 : value
  return `${Math.round(pct)}%`
}
