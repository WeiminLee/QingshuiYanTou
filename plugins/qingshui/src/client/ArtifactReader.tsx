/**
 * ArtifactReader: the full-screen reading surface for one session artifact —
 * announcement chapters on the left, the evidence body (with the cited spans
 * marked) in the middle, the retained PDF on the right. Mounted once by the
 * `shell.overlay` slot; the artifact itself comes from the module-scope
 * reader store, so every entry point opens it without threading props.
 *
 * Every network call degrades on its own: a failed document hides the chapter
 * rail, a failed evidence fetch offers a retry, and an unarchived PDF is said
 * in plain words instead of an empty frame. Highlighting slices plain text
 * into React text nodes — no HTML string is ever built from evidence content,
 * so `<` and `&` in a source document can never become markup.
 */
import { Fragment, useCallback, useEffect, useRef, useState, useSyncExternalStore } from 'react'
import { createPortal } from 'react-dom'
import {
  chapterLabel, clampSpans, closeArtifact, getArtifactState, splitBySpans, subscribeArtifact,
  type Artifact, type ArtifactSpan,
} from './artifact-store.ts'
import {
  fetchEvEvidence, getEvEvidence, invalidateEvEvidence, subscribeEvCite, type EvEvidence,
} from './ev-cite-store.ts'
import { asEvidenceDoc, formatConfidence, formatDate, sourceTypeLabel } from './toolviews/model.ts'

/** Rendered lines shown before the body folds. */
const COLLAPSED_LINES = 40
/** A body this long overflows 40 rendered lines even without newlines — fold it too. */
const COLLAPSED_CHARS = 1200
/** Stated wherever the PDF column is not available, instead of an empty frame. */
const UNARCHIVED_NOTE = '原文未归档：该公告入库时 PDF 已被清理，新公告自本次变更起会保留'

/** Document response from `GET /qingshui/document/<ann_id>`, parsed defensively. */
type ReaderChapter = {
  evidence_id: string
  /** Kept-chapter ordinal; NaN when the API omitted it, so chapterLabel falls back to the heading. */
  chapter_index: number
  heading: string | null
  chars: number | null
}

type ReaderDocument = {
  ts_code: string
  source_name: string
  publish_date: string
  title: string | null
  pdf: { exists: boolean }
  chapters: ReaderChapter[]
}

type DocState =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'ok'; doc: ReaderDocument }

/** Evidence entry, plus the idle state an absent evidence id leaves behind. */
type BodyState = EvEvidence | { status: 'idle' }

const BODY_IDLE: BodyState = { status: 'idle' }

/**
 * Reader root: renders nothing until an artifact is opened, then portals the
 * dialog to the body so a transformed or clipped shell cannot crop it.
 * @returns the dialog, or null when the reader is closed.
 */
export function ArtifactReader(): React.ReactElement | null {
  const state = useSyncExternalStore(subscribeArtifact, getArtifactState)
  const artifact = state.artifact
  if (artifact === undefined || typeof document === 'undefined') return null
  // Keying by artifact identity resets chapter selection, folding, and pane
  // toggles whenever a different artifact (or different spans) is opened.
  return createPortal(<ReaderDialog key={artifactKey(artifact)} artifact={artifact} />, document.body)
}

/** Remount identity for one artifact: kind, ids, and the span set. */
function artifactKey(artifact: Artifact): string {
  const spans = artifact.spans?.map(span => `${span.start}-${span.end}`).join(',') ?? ''
  return artifact.kind === 'document'
    ? `d:${artifact.annId}:${artifact.evidenceId ?? ''}:${spans}`
    : `e:${artifact.evidenceId}:${spans}`
}

/**
 * @param artifact - what to read; a document carries an ann_id, a single
 *   evidence view only carries its id.
 */
