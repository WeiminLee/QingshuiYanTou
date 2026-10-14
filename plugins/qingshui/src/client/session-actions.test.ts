import assert from 'node:assert/strict'
import { describe, it } from 'node:test'
import { archiveSession, createAndOpenSession, renameSession } from './session-actions.ts'

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

describe('archiveSession', () => {
  it('delegates to workspaces.archiveSession', async () => {
    const seen: unknown[] = []
    await archiveSession({ archiveSession: async id => { seen.push(id) } }, 'sess-1')
    assert.deepEqual(seen, ['sess-1'])
  })

  it('is a no-op when the service face is absent', async () => {
    await archiveSession({}, 'sess-1')
  })
})

describe('renameSession', () => {
  const makeSessions = (ok: boolean) => ({
    binding: (id: string) => ({
      session: {
        rename: async (title: string) => {
          seen.push([id, title])
          return ok ? { ok: true, value: { title, seq: 1 } } : { ok: false, error: { code: 'x', message: 'boom' } }
        },
      },
    }),
  })
  const seen: unknown[] = []

  it('trims and renames through the session binding', async () => {
    const result = await renameSession(makeSessions(true), 'sess-1', '  硅片预期差挖掘  ')
    assert.equal(result, true)
    assert.deepEqual(seen, [['sess-1', '硅片预期差挖掘']])
  })

  it('rejects empty titles', async () => {
    const result = await renameSession(makeSessions(true), 'sess-1', '   ')
    assert.equal(result, false)
    assert.equal(seen.length, 1)
  })

  it('reports rpc failure as false', async () => {
    const result = await renameSession(makeSessions(false), 'sess-1', 'x')
    assert.equal(result, false)
  })
})
