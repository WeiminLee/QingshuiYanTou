/**
 * Reader state for the artifact viewer: which document/evidence is open, plus
 * the pure span helpers it renders with. One module-scope store, no React, so
 * three unrelated entry points (evidence card, panel header, finding card) can
 * open the reader without threading props. React binds via
 * useSyncExternalStore against the stable snapshot returned by
 * getArtifactState().
 *
 * openEvidenceArtifact is the one asynchronous entry: it resolves the parent
 * announcement of an evidence row through the evidence cache so an entry point
 * that only holds an evidence id still opens the whole document.
 */
import { fetchEvEvidence, getEvEvidence, subscribeEvCite } from './ev-cite-store.ts'
import { evidenceAnnId } from './toolviews/model.ts'

/** Half-open character range into an evidence body: `[start, end)`. */
export type ArtifactSpan = { start: number; end: number }

/**
 * How long an asynchronous open waits for the evidence row that names its
 * parent announcement. Past this the reader opens the single-evidence view,
 * which shows its own load state and retry.
 */
const EVIDENCE_WAIT_MS = 4000

export type Artifact =
  | { kind: 'document'; annId: string; evidenceId?: string; spans?: ArtifactSpan[] }
  | { kind: 'evidence'; evidenceId: string; spans?: ArtifactSpan[] }

export type ArtifactState = { artifact?: Artifact }

type Listener = () => void

export type ArtifactSegment = { text: string; marked: boolean }

const listeners = new Set<Listener>()

let state: ArtifactState = {}

/**
 * Monotonic token of the newest open intent. An asynchronous opener reserves
 * one before its await and applies only while it is still the newest: two
 * anchors clicked inside one evidence round-trip resolve in either order, and
 * the later click must win rather than whichever fetch answered last.
 */
let openGeneration = 0

/**
 * Stable snapshot source for useSyncExternalStore.
 * @returns the current state, a new object only after a notification.
 */
export function getArtifactState(): ArtifactState {
  return state
}

/**
 * Subscribe to reader open/close changes.
 * @param fn - change callback.
 * @returns unsubscribe.
 */
export function subscribeArtifact(fn: Listener): () => void {
  listeners.add(fn)
  return () => { listeners.delete(fn) }
}

function publish(next: ArtifactState): void {
  state = next
  for (const listener of [...listeners]) listener()
}

/** Claim the newest open intent. @returns its generation token. */
function beginOpen(): number {
  openGeneration += 1
  return openGeneration
}

/**
 * Open the reader on one artifact. Re-opening the same artifact is a no-op so
 * subscribers are notified once per real change; either way the call becomes
 * the newest open intent, superseding any asynchronous open still in flight.
 * @param artifact - document or single-evidence view to show.
 */
export function openArtifact(artifact: Artifact): void {
  beginOpen()
  if (state.artifact !== undefined && sameArtifact(state.artifact, artifact)) return
  publish({ artifact: cloneArtifact(artifact) })
}

/** Close the reader. No notification when it is already closed. */
export function closeArtifact(): void {
  if (state.artifact === undefined) return
  publish({})
}

/**
 * Open the reader for one evidence id. The evidence row names its parent
 * announcement (`source_ref.ann_id`) when it has one, so that id is resolved
 * first and the reader opens the whole document; evidence without a parent
 * (IRM / research reports / uploads) opens alone. A failed or timed-out lookup
 * opens the single-evidence view too — the reader states its own load failure
 * there instead of blocking the click. Resolution applies only while this call
 * is still the newest open intent.
 * @param evidenceId - evidence to read.
 * @param spans - ranges to mark in that evidence body (a finding's sentence).
 */
export async function openEvidenceArtifact(evidenceId: string, spans?: ArtifactSpan[]): Promise<void> {
  const generation = beginOpen()
  const doc = await waitForEvidence(evidenceId)
  if (generation !== openGeneration) return
  const annId = evidenceAnnId(doc)
  if (annId === undefined) {
    openArtifact({ kind: 'evidence', evidenceId, ...(spans === undefined ? {} : { spans }) })
    return
  }
  openArtifact({ kind: 'document', annId, evidenceId, ...(spans === undefined ? {} : { spans }) })
}

/**
 * Wait for the evidence cache to settle on one id. Reading through
 * getEvEvidence keeps the reader's own lookup on the same cached entry, so
 * opening costs one fetch no matter how many places asked first. The wait is
 * bounded: a hung evidence request must not leave an opener pending, and the
 * shared ev-cite listener is released on every exit path.
 * @param id - evidence id.
 * @returns the raw evidence document, or undefined when it failed or ran out of time.
 */
