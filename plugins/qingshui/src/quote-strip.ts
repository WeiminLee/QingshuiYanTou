/** Board quotes on the research shell. 科创板 uses 科创50, 北交所 uses 北证50. */

export const SHANGHAI_TS_CODE = '000001.SH'

export const BOARD_INDEXES = [
  { tsCode: '000001.SH', label: '上证' },
  { tsCode: '399006.SZ', label: '创业板' },
  { tsCode: '000688.SH', label: '科创板' },
  { tsCode: '899050.BJ', label: '北交所' },
] as const

export type IndexQuote = {
  tsCode: string
  name: string
  close: string
  pct: string
  up: boolean
  tradeDate: string
}

export type BoardDirection = 'up' | 'down' | 'flat' | 'absent'

export type BoardQuote = {
  tsCode: string
  label: string
  name: string
  close: string | null
  pct: string | null
  direction: BoardDirection
  tradeDate: string
}

function asRecord(value: unknown): Record<string, unknown> | undefined {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) return undefined
  return value as Record<string, unknown>
}

function formatClose(value: unknown): string | undefined {
  const n = typeof value === 'number' ? value : typeof value === 'string' ? Number(value) : NaN
  if (!Number.isFinite(n)) return undefined
  return n.toFixed(2)
}

function formatPct(value: unknown): { text: string; up: boolean } | undefined {
  const n = typeof value === 'number' ? value : typeof value === 'string' ? Number(value) : NaN
  if (!Number.isFinite(n)) return undefined
  const sign = n > 0 ? '+' : ''
  return { text: `${sign}${n.toFixed(2)}%`, up: n > 0 }
}

/**
 * Pick the Shanghai composite from a market snapshot payload.
 * @param payload - Knowledge `/market/snapshot` JSON.
 * @returns the strip row, or null when that index is absent.
 */
export function pickShanghaiQuote(payload: unknown): IndexQuote | null {
  const body = asRecord(payload)
  if (body === undefined || !Array.isArray(body.indices)) return null
  const tradeDate = typeof body.trade_date === 'string' ? body.trade_date : ''
  for (const item of body.indices) {
    const row = asRecord(item)
    if (row === undefined || row.ts_code !== SHANGHAI_TS_CODE) continue
    const close = formatClose(row.close)
    const pct = formatPct(row.pct_chg)
    const name = typeof row.name === 'string' ? row.name : ''
    if (close === undefined || pct === undefined || name === '') return null
    return { tsCode: SHANGHAI_TS_CODE, name, close, pct: pct.text, up: pct.up, tradeDate }
  }
  return null
}

function quoteFromRow(row: Record<string, unknown> | undefined, tradeDate: string, tsCode: string, label: string): BoardQuote {
  const absent: BoardQuote = {
    tsCode, label, name: label, close: null, pct: null, direction: 'absent', tradeDate,
  }
  if (row === undefined) return absent
  const close = formatClose(row.close)
  const pct = formatPct(row.pct_chg)
  const name = typeof row.name === 'string' && row.name !== '' ? row.name : label
  if (close === undefined || pct === undefined) return { ...absent, name }
  const direction: BoardDirection = pct.text.startsWith('+') ? 'up' : pct.text.startsWith('-') ? 'down' : 'flat'
  return { tsCode, label, name, close, pct: pct.text, direction, tradeDate }
}

/**
 * Four board rows in display order. A missing index stays in the strip as absent.
 * @param payload - Knowledge `/market/snapshot` JSON.
 */
export function pickBoardQuotes(payload: unknown): BoardQuote[] {
  const body = asRecord(payload)
  const tradeDate = body !== undefined && typeof body.trade_date === 'string' ? body.trade_date : ''
  const byCode = new Map<string, Record<string, unknown>>()
  if (body !== undefined && Array.isArray(body.indices)) {
    for (const item of body.indices) {
      const row = asRecord(item)
      if (row !== undefined && typeof row.ts_code === 'string') byCode.set(row.ts_code, row)
    }
  }
  return BOARD_INDEXES.map(board => quoteFromRow(byCode.get(board.tsCode), tradeDate, board.tsCode, board.label))
}
