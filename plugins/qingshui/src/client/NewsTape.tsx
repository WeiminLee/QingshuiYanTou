import { useEffect, useState } from 'react'
import { newsAnalysisPrompt, type NewsItem } from '../news-tape.ts'

type Load =
  | { status: 'loading' }
  | { status: 'ok'; items: NewsItem[] }
  | { status: 'absent' }

/** Scrolling telegraph. A row sends that item into the expected-gap chat. */
export function NewsTape(props: { onAsk: (text: string) => void }): React.ReactElement {
  const [load, setLoad] = useState<Load>({ status: 'loading' })
  const [reduced, setReduced] = useState(false)

  useEffect(() => {
    const media = window.matchMedia('(prefers-reduced-motion: reduce)')
    const apply = (): void => { setReduced(media.matches) }
    apply()
    media.addEventListener('change', apply)
    return () => { media.removeEventListener('change', apply) }
  }, [])

  useEffect(() => {
    let cancelled = false
    const pull = (): void => {
      void fetch('/qingshui/news', { headers: { accept: 'application/json' } })
        .then(async (res) => {
          if (!res.ok) return { status: 'absent' } as const
          const body = await res.json() as { items?: NewsItem[] }
          if (!Array.isArray(body.items)) return { status: 'absent' } as const
          return { status: 'ok', items: body.items } as const
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

  const items = load.status === 'ok' ? load.items : []
  const animate = !reduced && items.length > 1
  const rows = animate ? [...items, ...items] : items
  const empty = load.status === 'loading' ? '正在取快讯' : load.status === 'absent' ? '快讯暂时取不到' : '快讯还没到'

  return (
    <section className="qs-tape" aria-label="快讯" data-state={items.length > 0 ? 'ready' : load.status}>
      {items.length === 0 ? <p className="qs-tape-empty">{empty}</p> : (
        <div
          className={animate ? 'qs-tape-track' : 'qs-tape-track qs-tape-still'}
          style={animate ? { animationDuration: `${Math.max(items.length * 7, 42)}s` } : undefined}
        >
          {rows.map((item, index) => {
            const clone = animate && index >= items.length
            return (
            <button
              key={`${item.eventId}-${index}`}
              type="button"
              className="qs-tape-row"
              title="用这条快讯看预期差"
              aria-hidden={clone ? true : undefined}
              tabIndex={clone ? -1 : undefined}
              onClick={() => { props.onAsk(newsAnalysisPrompt(item)) }}
            >
              <span className="qs-tape-time">{item.timeLabel}</span>
              <span className="qs-tape-title">{item.title}</span>
              <span className="qs-tape-go">分析预期差</span>
            </button>
            )
          })}
        </div>
      )}
    </section>
  )
}
