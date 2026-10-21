/** Locale keys for the qingshui research-shell sidebar + toolview cards. */
export type QingshuiShellKey =
  | 'sessions.heading'
  | 'sessions.new'
  | 'sessions.empty'
  | 'sessions.untitled'
  | 'sessions.today'
  | 'sessions.yesterday'
  | 'sessions.earlier'
  | 'sessions.rename'
  | 'sessions.renameShort'
  | 'sessions.archiveShort'
  | 'sessions.renameAria'
  | 'sessions.archive'
  | 'sessions.archiveConfirm'
  | 'sessions.archiveAria'
  | 'sessions.cancel'
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
  | 'tv.finding.title'
  | 'tv.finding.loading'
  | 'tv.finding.empty'
  | 'tv.finding.summary'
  | 'tv.finding.summaryFindings'
  | 'tv.finding.untitled'
  | 'tv.finding.confidence'
  | 'tv.finding.supportCount'
  | 'tv.finding.contradicts'
  | 'tv.finding.insufficient'
  | 'tv.finding.supersedes'

export const zh: Record<QingshuiShellKey, string> = {
  'sessions.heading': '投研会话',
  'sessions.new': '新建对话',
  'sessions.empty': '暂无会话',
  'sessions.untitled': '新对话',
  'sessions.today': '今天',
  'sessions.yesterday': '昨天',
  'sessions.earlier': '更早',
  'sessions.rename': '重命名',
  'sessions.renameShort': '改名',
  'sessions.archiveShort': '归档',
  'sessions.renameAria': '重命名会话',
  'sessions.archive': '归档',
  'sessions.archiveConfirm': '确认归档？',
  'sessions.archiveAria': '归档会话',
  'sessions.cancel': '取消',
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
  'tv.finding.title': '判断台账',
  'tv.finding.loading': '正在拉取判断台账…',
  'tv.finding.empty': '暂无判断',
  'tv.finding.summary': '{observations} 条观察 · {findings} 条判断',
  'tv.finding.summaryFindings': '{findings} 条判断',
  'tv.finding.untitled': '（未命名判断）',
  'tv.finding.confidence': '置信度',
  'tv.finding.supportCount': '证据锚点',
  'tv.finding.contradicts': '证伪',
  'tv.finding.insufficient': '证据锚点不足，置信度有限，请谨慎采信',
  'tv.finding.supersedes': '取代',
}

export const en: Record<QingshuiShellKey, string> = {
  'sessions.heading': 'Research chats',
  'sessions.new': 'New chat',
  'sessions.empty': 'No chats yet',
  'sessions.untitled': 'New chat',
  'sessions.today': 'Today',
  'sessions.yesterday': 'Yesterday',
  'sessions.earlier': 'Earlier',
  'sessions.rename': 'Rename',
  'sessions.renameShort': 'Rename',
  'sessions.archiveShort': 'Archive',
  'sessions.renameAria': 'Rename chat',
  'sessions.archive': 'Archive',
  'sessions.archiveConfirm': 'Archive?',
  'sessions.archiveAria': 'Archive chat',
  'sessions.cancel': 'Cancel',
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
  'tv.finding.title': 'Findings',
  'tv.finding.loading': 'Loading findings…',
  'tv.finding.empty': 'No findings',
  'tv.finding.summary': '{observations} observations · {findings} findings',
  'tv.finding.summaryFindings': '{findings} findings',
  'tv.finding.untitled': '(untitled finding)',
  'tv.finding.confidence': 'Confidence',
  'tv.finding.supportCount': 'Anchors',
  'tv.finding.contradicts': 'Contradicts',
  'tv.finding.insufficient': 'Few evidence anchors — treat confidence with caution',
  'tv.finding.supersedes': 'Supersedes',
}
