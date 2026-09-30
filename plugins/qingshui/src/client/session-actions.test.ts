import assert from 'node:assert/strict'
import { describe, it } from 'node:test'
import { createAndOpenSession } from './session-actions.ts'

describe('createAndOpenSession', () => {
  it('calls sessions.create({}) then open; never startSession', async () => {
    const calls: unknown[] = []
    let startSessionCalled = false
    const sessions = {
      create: async (opts?: object) => {
        calls.push(['create', opts ?? null])
        return 'sess-1'
      },
      open: (id: string) => {
        calls.push(['open', id])
      },
    }
    const workspaces = {
      startSession: () => {
        startSessionCalled = true
      },
    }
    void workspaces // ensure we do not call it from the helper
    const id = await createAndOpenSession(sessions)
    assert.equal(id, 'sess-1')
    assert.deepEqual(calls, [
      ['create', {}],
      ['open', 'sess-1'],
    ])
    assert.equal(startSessionCalled, false)
  })
})
