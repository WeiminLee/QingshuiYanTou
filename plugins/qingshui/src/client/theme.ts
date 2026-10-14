/** Minimal research-shell sidebar styles (dsh semantic tokens only). */
export const SHELL_CSS = `
.qs-shell { display: flex; flex-direction: column; height: 100%; min-height: 0; gap: 8px; padding: 0 8px 8px; }
.qs-shell-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 4px 4px 0; }
.qs-shell-title { font: var(--dsw-font-xxs-12); font-weight: 600; color: var(--dsw-alias-label-secondary); }
.qs-shell-new { display: inline-flex; align-items: center; gap: 6px; border: none; border-radius: 6px; padding: 6px 8px; cursor: pointer; font: var(--dsw-font-xs-13); background: var(--dsw-alias-interactive-bg-hover); color: var(--dsw-alias-label-primary); }
.qs-shell-new:hover { background: var(--dsw-alias-interactive-bg-active, var(--dsw-alias-interactive-bg-hover)); }
.qs-shell-new:disabled { opacity: 0.5; cursor: default; }
.qs-shell-list { flex: 1; min-height: 0; overflow: auto; display: flex; flex-direction: column; gap: 2px; }
.qs-shell-item { position: relative; display: flex; align-items: center; border-radius: 6px; }
.qs-shell-item[data-active="true"] .qs-shell-row { background: var(--dsw-alias-interactive-bg-hover); font-weight: 600; }
.qs-shell-row { flex: 1; min-width: 0; display: flex; align-items: center; gap: 8px; width: 100%; text-align: left; border: none; border-radius: 6px; padding: 8px; cursor: pointer; font: var(--dsw-font-xs-13); background: transparent; color: var(--dsw-alias-label-primary); }
.qs-shell-row:hover { background: var(--dsw-alias-interactive-bg-hover); }
.qs-shell-item-actions { position: absolute; right: 4px; top: 50%; transform: translateY(-50%); display: none; align-items: center; gap: 2px; }
.qs-shell-item:hover .qs-shell-item-actions, .qs-shell-item:focus-within .qs-shell-item-actions { display: flex; }
.qs-shell-item:hover .qs-shell-row { padding-right: 56px; }
.qs-shell-icon-btn { border: none; border-radius: 5px; padding: 4px 6px; cursor: pointer; font: var(--dsw-font-xxs-12); background: var(--dsw-alias-bg-layer-1); color: var(--dsw-alias-label-secondary); }
.qs-shell-icon-btn:hover { background: var(--dsw-alias-interactive-bg-active, var(--dsw-alias-interactive-bg-hover)); color: var(--dsw-alias-label-primary); }
.qs-shell-icon-btn[data-confirm="true"] { background: color-mix(in srgb, var(--dsw-static-red-400) 14%, transparent); color: var(--dsw-static-red-400); white-space: nowrap; }
.qs-shell-rename { flex: 1; min-width: 0; margin: 2px; padding: 6px 8px; border: 1px solid var(--dsw-alias-border-l2); border-radius: 6px; font: var(--dsw-font-xs-13); background: var(--dsw-alias-bg-layer-1); color: var(--dsw-alias-label-primary); outline: none; }
.qs-shell-rename:focus { border-color: var(--dsw-alias-border-l4, var(--dsw-alias-border-l2)); }
.qs-shell-row-title { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.qs-shell-empty { padding: 12px 4px; color: var(--dsw-alias-label-tertiary); font: var(--dsw-font-xs-13); }
.qs-shell-rail { display: flex; flex-direction: column; align-items: center; gap: 8px; padding-top: 4px; }
.qs-shell-rail-btn { width: 32px; height: 32px; border: none; border-radius: 8px; cursor: pointer; background: transparent; color: var(--dsw-alias-label-secondary); font: var(--dsw-font-xs-13); }
.qs-shell-rail-btn:hover { background: var(--dsw-alias-interactive-bg-hover); }

.qs-conv { display: flex; flex-direction: column; height: 100%; min-height: 0; min-width: 0; flex: 1 1 auto; align-self: stretch; background: var(--dsw-alias-bg-base);
  --dsh-chat-content-width: 748px;
  --dsh-composer-card-max-width: calc(var(--dsh-chat-content-width) + 32px);
  --dsh-composer-side-clearance: 16px;
  --dsh-composer-dock-inset: 8px;
}
.qs-conv-scroll { display: flex; flex: 1; flex-direction: column; min-height: 0; overflow-x: hidden; overflow-y: auto; scrollbar-gutter: stable; }
/* Archive Home IA: composer pinned at bottom of the conversation pane
   (not vertically centered like stock dsh hero). */
.qs-conv[data-phase="hero"] .qs-conv-scroll { justify-content: flex-end; }
.qs-conv[data-phase="hero"] .qs-conv-seat,
.qs-conv[data-phase="active"] .qs-conv-seat {
  position: sticky; bottom: 0; z-index: 7;
  background: linear-gradient(180deg, color-mix(in srgb, var(--dsw-alias-bg-base) 0%, transparent) 0px, var(--dsw-alias-bg-base) 36px);
}
.qs-conv[data-phase="active"] { overflow: hidden; }
/* Shadow root replaces stock ConversationRoot, so the stock active-phase
   flex: 1 0 auto / min-height: auto on the session body (viewArea) stops
   matching. Without it the body keeps flex:1/min-height:0, its content
   overflows the untall body, and the composer seat's flow position lands
   mid-transcript — sticky bottom:0 then has nothing to pin against in a
   long chat. */
.qs-conv[data-phase="active"] .qs-conv-scroll > [data-slot="conversation.session"] > div {
  flex: 1 0 auto; min-height: auto;
}
.qs-conv[data-phase="settling"] .qs-conv-seat { visibility: hidden; }
.qs-conv-seat { display: flex; flex: none; flex-direction: column; --dsh-composer-text-max-height: 336px; }
.qs-conv-stack { display: flex; flex-direction: column; gap: 6px; }
.qs-conv-stack-hero {
  position: relative; align-self: center; gap: 8px; padding-bottom: 16px; z-index: 1;
  width: min(calc(var(--dsh-composer-card-max-width) + 2 * var(--dsh-composer-side-clearance)), 100%);
}

/* ── assistant-step shadow: mirrors stock AssistantMarkdown + Think row ── */
.qs-qa-root { display: flex; flex-direction: column; font-size: 16px; line-height: 28px; color: var(--dsw-alias-label-primary); }
.qs-qa-body { display: flex; flex-direction: column; gap: 16px; }
.qs-qa-body .md-table-wide {
  --dsh-table-spare: max(0px, calc((100cqw - var(--dsh-chat-content-width, 748px)) / 2));
  --dsh-table-lead: calc(var(--dsh-table-spare) + min(var(--dsh-chat-content-width, 748px), 100cqw) - 100%);
  box-sizing: border-box;
  width: calc(100% + var(--dsh-table-lead) + var(--dsh-table-spare));
  max-width: none;
  margin-left: calc(-1 * var(--dsh-table-lead));
  padding-left: var(--dsh-table-lead);
}
.qs-qa-stopped { align-self: flex-start; padding: 0 6px; border-radius: 6px; background: var(--dsw-alias-interactive-bg-hover); color: var(--dsw-alias-label-tertiary); font-size: 11px; line-height: 18px; }
.qs-qa-images { display: flex; }

.qs-think { display: flex; flex-direction: column; }
.qs-think-row { position: relative; overflow: hidden; }
.qs-think[data-state="running"] .qs-think-row::after {
  content: '';
  position: absolute;
  inset-block: 0;
  left: 0;
  width: 300px;
  background: linear-gradient(90deg, transparent 0%, color-mix(in srgb, var(--dsw-alias-bg-base) 60%, transparent) 55%, transparent 100%);
  animation: qs-think-sweep 2.6s ease-out infinite;
  pointer-events: none;
}
@keyframes qs-think-sweep { 0% { left: -300px; } 90%, 100% { left: 100%; } }
.qs-think-leading { flex-shrink: 0; }
.qs-think-chevron { color: var(--dsw-alias-label-secondary); }
.qs-think-title { font-weight: 400; }
.qs-think-sep { flex: none; width: 2px; height: 2px; margin: 0 8px; border-radius: 1px; background: var(--dsw-alias-label-caption); }
.qs-think-summary { min-width: 0; overflow: hidden; flex: 1 1 auto; color: var(--dsw-alias-label-tertiary); font-size: 14px; line-height: 24px; text-overflow: ellipsis; white-space: nowrap; }
.qs-think-summary[data-follow-end] { text-overflow: clip; }
.qs-think-body { padding: 4px 0 4px 22px; color: var(--dsw-alias-label-tertiary); font-size: 14px; line-height: 24px; white-space: pre-wrap; word-break: break-word; }
.qs-visually-hidden { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }
@media (prefers-reduced-motion: reduce) { .qs-think[data-state="running"] .qs-think-row::after { animation: none; } }

/* ── EV citation chips + evidence popover / pinned card ── */
/* Chip itself is the stock fileMention button inside MarkdownText; recolor to
   the evidence accent without touching its layout. */
.qs-qa-wrap code button { color: var(--dsw-static-deepseek-500); }

.qs-ev-pop {
  position: fixed; z-index: 2147483000;
  max-height: min(420px, 70vh); overflow: auto;
  border: 1px solid var(--dsw-alias-border-l2); border-radius: 10px;
  background: var(--dsw-alias-bg-layer-1);
  box-shadow: 0 8px 28px color-mix(in srgb, #000 22%, transparent);
  padding: 10px 12px; display: flex; flex-direction: column; gap: 6px;
}
.qs-ev-backdrop {
  position: fixed; inset: 0; z-index: 2147483100;
  background: color-mix(in srgb, #000 36%, transparent);
  display: flex; align-items: center; justify-content: center; padding: 24px;
}
.qs-ev-card {
  width: min(620px, 100%); max-height: 82vh; overflow: auto;
  border: 1px solid var(--dsw-alias-border-l2); border-radius: 12px;
  background: var(--dsw-alias-bg-layer-1);
  box-shadow: 0 16px 48px color-mix(in srgb, #000 30%, transparent);
  padding: 0 0 14px; display: flex; flex-direction: column; gap: 8px;
}
.qs-ev-card-head {
  display: flex; align-items: center; justify-content: space-between;
  padding: 10px 14px 6px; position: sticky; top: 0;
  background: var(--dsw-alias-bg-layer-1);
}
.qs-ev-card-title { font: var(--dsw-font-s-strong-14); color: var(--dsw-alias-label-primary); }
.qs-ev-card-close { border: none; background: transparent; color: var(--dsw-alias-label-secondary); font-size: 18px; line-height: 1; cursor: pointer; padding: 2px 8px; border-radius: 6px; }
.qs-ev-card-close:hover { background: var(--dsw-alias-interactive-bg-hover); color: var(--dsw-alias-label-primary); }
.qs-ev-pop > *, .qs-ev-card > .qs-ev-doc-title, .qs-ev-card > .qs-ev-meta, .qs-ev-card > .qs-ev-text, .qs-ev-card > .qs-ev-toggle, .qs-ev-card > .qs-ev-foot, .qs-ev-card > .qs-ev-status { margin-inline: 12px; }
.qs-ev-doc-title { font: var(--dsw-font-xs-strong-13); color: var(--dsw-alias-label-primary); line-height: 1.5; }
.qs-ev-meta { display: flex; flex-wrap: wrap; align-items: center; gap: 4px 10px; color: var(--dsw-alias-label-tertiary); font: var(--dsw-font-xxs-12); }
.qs-ev-badge { display: inline-flex; align-items: center; flex: none; border-radius: 4px; padding: 1px 6px; font: var(--dsw-font-xxxs-11); line-height: 16px; color: var(--dsw-alias-label-secondary); background: var(--dsw-alias-interactive-bg-hover); }
.qs-ev-text { color: var(--dsw-alias-label-secondary); font: var(--dsw-font-xs-13); line-height: 1.6; white-space: pre-wrap; word-break: break-word; }
.qs-ev-text[data-collapsed="true"] { display: -webkit-box; -webkit-box-orient: vertical; overflow: hidden; }
.qs-ev-toggle { align-self: flex-start; border: none; background: transparent; cursor: pointer; color: var(--dsw-static-deepseek-500); font: var(--dsw-font-xxs-12); padding: 0; }
.qs-ev-toggle:hover { text-decoration: underline; }
.qs-ev-foot { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-top: 2px; }
.qs-ev-mono { font-family: var(--dsw-font-family-mono, ui-monospace, SFMono-Regular, Menlo, monospace); font-size: 11px; color: var(--dsw-alias-label-dimmed); word-break: break-all; }
.qs-ev-pdf { color: var(--dsw-static-deepseek-500); font: var(--dsw-font-xxs-12); text-decoration: none; }
.qs-ev-pdf:hover { text-decoration: underline; }
.qs-ev-status { color: var(--dsw-alias-label-tertiary); font: var(--dsw-font-xs-13); }
.qs-ev-error { color: var(--dsw-alias-state-error-primary); display: flex; flex-direction: column; gap: 6px; }
.qs-ev-hint { color: var(--dsw-alias-label-tertiary); font: var(--dsw-font-xxs-12); }
.qs-ev-retry { align-self: flex-start; border: 1px solid var(--dsw-alias-border-l2); border-radius: 6px; background: transparent; color: var(--dsw-alias-label-primary); font: var(--dsw-font-xxs-12); padding: 3px 10px; cursor: pointer; }
.qs-ev-retry:hover { background: var(--dsw-alias-interactive-bg-hover); }
`

const TAG_ID = 'qingshui-shell'

/** Idempotent style install; returns disposer. */
export function installClientStyles(): () => void {
  if (typeof document === 'undefined') return () => undefined
  let tag = document.querySelector(`style[data-plugin-css="${TAG_ID}"]`)
  if (tag === null) {
    tag = document.createElement('style')
    tag.setAttribute('data-plugin-css', TAG_ID)
    tag.textContent = SHELL_CSS
    document.head.appendChild(tag)
  }
  return () => { tag?.remove() }
}
