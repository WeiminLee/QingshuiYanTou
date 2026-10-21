import { useEffect, useMemo, useRef, useState } from 'react'
import { RESEARCH_MODULES, type ResearchModule } from './research-modules.ts'
import { groupSessionRows, sessionStamp, type SessionBucket } from './session-groups.ts'

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

/** Recent sessions shown before the list folds itself behind「展开全部」. */
export const VISIBLE_SESSION_LIMIT = 7

const BUCKET_LABEL: Record<SessionBucket, string> = {
  today: 'sessions.today',
  yesterday: 'sessions.yesterday',
  earlier: 'sessions.earlier',
}

export type SessionBrowserProps = {
  wide: boolean
  expandSidebar: () => void
  useSessions: <S>(select: (state: ListState) => S) => S
  useWorkspaces: <S>(select: (state: { archivedSessionIds: readonly string[] }) => S) => S
  t: (key: string) => string
  openSession: (sessionId: string) => void
  archiveSession: (sessionId: string) => Promise<void>
  renameSession: (sessionId: string, title: string) => Promise<boolean>
  /** Start a new chat in this module's lane. */
  startModule: (module: ResearchModule) => void
}

/** Flat research-session list for sidebar.workspaces (no workspace / path tree). */
export function SessionBrowser(props: SessionBrowserProps) {
  const {
    wide, useSessions, useWorkspaces, t,
    openSession, archiveSession, renameSession, startModule,
  } = props
  const list = useSessions(s => s)
  const archived = useWorkspaces(s => s.archivedSessionIds)
  const [editing, setEditing] = useState<{ id: string; draft: string } | null>(null)
  const [confirmId, setConfirmId] = useState<string | undefined>(undefined)
  const [expanded, setExpanded] = useState(false)
  const confirmTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => () => {
    if (confirmTimer.current !== null) clearTimeout(confirmTimer.current)
  }, [])

  const rows = useMemo(() => {
    const archivedSet = new Set(archived)
    return list.ids
      .map(id => list.byId[id])
      .filter(row => row !== undefined && !archivedSet.has(row.id))
      .sort((a, b) => b.updatedAt - a.updatedAt)
  }, [list.ids, list.byId, archived])

  const folded = !expanded && rows.length > VISIBLE_SESSION_LIMIT
  const visibleRows = folded ? rows.slice(0, VISIBLE_SESSION_LIMIT) : rows
  const groups = useMemo(() => groupSessionRows(visibleRows, Date.now()), [visibleRows])

  if (!wide) return null

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
      </div>
      <div className="qs-shell-list" role="list">
        {rows.length === 0 ? (
          <div className="qs-shell-empty">{t('sessions.empty')}</div>
        ) : groups.map(group => (
          <div key={group.bucket} className="qs-shell-group">
            <div className="qs-shell-group-label">{t(BUCKET_LABEL[group.bucket])}</div>
            {group.rows.map(row => (
              <div
                key={row.id}
                role="listitem"
                className="qs-shell-item"
                data-active={list.current === row.id ? 'true' : 'false'}
                data-blank={row.blank ? 'true' : 'false'}
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
                        <span className="qs-shell-time">{sessionStamp(row.updatedAt, group.bucket)}</span>
                      </button>
                      <span className="qs-shell-item-actions">
                        <button
                          type="button"
                          className="qs-shell-icon-btn"
                          aria-label={t('sessions.renameAria')}
                          title={t('sessions.rename')}
                          onClick={() => { beginRename(row) }}
                        >
                          {t('sessions.renameShort')}
                        </button>
                        <button
                          type="button"
                          className="qs-shell-icon-btn"
                          data-confirm={confirmId === row.id ? 'true' : 'false'}
                          aria-label={confirmId === row.id ? t('sessions.archiveConfirm') : t('sessions.archiveAria')}
                          title={confirmId === row.id ? t('sessions.archiveConfirm') : t('sessions.archive')}
                          onClick={() => { askArchive(row.id) }}
                        >
                          {confirmId === row.id ? t('sessions.archiveConfirm') : t('sessions.archiveShort')}
                        </button>
                      </span>
                    </>
                  )}
              </div>
            ))}
          </div>
        ))}
      </div>
      {rows.length > VISIBLE_SESSION_LIMIT ? (
        <button
          type="button"
          className="qs-shell-toggle"
          aria-expanded={expanded}
          onClick={() => { setExpanded(!expanded) }}
        >
          {expanded ? t('sessions.showLess') : t('sessions.showAll')}
        </button>
      ) : null}
      <nav className="qs-modules" aria-label="核心功能">
        {RESEARCH_MODULES.map(module => (
          <button
            key={module.id}
            type="button"
            className="qs-module"
            data-id={module.id}
            title={module.hint}
            onClick={() => { startModule(module) }}
          >
            <span className="qs-module-label">{module.label}</span>
            <span className="qs-module-hint">{module.hint}</span>
          </button>
        ))}
      </nav>
    </div>
  )
}
