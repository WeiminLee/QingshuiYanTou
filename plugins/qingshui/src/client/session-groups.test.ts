import assert from 'node:assert/strict'
import { describe, it } from 'node:test'
import { groupSessionRows, sessionBucket, sessionClock, sessionStamp } from './session-groups.ts'

describe('session sidebar groups', () => {
  const now = new Date(2026, 9, 20, 15, 0, 0, 0).getTime()

  it('splits today, yesterday, and earlier on the local midnight', () => {
    assert.equal(sessionBucket(new Date(2026, 9, 20, 0, 0, 0, 0).getTime(), now), 'today')
    assert.equal(sessionBucket(new Date(2026, 9, 20, 9, 30).getTime(), now), 'today')
    assert.equal(sessionBucket(new Date(2026, 9, 19, 23, 59).getTime(), now), 'yesterday')
    assert.equal(sessionBucket(new Date(2026, 9, 19, 0, 0).getTime(), now), 'yesterday')
    assert.equal(sessionBucket(new Date(2026, 9, 18, 23, 59).getTime(), now), 'earlier')
  })

  it('formats a 24-hour clock', () => {
    assert.equal(sessionClock(new Date(2026, 9, 20, 9, 5).getTime()), '09:05')
  })

  it('stamps today/yesterday as clock, earlier as month-day', () => {
    const t = new Date(2026, 9, 20, 9, 5).getTime()
    assert.equal(sessionStamp(t, 'today'), '09:05')
    assert.equal(sessionStamp(t, 'yesterday'), '09:05')
    assert.equal(sessionStamp(new Date(2026, 9, 3, 23, 0).getTime(), 'earlier'), '10-03')
  })

  it('drops empty groups and keeps row order', () => {
    const rows = [
      { id: 'a', updatedAt: new Date(2026, 9, 20, 14, 0).getTime() },
      { id: 'b', updatedAt: new Date(2026, 9, 20, 9, 0).getTime() },
      { id: 'c', updatedAt: new Date(2026, 9, 17, 11, 0).getTime() },
    ]
    assert.deepEqual(groupSessionRows(rows, now), [
      { bucket: 'today', rows: [rows[0], rows[1]] },
      { bucket: 'earlier', rows: [rows[2]] },
    ])
  })
})
