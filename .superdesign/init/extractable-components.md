# Extractable components

## ResearchSidebar
- Source: `plugins/qingshui/src/client/SessionBrowser.tsx`
- Category: layout
- Description: Left column with brand, new chat, session list, and settings
- Extractable props: activeTitle (string, default: "新对话")
- Hardcoded: 清水投研, 新会话, 投研会话, ledger SVG, ✎, 🗄, 设置

## ResearchComposer
- Source: `plugins/qingshui/src/client/ResearchConversation.tsx`
- Category: layout
- Description: Bottom composer capsule for a blank research chat
- Extractable props: placeholder (string, default: "问一只股票、一条公告，或一个预期差"), modelName (string, default: "GLM 5.3")
- Hardcoded: plus button, send arrow, capsule radius

## EvidenceCard
- Source: `plugins/qingshui/src/client/toolviews/evidence-card.tsx`
- Category: basic
- Description: Cited filing card with title, source, excerpt, and evidence id
- Extractable props: title (string), source (string), excerpt (string)
- Hardcoded: 证据原文 label, PDF link treatment, mono id
