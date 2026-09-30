/** Locale keys for the qingshui research-shell sidebar. */
export type QingshuiShellKey =
  | 'sessions.heading'
  | 'sessions.new'
  | 'sessions.empty'
  | 'sessions.untitled'

export const zh: Record<QingshuiShellKey, string> = {
  'sessions.heading': '投研会话',
  'sessions.new': '新建对话',
  'sessions.empty': '暂无会话',
  'sessions.untitled': '新对话',
}

export const en: Record<QingshuiShellKey, string> = {
  'sessions.heading': 'Research chats',
  'sessions.new': 'New chat',
  'sessions.empty': 'No chats yet',
  'sessions.untitled': 'New chat',
}
