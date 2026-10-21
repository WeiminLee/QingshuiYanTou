import { strict as assert } from 'node:assert'
import { test } from 'node:test'
import {
  chapterLabel, clampSpans, closeArtifact, getArtifactState, openArtifact,
  openEvidenceArtifact, splitBySpans, subscribeArtifact,
} from './artifact-store.ts'

const DOC = {
  kind: 'document' as const,
  annId: '2200763',
  evidenceId: 'EV:c2162ae848cc32706670f57a4af482e73b7518901ef522833b03248babb8c422',
  spans: [{ start: 4, end: 12 }],
}

test('openArtifact publishes once, dedupes identical artifacts, and closeArtifact publishes once', () => {
  closeArtifact()
  let notifications = 0
  const off = subscribeArtifact(() => { notifications += 1 })

  assert.equal(getArtifactState().artifact, undefined)

  openArtifact(DOC)
  assert.equal(notifications, 1)
  const opened = getArtifactState()
  assert.deepEqual(opened.artifact, DOC)

  // Same artifact again: the state is unchanged, so subscribers stay quiet and
  // the snapshot object must be the very same reference (useSyncExternalStore).
  openArtifact({ ...DOC, spans: [{ start: 4, end: 12 }] })
  assert.equal(notifications, 1)
  assert.equal(getArtifactState(), opened)

  // A different artifact replaces the snapshot.
  openArtifact({ kind: 'evidence', evidenceId: 'EV:3fe7ff02', spans: [{ start: 0, end: 3 }] })
  assert.equal(notifications, 2)
  assert.notEqual(getArtifactState(), opened)
  assert.deepEqual(getArtifactState().artifact, {
    kind: 'evidence', evidenceId: 'EV:3fe7ff02', spans: [{ start: 0, end: 3 }],
  })

  closeArtifact()
  assert.equal(notifications, 3)
  assert.equal(getArtifactState().artifact, undefined)

  // Closing an already-closed reader does not notify.
  closeArtifact()
  assert.equal(notifications, 3)

  off()
})

test('a different annId, evidenceId or span set each notifies', () => {
  closeArtifact()
  let notifications = 0
  const off = subscribeArtifact(() => { notifications += 1 })

  openArtifact({ kind: 'document', annId: '1' })
  openArtifact({ kind: 'document', annId: '1', evidenceId: 'EV:1' })
  openArtifact({ kind: 'document', annId: '1', evidenceId: 'EV:1', spans: [{ start: 0, end: 1 }] })
  openArtifact({ kind: 'document', annId: '1', evidenceId: 'EV:1', spans: [{ start: 0, end: 2 }] })
  openArtifact({ kind: 'document', annId: '2', evidenceId: 'EV:1', spans: [{ start: 0, end: 2 }] })
  assert.equal(notifications, 5)

  off()
  closeArtifact()
})

test('getArtifactState snapshot is stable between notifications', () => {
  closeArtifact()
  const before = getArtifactState()
  assert.equal(getArtifactState(), before)

  openArtifact({ kind: 'evidence', evidenceId: 'EV:abc' })
  const opened = getArtifactState()
  assert.equal(getArtifactState(), opened)

  closeArtifact()
  const closed = getArtifactState()
  assert.equal(getArtifactState(), closed)
  assert.equal(closed.artifact, undefined)
})

test('openEvidenceArtifact resolves the parent ann_id, else opens the evidence alone', async () => {
  closeArtifact()
  const original = globalThis.fetch
  const requested: string[] = []
  const reply = (doc: Record<string, unknown>): Response =>
    ({ ok: true, json: async () => ({ ok: true, doc }) }) as unknown as Response
  globalThis.fetch = (async (input: unknown) => {
    const url = decodeURIComponent(String(input))
    requested.push(url)
    return url.includes('EV:announcement')
      ? reply({ evidence_id: 'EV:announcement', source_ref: { ann_id: 880123 } })
      : reply({ evidence_id: 'EV:irm', source_ref: { pdf_url: 'http://example.com/x.pdf' } })
  }) as typeof fetch

  try {
    await openEvidenceArtifact('EV:announcement', [{ start: 3, end: 9 }])
    assert.deepEqual(getArtifactState().artifact, {
      kind: 'document', annId: '880123', evidenceId: 'EV:announcement', spans: [{ start: 3, end: 9 }],
    })

    await openEvidenceArtifact('EV:irm')
    assert.deepEqual(getArtifactState().artifact, { kind: 'evidence', evidenceId: 'EV:irm' })
  } finally {
    globalThis.fetch = original
  }
  // One fetch per id: the reader later reads the same cached entries.
  assert.deepEqual(requested.length, 2)
  closeArtifact()
})

