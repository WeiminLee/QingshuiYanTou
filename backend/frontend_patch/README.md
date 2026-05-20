# 前端改造指南 - AskUserQuestion

## 文件清单

需要添加/修改的文件：

1. `frontend/src/components/ClarificationCard.vue` (新增)
2. `frontend/src/types/chat.ts` (修改 - 添加 ClarificationQuestion 类型)
3. `frontend/src/composables/useChatSession.ts` (修改 - 添加澄清状态处理)
4. `frontend/src/views/Home.vue` (修改 - 添加 ClarificationCard 组件)

## 步骤 1: 添加 ClarificationCard 组件

复制 `ClarificationCard.vue` 到 `frontend/src/components/`

## 步骤 2: 修改 types/chat.ts

在 ChatMessageItem 接口中添加：
```typescript
/** AskUserQuestion 澄清问题 */
clarificationQuestions?: ClarificationQuestion[]
```

添加新接口：
```typescript
export interface ClarificationQuestion {
  question: string
  header?: string
  options: ClarificationOption[]
  multiSelect?: boolean
}

export interface ClarificationOption {
  label: string
  description?: string
  preview?: string
}
```

## 步骤 3: 修改 useChatSession.ts

1. 导入类型：
```typescript
import type { ClarificationQuestion } from '@/types/chat'
```

2. 在 useChatSession 中添加状态：
```typescript
const clarificationPending = ref(false)
```

3. 在 addAssistantMessage 的返回对象中添加：
```typescript
clarificationQuestions: []
```

4. 在 addToolCall 函数中，识别 AskUserQuestion 工具：
```typescript
if (toolCall.name === 'AskUserQuestion' || toolCall.name === 'ask_clarification') {
  try {
    const args = toolCall.arguments ? JSON.parse(toolCall.arguments) : {}
    if (args.questions) {
      clarificationPending.value = true
      updateMessage(id, { clarificationQuestions: args.questions })
    }
  } catch {}
}
```

5. 添加 clearClarification 函数：
```typescript
function clearClarification(): void {
  clarificationPending.value = false
  const id = currentAssistantId.value
  if (id) {
    updateMessage(id, { clarificationQuestions: [] })
  }
}
```

6. 在 return 中导出 clearClarification

7. 在 reset 函数中重置 clarificationPending = false

## 步骤 4: 修改 Home.vue

1. 导入 ClarificationCard：
```typescript
import ClarificationCard from '@/components/ClarificationCard.vue'
```

2. 解构 clarificationPending 和 clearClarification：
```typescript
const { clarificationPending, clearClarification } = useChatSession()
```

3. 添加 computed 获取当前澄清：
```typescript
const currentClarification = computed(() => {
  const msg = messages.value.find(m => m.role === 'assistant' && m.clarificationQuestions?.length)
  return msg?.clarificationQuestions || null
})
```

4. 添加处理函数：
```typescript
function handleClarificationAnswer(answer: string) {
  clearClarification()
  handleSend(answer)
}
```

5. 在模板中找到 `<template #content="{ item }">` 部分，在 toolCalls 渲染后添加：
```vue
<!-- Clarification Card -->
<ClarificationCard
  v-if="currentClarification && item.id === currentClarificationId"
  :questions="currentClarification"
  @answer="handleClarificationAnswer"
/>
```

其中 currentClarificationId 需要定义为当前显示澄清的消息 ID。