function waitForEvidence(id: string): Promise<Record<string, unknown> | undefined> {
  const cached = getEvEvidence(id, fetchEvEvidence)
  if (cached.status !== 'loading') {
    return Promise.resolve(cached.status === 'ok' ? cached.doc : undefined)
  }
  return new Promise((resolve) => {
    const finish = (doc: Record<string, unknown> | undefined): void => {
      clearTimeout(timer)
      unsubscribe()
      resolve(doc)
    }
    const unsubscribe = subscribeEvCite(() => {
      const entry = getEvEvidence(id, fetchEvEvidence)
      if (entry.status === 'loading') return
      finish(entry.status === 'ok' ? entry.doc : undefined)
    })
    const timer = setTimeout(() => { finish(undefined) }, EVIDENCE_WAIT_MS)
  })
}

function cloneArtifact(artifact: Artifact): Artifact {
  if (artifact.spans === undefined) return { ...artifact }
  return { ...artifact, spans: artifact.spans.map(span => ({ start: span.start, end: span.end })) }
}

function sameArtifact(a: Artifact, b: Artifact): boolean {
  if (a.kind !== b.kind) return false
  if (a.kind === 'document' && (b.kind !== 'document' || a.annId !== b.annId)) return false
  return a.evidenceId === b.evidenceId && sameSpans(a.spans, b.spans)
}

function sameSpans(a: ArtifactSpan[] | undefined, b: ArtifactSpan[] | undefined): boolean {
  if (a === undefined || b === undefined) return a === b
  if (a.length !== b.length) return false
  for (let index = 0; index < a.length; index += 1) {
    if (a[index].start !== b[index].start || a[index].end !== b[index].end) return false
  }
  return true
}

/**
 * Drop spans that cannot index into a body of `length` characters: negative,
 * past the end, reversed, empty, or non-integer. Survivors are sorted by start
 * and overlaps/adjacency are merged so rendering never double-marks text.
 * @param spans - raw spans, possibly absent or dirty.
 * @param length - character length of the text they will slice.
 * @returns clean, sorted, non-overlapping spans.
 */
export function clampSpans(spans: ArtifactSpan[] | undefined, length: number): ArtifactSpan[] {
  if (!Array.isArray(spans) || spans.length === 0) return []
  if (!Number.isFinite(length) || length <= 0) return []

  const kept: ArtifactSpan[] = []
  for (const span of spans) {
    if (span === null || typeof span !== 'object') continue
    const start = span.start
    const end = span.end
    if (!Number.isInteger(start) || !Number.isInteger(end)) continue
    if (start < 0 || end > length || start >= end) continue
    kept.push({ start, end })
  }

  kept.sort((left, right) => left.start - right.start || left.end - right.end)
  const merged: ArtifactSpan[] = []
  for (const span of kept) {
    const last = merged[merged.length - 1]
    if (last !== undefined && span.start <= last.end) {
      if (span.end > last.end) last.end = span.end
    } else {
      merged.push({ start: span.start, end: span.end })
    }
  }
  return merged
}

/**
 * Slice text into marked and unmarked runs. Slicing is by code point, not
 * UTF-16 code unit: server offsets come from Python `len()`, where an astral
 * character (emoji, CJK Ext-B) counts as one, so slicing the string directly
 * would land inside a surrogate pair and shift every later mark. Slices only —
 * the caller renders each run as a text node, so `<` or `&` in the source can
 * never become markup. Spans are clamped first, so concatenating the segment
 * texts always returns the input unchanged.
 * @param text - plain text body.
 * @param spans - highlights, possibly dirty; clamped internally.
 * @returns ordered segments covering the whole input.
 */
export function splitBySpans(text: string, spans: ArtifactSpan[]): ArtifactSegment[] {
  const codePoints = Array.from(text)
  const segments: ArtifactSegment[] = []
  let cursor = 0
  for (const span of clampSpans(spans, codePoints.length)) {
    if (span.start > cursor) {
      segments.push({ text: codePoints.slice(cursor, span.start).join(''), marked: false })
    }
    segments.push({ text: codePoints.slice(span.start, span.end).join(''), marked: true })
    cursor = span.end
  }
  if (cursor < codePoints.length) segments.push({ text: codePoints.slice(cursor).join(''), marked: false })
  return segments
}

/**
 * Label for one retained chapter: the stored ordinal as a 1-based prefix plus
 * its heading. `chapter_index` is 0-based over KEPT chapters — the extraction
 * loop assigns it from `enumerate(keep_chapters)`, not over the parsed total —
 * so `+1` is the kept-chapter position and the parsed total never appears.
 * @param chapter - `chapter_index` and `heading` from the document API.
 */
export function chapterLabel(chapter: { chapter_index: number; heading: string | null }): string {
  const heading = typeof chapter.heading === 'string' ? chapter.heading.trim() : ''
  const index = chapter.chapter_index
  // The document API can emit a null ordinal; label by heading alone then.
  const prefix = Number.isInteger(index) ? `第 ${index + 1} 段` : null
  if (prefix === null) return heading || '章节'
  return heading === '' ? prefix : `${prefix} · ${heading}`
}
