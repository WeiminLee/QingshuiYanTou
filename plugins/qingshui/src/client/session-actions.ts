/**
 * Session create/open helpers for the research shell.
 * Never call workspaces.startSession() without a workspace — that only clear()s.
 */

export type SessionsPort = {
  create: (opts?: { workspaceId?: string; cwd?: string; sessionId?: string }) => Promise<string>
  open: (sessionId: string) => void
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
