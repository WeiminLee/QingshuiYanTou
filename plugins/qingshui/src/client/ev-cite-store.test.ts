import { strict as assert } from 'node:assert'
import { test } from 'node:test'
import {
  closeEvHover, closeEvPinned, getEvCiteState, getEvEvidence, invalidateEvEvidence,
  openEvHover, pinEvEvidence, subscribeEvCite,
} from './ev-cite-store.ts'

const FULL_ID = 'EV:c2162ae848cc32706670f57a4af482e73b7518901ef522833b03248babb8c422'
const ANCHOR = { x: 10, y: 20, width: 80, height: 20 }

function resetState(): void {
  // Drive every mode back to closed through the public API.
  closeEvHover()
  closeEvPinned()
  invalidateEvEvidence('EV:3fe7ff02')
  invalidateEvEvidence(FULL_ID)
}

test('hover opens, dedupes identical anchors, and closes', () => {
  resetState()
  let notifications = 0
  const off = subscribeEvCite(() => { notifications += 1 })

  openEvHover('EV:3fe7ff02', ANCHOR)
  assert.equal(getEvCiteState().mode, 'hover')
  const afterOpen = notifications

  openEvHover('EV:3fe7ff02', ANCHOR)
  assert.equal(notifications, afterOpen)

  openEvHover('EV:3fe7ff02', { ...ANCHOR, y: 25 })
  assert.notEqual(notifications, afterOpen)

  closeEvHover(FULL_ID)
  assert.equal(getEvCiteState().mode, 'hover')
  closeEvHover()
  assert.equal(getEvCiteState().mode, 'closed')
  off()
})

test('pinned state overrides hover and close path', () => {
  resetState()
  openEvHover('EV:3fe7ff02', ANCHOR)
  pinEvEvidence(FULL_ID)
  assert.equal(getEvCiteState().mode, 'pinned')
  openEvHover('EV:3fe7ff02', ANCHOR)
  assert.equal(getEvCiteState().mode, 'pinned')
  closeEvPinned()
  assert.equal(getEvCiteState().mode, 'closed')
})

test('getEvEvidence caches per id and retries after invalidate', async () => {
  resetState()
  let calls = 0
  const fetcher = async (id: string) => {
    calls += 1
    return { status: 'ok' as const, doc: { evidence_id: id } }
  }

  const first = getEvEvidence('EV:3fe7ff02', fetcher)
  assert.equal(first.status, 'loading')
  assert.equal(calls, 1)
  const second = getEvEvidence('EV:3fe7ff02', fetcher)
  assert.equal(second.status, 'loading')
  assert.equal(calls, 1)

  await new Promise(resolve => setTimeout(resolve, 5))
  const settled = getEvEvidence('EV:3fe7ff02', fetcher)
  assert.equal(settled.status, 'ok')
  const okSettled = settled as { status: 'ok'; doc: Record<string, unknown> }
  assert.equal(okSettled.doc.evidence_id, 'EV:3fe7ff02')

  invalidateEvEvidence('EV:3fe7ff02')
  const again = getEvEvidence('EV:3fe7ff02', fetcher)
  assert.equal(again.status, 'loading')
  assert.equal(calls, 2)
})
