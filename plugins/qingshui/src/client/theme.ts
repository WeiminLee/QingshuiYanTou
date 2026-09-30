/** Minimal research-shell sidebar styles (dsh semantic tokens only). */
export const SHELL_CSS = `
.qs-shell { display: flex; flex-direction: column; height: 100%; min-height: 0; gap: 8px; padding: 0 8px 8px; }
.qs-shell-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 4px 4px 0; }
.qs-shell-title { font: var(--dsw-font-xxs-12); font-weight: 600; color: var(--dsw-alias-label-secondary); }
.qs-shell-new { display: inline-flex; align-items: center; gap: 6px; border: none; border-radius: 6px; padding: 6px 8px; cursor: pointer; font: var(--dsw-font-xs-13); background: var(--dsw-alias-interactive-bg-hover); color: var(--dsw-alias-label-primary); }
.qs-shell-new:hover { background: var(--dsw-alias-interactive-bg-active, var(--dsw-alias-interactive-bg-hover)); }
.qs-shell-new:disabled { opacity: 0.5; cursor: default; }
.qs-shell-list { flex: 1; min-height: 0; overflow: auto; display: flex; flex-direction: column; gap: 2px; }
.qs-shell-row { display: flex; align-items: center; gap: 8px; width: 100%; text-align: left; border: none; border-radius: 6px; padding: 8px; cursor: pointer; font: var(--dsw-font-xs-13); background: transparent; color: var(--dsw-alias-label-primary); }
.qs-shell-row:hover { background: var(--dsw-alias-interactive-bg-hover); }
.qs-shell-row[data-active="true"] { background: var(--dsw-alias-interactive-bg-hover); font-weight: 600; }
.qs-shell-row-title { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.qs-shell-empty { padding: 12px 4px; color: var(--dsw-alias-label-tertiary); font: var(--dsw-font-xs-13); }
.qs-shell-rail { display: flex; flex-direction: column; align-items: center; gap: 8px; padding-top: 4px; }
.qs-shell-rail-btn { width: 32px; height: 32px; border: none; border-radius: 8px; cursor: pointer; background: transparent; color: var(--dsw-alias-label-secondary); font: var(--dsw-font-xs-13); }
.qs-shell-rail-btn:hover { background: var(--dsw-alias-interactive-bg-hover); }

.qs-conv { display: flex; flex-direction: column; height: 100%; min-width: 0; background: var(--dsw-alias-bg-base);
  --dsh-chat-content-width: 748px;
  --dsh-composer-card-max-width: calc(var(--dsh-chat-content-width) + 32px);
  --dsh-composer-side-clearance: 16px;
  --dsh-composer-dock-inset: 8px;
}
.qs-conv-scroll { display: flex; flex: 1; flex-direction: column; min-height: 0; overflow-x: hidden; overflow-y: auto; scrollbar-gutter: stable; }
.qs-conv[data-phase="hero"] .qs-conv-scroll { justify-content: center; }
.qs-conv[data-phase="active"] { overflow: hidden; }
.qs-conv[data-phase="active"] .qs-conv-seat {
  position: sticky; bottom: 0; z-index: 7;
  background: linear-gradient(180deg, color-mix(in srgb, var(--dsw-alias-bg-base) 0%, transparent) 0px, var(--dsw-alias-bg-base) 36px);
}
.qs-conv[data-phase="settling"] .qs-conv-seat { visibility: hidden; }
.qs-conv-seat { display: flex; flex: none; flex-direction: column; --dsh-composer-text-max-height: 336px; }
.qs-conv-stack { display: flex; flex-direction: column; gap: 6px; }
.qs-conv-stack-hero {
  position: relative; align-self: center; gap: 8px; padding-bottom: 32px; z-index: 1;
  width: min(calc(var(--dsh-composer-card-max-width) + 2 * var(--dsh-composer-side-clearance)), 100%);
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
    tag.textContent = SHELL_CSS
    document.head.appendChild(tag)
  }
  return () => { tag?.remove() }
}
