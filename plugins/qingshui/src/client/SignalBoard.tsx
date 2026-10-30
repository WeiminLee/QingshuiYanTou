import { useEffect, useState } from 'react'
import { laneScrollRows, signalAnalysisPrompt, type SignalCard, type SignalLaneView } from '../signal-board.ts'

type Load =
  | { status: 'loading' }
  | { status: 'ok'; lanes: SignalLaneView[] }
  | { status: 'absent' }

function rowText(item: SignalCard): string {
  return item.tag === '' ? item.summary : `${item.tag} ${item.summary}`
}

/** Four processed-signal lanes. `rows` caps each lane; `dock` sits above the composer. */
export function SignalBoard(props: { onAsk: (text: string) => void; rows?: number; dock?: boolean }): React.ReactElement {
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
      void fetch('/qingshui/signals', { headers: { accept: 'application/json' } })
        .then(async (res) => {
          if (!res.ok) return { status: 'absent' } as const
          const body = await res.json() as { lanes?: SignalLaneView[] }
          if (!Array.isArray(body.lanes) || body.lanes.length === 0) return { status: 'absent' } as const
          return { status: 'ok', lanes: body.lanes } as const
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

  const lanes = load.status === 'ok' ? load.lanes : []
  return (
    <section
      className={props.dock === true ? 'qs-signals qs-signals-dock' : 'qs-signals'}
      aria-label="信号"
      data-state={load.status}
    >
      {load.status !== 'ok' ? (
        <p className="qs-signal-empty">{load.status === 'loading' ? '正在取信号' : '信号暂时取不到'}</p>
      ) : lanes.map(lane => {
        const { rows, roll } = laneScrollRows(lane.items, props.rows, reduced)
        const bodyStyle = roll && props.rows !== undefined ? { height: `${props.rows * 26}px` } : undefined
        const trackStyle = roll ? { animationDuration: `${Math.max(lane.items.length * 4, 16)}s` } : undefined
        return (
        <div key={lane.id} className="qs-signal-lane">
          <div className="qs-signal-lane-name">{lane.label}</div>
          {lane.absent ? <p className="qs-signal-empty">暂时取不到</p> : lane.items.length === 0 ? (
            <p className="qs-signal-empty">还没有</p>
          ) : (
            <div className="qs-signal-body" data-roll={roll ? 'true' : undefined} style={bodyStyle}>
              <div className={roll ? 'qs-signal-track qs-signal-track-roll' : 'qs-signal-track'} style={trackStyle}>
                {rows.map((item, index) => {
                  const clone = roll && index >= lane.items.length
                  return (
                  <button
                    key={`${item.signalId}-${index}`}
                    type="button"
                    className="qs-signal-row"
                    title={item.subject === '' ? item.summary : item.subject}
                    aria-hidden={clone ? true : undefined}
                    tabIndex={clone ? -1 : undefined}
                    onClick={() => { props.onAsk(signalAnalysisPrompt(item)) }}
                  >
                    <span className={item.direction === 'up' ? 'qs-signal-mark qs-board-up' : item.direction === 'down' ? 'qs-signal-mark qs-board-down' : 'qs-signal-mark qs-board-flat'}>
                      {item.mark}
                    </span>
                    <span className="qs-signal-text">{rowText(item)}</span>
                  </button>
                  )
                })}
              </div>
            </div>
          )}
        </div>
        )
      })}
    </section>
  )
}
