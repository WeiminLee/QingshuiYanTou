import { useEffect, useState } from 'react'
import { pickOverseasMarkets, type OverseasDirection, type OverseasMarket } from '../overseas-strip.ts'

type Load =
  | { status: 'loading' }
  | { status: 'ok'; asOf: string; markets: OverseasMarket[] }
  | { status: 'absent' }

function dirClass(direction: OverseasDirection): string {
  if (direction === 'up') return 'qs-overseas-up'
  if (direction === 'down') return 'qs-overseas-down'
  return 'qs-overseas-flat'
}

/** US / TW / KR core tickers under the board quotes. Hidden when the API is absent. */
export function OverseasStrip(): React.ReactElement | null {
  const [load, setLoad] = useState<Load>({ status: 'loading' })

  useEffect(() => {
    let cancelled = false
    const pull = (): void => {
      void fetch('/qingshui/overseas-snapshot', { headers: { accept: 'application/json' } })
        .then(async (res) => {
          if (!res.ok) return { status: 'absent' } as const
          const body = await res.json() as Record<string, unknown>
          const markets = pickOverseasMarkets(body, 4)
          if (markets.length === 0) return { status: 'absent' } as const
          return {
            status: 'ok',
            asOf: typeof body.as_of === 'string' ? body.as_of : '',
            markets,
          } as const
        })
        .catch(() => ({ status: 'absent' } as const))
        .then(next => { if (!cancelled) setLoad(next) })
    }
    pull()
    const timer = setInterval(pull, 60_000)
    return () => {
      cancelled = true
      clearInterval(timer)
    }
  }, [])

  if (load.status !== 'ok') return null

  return (
    <div className="qs-overseas" role="status" aria-label="外围市场">
      <div className="qs-overseas-head">
        <span>外围市场</span>
        <span className="qs-overseas-date">{load.asOf}</span>
      </div>
      {load.markets.map(market => (
        <div className="qs-overseas-row" key={market.market}>
          <span className="qs-overseas-market">{market.name}</span>
          <span className={`qs-overseas-pct ${dirClass(market.direction)}`}>
            {market.pct ?? '—'}
          </span>
          <div className="qs-overseas-symbols">
            {market.symbols.map(symbol => (
              <span className="qs-overseas-symbol" key={symbol.tsCode} title={symbol.name}>
                <span className="qs-overseas-name">{symbol.name}</span>
                <span className={dirClass(symbol.direction)}>{symbol.pct ?? '—'}</span>
              </span>
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}
