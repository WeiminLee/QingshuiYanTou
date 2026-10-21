# Theme — light research shell

No Tailwind. Tokens come from `dsh/packages/client/ui-theme/src/styles/design-platform.css` (`body` = light). Plugin CSS only references those aliases.

## Compact tokens (light)

- Canvas: `--dsw-alias-bg-base` → neutral bluish 00 (white)
- Sidebar module: `--dsw-alias-bg-module-platform` → neutral bluish 60 (cool gray)
- Primary text: `--dsw-alias-label-primary` → neutral bluish 1000 (near black)
- Secondary text: `--dsw-alias-label-secondary` → neutral bluish 700 `rgb(97, 102, 107)`
- Tertiary: `--dsw-alias-label-tertiary` → neutral bluish 600
- Hover wash: `--dsw-alias-interactive-bg-hover` `rgba(38, 49, 72, 0.06)`
- Hairline: `--dsw-alias-border-l2` `rgba(0, 0, 0, 0.1)`
- Info / citation blue: `--dsw-static-deepseek-500` `rgb(65, 118, 230)`
- Danger: `--dsw-static-red-400` `rgb(242, 90, 90)`
- Type: system UI sans. Sizes used: 11, 12, 13, 14, 16/28 for the answer body
- Radius: 6px rows, 8–12px cards, composer capsule is a large rounded rectangle
- Sidebar width: about 280px expanded, 56px rail
- Chat measure: `--dsh-chat-content-width: 748px`
- Shadow: evidence popover `0 8px 28px` at 22% black; pinned card `0 16px 48px` at 30% black

## Plugin selectors that matter

From `plugins/qingshui/src/client/theme.ts`:

- `.qs-shell`, `.qs-shell-title`, `.qs-shell-row`, `.qs-shell-item[data-active="true"]`
- `.qs-brand-name` — 14px semibold, letter-spacing 0.06em
- `.qs-conv` — column, content width 748px
- `.qs-ev-pop` / `.qs-ev-card` — evidence hover and pinned card
- Hidden coding chrome: `[data-slot="conversation.composer.dock"]`, permission button, context meter, branch button, `[data-slot="details"]`, `[data-slot="settings.action"]`

## Raw alias block (light `body`)

```css
body {
  --dsw-alias-bg-base: var(--dsw-static-neutral-bluish-00);
  --dsw-alias-bg-module-platform: var(--dsw-static-neutral-bluish-60);
  --dsw-alias-border-l2: rgba(0, 0, 0, 0.1);
  --dsw-alias-interactive-bg-hover: rgba(38, 49, 72, 0.06);
  --dsw-alias-label-primary: var(--dsw-static-neutral-bluish-1000);
  --dsw-alias-label-secondary: var(--dsw-static-neutral-bluish-700);
  --dsw-alias-label-tertiary: var(--dsw-static-neutral-bluish-600);
  --dsw-alias-state-business-primary: var(--dsw-static-deepseek-500);
  --dsw-static-deepseek-500: rgb(65, 118, 230);
  --dsw-static-red-400: rgb(242, 90, 90);
}
```
