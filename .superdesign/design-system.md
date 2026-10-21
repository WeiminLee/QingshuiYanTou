# 清水投研 — design system

## Product

清水投研 is a single-user research agent for professional investors. It is an agent product, not a coding workspace. The person asks about one stock, one filing, a sector, or the session's market, and the answer is a judgment anchored to evidence ids (`EV:`).

Jobs:

- Start a research chat with no workspace, folder, or repo.
- Read a conclusion first, then the table, then the cited evidence.
- Open an evidence card (title, source, date, excerpt) without a code inspector.
- Keep model API keys in Settings → 模型. Language and appearance stay in 通用设置.

Out of the product: file trees, terminals, permission modes, context-token rings, plugin inventories, branch-conversation, and harness beta notices.

## Current visual (ground truth)

Light, cool-gray, one accent blue. Do not invent a second palette during reproduction.

- Background: white `#ffffff` (`--dsw-alias-bg-base`)
- Sidebar: cool gray wash, about 280px
- Text: near-black primary, `rgb(97, 102, 107)` secondary
- Hover: `rgba(38, 49, 72, 0.06)`
- Border: `rgba(0, 0, 0, 0.1)`
- Accent: `rgb(65, 118, 230)` for citations and links only
- Danger: `rgb(242, 90, 90)` for archive confirm
- Font: system sans. Answer body 16px / 28px. UI chrome 12–14px
- Radius: 6px list rows, 10–12px cards, large capsule for the composer
- Content width: 748px centered in the conversation column
- Motion: 150ms sidebar fade. No decorative gradients.

## Layout

```
┌ 清水投研          ┐┌ 回答区（空则只有底部输入） ─────────┐
│ 新会话            ││                                     │
│ 投研会话          ││                                     │
│  当前对话         ││  [ 问一只股票、一条公告，或一个预期差 ] │
│  …                ││  +                          GLM 5.3 ↑ │
│ 设置              │└─────────────────────────────────────┘
└───────────────────┘
```

Brand mark is a 24px ledger outline (rounded rect, three text rules), then the word 清水投研. Do not replace it with a fish, initials, or an emoji.
