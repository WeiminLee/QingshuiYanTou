/**
 * EvCiteLayer: one portal-mounted interaction layer for EV citation chips.
 * Hover (delegated from the assistant step views) shows an anchored preview;
 * chip clicks pin a larger card. Evidence bodies come from the same-origin
 * host route through the store's cache.
 */
import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from 'react'
import { createPortal } from 'react-dom'
import { openEvidenceArtifact } from './artifact-store.ts'
import { evIdOf } from './ev-cite.ts'
import {
  closeEvHover, fetchEvEvidence, getEvCiteState, getEvEvidence,
  invalidateEvEvidence, openEvHover, subscribeEvCite, type EvAnchor,
} from './ev-cite-store.ts'
import { asEvidenceDoc, formatDate, sourceTypeLabel } from './toolviews/model.ts'

const HOVER_OPEN_DELAY_MS = 250
const HOVER_CLOSE_GRACE_MS = 150

/** Hover id the popover itself has claimed (moving onto it keeps it open). */
let popoverHoverId: string | undefined

export function EvCiteLayer(): React.ReactElement | null {
  const state = useSyncExternalStore(subscribeEvCite, getEvCiteState)
  if (state.mode !== 'hover') return null
  return createPortal(<EvPopover id={state.id} anchor={state.anchor} />, document.body)
}

/** Anchored hover preview: follows the chip rect, clamped to the viewport. */
function EvPopover({ id, anchor }: { id: string; anchor: EvAnchor }): React.ReactElement {
  const content = <EvBody id={id} lines={4} />
  const [style, setStyle] = useState<React.CSSProperties | null>(null)
  const placementRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    const popover = placementRef.current
    if (popover !== null) {
      const margin = 8
      const { innerWidth, innerHeight } = window
      const width = Math.min(420, innerWidth - 2 * margin)
      const height = popover.offsetHeight
      let x = anchor.x + anchor.width / 2 - width / 2
      x = Math.min(Math.max(margin, x), innerWidth - width - margin)
      const fitsBelow = anchor.y + anchor.height + 6 + height <= innerHeight - margin
      const y = fitsBelow ? anchor.y + anchor.height + 6 : Math.max(margin, anchor.y - height - 6)
      setStyle({ left: `${Math.round(x)}px`, top: `${Math.round(y)}px`, width: `${width}px` })
    }
    const dismiss = (): void => { closeEvHover(id) }
    window.addEventListener('scroll', dismiss, { capture: true, passive: true })
    window.addEventListener('resize', dismiss, { passive: true })
    return () => {
      window.removeEventListener('scroll', dismiss, { capture: true } as EventListenerOptions)
      window.removeEventListener('resize', dismiss)
    }
  }, [anchor, id])

  return (
    <div
      ref={placementRef}
      className="qs-ev-pop"
      style={style ?? { position: 'fixed', left: '-9999px', top: '0px' }}
      onMouseEnter={() => { popoverHoverId = id }}
      onMouseLeave={() => { popoverHoverId = undefined; closeEvHover(id) }}
    >
      {content}
    </div>
  )
}

