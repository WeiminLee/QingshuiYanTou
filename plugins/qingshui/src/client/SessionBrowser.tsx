import { useState } from 'react'
import { createAndOpenSession } from './session-actions.ts'

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

export type SessionBrowserProps = {
  wide: boolean
  expandSidebar: () => void
  useSessions: <S>(select: (state: ListState) => S) => S
  t: (key: string) => string
  createSession: () => Promise<string>
  openSession: (sessionId: string) => void
}

/** Flat research-session list for sidebar.workspaces (no workspace / path tree). */
export function SessionBrowser(props: SessionBrowserProps) {
  const { wide, expandSidebar, useSessions, t, createSession, openSession } = props
  const list = useSessions(s => s)
  const [busy, setBusy] = useState(false)

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

  const rows = list.ids
    .map(id => list.byId[id])
    .filter((row): row is SessionRow => row !== undefined)
    .slice()
    .sort((a, b) => b.updatedAt - a.updatedAt)

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
          <button
            key={row.id}
            type="button"
            role="listitem"
            className="qs-shell-row"
            data-active={list.current === row.id ? 'true' : 'false'}
            onClick={() => { openSession(row.id) }}
          >
            <span className="qs-shell-row-title">
              {row.displayTitle || row.title || t('sessions.untitled')}
            </span>
          </button>
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
