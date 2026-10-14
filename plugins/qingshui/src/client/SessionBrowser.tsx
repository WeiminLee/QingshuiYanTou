import { useEffect, useRef, useState } from 'react'
import { archiveSession, createAndOpenSession, renameSession } from './session-actions.ts'

type SessionRow = {
  id: string
  displayTitle: string
  title?: string
  updatedAt: number
  blank: boolean
}

type ListState = {
  ids: string[]
  byId: Record<string, SessionRow>
  current: string | undefined
  phase: string
}

/** Confirmation window for the archive two-step (ms). */
const ARCHIVE_CONFIRM_MS = 3000

export type SessionBrowserProps = {
  wide: boolean
  expandSidebar: () => void
  useSessions: <S>(select: (state: ListState) => S) => S
  useWorkspaces: <S>(select: (state: { archivedSessionIds: readonly string[] }) => S) => S
  t: (key: string) => string
  createSession: () => Promise<string>
  openSession: (sessionId: string) => void
  archiveSession: (sessionId: string) => Promise<void>
  renameSession: (sessionId: string, title: string) => Promise<boolean>
}

/** Flat research-session list for sidebar.workspaces (no workspace / path tree). */
export function SessionBrowser(props: SessionBrowserProps) {
  const {
    wide, expandSidebar, useSessions, useWorkspaces, t,
    createSession, openSession, archiveSession, renameSession,
  } = props
  const list = useSessions(s => s)
  const archived = useWorkspaces(s => s.archivedSessionIds)
  const [busy, setBusy] = useState(false)
  const [editing, setEditing] = useState<{ id: string; draft: string } | null>(null)
  const [confirmId, setConfirmId] = useState<string | undefined>(undefined)
  const confirmTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => () => {
    if (confirmTimer.current !== null) clearTimeout(confirmTimer.current)
  }, [])

  const onNew = (): void => {
    if (busy) return
    if (!wide) expandSidebar()
    setBusy(true)
    void createSession()
      .catch((error: unknown) => { console.warn('qingshui: new session failed', error) })
      .finally(() => { setBusy(false) })
  }

  if (!wide) {
    return (
      <div className="qs-shell-rail">
        <button type="button" className="qs-shell-rail-btn" aria-label={t('sessions.new')} onClick={onNew} disabled={busy}>
          +
        </button>
      </div>
    )
  }

  const archivedSet = new Set(archived)
  const rows = list.ids
    .map(id => list.byId[id])
    .filter(row => row !== undefined && !archivedSet.has(row.id))
    .slice()
    .sort((a, b) => b.updatedAt - a.updatedAt)

  const beginRename = (row: SessionRow): void => {
    if (confirmTimer.current !== null) {
      clearTimeout(confirmTimer.current)
      confirmTimer.current = null
    }
    setConfirmId(undefined)
    setEditing({ id: row.id, draft: row.title ?? (row.blank ? '' : (row.displayTitle || '')) })
  }

  const commitRename = (): void => {
    const current = editing
    setEditing(null)
    if (current === null) return
    const original = list.byId[current.id]
    if (original === undefined) return
    const title = current.draft.trim()
    if (title === '' || title === original.title) return
    void renameSession(current.id, title)
      .then(ok => { if (ok !== true) console.warn('qingshui: rename failed', current.id) })
      .catch((error: unknown) => { console.warn('qingshui: rename failed', error) })
  }

  const askArchive = (id: string): void => {
    if (confirmId === id) {
      if (confirmTimer.current !== null) {
        clearTimeout(confirmTimer.current)
        confirmTimer.current = null
      }
      setConfirmId(undefined)
      void archiveSession(id).catch((error: unknown) => { console.warn('qingshui: archive failed', error) })
      return
    }
    setConfirmId(id)
    if (confirmTimer.current !== null) clearTimeout(confirmTimer.current)
    confirmTimer.current = setTimeout(() => {
      confirmTimer.current = null
      setConfirmId(undefined)
    }, ARCHIVE_CONFIRM_MS)
  }

  return (
    <div className="qs-shell">
      <div className="qs-shell-head">
        <span className="qs-shell-title">{t('sessions.heading')}</span>
        <button type="button" className="qs-shell-new" onClick={onNew} disabled={busy}>
          {t('sessions.new')}
        </button>
      </div>
      <div className="qs-shell-list" role="list">
        {rows.length === 0 ? (
          <div className="qs-shell-empty">{t('sessions.empty')}</div>
        ) : rows.map(row => (
          <div
            key={row.id}
            role="listitem"
            className="qs-shell-item"
            data-active={list.current === row.id ? 'true' : 'false'}
          >
            {editing?.id === row.id
              ? (
                <input
                  className="qs-shell-rename"
                  value={editing.draft}
                  autoFocus
                  aria-label={t('sessions.renameAria')}
                  onChange={event => { setEditing({ id: row.id, draft: event.target.value }) }}
                  onKeyDown={event => {
                    if (event.key === 'Enter') commitRename()
                    if (event.key === 'Escape') setEditing(null)
                  }}
                  onBlur={commitRename}
                />
              )
              : (
                <>
                  <button
                    type="button"
                    className="qs-shell-row"
                    data-active={list.current === row.id ? 'true' : 'false'}
                    onClick={() => { openSession(row.id) }}
                  >
                    <span className="qs-shell-row-title">
                      {row.title ?? (row.blank ? t('sessions.untitled') : (row.displayTitle || t('sessions.untitled')))}
                    </span>
                  </button>
                  <span className="qs-shell-item-actions">
                    <button
                      type="button"
                      className="qs-shell-icon-btn"
                      aria-label={t('sessions.renameAria')}
                      title={t('sessions.rename')}
                      onClick={() => { beginRename(row) }}
                    >
                      ✎
                    </button>
                    <button
                      type="button"
                      className="qs-shell-icon-btn"
                      data-confirm={confirmId === row.id ? 'true' : 'false'}
                      aria-label={confirmId === row.id ? t('sessions.archiveConfirm') : t('sessions.archiveAria')}
                      title={confirmId === row.id ? t('sessions.archiveConfirm') : t('sessions.archive')}
                      onClick={() => { askArchive(row.id) }}
                    >
                      {confirmId === row.id ? t('sessions.archiveConfirm') : '🗄'}
                    </button>
                  </span>
                </>
              )}
          </div>
        ))}
      </div>
    </div>
  )
}

/** Factory kept for tests — mirrors createAndOpenSession wiring. */
export function wireCreateSession(sessions: {
  create: (opts?: object) => Promise<string>
  open: (id: string) => void
}): () => Promise<string> {
  return () => createAndOpenSession(sessions)
}