test('openEvidenceArtifact keeps the newest click when evidence resolutions race', async () => {
  closeArtifact()
  const original = globalThis.fetch
  const pending: Array<(doc: Record<string, unknown>) => void> = []
  globalThis.fetch = (() => new Promise<Response>((resolve) => {
    pending.push((doc) => {
      resolve({ ok: true, json: async () => ({ ok: true, doc }) } as unknown as Response)
    })
  })) as typeof fetch

  try {
    const slow = openEvidenceArtifact('EV:slow')
    const fast = openEvidenceArtifact('EV:fast')
    assert.equal(pending.length, 2, 'each open asks for its own evidence row')

    // The later click answers first and opens; the earlier one answers last.
    pending[1]?.({ evidence_id: 'EV:fast' })
    await fast
    assert.deepEqual(getArtifactState().artifact, { kind: 'evidence', evidenceId: 'EV:fast' })

    pending[0]?.({ evidence_id: 'EV:slow', source_ref: { ann_id: '880123' } })
    await slow
    assert.deepEqual(
      getArtifactState().artifact,
      { kind: 'evidence', evidenceId: 'EV:fast' },
      'the stale resolution must not replace the open a later click already made',
    )
  } finally {
    globalThis.fetch = original
    closeArtifact()
  }
})

test('closeArtifact cancels a pending evidence open', async () => {
  closeArtifact()
  const original = globalThis.fetch
  const pending: Array<(doc: Record<string, unknown>) => void> = []
  globalThis.fetch = (() => new Promise<Response>((resolve) => {
    pending.push((doc) => {
      resolve({ ok: true, json: async () => ({ ok: true, doc }) } as unknown as Response)
    })
  })) as typeof fetch

  try {
    const opening = openEvidenceArtifact('EV:pending-close')
    assert.equal(pending.length, 1, 'the open is waiting on its evidence row')

    closeArtifact()
    pending[0]?.({ evidence_id: 'EV:pending-close', source_ref: { ann_id: '880123' } })
    await opening

    assert.equal(
      getArtifactState().artifact,
      undefined,
      'a close must not be undone by an open that resolves afterwards',
    )
  } finally {
    globalThis.fetch = original
    closeArtifact()
  }
})

test('clampSpans drops out-of-range, reversed, empty and non-integer spans', () => {
  assert.deepEqual(clampSpans(undefined, 10), [])
  assert.deepEqual(clampSpans([], 10), [])
  assert.deepEqual(clampSpans([{ start: 0, end: 1 }], 0), [])

  const spans = [
    { start: 9, end: 11 },   // end past the text
    { start: -1, end: 2 },   // start before the text
    { start: 3, end: 2 },    // reversed
    { start: 2, end: 2 },    // empty
    { start: 1.5, end: 3 },  // non-integer start
    { start: 1, end: Number.NaN }, // non-integer end
    { start: Number.NaN, end: 4 },
    { start: 0, end: 2 },    // kept
  ]
  assert.deepEqual(clampSpans(spans, 10), [{ start: 0, end: 2 }])
})

test('clampSpans sorts by start and merges overlaps and adjacency', () => {
  assert.deepEqual(
    clampSpans([
      { start: 6, end: 9 },
      { start: 0, end: 2 },
      { start: 1, end: 4 },
      { start: 4, end: 6 },
    ], 10),
    [{ start: 0, end: 9 }],
  )

  // Adjacent ranges touch and merge; a real gap does not.
  assert.deepEqual(
    clampSpans([{ start: 0, end: 1 }, { start: 2, end: 3 }], 5),
    [{ start: 0, end: 1 }, { start: 2, end: 3 }],
  )
  assert.deepEqual(
    clampSpans([{ start: 2, end: 3 }, { start: 0, end: 2 }], 5),
    [{ start: 0, end: 3 }],
  )
})

