/** Minimal research-shell sidebar styles (dsh semantic tokens only). */
export const SHELL_CSS = `
/* Single source of truth for the research-shell accent. Mirrors the harness
   deepseek accent the evidence layer already reads via --dsw-static-deepseek-500. */
.qs-shell, .qs-conv { --qs-accent: rgb(65, 118, 230); }
.qs-shell { display: flex; flex-direction: column; height: 100%; min-height: 0; gap: 8px; padding: 0 8px 8px; }
.qs-shell-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 4px 4px 0; }
.qs-shell-title { font: var(--dsw-font-xxs-12); font-weight: 600; color: var(--dsw-alias-label-secondary); }
.qs-shell-new { display: inline-flex; align-items: center; gap: 6px; border: none; border-radius: 6px; padding: 6px 8px; cursor: pointer; font: var(--dsw-font-xs-13); background: var(--dsw-alias-interactive-bg-hover); color: var(--dsw-alias-label-primary); }
.qs-shell-new:hover { background: var(--dsw-alias-interactive-bg-active, var(--dsw-alias-interactive-bg-hover)); }
.qs-shell-new:disabled { opacity: 0.5; cursor: default; }
.qs-shell-list { flex: 1; min-height: 0; overflow: auto; display: flex; flex-direction: column; gap: 2px; }
.qs-shell-item { position: relative; display: flex; align-items: center; border-radius: 6px; }
.qs-shell-item[data-active="true"] .qs-shell-row { background: var(--dsw-alias-interactive-bg-active, var(--dsw-alias-interactive-bg-hover)); font-weight: 600; box-shadow: inset 2px 0 0 var(--qs-accent); }
.qs-shell-item[data-blank="true"]:not([data-active="true"]) .qs-shell-row { color: var(--dsw-alias-label-tertiary); }
.qs-shell-row { flex: 1; min-width: 0; display: flex; align-items: center; gap: 8px; width: 100%; text-align: left; border: none; border-radius: 6px; padding: 8px; cursor: pointer; font: var(--dsw-font-xs-13); background: transparent; color: var(--dsw-alias-label-primary); }
.qs-shell-row:hover { background: var(--dsw-alias-interactive-bg-hover); }
.qs-shell-item-actions { position: absolute; right: 4px; top: 50%; transform: translateY(-50%); display: none; align-items: center; gap: 2px; }
.qs-shell-item:hover .qs-shell-item-actions, .qs-shell-item:focus-within .qs-shell-item-actions { display: flex; }
.qs-shell-item:hover .qs-shell-row, .qs-shell-item:focus-within .qs-shell-row { padding-right: 96px; }
.qs-shell-icon-btn { border: none; border-radius: 5px; padding: 4px 6px; cursor: pointer; font: var(--dsw-font-xxs-12); background: var(--dsw-alias-bg-layer-1); color: var(--dsw-alias-label-secondary); }
.qs-shell-icon-btn:hover { background: var(--dsw-alias-interactive-bg-active, var(--dsw-alias-interactive-bg-hover)); color: var(--dsw-alias-label-primary); }
.qs-shell-icon-btn[data-confirm="true"] { background: color-mix(in srgb, var(--dsw-static-red-400) 14%, transparent); color: var(--dsw-static-red-400); white-space: nowrap; }
.qs-shell-rename { flex: 1; min-width: 0; margin: 2px; padding: 6px 8px; border: 1px solid var(--dsw-alias-border-l2); border-radius: 6px; font: var(--dsw-font-xs-13); background: var(--dsw-alias-bg-layer-1); color: var(--dsw-alias-label-primary); outline: none; }
.qs-shell-rename:focus { border-color: var(--dsw-alias-border-l4, var(--dsw-alias-border-l2)); }
.qs-shell-row-title { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.qs-shell-group-label { padding: 12px 8px 2px; font: var(--dsw-font-xxs-12); color: var(--dsw-alias-label-tertiary); }
.qs-shell-time { flex: none; font-size: 11px; line-height: 16px; font-variant-numeric: tabular-nums; color: var(--dsw-alias-label-tertiary); }
.qs-shell-item:hover .qs-shell-time, .qs-shell-item:focus-within .qs-shell-time { visibility: hidden; }
.qs-shell-empty { padding: 12px 4px; color: var(--dsw-alias-label-tertiary); font: var(--dsw-font-xs-13); }
.qs-shell-rail { display: flex; flex-direction: column; align-items: center; gap: 8px; padding-top: 4px; }
.qs-shell-rail-btn { width: 32px; height: 32px; border: none; border-radius: 8px; cursor: pointer; background: transparent; color: var(--dsw-alias-label-secondary); font: var(--dsw-font-xs-13); }
.qs-shell-rail-btn:hover { background: var(--dsw-alias-interactive-bg-hover); }
.qs-brand-name { font: var(--dsw-font-s-strong-14); color: var(--dsw-alias-label-primary); letter-spacing: 0.06em; }

/* Composer leftovers that live inside ui-conversation and cannot be unmounted
   without dropping the chat itself: permission chip, context ring, token
   stats, coding todo strip, and "branch conversation". */
[data-qs-conversation="research"] [data-slot="conversation.composer.dock"],
[data-qs-conversation="research"] [data-testid="todo-panel"],
[data-qs-conversation="research"] button[aria-label^="访问模式"],
[data-qs-conversation="research"] button[aria-label^="Access mode"],
[data-qs-conversation="research"] button[aria-label^="上下文已用"],
[data-qs-conversation="research"] button[aria-label*="of context used"],
[data-qs-conversation="research"] button[aria-label="在新对话中分支"],
[data-qs-conversation="research"] button[aria-label="Branch into a new conversation"] { display: none; }
/* Loopback-only "open the harness YAML" action. Slot wrapper is inline display:contents. */
[data-slot="settings.action"] { display: none !important; }
/* Coding tool-inspector column. The slot wrapper is inline display:contents,
   so the hide has to win that. Evidence and kline stay in the transcript cards. */
[data-slot="details"] { display: none !important; }
/* Harness context-injection rows (AGENTS.md, system prompt, skill catalog). */
[data-qs-conversation="research"] div:has(> [data-disclosure-row] [data-context-source]),
[data-qs-conversation="research"] div:has(> [data-disclosure-row] [data-context-recall-icon]) { display: none !important; }

.qs-conv { display: flex; flex-direction: column; height: 100%; min-height: 0; min-width: 0; flex: 1 1 auto; align-self: stretch; background: var(--dsw-alias-bg-base);
  --dsh-chat-content-width: 748px;
  --dsh-composer-card-max-width: calc(var(--dsh-chat-content-width) + 32px);
  --dsh-composer-side-clearance: 16px;
  --dsh-composer-dock-inset: 8px;
}
/* Market strip: quotes + news share one row on wide desktops, stack on narrow.
   The wrapper owns the outer bottom border; the boards keep their own only as
   the narrow-mode separator between the two stacked rows. */
.qs-market { display: flex; flex-direction: column; flex: none; border-bottom: 1px solid var(--dsw-alias-border-l2); background: var(--dsw-alias-bg-base); }
.qs-market > .qs-tape { border-bottom: none; }
.qs-boards { display: grid; grid-template-columns: 1fr 1fr; flex: none; border-bottom: 1px solid var(--dsw-alias-border-l2); background: var(--dsw-alias-bg-base); }
.qs-board { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; min-width: 0; padding: 9px 16px; border-bottom: 1px solid var(--dsw-alias-border-l2); }
.qs-board:nth-child(odd) { border-right: 1px solid var(--dsw-alias-border-l2); }
.qs-board:nth-last-child(-n+2) { border-bottom: none; }
.qs-board-name { flex: none; font: var(--dsw-font-xxs-12); color: var(--dsw-alias-label-secondary); }
.qs-board-figures { display: flex; align-items: baseline; gap: 8px; min-width: 0; }
.qs-board-close { color: var(--dsw-alias-label-tertiary); font: var(--dsw-font-xxs-12); font-variant-numeric: tabular-nums; }
.qs-board-up, .qs-board-down, .qs-board-flat { font-size: 15px; line-height: 20px; font-weight: 600; font-variant-numeric: tabular-nums; }
.qs-board-up { color: var(--dsw-static-red-600, var(--dsw-static-red-400)); }
.qs-board-down { color: var(--dsw-alias-state-success-primary, var(--dsw-static-green-500, #1f8a4c)); }
.qs-board-flat { color: var(--dsw-alias-label-primary); }
.qs-tape { flex: none; height: 44px; min-width: 0; max-width: 100%; overflow: hidden; border-bottom: 1px solid var(--dsw-alias-border-l2); background: var(--dsw-alias-bg-base); display: flex; align-items: center; }
.qs-tape-empty { margin: 0; padding: 0 16px; color: var(--dsw-alias-label-tertiary); font: var(--dsw-font-xs-13); white-space: nowrap; }
.qs-tape-track { display: flex; flex-direction: row; align-items: center; width: max-content; }
.qs-tape-track:not(.qs-tape-still) { animation: qs-tape-marquee linear infinite; }
.qs-tape:hover .qs-tape-track, .qs-tape:focus-within .qs-tape-track { animation-play-state: paused; }
.qs-tape-row { display: inline-flex; align-items: center; gap: 8px; flex: none; width: auto; max-width: 520px; height: 44px; padding: 0 16px; border: none; border-right: 1px solid var(--dsw-alias-border-l2); background: transparent; text-align: left; cursor: pointer; color: var(--dsw-alias-label-primary); font-size: 13px; line-height: 20px; }
.qs-tape-row:hover { background: var(--dsw-alias-interactive-bg-hover); }
.qs-tape-row:focus-visible { outline: 2px solid var(--qs-accent); outline-offset: -2px; }
.qs-tape-time { flex: none; color: var(--dsw-alias-label-tertiary); font-size: 12px; line-height: 20px; font-variant-numeric: tabular-nums; }
.qs-tape-title { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.qs-tape-go { display: none; flex: none; color: var(--qs-accent); font-size: 12px; line-height: 20px; white-space: nowrap; }
.qs-tape-row:hover .qs-tape-go, .qs-tape-row:focus-visible .qs-tape-go { display: inline; }
@keyframes qs-tape-marquee { from { transform: translateX(0); } to { transform: translateX(-50%); } }
@media (min-width: 840px) {
  .qs-boards { grid-template-columns: repeat(4, minmax(0, 1fr)); }
  .qs-board { border-bottom: none; border-right: 1px solid var(--dsw-alias-border-l2); }
  .qs-board:last-child { border-right: none; }
}
/* Wide desktop: fold quotes + news onto one row (boards keep ~60%, marquee fills). */
@media (min-width: 1280px) {
  .qs-market { flex-direction: row; align-items: stretch; }
  .qs-market > .qs-boards { flex: 0 0 60%; border-bottom: none; border-right: 1px solid var(--dsw-alias-border-l2); }
  .qs-market > .qs-tape { flex: 1 1 auto; min-width: 0; }
}
@media (prefers-reduced-motion: reduce) {
  .qs-tape { overflow-x: auto; overflow-y: hidden; }
  .qs-tape-track { animation: none; }
}
.qs-signals { display: grid; grid-template-columns: 1fr 1fr; flex: none; border-bottom: 1px solid var(--dsw-alias-border-l2); background: var(--dsw-alias-bg-base); }
.qs-signals[data-state="loading"], .qs-signals[data-state="absent"] { display: flex; align-items: center; min-height: 36px; }
.qs-signal-lane { min-width: 0; display: flex; flex-direction: column; padding: 8px 0 6px; border-bottom: 1px solid var(--dsw-alias-border-l2); }
.qs-signal-lane:nth-child(odd) { border-right: 1px solid var(--dsw-alias-border-l2); }
.qs-signal-lane:nth-last-child(-n+2) { border-bottom: none; }
.qs-signal-lane-name { padding: 0 12px 2px; font: var(--dsw-font-xxs-12); color: var(--dsw-alias-label-secondary); }
.qs-signal-row { display: grid; grid-template-columns: 16px minmax(0, 1fr); gap: 8px; align-items: baseline; width: 100%; padding: 3px 12px; border: none; background: transparent; text-align: left; cursor: pointer; color: var(--dsw-alias-label-primary); }
.qs-signal-row:hover { background: var(--dsw-alias-interactive-bg-hover); }
.qs-signal-row:focus-visible { outline: 2px solid var(--qs-accent); outline-offset: -2px; }
.qs-signal-mark { font-size: 12px; line-height: 20px; font-weight: 600; }
.qs-signal-text { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 13px; line-height: 20px; }
.qs-signal-empty { margin: 0; padding: 2px 12px 4px; color: var(--dsw-alias-label-tertiary); font: var(--dsw-font-xxs-12); }
.qs-signals-dock { border-bottom: none; border-top: 1px solid var(--dsw-alias-border-l2); max-height: 148px; overflow: auto; }
/* Hero: the signal board is a briefing directly above the composer (inside the
   centered cluster), so it no longer matches the old direct-child selector. */
.qs-hero-cluster > .qs-signals { max-height: 32vh; overflow: auto; margin-bottom: 12px; }
@media (min-width: 840px) {
  .qs-signals[data-state="ok"] { grid-template-columns: repeat(4, minmax(0, 1fr)); }
  .qs-signal-lane { border-bottom: none; border-right: 1px solid var(--dsw-alias-border-l2); }
  .qs-signal-lane:last-child { border-right: none; }
}
.qs-conv-main { display: flex; flex: 1; min-height: 0; min-width: 0; }
.qs-conv-scroll { display: flex; flex: 1; flex-direction: column; min-height: 0; min-width: 0; overflow-x: hidden; overflow-y: auto; scrollbar-gutter: stable; }
/* Suggested questions sit under the centered composer. Each sentence hugs
   its own width so the hover wash is not a full-width bar. */
.qs-starts { width: 100%; margin: 10px 0 0; padding: 0 8px; display: flex; flex-direction: column; align-items: flex-start; }
.qs-starts-row { display: block; width: fit-content; max-width: 100%; text-align: left; border: none; border-radius: 8px; padding: 5px 10px; cursor: pointer; background: transparent; color: var(--dsw-alias-label-secondary); font-size: 14px; font-weight: 400; line-height: 22px; }
.qs-starts-row:hover { background: var(--dsw-alias-interactive-bg-hover); color: var(--qs-accent); }
.qs-starts-row:focus-visible { outline: 2px solid var(--qs-accent); outline-offset: 2px; }
.qs-ev-rail { width: 320px; flex: none; overflow: auto; border-left: 1px solid var(--dsw-alias-border-l2); background: var(--dsw-alias-bg-base); }
.qs-conv[data-evidence="open"] { --dsh-chat-content-width: 560px; }
/* Narrow window: the rail overlays the transcript instead of squeezing it.
   Content width returns to 748px (the rail floats on top); the composer card
   max-width re-resolves from it automatically. */
@media (max-width: 1280px) {
  .qs-conv[data-evidence="open"] { --dsh-chat-content-width: 748px; }
  .qs-conv-main { position: relative; }
  .qs-ev-rail {
    position: absolute; top: 0; right: 0; bottom: 0; z-index: 8;
    width: min(320px, 88%);
    box-shadow: -16px 0 40px color-mix(in srgb, #000 26%, transparent);
  }
}
/* Blank desk: the composer and the questions under it sit in the middle.
   A running chat pins the signal dock and the composer to the bottom. */
.qs-conv[data-phase="hero"] .qs-conv-scroll { justify-content: safe center; }
.qs-conv[data-phase="hero"] .qs-conv-scroll > [data-slot="conversation.session"] { display: none; }
.qs-hero-cluster {
  width: min(calc(var(--dsh-composer-card-max-width) + 2 * var(--dsh-composer-side-clearance)), 100%);
  margin: 0 auto; display: flex; flex: none; flex-direction: column; align-items: stretch;
}
.qs-active-foot {
  position: sticky; bottom: 0; z-index: 7; margin-top: auto; display: flex; flex: none; flex-direction: column;
  background: linear-gradient(180deg, color-mix(in srgb, var(--dsw-alias-bg-base) 0%, transparent) 0px, var(--dsw-alias-bg-base) 28px);
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
.qs-conv-seat { display: flex; flex: none; flex-direction: column; position: relative; z-index: 1; visibility: visible; --dsh-composer-text-max-height: 336px; }
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

/* ── data-plane connectivity badge（/qingshui/health 探活） ── */
.qs-net { position: fixed; top: 12px; right: 12px; z-index: 2147483000; display: flex; align-items: center; gap: 8px; max-width: 440px; border: 1px solid color-mix(in srgb, var(--dsw-static-amber-500) 32%, transparent); border-radius: 10px; background: var(--dsw-alias-bg-layer-1); box-shadow: 0 8px 28px color-mix(in srgb, #000 22%, transparent); padding: 8px 12px; }
.qs-net-icon { flex: none; color: var(--dsw-static-amber-500); font-size: 14px; line-height: 20px; }
.qs-net-text { flex: none; font: var(--dsw-font-xs-strong-13); color: var(--dsw-static-amber-500); }
.qs-net-error { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--dsw-alias-label-secondary); font: var(--dsw-font-xxs-12); }
.qs-net-retry { flex: none; border: 1px solid var(--dsw-alias-border-l2); border-radius: 6px; background: transparent; color: var(--dsw-alias-label-primary); font: var(--dsw-font-xxs-12); padding: 3px 10px; cursor: pointer; }
.qs-net-retry:hover { background: var(--dsw-alias-interactive-bg-hover); }

/* ── research panel（右侧常驻：结论 + 证据） ── */
.qs-panel { width: 320px; flex: none; display: flex; flex-direction: column; min-height: 0; overflow: auto; border-left: 1px solid var(--dsw-alias-border-l2); background: var(--dsw-alias-bg-base); }
.qs-panel-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 10px 12px; border-bottom: 1px solid var(--dsw-alias-border-l2); position: sticky; top: 0; background: var(--dsw-alias-bg-base); z-index: 1; }
.qs-panel-title { font: var(--dsw-font-xs-strong-13); color: var(--dsw-alias-label-primary); }
.qs-panel-refresh { border: 1px solid var(--dsw-alias-border-l2); border-radius: 6px; background: transparent; color: var(--dsw-alias-label-secondary); font: var(--dsw-font-xxs-12); padding: 3px 10px; cursor: pointer; }
.qs-panel-refresh:hover { background: var(--dsw-alias-interactive-bg-hover); }
.qs-panel-body { display: flex; flex-direction: column; gap: 16px; padding: 12px; }
.qs-panel-section { display: flex; flex-direction: column; gap: 8px; }
.qs-panel-section-title { display: flex; align-items: center; justify-content: space-between; gap: 8px; font: var(--dsw-font-xxs-strong-12); color: var(--dsw-alias-label-secondary); }
.qs-panel-close { border: none; background: transparent; cursor: pointer; color: var(--dsw-alias-label-tertiary); font-size: 16px; line-height: 16px; padding: 0; }
.qs-panel-close:hover { color: var(--dsw-alias-label-primary); }
.qs-panel-status { color: var(--dsw-alias-label-tertiary); font: var(--dsw-font-xs-13); padding: 4px 0; }
.qs-panel-empty { color: var(--dsw-alias-label-tertiary); font: var(--dsw-font-xs-13); padding: 4px 0; }
.qs-panel-error { color: var(--dsw-alias-state-error-primary); font: var(--dsw-font-xs-13); display: flex; flex-direction: column; gap: 6px; }
/* Narrow window: drop the persistent panel; the chat takes the full width. */
@media (max-width: 1280px) {
  .qs-panel { display: none; }
}
`

const TAG_ID = 'qingshui-shell'

/** Idempotent style install; returns disposer. */
export function installClientStyles(): () => void {
  if (typeof document === 'undefined') return () => undefined
  let tag = document.querySelector(`style[data-plugin-css="${TAG_ID}"]`)
  if (tag === null) {
    tag = document.createElement('style')
    tag.setAttribute('data-plugin-css', TAG_ID)
    document.head.appendChild(tag)
  }
  tag.textContent = SHELL_CSS
  return () => { tag?.remove() }
}
