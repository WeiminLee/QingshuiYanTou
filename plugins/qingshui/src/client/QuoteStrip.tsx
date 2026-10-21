import { useEffect, useState } from 'react'
import { BOARD_INDEXES, type BoardQuote } from '../quote-strip.ts'

type Load =
  | { status: 'loading' }
  | { status: 'ok'; quotes: BoardQuote[] }
  | { status: 'absent' }

function absentBoards(): BoardQuote[] {
  return BOARD_INDEXES.map(board => ({
    tsCode: board.tsCode,
    label: board.label,
    name: board.label,
    close: null,
    pct: null,
    direction: 'absent',
    tradeDate: '',
  }))
}

/** Four board quotes across the top of the research column. */
export function QuoteStrip(): React.ReactElement {
  const [load, setLoad] = useState<Load>({ status: 'loading' })

  useEffect(() => {
    let cancelled = false
    const pull = (): void => {
      void fetch('/qingshui/market-snapshot', { headers: { accept: 'application/json' } })
        .then(async (res) => {
          if (!res.ok) return { status: 'absent' } as const
          const body = await res.json() as { quotes?: BoardQuote[] }
          if (!Array.isArray(body.quotes) || body.quotes.length === 0) return { status: 'absent' } as const
          return { status: 'ok', quotes: body.quotes } as const
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

  const quotes = load.status === 'ok' ? load.quotes : absentBoards()
  const tradeDate = quotes.find(quote => quote.tradeDate !== '')?.tradeDate ?? ''
  return (
    <div className="qs-boards" role="status" aria-label={tradeDate === '' ? '行情' : `行情 ${tradeDate}`}>
      {quotes.map(quote => (
        <div key={quote.tsCode} className="qs-board" title={quote.name}>
          <span className="qs-board-name">{quote.label}</span>
          <span className="qs-board-figures">
            {quote.close === null ? null : <span className="qs-board-close">{quote.close}</span>}
            <span className={quote.direction === 'up' ? 'qs-board-up' : quote.direction === 'down' ? 'qs-board-down' : 'qs-board-flat'}>
              {quote.pct ?? '暂无'}
            </span>
          </span>
        </div>
      ))}
    </div>
  )
}