function ReaderDialog({ artifact }: { artifact: Artifact }): React.ReactElement {
  const panelRef = useRef<HTMLDivElement | null>(null)
  const [selectedId, setSelectedId] = useState<string | undefined>(artifact.evidenceId)
  // Only the ≤720px layout consumes this: there the rail is a slide-over, so it
  // starts closed and the body keeps the screen. Above that it is always on.
  const [railOpen, setRailOpen] = useState(false)
  const [pdfOpen, setPdfOpen] = useState(true)
  const [discoveredAnnId, setDiscoveredAnnId] = useState<string | undefined>(undefined)

  // The artifact's own evidence id is the only stable anchor for finding the
  // parent document; the body may later switch chapters.
  const anchor = useEvidence(artifact.evidenceId)
  const anchorAnnId = anchor.state.status === 'ok' ? annIdOf(anchor.state.doc) : undefined
  useEffect(() => {
    if (artifact.kind === 'document' || anchorAnnId === undefined) return
    setDiscoveredAnnId(previous => (previous === anchorAnnId ? previous : anchorAnnId))
  }, [artifact.kind, anchorAnnId])

  const annId = artifact.kind === 'document' ? artifact.annId : discoveredAnnId
  const documentState = useDocument(annId)
  const doc = documentState.state.status === 'ok' ? documentState.state.doc : undefined
  const chapters = doc?.chapters ?? []
  const displayId = selectedId ?? artifact.evidenceId ?? chapters[0]?.evidence_id
  const body = useEvidence(displayId)

  const showRail = chapters.length > 0
  const pdfHref = annId === undefined ? undefined : `/qingshui/pdf/${encodeURIComponent(annId)}`
  const showPdf = pdfHref !== undefined && doc !== undefined && pdfOpen
  // A highlight only applies to the evidence it was opened for; browsing other
  // chapters must not paint stale ranges over unrelated text.
  const spans = displayId !== undefined && displayId === artifact.evidenceId ? artifact.spans : undefined

  const bodyDoc = body.state.status === 'ok' ? asEvidenceDoc(body.state.doc) : undefined
  const title = doc?.title ?? bodyDoc?.title ?? doc?.source_name ?? bodyDoc?.source_name ?? ''

  // Focus moves into the dialog on open and returns to the opener on close.
  useEffect(() => {
    const opener = document.activeElement
    panelRef.current?.focus()
    return () => {
      if (opener instanceof HTMLElement && opener.isConnected) opener.focus()
    }
  }, [])

  // Esc closes from anywhere inside the dialog; the page behind stays put.
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent): void => {
      if (event.key !== 'Escape') return
      event.preventDefault()
      closeArtifact()
    }
    document.addEventListener('keydown', onKeyDown)
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.removeEventListener('keydown', onKeyDown)
      document.body.style.overflow = previousOverflow
    }
  }, [])

  const onBackdropMouseDown = (event: React.MouseEvent<HTMLDivElement>): void => {
    // mouseDown, not click: a text selection dragged out of the panel must not
    // be read as a dismiss.
    if (event.target === event.currentTarget) closeArtifact()
  }

  const trapFocus = (event: React.KeyboardEvent<HTMLDivElement>): void => {
    if (event.key !== 'Tab') return
    const panel = panelRef.current
    if (panel === null) return
    const focusable = [...panel.querySelectorAll<HTMLElement>(
      'button, [href], iframe, input, select, textarea, [tabindex]:not([tabindex="-1"])',
    )].filter(element => !element.hasAttribute('disabled') && element.getClientRects().length > 0)
    const first = focusable[0]
    const last = focusable[focusable.length - 1]
    if (first === undefined || last === undefined) {
      event.preventDefault()
      panel.focus()
      return
    }
    const active = document.activeElement
    if (event.shiftKey && (active === first || active === panel)) {
      event.preventDefault()
      last.focus()
    } else if (!event.shiftKey && active === last) {
      event.preventDefault()
      first.focus()
    }
  }

  const subParts: React.ReactNode[] = []
  if (doc !== undefined && doc.ts_code !== '') subParts.push(<span key="ts">{doc.ts_code}</span>)
  const date = formatDate(doc?.publish_date ?? bodyDoc?.publish_date)
  if (date !== '') subParts.push(<span key="date">{date}</span>)
  if (bodyDoc !== undefined) {
    subParts.push(<span key="type" className="qs-art-badge">{sourceTypeLabel(bodyDoc.source_type)}</span>)
  }

  const columns = [
    showRail ? '220px' : null,
    'minmax(0, 1fr)',
    showPdf ? 'minmax(0, 42%)' : null,
  ].filter((part): part is string => part !== null).join(' ')

  return (
    <div className="qs-art-backdrop" onMouseDown={onBackdropMouseDown}>
      <div
        ref={panelRef}
        className="qs-art-panel"
        role="dialog"
        aria-modal="true"
        aria-label={title === '' ? '产物阅读器' : `产物阅读器：${title}`}
        tabIndex={-1}
        onKeyDown={trapFocus}
      >
        <header className="qs-art-head">
          <div className="qs-art-head-main">
            <div className="qs-art-title">{title === '' ? '未命名材料' : title}</div>
            <div className="qs-art-sub">{subParts}</div>
          </div>
          <div className="qs-art-actions">
            {showRail ? (
              <button
                type="button"
                className="qs-art-btn qs-art-rail-toggle"
                aria-pressed={railOpen}
                onClick={() => { setRailOpen(open => !open) }}
              >
                章节
              </button>
            ) : null}
            {pdfHref === undefined || doc === undefined ? null : (
              <>
                {/* Wide: toggles the PDF column. Narrow (≤1100px): the column is
                    unavailable, so the same affordance opens a tab instead —
                    only when there is a file to open. */}
                <button
                  type="button"
                  className="qs-art-btn qs-art-pdf-toggle"
                  aria-pressed={pdfOpen}
                  onClick={() => { setPdfOpen(open => !open) }}
                >
                  原文
                </button>
                {doc.pdf.exists ? (
                  <a className="qs-art-btn qs-art-pdf-link" href={pdfHref} target="_blank" rel="noreferrer">原文</a>
                ) : null}
              </>
            )}
            <button type="button" className="qs-art-btn qs-art-close" onClick={() => { closeArtifact() }}>关闭</button>
          </div>
        </header>

        <div
          className="qs-art-grid"
          data-rail={showRail ? 'true' : 'false'}
          data-open={railOpen ? 'true' : 'false'}
          style={{ '--qs-art-cols': columns } as React.CSSProperties}
        >
          {showRail ? (
            <nav className="qs-art-rail" aria-label="文档章节">
              <div className="qs-art-rail-head">{`章节 ${chapters.length}`}</div>
              <div className="qs-art-rail-list">
                {chapters.map((chapter) => {
                  const label = chapterLabel(chapter)
                  return (
                    <button
                      key={chapter.evidence_id}
                      type="button"
                      className="qs-art-chapter"
                      title={label}
                      data-active={chapter.evidence_id === displayId ? 'true' : undefined}
                      aria-current={chapter.evidence_id === displayId ? 'true' : undefined}
                      onClick={() => {
                        setSelectedId(chapter.evidence_id)
                        setRailOpen(false)
                      }}
                    >
                      <span className="qs-art-chapter-label">{label}</span>
                      {chapter.chars === null ? null : <span className="qs-art-chapter-chars">{chapter.chars}</span>}
                    </button>
                  )
                })}
              </div>
            </nav>
          ) : null}

          <article className="qs-art-body" aria-label="证据正文">
            {/* The narrow layout has no PDF column, so the same statement sits
                here (CSS shows it below 1100px only). */}
            {doc !== undefined && !doc.pdf.exists ? <p className="qs-art-note qs-art-note-inline">{UNARCHIVED_NOTE}</p> : null}
            {displayId !== undefined ? (
              <EvidencePane
                key={displayId}
                id={displayId}
                state={body.state}
                spans={spans}
                onRetry={body.retry}
              />
            ) : documentState.state.status === 'loading' ? (
              <div className="qs-art-status">加载文档章节…</div>
            ) : documentState.state.status === 'error' ? (
              <div className="qs-art-status qs-art-error">
                <div>{documentState.state.message}</div>
                <button type="button" className="qs-art-btn" onClick={documentState.retry}>重试</button>
              </div>
            ) : (
              <div className="qs-art-status">该产物没有可显示的正文</div>
            )}
          </article>

          {showPdf && pdfHref !== undefined && doc !== undefined ? (
            <aside className="qs-art-pdf" aria-label="原文 PDF">
              {doc.pdf.exists ? (
                <iframe className="qs-art-frame" src={pdfHref} title="原文 PDF" />
              ) : (
                // Never an empty frame: an unarchived PDF is stated, not implied.
                <p className="qs-art-note">{UNARCHIVED_NOTE}</p>
              )}
            </aside>
          ) : null}
        </div>
      </div>
    </div>
  )
}