/** Evidence body shared by the hover preview, the side rail, and the research panel. */
export function EvBody({ id, lines }: { id: string; lines: number }): React.ReactElement {
  const entry = useEvEvidence(id)
  const [expanded, setExpanded] = useState(false)

  if (entry.status === 'loading') {
    return <div className="qs-ev-status">加载证据中…</div>
  }
  if (entry.status === 'error') {
    return (
      <div className="qs-ev-status qs-ev-error">
        <div>{entry.message}</div>
        {entry.shortId === true
          ? <div className="qs-ev-hint">该引用为短 ID；完整 evidence_id 为 64 位十六进制（EV:sha256），请以完整 ID 核验。</div>
          : null}
        <button type="button" className="qs-ev-retry" onClick={() => { invalidateEvEvidence(id) }}>重试</button>
      </div>
    )
  }
  const doc = asEvidenceDoc(entry.doc)
  if (doc === undefined) {
    return <div className="qs-ev-status qs-ev-error">证据返回格式无法解析（evidence_id：{id}）</div>
  }

  const evidenceId = doc.evidence_id === '' ? id : doc.evidence_id
  const title = doc.title ?? doc.source_name ?? '无标题'
  const meta: string[] = []
  const date = formatDate(doc.publish_date)
  if (date !== '') meta.push(date)
  if (doc.source_name !== '' && doc.source_name !== title) meta.push(doc.source_name)
  if (doc.ts_code !== undefined && doc.ts_code !== '') meta.push(doc.ts_code)

  return (
    <>
      <div className="qs-ev-doc-title">{title}</div>
      <div className="qs-ev-meta">
        <span className="qs-ev-badge">{sourceTypeLabel(doc.source_type)}</span>
        {meta.map(part => <span key={part}>{part}</span>)}
      </div>
      <div
        className="qs-ev-text"
        data-collapsed={!expanded || undefined}
        style={expanded ? undefined : { WebkitLineClamp: lines }}
      >
        {doc.text_excerpt}
      </div>
      <button
        type="button"
        className="qs-ev-toggle"
        onClick={() => { setExpanded(!expanded) }}
      >
        {expanded ? '收起' : '展开全文'}
      </button>
      <div className="qs-ev-foot">
        <span className="qs-ev-mono">{doc.evidence_id}</span>
        <span className="qs-ev-foot-actions">
          <button
            type="button"
            className="qs-ev-open"
            onClick={() => { void openEvidenceArtifact(evidenceId) }}
          >
            查看原文
          </button>
          {doc.pdf_url === undefined || doc.pdf_url === ''
            ? null
            : (
              <a className="qs-ev-pdf" href={doc.pdf_url} target="_blank" rel="noreferrer">
                原文 PDF
              </a>
            )}
        </span>
      </div>
    </>
  )
}

/** Subscribe to the store's evidence cache for one id (fetch kicks on miss). */
function useEvEvidence(id: string): { status: 'loading' } | { status: 'error'; message: string; shortId?: boolean } | { status: 'ok'; doc: Record<string, unknown> } {
  return useSyncExternalStore(
    subscribeEvCite,
    () => getEvEvidence(id, fetchEvEvidence),
  )
}

/**
 * Hover delegation for assistant step views: chip hover opens the preview
 * after a delay; leaving the chip closes it unless the popover was entered.
 * Mount the handlers on the assistant message wrapper.
 * @returns onMouseOver / onMouseOut React handlers.
 */
export function useEvHoverDelegation(): {
  onMouseOver: (event: React.MouseEvent<HTMLDivElement>) => void
  onMouseOut: (event: React.MouseEvent<HTMLDivElement>) => void
} {
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const activeRef = useRef<string | undefined>(undefined)

  const clear = useCallback((): void => {
    if (timerRef.current !== null) {
      clearTimeout(timerRef.current)
      timerRef.current = null
    }
  }, [])

  useEffect(() => clear, [clear])

  const onMouseOver = useCallback((event: React.MouseEvent<HTMLDivElement>): void => {
    const button = event.target instanceof Element ? event.target.closest('button') : null
    const id = button !== null ? evIdOf(button.textContent ?? '') : undefined
    if (id === undefined) {
      if (activeRef.current !== undefined && popoverHoverId !== activeRef.current) {
        closeEvHover(activeRef.current)
        activeRef.current = undefined
      }
      clear()
      return
    }
    if (activeRef.current === id) return
    clear()
    const rect = button.getBoundingClientRect()
    timerRef.current = setTimeout(() => {
      activeRef.current = id
      openEvHover(id, { x: rect.x, y: rect.y, width: rect.width, height: rect.height })
    }, HOVER_OPEN_DELAY_MS)
  }, [clear])

  const onMouseOut = useCallback((event: React.MouseEvent<HTMLDivElement>): void => {
    const button = event.target instanceof Element ? event.target.closest('button') : null
    if (button === null) return
    const id = evIdOf(button.textContent ?? '')
    if (id === undefined) return
    clear()
    timerRef.current = setTimeout(() => {
      if (popoverHoverId === id) return
      closeEvHover(id)
      activeRef.current = undefined
    }, HOVER_CLOSE_GRACE_MS)
  }, [])

  return { onMouseOver, onMouseOut }
}
