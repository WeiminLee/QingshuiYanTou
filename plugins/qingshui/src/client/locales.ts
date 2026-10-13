/** Locale keys for the qingshui research-shell sidebar + toolview cards. */
export type QingshuiShellKey =
  | 'sessions.heading'
  | 'sessions.new'
  | 'sessions.empty'
  | 'sessions.untitled'
  | 'tv.expand'
  | 'tv.collapse'
  | 'tv.kline.title'
  | 'tv.kline.loading'
  | 'tv.kline.empty'
  | 'tv.kline.summary'
  | 'tv.evidence.title'
  | 'tv.evidence.loading'
  | 'tv.evidence.confidence'
  | 'tv.evidence.pdf'
  | 'tv.search.title'
  | 'tv.search.loading'
  | 'tv.search.entities'
  | 'tv.search.chunks'
  | 'tv.search.empty'
  | 'tv.history.title'
  | 'tv.history.loading'
  | 'tv.history.empty'

export const zh: Record<QingshuiShellKey, string> = {
  'sessions.heading': '投研会话',
  'sessions.new': '新建对话',
  'sessions.empty': '暂无会话',
  'sessions.untitled': '新对话',
  'tv.expand': '展开',
  'tv.collapse': '收起',
  'tv.kline.title': 'K 线',
  'tv.kline.loading': '正在获取 {ts_code} K 线数据…',
  'tv.kline.empty': '该区间暂无 K 线数据',
  'tv.kline.summary': '{freq} · {range} · 共 {count} 条',
  'tv.evidence.title': '证据原文',
  'tv.evidence.loading': '正在拉取证据 {evidence_id}…',
  'tv.evidence.confidence': '置信度 {value}',
  'tv.evidence.pdf': '查看原始 PDF ↗',
  'tv.search.title': '语义检索',
  'tv.search.loading': '正在检索 {query}…',
  'tv.search.entities': '相关实体',
  'tv.search.chunks': '证据片段',
  'tv.search.empty': '未检索到相关证据或实体',
  'tv.history.title': '历史证据时间线',
  'tv.history.loading': '正在拉取历史证据…',
  'tv.history.empty': '暂无历史证据',
}

export const en: Record<QingshuiShellKey, string> = {
  'sessions.heading': 'Research chats',
  'sessions.new': 'New chat',
  'sessions.empty': 'No chats yet',
  'sessions.untitled': 'New chat',
  'tv.expand': 'Expand',
  'tv.collapse': 'Collapse',
  'tv.kline.title': 'Kline',
  'tv.kline.loading': 'Loading kline for {ts_code}…',
  'tv.kline.empty': 'No kline data in this range',
  'tv.kline.summary': '{freq} · {range} · {count} bars',
  'tv.evidence.title': 'Evidence',
  'tv.evidence.loading': 'Fetching evidence {evidence_id}…',
  'tv.evidence.confidence': 'Confidence {value}',
  'tv.evidence.pdf': 'View source PDF ↗',
  'tv.search.title': 'Semantic search',
  'tv.search.loading': 'Searching {query}…',
  'tv.search.entities': 'Related entities',
  'tv.search.chunks': 'Evidence chunks',
  'tv.search.empty': 'No matching evidence or entities',
  'tv.history.title': 'Evidence timeline',
  'tv.history.loading': 'Loading evidence history…',
  'tv.history.empty': 'No evidence history',
}