/**
 * Middle pane: one evidence body, with the cited spans marked and long text
 * folded. Remounted per evidence id (key), so folding resets per chapter.
 * @param id - evidence id the body belongs to.
 * @param state - cached evidence entry (fetch is kicked by the store).
 * @param spans - ranges to highlight; already scoped to this id by the caller.
 * @param onRetry - drops the cached failure and refetches.
 */
function EvidencePane({ id, state, spans, onRetry }: {
  id: string
  state: BodyState
  spans: ArtifactSpan[] | undefined
  onRetry: () => void
}): React.ReactElement {
  const [expanded, setExpanded] = useState(false)

  if (state.status === 'idle' || state.status === 'loading') {
    return <div className="qs-art-status">加载证据正文…</div>
  }
  if (state.status === 'error') {
    return (
      <div className="qs-art-status qs-art-error">
        <div>{state.message}</div>
        <button type="button" className="qs-art-btn" onClick={onRetry}>重试</button>
      </div>
    )
  }
  const doc = asEvidenceDoc(state.doc)
  if (doc === undefined) {
    return <div className="qs-art-status qs-art-error">{`证据返回格式无法解析（${id}）`}</div>
  }

  const text = doc.text_excerpt
  const foldable = text.split('\n').length > COLLAPSED_LINES || text.length > COLLAPSED_CHARS
  const collapsed = foldable && !expanded
  const confidence = formatConfidence(doc.confidence)

  return (
    <>
      <div className="qs-art-meta">
        <span className="qs-art-badge">{sourceTypeLabel(doc.source_type)}</span>
        {confidence === '' ? null : <span>{`置信度 ${confidence}`}</span>}
        <span className="qs-art-mono">{doc.evidence_id === '' ? id : doc.evidence_id}</span>
      </div>
      {text === '' ? (
        <div className="qs-art-status">正文为空</div>
      ) : (
        <div
          className="qs-art-text"
          data-collapsed={collapsed ? 'true' : undefined}
          style={collapsed ? { WebkitLineClamp: COLLAPSED_LINES } : undefined}
        >
          {renderSegments(text, spans)}
        </div>
      )}
      {foldable ? (
        <button type="button" className="qs-art-link" onClick={() => { setExpanded(open => !open) }}>
          {expanded ? '收起' : '展开全文'}
        </button>
      ) : null}
    </>
  )
}

