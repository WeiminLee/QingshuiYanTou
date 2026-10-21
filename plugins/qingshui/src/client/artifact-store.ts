/**
 * Reader state for the artifact viewer: which document/evidence is open, plus
 * the pure span helpers it renders with. One module-scope store, no React, so
 * three unrelated entry points (evidence card, panel header, finding card) can
 * open the reader without threading props. React binds via
 * useSyncExternalStore against the stable snapshot returned by
 * getArtifactState().
 */

/** Half-open character range into an evidence body: `[start, end)`. */
export type ArtifactSpan = { start: number; end: number }

export type Artifact =
  | { kind: 'document'; annId: string; evidenceId?: string; spans?: ArtifactSpan[] }
  | { kind: 'evidence'; evidenceId: string; spans?: ArtifactSpan[] }

export type ArtifactState = { artifact?: Artifact }

type Listener = () => void

export type ArtifactSegment = { text: string; marked: boolean }

const listeners = new Set<Listener>()

let state: ArtifactState = {}

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

/**
 * Open the reader on one artifact. Re-opening the same artifact is a no-op so
 * subscribers are notified once per real change.
 * @param artifact - document or single-evidence view to show.
 */
export function openArtifact(artifact: Artifact): void {
  if (state.artifact !== undefined && sameArtifact(state.artifact, artifact)) return
  publish({ artifact: cloneArtifact(artifact) })
}

/** Close the reader. No notification when it is already closed. */
export function closeArtifact(): void {
  if (state.artifact === undefined) return
  publish({})
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
 * Slice text into marked and unmarked runs. Slices only — the caller renders
 * each run as a text node, so `<` or `&` in the source can never become markup.
 * Spans are clamped first, so concatenating the segment texts always returns
 * the input unchanged.
 * @param text - plain text body.
 * @param spans - highlights, possibly dirty; clamped internally.
 * @returns ordered segments covering the whole input.
 */
export function splitBySpans(text: string, spans: ArtifactSpan[]): ArtifactSegment[] {
  const segments: ArtifactSegment[] = []
  let cursor = 0
  for (const span of clampSpans(spans, text.length)) {
    if (span.start > cursor) segments.push({ text: text.slice(cursor, span.start), marked: false })
    segments.push({ text: text.slice(span.start, span.end), marked: true })
    cursor = span.end
  }
  if (cursor < text.length) segments.push({ text: text.slice(cursor), marked: false })
  return segments
}

/**
 * Label for one retained chapter: the stored 0-based ordinal as a 1-based
 * prefix plus its heading. The parsed total is deliberately absent — the
 * ordinal is a kept-chapter index, so a ratio would mislead.
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
