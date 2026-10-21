/** Processed signals, grouped into the four desks on the research shell. */

export const SIGNAL_LANE_LIMIT = 4

export type SignalLaneId = 'news' | 'announcement' | 'event' | 'mapping'

export type SignalSource = {
  sourceType: string
  tag: string
}

export type SignalLaneSpec = {
  id: SignalLaneId
  label: string
  sources: SignalSource[]
}

export const SIGNAL_LANES: SignalLaneSpec[] = [
  {
    id: 'news',
    label: '新闻快讯',
    sources: [
      { sourceType: 'news:llm', tag: '' },
      { sourceType: 'news', tag: '' },
    ],
  },
  {
    id: 'announcement',
    label: '公告',
    sources: [
      { sourceType: 'announcement:llm', tag: '' },
      { sourceType: 'announcement', tag: '' },
    ],
  },
  {
    id: 'event',
    label: '事件',
    sources: [
      { sourceType: 'event:llm', tag: '' },
      { sourceType: 'event', tag: '' },
      { sourceType: 'irm:llm', tag: '' },
      { sourceType: 'irm', tag: '' },
    ],
  },
  {
    id: 'mapping',
    label: '美股 / 台股',
    sources: [
      { sourceType: 'us_map:llm', tag: '美股' },
      { sourceType: 'us_map', tag: '美股' },
      { sourceType: 'tw_map:llm', tag: '台股' },
      { sourceType: 'tw_map', tag: '台股' },
    ],
  },
]

export type SignalDirection = 'up' | 'down' | 'flat'

export type SignalCard = {
  signalId: string
  lane: SignalLaneId
  label: string
  tag: string
  subject: string
  summary: string
  mark: string
  direction: SignalDirection
  valueScore: number
}

export type SignalLaneView = {
  id: SignalLaneId
  label: string
  items: SignalCard[]
  absent: boolean
}

function asRecord(value: unknown): Record<string, unknown> | undefined {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) return undefined
  return value as Record<string, unknown>
}

function polarityMark(polarity: string): { mark: string; direction: SignalDirection } {
  if (polarity === 'positive' || polarity === 'bullish') return { mark: '正', direction: 'up' }
  if (polarity === 'negative' || polarity === 'risk' || polarity === 'bearish') return { mark: '负', direction: 'down' }
  return { mark: '平', direction: 'flat' }
}

/**
 * One knowledge list payload into cards. Rows without an id or a sentence are dropped.
 */
export function shapeSignalItems(payload: unknown, lane: SignalLaneSpec, tag: string): SignalCard[] {
  const body = asRecord(payload)
  if (body === undefined || !Array.isArray(body.items)) return []
  const cards: SignalCard[] = []
  for (const raw of body.items) {
    const row = asRecord(raw)
    if (row === undefined) continue
    const signalId = typeof row.signal_id === 'string' ? row.signal_id.trim() : ''
    const summaryRaw = typeof row.summary === 'string' ? row.summary.trim() : ''
    const title = typeof row.title === 'string' ? row.title.trim() : ''
    const summary = summaryRaw !== '' ? summaryRaw : title
    if (signalId === '' || summary === '') continue
    const subject = typeof row.subject_name === 'string' ? row.subject_name.trim() : ''
    const polarity = typeof row.polarity === 'string' ? row.polarity : ''
    const valueScore = typeof row.value_score === 'number' && Number.isFinite(row.value_score) ? row.value_score : 0
    const marked = polarityMark(polarity)
    cards.push({
      signalId,
      lane: lane.id,
      label: lane.label,
      tag,
      subject,
      summary,
      mark: marked.mark,
      direction: marked.direction,
      valueScore,
    })
  }
  return cards
}

/** Highest value first. The same signal from two source queries is kept once. */
export function mergeSignals(items: SignalCard[], limit = SIGNAL_LANE_LIMIT): SignalCard[] {
  const seen = new Set<string>()
  const ranked = [...items].sort((a, b) => b.valueScore - a.valueScore)
  const kept: SignalCard[] = []
  for (const item of ranked) {
    if (seen.has(item.signalId)) continue
    seen.add(item.signalId)
    kept.push(item)
    if (kept.length >= limit) break
  }
  return kept
}

/**
 * Ask the analyst to go under a signal that was already extracted from raw text.
 */
export function signalAnalysisPrompt(item: Pick<SignalCard, 'label' | 'tag' | 'summary' | 'subject' | 'signalId'>): string {
  const where = item.tag === '' ? item.label : `${item.tag}映射`
  const subject = item.subject === '' ? '' : `主体 ${item.subject}。`
  return `分析这条${where}信号的预期差：${item.summary}。${subject}信号 ${item.signalId}。这是从原始材料抽出的信号，继续看边际变化，不要把摘要复述成结论。`
}

/**
 * Load the four lanes. A source that throws is skipped; a lane is absent only when every source threw.
 */
export async function loadSignalBoard(
  list: (sourceType: string, limit: number) => Promise<unknown>,
): Promise<SignalLaneView[]> {
  return Promise.all(SIGNAL_LANES.map(async lane => {
    const batches = await Promise.all(lane.sources.map(async source => {
      try {
        const payload = await list(source.sourceType, SIGNAL_LANE_LIMIT)
        return shapeSignalItems(payload, lane, source.tag)
      } catch {
        return null
      }
    }))
    const absent = batches.every(batch => batch === null)
    const items = mergeSignals(batches.flatMap(batch => batch ?? []))
    return { id: lane.id, label: lane.label, items, absent }
  }))
}
