/** Overseas market strip: US / TW / KR core tickers. */

export type OverseasDirection = 'up' | 'down' | 'flat' | 'absent'

export type OverseasSymbol = {
  tsCode: string
  name: string
  close: number | null
  pct: string | null
  direction: OverseasDirection
}

export type OverseasMarket = {
  market: string
  name: string
  tradeDate: string
  pct: string | null
  direction: OverseasDirection
  symbols: OverseasSymbol[]
}

function asRecord(value: unknown): Record<string, unknown> | undefined {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) return undefined
  return value as Record<string, unknown>
}

function asNumber(value: unknown): number | null {
  const n = typeof value === 'number' ? value : typeof value === 'string' ? Number(value) : NaN
  return Number.isFinite(n) ? n : null
}

function formatPct(n: number | null): { text: string | null; direction: OverseasDirection } {
  if (n === null) return { text: null, direction: 'absent' }
  const sign = n > 0 ? '+' : ''
  return { text: `${sign}${n.toFixed(2)}%`, direction: n > 0 ? 'up' : n < 0 ? 'down' : 'flat' }
}

/**
 * Normalize the Knowledge `/market/overseas` payload into strip rows.
 * @param payload - backend JSON.
 * @param limit - tickers shown per market.
 * @returns markets in US/TW/KR order; empty when the payload is unusable.
 */
export function pickOverseasMarkets(payload: unknown, limit = 4): OverseasMarket[] {
  const body = asRecord(payload)
  if (body === undefined || !Array.isArray(body.markets)) return []
  const rows: OverseasMarket[] = []
  for (const raw of body.markets) {
    const item = asRecord(raw)
    if (item === undefined) continue
    const symbolsRaw = Array.isArray(item.symbols) ? item.symbols : []
    const symbols: OverseasSymbol[] = []
    for (const rawSymbol of symbolsRaw.slice(0, limit)) {
      const symbol = asRecord(rawSymbol)
      if (symbol === undefined) continue
      const pct = formatPct(asNumber(symbol.pct_chg))
      symbols.push({
        tsCode: typeof symbol.ts_code === 'string' ? symbol.ts_code : '',
        name: typeof symbol.name === 'string' ? symbol.name : '',
        close: asNumber(symbol.close),
        pct: pct.text,
        direction: pct.direction,
      })
    }
    const marketPct = formatPct(asNumber(item.pct_chg))
    rows.push({
      market: typeof item.market === 'string' ? item.market : '',
      name: typeof item.name === 'string' ? item.name : '',
      tradeDate: typeof item.trade_date === 'string' ? item.trade_date : '',
      pct: marketPct.text,
      direction: marketPct.direction,
      symbols,
    })
  }
  return rows
}
