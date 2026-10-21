/** Latest telegraph rows for the research-shell news tape. */

export type NewsItem = {
  eventId: string
  title: string
  source: string
  publishAt: string
  timeLabel: string
}

function asRecord(value: unknown): Record<string, unknown> | undefined {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) return undefined
  return value as Record<string, unknown>
}

/** Map stored source codes onto the label a reader expects. */
export function newsSourceLabel(source: string): string {
  if (source === 'tushare' || source === 'cls') return '财联社'
  if (source === 'eastmoney_flash') return '东财'
  if (source === 'wallstreetcn') return '华尔街见闻'
  if (source === 'ths') return '同花顺'
  if (source === 'sina') return '新浪'
  return source === '' ? '快讯' : source
}

/** Shanghai clock, `MM-DD HH:mm`. Unparseable strings pass through trimmed. */
export function formatNewsTime(raw: string): string {
  const trimmed = raw.trim()
  if (trimmed === '') return ''
  const parsed = new Date(trimmed.includes('T') || trimmed.endsWith('Z') ? trimmed : trimmed.replace(' ', 'T'))
  if (Number.isNaN(parsed.getTime())) return trimmed.slice(0, 16)
  const parts = new Intl.DateTimeFormat('en-GB', {
    timeZone: 'Asia/Shanghai',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  }).formatToParts(parsed)
  const pick = (type: Intl.DateTimeFormatPartTypes): string => parts.find(part => part.type === type)?.value ?? ''
  return `${pick('month')}-${pick('day')} ${pick('hour')}:${pick('minute')}`
}

/**
 * Prompt that starts an expected-gap turn for one telegraph item.
 * The title is the surface; the instruction tells the analyst not to stop there.
 */
export function newsAnalysisPrompt(item: Pick<NewsItem, 'eventId' | 'title' | 'source'>): string {
  return `分析这条${item.source}快讯的预期差：${item.title}。事件编号 ${item.eventId}。先用 get_event_detail 取全文，再按预期差流程看它指向的主体和维度有没有新的边际变化。不要把标题复述成结论。`
}

/**
 * Shape a knowledge `events/recent` payload into tape rows.
 * @param payload - JSON body.
 */
export function shapeNewsFeed(payload: unknown): NewsItem[] {
  const body = asRecord(payload)
  if (body === undefined || !Array.isArray(body.items)) return []
  const items: NewsItem[] = []
  for (const raw of body.items) {
    const row = asRecord(raw)
    if (row === undefined) continue
    const eventId = typeof row.event_id === 'string' ? row.event_id.trim() : ''
    const title = typeof row.title === 'string' ? row.title.trim() : ''
    if (eventId === '' || title === '') continue
    const source = newsSourceLabel(typeof row.source === 'string' ? row.source : '')
    const publishAt = typeof row.publish_at === 'string' ? row.publish_at : ''
    items.push({ eventId, title, source, publishAt, timeLabel: formatNewsTime(publishAt) })
  }
  return items
}
