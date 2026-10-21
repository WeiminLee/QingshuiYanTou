# Pages

## / Research shell
Entry: `plugins/qingshui/src/client/index.ts` (`apply`)
Dependencies:
- plugins/qingshui/src/client/Brand.tsx
- plugins/qingshui/src/client/SessionBrowser.tsx
  - plugins/qingshui/src/client/session-actions.ts
  - plugins/qingshui/src/client/locales.ts
- plugins/qingshui/src/client/ResearchConversation.tsx
  - plugins/qingshui/src/client/conversation-owner.ts
  - plugins/qingshui/src/client/ev-cite-layer.tsx
  - plugins/qingshui/src/client/ev-view.tsx
- plugins/qingshui/src/client/theme.ts
- plugins/qingshui/src/client/toolviews/index.ts
  - plugins/qingshui/src/client/toolviews/evidence-card.tsx
    - plugins/qingshui/src/client/toolviews/common.tsx
  - plugins/qingshui/src/client/toolviews/kline-card.tsx
  - plugins/qingshui/src/client/toolviews/evidence-list-card.tsx
  - plugins/qingshui/src/client/toolviews/evidence-timeline.tsx
- dsh/packages/client/ui-sidebar/src/client/SidebarRoot.tsx
- dsh/packages/client/ui-conversation/src/client/skeleton/InputBar.tsx
- dsh/packages/client/ui-settings-general/src/client/SettingsRoot.tsx
- dsh/packages/client/ui-settings-models/src/client/ModelsSection.tsx

## Settings modal (same URL)
Entry: gear button in SidebarRoot → SettingsRoot
- General: language, appearance
- Models: API key, base URL, add provider