/**
 * Plain-text runs: marked runs become `<mark>`, everything else is a text node.
 * Spans are clamped against the code-point count first (server offsets count
 * code points, not UTF-16 units); splitBySpans clamps again, harmlessly.
 * @param text - evidence body.
 * @param spans - highlight ranges, possibly out of range.
 */
function renderSegments(text: string, spans: ArtifactSpan[] | undefined): React.ReactNode[] {
  const segments = splitBySpans(text, clampSpans(spans, Array.from(text).length))
  return segments.map((segment, index) => (segment.marked
    ? <mark key={index} className="qs-art-mark">{segment.text}</mark>
    : <Fragment key={index}>{segment.text}</Fragment>))
}

/** Cached evidence lookup, kicking a fetch on miss through the ev-cite store. */
function useEvidence(id: string | undefined): { state: BodyState; retry: () => void } {
  const state = useSyncExternalStore(
    subscribeEvCite,
    () => (id === undefined ? BODY_IDLE : getEvEvidence(id, fetchEvEvidence)),
  )
  const retry = useCallback(() => {
    if (id !== undefined) invalidateEvEvidence(id)
  }, [id])
  return { state, retry }
}

/** Document fetch for one ann_id; idle while no ann_id is known. */
function useDocument(annId: string | undefined): { state: DocState; retry: () => void } {
  const [state, setState] = useState<DocState>({ status: 'idle' })
  const [nonce, setNonce] = useState(0)

  useEffect(() => {
    if (annId === undefined) {
      setState(previous => (previous.status === 'idle' ? previous : { status: 'idle' }))
      return
    }
    let cancelled = false
    setState({ status: 'loading' })
    void loadDocument(annId)
      .then((doc) => { if (!cancelled) setState({ status: 'ok', doc }) })
      .catch((error: unknown) => {
        if (cancelled) return
        setState({ status: 'error', message: error instanceof Error ? error.message : '文档加载失败' })
      })
    return () => { cancelled = true }
  }, [annId, nonce])

  const retry = useCallback(() => { setNonce(value => value + 1) }, [])
  return { state, retry }
}

