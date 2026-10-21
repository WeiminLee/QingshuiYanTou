/** Toolview card styles (dsh semantic tokens only; dark-theme aware via aliases). */
export const TOOLVIEW_CSS = `
.qs-tv { border: 1px solid var(--dsw-alias-border-l2); border-radius: 10px; background: var(--dsw-alias-bg-layer-1); margin: 4px 0; overflow: hidden; }
.qs-tv-head { display: flex; align-items: center; gap: 8px; padding: 8px 12px; min-height: 20px; color: var(--dsw-alias-label-secondary); font: var(--dsw-font-xxs-12); }
.qs-tv-head-icon { display: inline-flex; align-items: center; color: var(--dsw-alias-label-tertiary); }
.qs-tv-title { font: var(--dsw-font-xxs-strong-12); color: var(--dsw-alias-label-primary); }
.qs-tv-summary { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--dsw-alias-label-tertiary); }
.qs-tv-body { padding: 0 12px 12px; display: flex; flex-direction: column; gap: 8px; }
.qs-tv-head + .qs-tv-body { padding-top: 0; }

.qs-tv-loading, .qs-tv-empty { color: var(--dsw-alias-label-tertiary); font: var(--dsw-font-xs-13); padding: 4px 0 8px; }
.qs-tv-error { color: var(--dsw-alias-state-error-primary); font: var(--dsw-font-xs-13); white-space: pre-wrap; word-break: break-all; }
.qs-tv-raw { margin: 0; max-height: 180px; overflow: auto; font: var(--dsw-font-xxxs-11); font-family: var(--dsw-font-family-mono, ui-monospace, SFMono-Regular, Menlo, monospace); color: var(--dsw-alias-label-secondary); white-space: pre-wrap; word-break: break-all; }

.qs-tv-badge { display: inline-flex; align-items: center; flex: none; border-radius: 4px; padding: 1px 6px; font: var(--dsw-font-xxxs-11); line-height: 16px; }
.qs-tv-badge[data-t="announcement"] { color: var(--dsw-static-blue-500); background: color-mix(in srgb, var(--dsw-static-blue-500) 12%, transparent); }
.qs-tv-badge[data-t="annual_report"] { color: var(--dsw-static-deepseek-500); background: color-mix(in srgb, var(--dsw-static-deepseek-500) 12%, transparent); }
.qs-tv-badge[data-t="research_report"] { color: var(--dsw-static-amber-500); background: color-mix(in srgb, var(--dsw-static-amber-500) 14%, transparent); }
.qs-tv-badge[data-t="irm"] { color: var(--dsw-static-green-500); background: color-mix(in srgb, var(--dsw-static-green-500) 12%, transparent); }
.qs-tv-badge[data-t="news"] { color: var(--dsw-static-red-400); background: color-mix(in srgb, var(--dsw-static-red-400) 12%, transparent); }
.qs-tv-badge[data-t="market"] { color: var(--dsw-alias-label-secondary); background: var(--dsw-alias-interactive-bg-hover); }
.qs-tv-badge[data-t="upload"] { color: var(--dsw-alias-label-secondary); background: var(--dsw-alias-interactive-bg-hover); }
.qs-tv-badge[data-t="unknown"] { color: var(--dsw-alias-label-tertiary); background: var(--dsw-alias-interactive-bg-hover); }

.qs-tv-mono { font-family: var(--dsw-font-family-mono, ui-monospace, SFMono-Regular, Menlo, monospace); font-size: 11px; color: var(--dsw-alias-label-dimmed); word-break: break-all; }
.qs-tv-meta { display: flex; flex-wrap: wrap; align-items: center; gap: 4px 10px; color: var(--dsw-alias-label-tertiary); font: var(--dsw-font-xxs-12); }
.qs-tv-doc-title { font: var(--dsw-font-xs-strong-13); color: var(--dsw-alias-label-primary); line-height: 1.5; }

.qs-tv-text { color: var(--dsw-alias-label-secondary); font: var(--dsw-font-xs-13); line-height: 1.6; white-space: pre-wrap; word-break: break-word; }
.qs-tv-text[data-collapsed="true"] { display: -webkit-box; -webkit-box-orient: vertical; overflow: hidden; }
.qs-tv-toggle { align-self: flex-start; border: none; background: none; padding: 0; cursor: pointer; color: var(--dsw-alias-brand-text, var(--dsw-static-blue-500)); font: var(--dsw-font-xxs-12); }
.qs-tv-toggle:hover { text-decoration: underline; }

.qs-tv-link { display: inline-flex; align-items: center; gap: 4px; color: var(--dsw-alias-brand-text, var(--dsw-static-blue-500)); font: var(--dsw-font-xxs-12); text-decoration: none; }
.qs-tv-link:hover { text-decoration: underline; }

.qs-tv-kline-chart { width: 100%; height: 352px; }
.qs-tv-kline-head { display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap; }
.qs-tv-kline-title { font: var(--dsw-font-xs-strong-13); color: var(--dsw-alias-label-primary); }

.qs-tv-row { display: flex; flex-direction: column; gap: 4px; padding: 8px 0; border-top: 1px solid var(--dsw-alias-border-l2); }
.qs-tv-row:first-child { border-top: none; padding-top: 0; }
.qs-tv-row-head { display: flex; align-items: center; gap: 6px; min-width: 0; }
.qs-tv-row-title { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font: var(--dsw-font-xxs-strong-12); color: var(--dsw-alias-label-primary); }
.qs-tv-row-date { flex: none; color: var(--dsw-alias-label-dimmed); font: var(--dsw-font-xxxs-11); }
.qs-tv-row-score { flex: none; color: var(--dsw-alias-label-tertiary); font: var(--dsw-font-xxxs-11); font-family: var(--dsw-font-family-mono, ui-monospace, SFMono-Regular, Menlo, monospace); }
.qs-tv-snippet { color: var(--dsw-alias-label-secondary); font: var(--dsw-font-xxs-12); line-height: 1.6; display: -webkit-box; -webkit-box-orient: vertical; -webkit-line-clamp: 3; overflow: hidden; white-space: pre-wrap; word-break: break-word; }

.qs-tv-tags { display: flex; flex-wrap: wrap; gap: 6px; }
.qs-tv-tag { display: inline-flex; align-items: center; gap: 4px; border: 1px solid var(--dsw-alias-border-l2); border-radius: 999px; padding: 1px 8px; font: var(--dsw-font-xxxs-11); color: var(--dsw-alias-label-secondary); }
.qs-tv-tag-kind { color: var(--dsw-alias-label-dimmed); }
.qs-tv-section { color: var(--dsw-alias-label-tertiary); font: var(--dsw-font-xxs-12); margin-top: 2px; }

.qs-tl { display: flex; flex-direction: column; }
.qs-tl-group { display: flex; gap: 10px; }
.qs-tl-rail { display: flex; flex-direction: column; align-items: center; flex: none; width: 10px; }
.qs-tl-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--dsw-alias-label-dimmed); margin-top: 5px; }
.qs-tl-line { flex: 1; width: 1px; background: var(--dsw-alias-border-l2); }
.qs-tl-group:last-child .qs-tl-line { display: none; }
.qs-tl-content { flex: 1; min-width: 0; padding-bottom: 12px; display: flex; flex-direction: column; gap: 6px; }
.qs-tl-date { font: var(--dsw-font-xxs-strong-12); color: var(--dsw-alias-label-primary); }
.qs-tl-item { display: flex; flex-direction: column; gap: 4px; padding: 6px 0; border-top: 1px dashed var(--dsw-alias-border-l2); }
.qs-tl-item:first-of-type { border-top: none; }

/* 判断台账 finding card（history_findings / search_findings） */
.qs-finding { display: flex; flex-direction: column; gap: 6px; padding: 10px 12px; border: 1px solid var(--dsw-alias-border-l2); border-radius: 10px; background: var(--dsw-alias-bg-layer-1); }
.qs-finding + .qs-finding { margin-top: 8px; }
.qs-finding-head { display: flex; flex-wrap: wrap; align-items: center; gap: 4px 8px; }
.qs-finding-badge { display: inline-flex; align-items: center; flex: none; border-radius: 4px; padding: 1px 6px; font: var(--dsw-font-xxxs-11); line-height: 16px; }
.qs-finding-badge[data-k="progression"] { color: var(--dsw-static-green-500); background: color-mix(in srgb, var(--dsw-static-green-500) 12%, transparent); }
.qs-finding-badge[data-k="regression"] { color: var(--dsw-static-red-400); background: color-mix(in srgb, var(--dsw-static-red-400) 12%, transparent); }
.qs-finding-badge[data-k="new_event"] { color: var(--dsw-static-blue-500); background: color-mix(in srgb, var(--dsw-static-blue-500) 12%, transparent); }
.qs-finding-badge[data-k="association"] { color: var(--dsw-alias-label-secondary); background: var(--dsw-alias-interactive-bg-hover); }
.qs-finding-badge[data-k="divergence"] { color: var(--dsw-static-deepseek-500); background: color-mix(in srgb, var(--dsw-static-deepseek-500) 14%, transparent); }
.qs-finding-badge[data-s="superseded"], .qs-finding-badge[data-s="dismissed"] { color: var(--dsw-alias-label-tertiary); background: var(--dsw-alias-interactive-bg-hover); }
.qs-finding-scope { color: var(--dsw-alias-label-tertiary); font: var(--dsw-font-xxxs-11); }
.qs-finding-date { margin-left: auto; color: var(--dsw-alias-label-tertiary); font: var(--dsw-font-xxxs-11); font-variant-numeric: tabular-nums; }
.qs-finding-title { font: var(--dsw-font-xs-strong-13); color: var(--dsw-alias-label-primary); }
.qs-finding-metrics { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 6px; }
.qs-finding-metric { min-width: 0; border: 1px solid var(--dsw-alias-border-l2); border-radius: 8px; padding: 6px 8px; }
.qs-finding-metric-label { display: block; color: var(--dsw-alias-label-tertiary); font: var(--dsw-font-xxxs-11); }
.qs-finding-metric-value { display: block; margin-top: 2px; color: var(--dsw-alias-label-primary); font: var(--dsw-font-xs-strong-13); font-variant-numeric: tabular-nums; }
.qs-finding-metric-value[data-tone="warning"] { color: var(--dsw-static-amber-500); }
.qs-finding-metric-value[data-tone="muted"] { color: var(--dsw-alias-label-tertiary); }
.qs-finding-note { border: 1px solid color-mix(in srgb, var(--dsw-static-amber-500) 28%, transparent); border-radius: 8px; padding: 5px 8px; background: color-mix(in srgb, var(--dsw-static-amber-500) 10%, transparent); color: var(--dsw-static-amber-500); font: var(--dsw-font-xxxs-11); }
.qs-finding-judgment { color: var(--dsw-alias-label-secondary); font: var(--dsw-font-xs-13); line-height: 1.6; white-space: pre-wrap; word-break: break-word; }
.qs-finding-foot { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.qs-finding-supersedes { color: var(--dsw-alias-label-tertiary); font: var(--dsw-font-xxxs-11); }
`

const TAG_ID = 'qingshui-toolviews'

/** Idempotent style install; returns disposer. */
export function installToolviewStyles(): () => void {
  if (typeof document === 'undefined') return () => undefined
  let tag = document.querySelector(`style[data-plugin-css="${TAG_ID}"]`)
  if (tag === null) {
    tag = document.createElement('style')
    tag.setAttribute('data-plugin-css', TAG_ID)
    tag.textContent = TOOLVIEW_CSS
    document.head.appendChild(tag)
  }
  return () => { tag?.remove() }
}