test('clampSpans keeps a full-range span intact and does not mutate its input', () => {
  const input = [{ start: 1, end: 4 }, { start: 0, end: 2 }]
  const out = clampSpans(input, 4)
  assert.deepEqual(out, [{ start: 0, end: 4 }])
  assert.deepEqual(input, [{ start: 1, end: 4 }, { start: 0, end: 2 }])
})

test('splitBySpans slices text and keeps HTML-looking input as plain text', () => {
  const input = 'a<script>x</script>b'
  const segments = splitBySpans(input, [{ start: 1, end: 8 }])

  assert.deepEqual(segments, [
    { text: 'a', marked: false },
    { text: '<script', marked: true },
    { text: '>x</script>b', marked: false },
  ])
  // Marked segments are raw slices — no markup is ever synthesised.
  assert.equal(segments[1].text, input.slice(1, 8))
  assert.equal(segments.some(segment => segment.text.includes('<mark')), false)
  // Concatenation reproduces the input byte for byte.
  assert.equal(segments.map(segment => segment.text).join(''), input)
})

test('splitBySpans handles prefixes, suffixes, whole-text and empty spans', () => {
  assert.deepEqual(splitBySpans('abcdef', [{ start: 0, end: 2 }, { start: 4, end: 6 }]), [
    { text: 'ab', marked: true },
    { text: 'cd', marked: false },
    { text: 'ef', marked: true },
  ])
  assert.deepEqual(splitBySpans('abc', [{ start: 0, end: 3 }]), [{ text: 'abc', marked: true }])
  assert.deepEqual(splitBySpans('abc', []), [{ text: 'abc', marked: false }])
  assert.deepEqual(splitBySpans('', []), [])
})

test('splitBySpans clamps dirty spans before slicing and still round-trips', () => {
  const input = 'abcdef'
  const segments = splitBySpans(input, [
    { start: 4, end: 99 },
    { start: 1, end: 3 },
    { start: 3, end: 2 },
  ])
  assert.deepEqual(segments, [
    { text: 'a', marked: false },
    { text: 'bc', marked: true },
    { text: 'def', marked: false },
  ])
  assert.equal(segments.map(segment => segment.text).join(''), input)
})

test('splitBySpans slices by code point so astral characters cannot shift a mark', () => {
  // Server spans are Python len() offsets (code points); '😀' is two UTF-16
  // code units, so UTF-16 slicing would land inside the surrogate pair.
  const input = '😀关于重大资产重组'
  const segments = splitBySpans(input, [{ start: 1, end: 5 }])

  assert.deepEqual(segments, [
    { text: '😀', marked: false },
    { text: '关于重大', marked: true },
    { text: '资产重组', marked: false },
  ])
  assert.equal(segments[1].text, '关于重大')
  assert.equal(segments.map(segment => segment.text).join(''), input)
})

test('splitBySpans keeps astral characters inside a marked span intact', () => {
  const input = '前😀后'
  const segments = splitBySpans(input, [{ start: 1, end: 2 }])
  assert.deepEqual(segments, [
    { text: '前', marked: false },
    { text: '😀', marked: true },
    { text: '后', marked: false },
  ])
  assert.equal(segments.map(segment => segment.text).join(''), input)
})

test('chapterLabel maps the 0-based kept-chapter ordinal to 第 N 段', () => {
  // chapter_index 91 is the 92nd kept chapter (0-based over KEPT chapters).
  assert.equal(chapterLabel({ chapter_index: 91, heading: '第三节 经营情况讨论与分析' }), '第 92 段 · 第三节 经营情况讨论与分析')
  assert.equal(chapterLabel({ chapter_index: 91, heading: null }), '第 92 段')
  assert.equal(chapterLabel({ chapter_index: 0, heading: '' }), '第 1 段')
  assert.equal(chapterLabel({ chapter_index: 0, heading: '   \n\t ' }), '第 1 段')
  assert.equal(chapterLabel({ chapter_index: 2, heading: '  资产负债表  ' }), '第 3 段 · 资产负债表')
})

test('chapterLabel degrades when the API omits the ordinal', () => {
  // document_service can emit chapter_index: null for rows without one.
  const chapter = { chapter_index: null as unknown as number, heading: '附注' }
  assert.equal(chapterLabel(chapter), '附注')
  assert.equal(chapterLabel({ chapter_index: null as unknown as number, heading: null }), '章节')
})