/**
 * @param annId - announcement id from the artifact or the evidence row.
 * @throws Error with a user-facing Chinese message on any failure.
 */
async function loadDocument(annId: string): Promise<ReaderDocument> {
  let res: Response
  try {
    res = await fetch(`/qingshui/document/${encodeURIComponent(annId)}`, { headers: { accept: 'application/json' } })
  } catch {
    throw new Error('无法连接本地知识路由（服务未启动或已断开）')
  }
  const payload = await res.json().catch(() => ({})) as { ok?: boolean; doc?: unknown; error?: string }
  if (!res.ok || payload.ok !== true) {
    throw new Error(payload.error ?? `文档加载失败（HTTP ${res.status}）`)
  }
  const doc = asReaderDocument(payload.doc)
  if (doc === undefined) throw new Error('文档返回格式无法解析')
  return doc
}

function asRecord(value: unknown): Record<string, unknown> | undefined {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : undefined
}

function asText(value: unknown): string | undefined {
  return typeof value === 'string' && value !== '' ? value : undefined
}

function asNumber(value: unknown): number | undefined {
  const raw = typeof value === 'number' ? value : typeof value === 'string' ? Number(value) : Number.NaN
  return Number.isFinite(raw) ? raw : undefined
}

/** Defensive parse of the document payload; undefined when it is not one. */
function asReaderDocument(value: unknown): ReaderDocument | undefined {
  const source = asRecord(value)
  if (source === undefined || !Array.isArray(source.chapters)) return undefined
  const pdf = asRecord(source.pdf)
  const chapters: ReaderChapter[] = []
  for (const raw of source.chapters) {
    const chapter = asRecord(raw)
    const evidenceId = chapter === undefined ? undefined : asText(chapter.evidence_id)
    if (chapter === undefined || evidenceId === undefined) continue
    chapters.push({
      evidence_id: evidenceId,
      chapter_index: asNumber(chapter.chapter_index) ?? Number.NaN,
      heading: asText(chapter.heading) ?? null,
      chars: asNumber(chapter.chars) ?? null,
    })
  }
  return {
    ts_code: asText(source.ts_code) ?? '',
    source_name: asText(source.source_name) ?? '',
    publish_date: asText(source.publish_date) ?? '',
    title: asText(source.title) ?? null,
    pdf: { exists: pdf?.exists === true },
    chapters,
  }
}

/**
 * Parent announcement id carried by an evidence row. Absent for IRM / research
 * report / upload evidence, which is exactly when the reader falls back to the
 * single-evidence view. Mongo stores PG ids as ints for announcements.
 * @param doc - raw evidence document.
 */
function annIdOf(doc: Record<string, unknown>): string | undefined {
  const ref = asRecord(doc.source_ref)
  if (ref === undefined) return undefined
  const raw = ref.ann_id
  if (typeof raw === 'string' && raw !== '') return raw
  if (typeof raw === 'number' && Number.isFinite(raw)) return String(raw)
  return undefined
}
