/** Day buckets for the research-session sidebar. Local calendar, not UTC. */

export type SessionBucket = 'today' | 'yesterday' | 'earlier'

export type GroupedSessions<T> = {
  bucket: SessionBucket
  rows: T[]
}

/** Which sidebar group a timestamp belongs to. */
export function sessionBucket(updatedAt: number, now: number): SessionBucket {
  const start = new Date(now)
  start.setHours(0, 0, 0, 0)
  const startMs = start.getTime()
  if (updatedAt >= startMs) return 'today'
  const yesterday = new Date(start)
  yesterday.setDate(yesterday.getDate() - 1)
  if (updatedAt >= yesterday.getTime()) return 'yesterday'
  return 'earlier'
}

/** 24-hour clock for a session row. */
export function sessionClock(updatedAt: number): string {
  const date = new Date(updatedAt)
  const hours = String(date.getHours()).padStart(2, '0')
  const minutes = String(date.getMinutes()).padStart(2, '0')
  return `${hours}:${minutes}`
}

/** Sidebar row stamp: HH:mm for today/yesterday, MM-DD for anything older. */
export function sessionStamp(updatedAt: number, bucket: SessionBucket): string {
  if (bucket === 'earlier') {
    const date = new Date(updatedAt)
    const month = String(date.getMonth() + 1).padStart(2, '0')
    const day = String(date.getDate()).padStart(2, '0')
    return `${month}-${day}`
  }
  return sessionClock(updatedAt)
}

const BUCKET_ORDER: SessionBucket[] = ['today', 'yesterday', 'earlier']

/** Keep the incoming order inside each non-empty day group. */
export function groupSessionRows<T extends { updatedAt: number }>(
  rows: readonly T[],
  now: number,
): GroupedSessions<T>[] {
  const buckets: Record<SessionBucket, T[]> = { today: [], yesterday: [], earlier: [] }
  for (const row of rows) buckets[sessionBucket(row.updatedAt, now)].push(row)
  return BUCKET_ORDER
    .filter(bucket => buckets[bucket].length > 0)
    .map(bucket => ({ bucket, rows: buckets[bucket] }))
}
