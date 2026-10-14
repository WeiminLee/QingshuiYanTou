/**
 * Session create/open/archive/rename helpers for the research shell.
 * Never call workspaces.startSession() without a workspace — that only clear()s.
 */

export type SessionsPort = {
  create: (opts?: { workspaceId?: string; cwd?: string; sessionId?: string }) => Promise<string>
  open: (sessionId: string) => void
  binding?: (sessionId: string) => { session?: { rename?: (title: string) => Promise<{ ok: boolean }> } } | undefined
}

/** Face of the workspaces service the sidebar consumes. */
export interface WorkspacesPort {
  archiveSession?: (sessionId: string) => Promise<void>
}

/**
 * Create a session with no workspaceId/cwd and open it.
 * @param sessions - client sessions service face
 * @returns the new session id
 */
export async function createAndOpenSession(sessions: SessionsPort): Promise<string> {
  const sessionId = await sessions.create({})
  sessions.open(sessionId)
  return sessionId
}

/**
 * Archive one session through the dsh-native registry-global archive set.
 * @param workspaces - client workspaces service face
 * @param sessionId - session to archive
 */
export async function archiveSession(workspaces: WorkspacesPort, sessionId: string): Promise<void> {
  await workspaces.archiveSession?.(sessionId)
}

/**
 * Rename one session via its per-session face (contract session.rename 1:1).
 * @param sessions - client sessions service face
 * @param sessionId - session to rename
 * @param raw - the authored title
 * @returns false when the value is empty after trimming or the call failed
 */
export async function renameSession(
  sessions: SessionsPort,
  sessionId: string,
  raw: string,
): Promise<boolean> {
  const title = raw.trim()
  if (title === '') return false
  const session = sessions.binding?.(sessionId)?.session
  if (session?.rename === undefined) return false
  const result = await session.rename(title)
  return result.ok === true
}
