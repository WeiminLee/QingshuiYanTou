# TDesign AI Chat 组件库使用文档

## 一、项目介绍
TDesign AI Chat 是腾讯 TDesign 团队推出的**企业级 AI 对话组件库**，基于 Vue 3 + TypeScript 构建，专为 AI 助手、智能客服、投研分析等场景设计。它原生支持流式输出、思考过程折叠、工具调用可视化等核心功能，完美匹配你的需求。

### 核心特性
- ✅ **思考过程折叠**：内置 `<Thinking>` 组件，支持流式渲染 + 默认折叠，可展开查看完整推理链
- ✅ **流式输出**：原生支持 SSE/WebSocket 流式渲染，内置打字机效果
- ✅ **工具调用隐藏**：自动解析 Tool Calls，仅在折叠面板中显示，不干扰主对话流
- ✅ **选项按钮渲染**：提供 `<ChatSuggestion>` 组件，将选项以按钮组形式呈现
- ✅ **企业级设计**：遵循 TDesign 设计规范，支持主题定制

---

## 二、快速开始
### 1. 安装依赖
```bash
npm install tdesign-ai-chat tdesign-vue-next
# 或
yarn add tdesign-ai-chat tdesign-vue-next
```

### 2. 引入样式与组件
在 `main.ts` 中全局引入：
```typescript
import { createApp } from 'vue'
import App from './App.vue'
import TDesign from 'tdesign-vue-next'
import 'tdesign-vue-next/es/style/index.css'
import TDesignAIChat from 'tdesign-ai-chat'
import 'tdesign-ai-chat/es/style/index.css'

const app = createApp(App)
app.use(TDesign)
app.use(TDesignAIChat)
app.mount('#app')
```

### 3. 基础使用示例
```vue
<template>
  <t-chat-container ref="chatContainerRef" :messages="messages">
    <template #message="{ message }">
      <t-chat-message :message="message">
        <!-- 思考过程 -->
        <template #thinking v-if="message.thinking">
          <t-thinking :content="message.thinkingContent" :collapsible="true" />
        </template>
        <!-- 选项按钮 -->
        <template #suggestion v-if="message.suggestions">
          <t-chat-suggestion :suggestions="message.suggestions" @select="handleSuggestionSelect" />
        </template>
      </t-chat-message>
    </template>
  </t-chat-container>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import type { ChatMessageItem } from 'tdesign-ai-chat'

const chatContainerRef = ref()
const messages = ref<ChatMessageItem[]>([])

// 模拟流式输出
const mockStreamOutput = async () => {
  const userMsg: ChatMessageItem = { role: 'user', content: '分析一下AI算力链条的投资机会' }
  const assistantMsg: ChatMessageItem = { 
    role: 'assistant', 
    content: '', 
    thinking: true, 
    thinkingContent: '',
    suggestions: []
  }
  messages.value.push(userMsg, assistantMsg)

  // 流式渲染思考过程
  const thinkingText = '正在分析市场数据...\n正在梳理产业链上下游...\n正在评估龙头公司估值...'
  for (let i = 0; i < thinkingText.length; i++) {
    await new Promise(resolve => setTimeout(resolve, 50))
    assistantMsg.thinkingContent = thinkingText.slice(0, i + 1)
  }

  // 流式渲染正文
  const contentText = 'AI算力链条核心分为上游（芯片、光模块）、中游（服务器、IDC）、下游（云厂商、大模型）。'
  for (let i = 0; i < contentText.length; i++) {
    await new Promise(resolve => setTimeout(resolve, 30))
    assistantMsg.content = contentText.slice(0, i + 1)
  }

  // 渲染选项按钮
  assistantMsg.suggestions = [
    { content: '查看上游芯片龙头', value: 'chip' },
    { content: '查看中游IDC公司', value: 'idc' },
    { content: '评估当前估值水平', value: 'valuation' }
  ]
}

const handleSuggestionSelect = (suggestion: { value: string }) => {
  console.log('选中选项:', suggestion.value)
}

onMounted(() => {
  mockStreamOutput()
})
</script>
```

---

## 三、核心组件详解

### 1. `t-chat-container` 对话容器
**用途**：管理对话列表、自动滚动、流式状态，是整个对话的根容器。

| Props | 说明 | 类型 | 默认值 |
|-------|------|------|--------|
| `messages` | 对话消息列表 | `ChatMessageItem[]` | `[]` |
| `auto-scroll` | 是否自动滚动到底部 | `boolean` | `true` |
| `scroll-behavior` | 滚动行为 | `'smooth' \| 'auto'` | `'smooth'` |

**插槽**：
- `#message`：自定义消息渲染
- `#input`：自定义输入框

---

### 2. `t-chat-message` 消息气泡
**用途**：区分用户/助手消息，渲染消息气泡、头像、时间等。

| Props | 说明 | 类型 | 默认值 |
|-------|------|------|--------|
| `message` | 单条消息数据 | `ChatMessageItem` | - |
| `avatar` | 自定义头像 | `string \| VNode` | - |
| `show-time` | 是否显示时间 | `boolean` | `false` |

**插槽**：
- `#thinking`：思考过程渲染
- `#suggestion`：选项按钮渲染
- `#tool-call`：工具调用渲染

---

### 3. `t-thinking` 思考过程组件
**用途**：实现可折叠的思考过程，支持流式渲染。

| Props | 说明 | 类型 | 默认值 |
|-------|------|------|--------|
| `content` | 思考内容（支持换行） | `string` | `''` |
| `collapsible` | 是否可折叠 | `boolean` | `true` |
| `default-collapsed` | 默认是否折叠 | `boolean` | `true` |
| `loading` | 是否显示加载动画 | `boolean` | `false` |

**示例**：
```vue
<t-thinking 
  :content="message.thinkingContent" 
  :collapsible="true" 
  :default-collapsed="true"
  :loading="message.thinkingLoading"
/>
```

---

### 4. `t-chat-suggestion` 选项按钮组件
**用途**：将选项以按钮组形式渲染在消息下方。

| Props | 说明 | 类型 | 默认值 |
|-------|------|------|--------|
| `suggestions` | 选项列表 | `Array<{ content: string, value: string }>` | `[]` |
| `mode` | 按钮模式 | `'outline' \| 'fill'` | `'outline'` |

**事件**：
- `@select`：选中选项时触发，参数为选中的选项对象

**示例**：
```vue
<t-chat-suggestion 
  :suggestions="[
    { content: '选项A', value: 'a' },
    { content: '选项B', value: 'b' }
  ]"
  mode="outline"
  @select="handleSelect"
/>
```

---

### 5. `t-tool-call` 工具调用组件
**用途**：隐藏函数名，仅展示工具执行状态与结果，支持折叠。

| Props | 说明 | 类型 | 默认值 |
|-------|------|------|--------|
| `tool-calls` | 工具调用列表 | `ToolCallItem[]` | `[]` |
| `collapsible` | 是否可折叠 | `boolean` | `true` |
| `show-function-name` | 是否显示函数名 | `boolean` | `false` |

**示例**（满足“不显示调用函数名称”需求）：
```vue
<t-tool-call 
  :tool-calls="message.toolCalls" 
  :show-function-name="false"
  :collapsible="true"
/>
```

---

## 四、流式输出实现方案
### 核心思路
结合 SSE (Server-Sent Events) 或 WebSocket，实时更新 `messages` 数组中对应消息的 `content` 或 `thinkingContent`，Vue 的响应式系统会自动触发视图更新。

SSE数据示例： https://tdesign.tencent.com/chat/sse
data: {"id":"7eced65bb3cb122d9f927563fc0e5673","created":1695218378,"choices":[{"delta":{"role":"assistant","content":"我是"}}],"usage":{"prompt_tokens":10,"completion_tokens":1,"total_tokens":11}}
data: {"id":"7eced65bb3cb122d9f927563fc0e5673","created":1695218378,"choices":[{"delta":{"role":"assistant","content":"由腾"}}],"usage":{"prompt_tokens":10,"completion_tokens":3,"total_tokens":13}}
data: {"id":"7eced65bb3cb122d9f927563fc0e5673","created":1695218378,"choices":[{"delta":{"role":"assistant","content":"讯公"}}],"usage":{"prompt_tokens":10,"completion_tokens":5,"total_tokens":15}}
data: {"id":"7eced65bb3cb122d9f927563fc0e5673","created":1695218378,"choices":[{"delta":{"role":"assistant","content":"司开"}}],"usage":{"prompt_tokens":10,"completion_tokens":7,"total_tokens":17}}
data: {"id":"7eced65bb3cb122d9f927563fc0e5673","created":1695218378,"choices":[{"delta":{"role":"assistant","content":"发的"}}],"usage":{"prompt_tokens":10,"completion_tokens":8,"total_tokens":18}}
data: {"id":"7eced65bb3cb122d9f927563fc0e5673","created":1695218378,"choices":[{"delta":{"role":"assistant","content":"大型"}}],"usage":{"prompt_tokens":10,"completion_tokens":9,"total_tokens":19}}
data: {"id":"7eced65bb3cb122d9f927563fc0e5673","created":1695218378,"choices":[{"delta":{"role":"assistant","content":"语言"}}],"usage":{"prompt_tokens":10,"completion_tokens":10,"total_tokens":20}}
data: {"id":"7eced65bb3cb122d9f927563fc0e5673","created":1695218378,"choices":[{"delta":{"role":"assistant","content":"模型"}}],"usage":{"prompt_tokens":10,"completion_tokens":11,"total_tokens":21}}


### 代码示例（SSE 版本）
```typescript
const streamOutputWithSSE = (query: string) => {
  const assistantMsg: ChatMessageItem = { 
    role: 'assistant', 
    content: '', 
    thinking: true, 
    thinkingContent: '',
    thinkingLoading: true
  }
  messages.value.push(assistantMsg)

  const eventSource = new EventSource(`/api/chat?query=${encodeURIComponent(query)}`)
  
  eventSource.onmessage = (event) => {
    const data = JSON.parse(event.data)
    if (data.type === 'thinking') {
      assistantMsg.thinkingContent += data.content
    } else if (data.type === 'content') {
      assistantMsg.thinkingLoading = false
      assistantMsg.content += data.content
    } else if (data.type === 'suggestions') {
      assistantMsg.suggestions = data.suggestions
      eventSource.close()
    }
  }

  eventSource.onerror = () => {
    eventSource.close()
  }
}
```

---

## 五、常见需求实现
### 1. 隐藏工具调用函数名
使用 `t-tool-call` 组件并设置 `:show-function-name="false"`：
```vue
<template #tool-call v-if="message.toolCalls">
  <t-tool-call :tool-calls="message.toolCalls" :show-function-name="false" />
</template>
```

### 2. 思考过程默认折叠
设置 `t-thinking` 的 `:default-collapsed="true"`：
```vue
<t-thinking :content="message.thinkingContent" :default-collapsed="true" />
```

### 3. 选项按钮放在折叠块下方
通过 `t-chat-message` 的 `#suggestion` 插槽实现，插槽会自动渲染在思考块/正文下方：
```vue
<t-chat-message :message="message">
  <template #thinking>...</template>
  <template #suggestion>
    <t-chat-suggestion :suggestions="message.suggestions" />
  </template>
</t-chat-message>
```

---

## 六、注意事项
1. **响应式更新**：确保 `messages` 数组及内部对象是 Vue 响应式的（使用 `ref` 或 `reactive`）
2. **自动滚动**：`t-chat-container` 默认开启自动滚动，若需手动控制可设置 `:auto-scroll="false"`
3. **主题定制**：可通过 TDesign 的 CSS 变量定制主题色，例如：
   ```css
   :root {
     --td-brand-color: #D4AF37; /* 品牌金色 */
   }
   ```

# TDesign AI Chat 组件库使用文档（续：高级功能篇）

> 本文档基于前序基础文档，新增 **图片嵌入**、**参考资料悬停引用**、**股票ID悬停卡片** 三大高级功能，所有功能均集成在 Markdown 渲染流程中。

---

## 七、高级功能实现
### 7.1 准备工作：安装依赖
首先安装 Markdown 核心库及扩展插件：
```bash
npm install markdown-it markdown-it-footnote markdown-it-regexp @vueuse/core
# 或
yarn add markdown-it markdown-it-footnote markdown-it-regexp @vueuse/core
```

### 7.2 图片嵌入功能
**需求**：支持 Markdown 原生图片语法 `![alt](url)`，点击图片可全屏预览。

#### 实现思路
1. 使用 `markdown-it` 渲染图片语法
2. 自定义图片渲染器，替换默认 `<img>` 标签为 TDesign 的 `<t-image>` 组件（支持预览）
3. 在 `t-chat-message` 中集成自定义 Markdown 渲染

#### 代码实现
```vue
<!-- CustomMarkdownRenderer.vue -->
<template>
  <div class="markdown-body">
    <div v-html="renderedContent"></div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import MarkdownIt from 'markdown-it'
import { Image as TImage } from 'tdesign-vue-next'
import { h, render } from 'vue'

const props = defineProps<{ content: string }>()

// 初始化 markdown-it
const md = new MarkdownIt({
  html: true,
  linkify: true,
  breaks: true
})

// 自定义图片渲染器
md.renderer.rules.image = (tokens, idx) => {
  const token = tokens[idx]
  const src = token.attrGet('src') || ''
  const alt = token.content || ''
  
  // 创建一个临时容器
  const container = document.createElement('div')
  
  // 渲染 TDesign Image 组件（支持预览）
  const vnode = h(TImage, {
    src,
    alt,
    fit: 'contain',
    style: 'max-width: 100%; max-height: 300px; margin: 8px 0; border-radius: 4px;'
  })
  
  render(vnode, container)
  return container.innerHTML
}

const renderedContent = computed(() => md.render(props.content))
</script>

<style scoped>
.markdown-body {
  line-height: 1.6;
}
.markdown-body :deep(img) {
  max-width: 100%;
  border-radius: 4px;
}
</style>
```

---

### 7.3 参考资料引用（悬停显示信息源）
**需求**：在 Markdown 中使用 `[^1]` 标记引用，鼠标悬停时显示参考资料详情（来源、标题、链接）。

#### 实现思路
1. 使用 `markdown-it-footnote` 插件解析 `[^1]` 语法
2. 自定义引用标记渲染器，将 `[^1]` 渲染为带悬停效果的标签
3. 使用 TDesign 的 `<t-popover>` 组件展示参考详情

#### 代码实现
```vue
<!-- CustomMarkdownRenderer.vue (更新版) -->
<template>
  <div class="markdown-body" ref="markdownRef">
    <div v-html="renderedContent"></div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch, nextTick } from 'vue'
import MarkdownIt from 'markdown-it'
import footnote from 'markdown-it-footnote'
import { Popover as TPopover } from 'tdesign-vue-next'
import { h, render } from 'vue'

const props = defineProps<{ 
  content: string, 
  references?: Record<string, { title: string, source: string, url: string }> 
}>()

const markdownRef = ref<HTMLElement>()

// 初始化 markdown-it 并注册 footnote 插件
const md = new MarkdownIt({
  html: true,
  linkify: true,
  breaks: true
}).use(footnote)

// 自定义引用标记渲染器（[^1]）
md.renderer.rules.footnote_ref = (tokens, idx) => {
  const token = tokens[idx]
  const id = token.meta.id
  const label = token.meta.label || id
  
  // 生成唯一 ID
  const refId = `ref-${id}`
  return `<span class="reference-tag" data-ref-id="${id}" id="${refId}">[${label}]</span>`
}

// 隐藏底部默认的 footnote 列表
md.renderer.rules.footnote_block_open = () => '<div style="display:none">'
md.renderer.rules.footnote_block_close = () => '</div>'

const renderedContent = computed(() => md.render(props.content))

// 渲染 Popover 悬停卡片
const renderReferencePopovers = async () => {
  await nextTick()
  if (!markdownRef.value || !props.references) return

  // 找到所有引用标记
  const refTags = markdownRef.value.querySelectorAll('.reference-tag')
  refTags.forEach(tag => {
    const refId = tag.getAttribute('data-ref-id')
    const refData = props.references?.[refId]
    if (!refData) return

    // 创建 Popover 内容
    const popoverContent = h('div', { style: 'padding: 4px 0;' }, [
      h('div', { style: 'font-weight: 600; margin-bottom: 4px;' }, refData.title),
      h('div', { style: 'color: #666; font-size: 12px; margin-bottom: 4px;' }, `来源：${refData.source}`),
      h('a', { 
        href: refData.url, 
        target: '_blank',
        style: 'color: #0052d9; font-size: 12px; text-decoration: none;'
      }, '查看原文')
    ])

    // 渲染 Popover
    const container = document.createElement('div')
    const vnode = h(TPopover, {
      trigger: 'hover',
      placement: 'top',
      showArrow: true,
      theme: 'light'
    }, {
      default: () => popoverContent,
      reference: () => tag.cloneNode(true)
    })

    render(vnode, container)
    tag.parentNode?.replaceChild(container.firstElementChild!, tag)
  })
}

watch(() => props.content, renderReferencePopovers, { immediate: true })
onMounted(renderReferencePopovers)
</script>

<style scoped>
.markdown-body {
  line-height: 1.6;
}
.reference-tag {
  color: #0052d9;
  cursor: pointer;
  font-size: 12px;
  background: #f0f2ff;
  padding: 2px 6px;
  border-radius: 4px;
  margin: 0 2px;
}
</style>
```

---

### 7.4 股票ID悬停卡片（K线+基本信息）
**需求**：自动识别 Markdown 中的股票ID（如 `600519.SH`、`000001.SZ`），鼠标悬停时显示 K线图和基本信息。

#### 实现思路
1. 使用 `markdown-it-regexp` 插件匹配股票ID正则
2. 自定义渲染器，将股票ID渲染为带悬停效果的标签
3. 使用 TDesign 的 `<t-popover>` 组件展示 K线和基本信息

#### 代码实现
```vue
<!-- CustomMarkdownRenderer.vue (最终完整版) -->
<template>
  <div class="markdown-body" ref="markdownRef">
    <div v-html="renderedContent"></div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch, nextTick } from 'vue'
import MarkdownIt from 'markdown-it'
import footnote from 'markdown-it-footnote'
import MarkdownItRegexp from 'markdown-it-regexp'
import { Popover as TPopover, Tag as TTag } from 'tdesign-vue-next'
import { h, render } from 'vue'

const props = defineProps<{ 
  content: string, 
  references?: Record<string, { title: string, source: string, url: string }>,
  stockInfo?: Record<string, { name: string, price: number, change: number, klineUrl: string }>
}>()

const markdownRef = ref<HTMLElement>()

// 1. 定义股票ID正则插件 (匹配 600519.SH, 000001.SZ 格式)
const stockPlugin = MarkdownItRegexp(
  /(\d{6}\.(SH|SZ))/,
  (match: RegExpExecArray) => {
    return { type: 'stock_id', content: match[1] }
  }
)

// 2. 初始化 markdown-it
const md = new MarkdownIt({
  html: true,
  linkify: true,
  breaks: true
})
.use(footnote)
.use(stockPlugin)

// 3. 自定义股票ID渲染器
md.renderer.rules.stock_id = (tokens, idx) => {
  const stockId = tokens[idx].content
  return `<span class="stock-tag" data-stock-id="${stockId}">${stockId}</span>`
}

// 4. 自定义引用标记渲染器（同7.3，此处省略重复代码）
md.renderer.rules.footnote_ref = (tokens, idx) => {
  const id = tokens[idx].meta.id
  return `<span class="reference-tag" data-ref-id="${id}">[${id}]</span>`
}
md.renderer.rules.footnote_block_open = () => '<div style="display:none">'
md.renderer.rules.footnote_block_close = () => '</div>'

const renderedContent = computed(() => md.render(props.content))

// 5. 统一渲染所有悬停组件
const renderInteractiveElements = async () => {
  await nextTick()
  if (!markdownRef.value) return

  // --- 渲染股票ID悬停卡片 ---
  const stockTags = markdownRef.value.querySelectorAll('.stock-tag')
  stockTags.forEach(tag => {
    const stockId = tag.getAttribute('data-stock-id')
    const stockData = props.stockInfo?.[stockId]
    if (!stockData) return

    // 构建 Popover 内容（含模拟 K线）
    const popoverContent = h('div', { style: 'width: 280px; padding: 8px 0;' }, [
      // 股票基本信息
      h('div', { style: 'display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; padding: 0 8px;' }, [
        h('div', [
          h('div', { style: 'font-weight: 600; font-size: 14px;' }, `${stockData.name} (${stockId})`),
          h('div', { style: 'font-size: 12px; color: #666; margin-top: 2px;' }, '上证指数 · 白酒')
        ]),
        h('div', { style: 'text-align: right;' }, [
          h('div', { style: `font-weight: 600; font-size: 16px; color: ${stockData.change >= 0 ? '#e34d59' : '#00a870'}` }, 
            `¥${stockData.price.toFixed(2)}`
          ),
          h('div', { style: `font-size: 12px; color: ${stockData.change >= 0 ? '#e34d59' : '#00a870'}` }, 
            `${stockData.change >= 0 ? '+' : ''}${stockData.change.toFixed(2)}%`
          )
        ])
      ]),
      // 模拟 K线图
      h('div', { style: 'height: 120px; background: #f7f8fa; border-radius: 4px; margin: 0 8px; display: flex; align-items: center; justify-content: center; color: #999; font-size: 12px;' },
        `K线图占位 (${stockData.klineUrl})`
      )
    ])

    // 渲染 Popover + Tag
    const container = document.createElement('div')
    const vnode = h(TPopover, {
      trigger: 'hover',
      placement: 'top',
      showArrow: true,
      theme: 'light',
      overlayStyle: 'padding: 0;'
    }, {
      default: () => popoverContent,
      reference: () => h(TTag, { 
        theme: 'default', 
        variant: 'light',
        style: 'cursor: pointer; margin: 0 2px;'
      }, { default: () => stockId })
    })

    render(vnode, container)
    tag.parentNode?.replaceChild(container.firstElementChild!, tag)
  })

  // --- 渲染参考资料悬停卡片 (同7.3，此处省略重复代码) ---
  const refTags = markdownRef.value.querySelectorAll('.reference-tag')
  // ... (复用7.3的逻辑)
}

watch(() => props.content, renderInteractiveElements, { immediate: true })
onMounted(renderInteractiveElements)
</script>

<style scoped>
.markdown-body {
  line-height: 1.6;
}
.reference-tag {
  color: #0052d9;
  cursor: pointer;
  font-size: 12px;
  background: #f0f2ff;
  padding: 2px 6px;
  border-radius: 4px;
  margin: 0 2px;
}
.stock-tag {
  color: #0052d9;
  cursor: pointer;
  text-decoration: underline;
  text-decoration-style: dotted;
}
</style>
```

---

### 7.5 完整整合示例：在对话中使用
将所有功能整合到 `t-chat-message` 中，实现完整的 AI 对话体验。

```vue
<template>
  <div class="chat-page">
    <t-chat-container ref="chatContainerRef" :messages="messages">
      <template #message="{ message }">
        <t-chat-message :message="message">
          <!-- 思考过程 (保留前序需求) -->
          <template #thinking v-if="message.thinking">
            <t-thinking 
              :content="message.thinkingContent" 
              :collapsible="true" 
              :default-collapsed="true"
            />
          </template>

          <!-- 自定义 Markdown 内容 (含图片/引用/股票) -->
          <template #content>
            <CustomMarkdownRenderer 
              :content="message.content"
              :references="message.references"
              :stock-info="message.stockInfo"
            />
          </template>

          <!-- 选项按钮 (保留前序需求) -->
          <template #suggestion v-if="message.suggestions">
            <t-chat-suggestion 
              :suggestions="message.suggestions" 
              @select="handleSuggestionSelect"
            />
          </template>
        </t-chat-message>
      </template>
    </t-chat-container>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import type { ChatMessageItem } from 'tdesign-ai-chat'
import CustomMarkdownRenderer from './CustomMarkdownRenderer.vue'

const chatContainerRef = ref()
const messages = ref<ChatMessageItem[]>([])

// 模拟完整对话数据
const mockFullConversation = async () => {
  const userMsg: ChatMessageItem = { 
    role: 'user', 
    content: '分析一下贵州茅台的投资价值' 
  }

  const assistantMsg: ChatMessageItem = { 
    role: 'assistant', 
    content: '', 
    thinking: true, 
    thinkingContent: '',
    suggestions: [],
    // 参考资料数据
    references: {
      '1': { title: '贵州茅台2025年年报', source: '上交所', url: 'https://example.com/600519-2025' },
      '2': { title: '白酒行业深度研报', source: '中信证券', url: 'https://example.com/baijiu-2025' }
    },
    // 股票信息数据
    stockInfo: {
      '600519.SH': { name: '贵州茅台', price: 1890.50, change: 2.35, klineUrl: 'https://example.com/kline/600519' }
    }
  }

  messages.value.push(userMsg, assistantMsg)

  // 1. 流式渲染思考过程
  const thinkingText = '正在查询公司年报...\n正在分析行业竞争格局...\n正在评估估值水平...'
  for (let i = 0; i < thinkingText.length; i++) {
    await new Promise(resolve => setTimeout(resolve, 50))
    assistantMsg.thinkingContent = thinkingText.slice(0, i + 1)
  }

  // 2. 流式渲染 Markdown 正文 (含图片、引用、股票ID)
  const contentMarkdown = `
## 贵州茅台 (600519.SH) 投资分析

### 核心观点
贵州茅台是白酒行业绝对龙头，品牌壁垒深厚，业绩确定性强。

### 财务数据
![茅台营收趋势](https://example.com/moutai-revenue.png)

根据公司2025年年报显示[^1]，公司营收同比增长15.2%，净利润增长18.5%。

### 估值建议
当前股价对应2025年PE为28倍，处于历史合理区间。建议关注 600519.SH 的回调机会。

### 风险提示
白酒行业政策风险[^2]、食品安全风险。
  `.trim()

  for (let i = 0; i < contentMarkdown.length; i++) {
    await new Promise(resolve => setTimeout(resolve, 20))
    assistantMsg.content = contentMarkdown.slice(0, i + 1)
  }

  // 3. 渲染选项按钮
  assistantMsg.suggestions = [
    { content: '查看详细估值模型', value: 'valuation' },
    { content: '对比五粮液', value: 'compare' },
    { content: '查看行业研报', value: 'report' }
  ]
}

const handleSuggestionSelect = (suggestion: { value: string }) => {
  console.log('选中选项:', suggestion.value)
}

onMounted(() => {
  mockFullConversation()
})
</script>

<style scoped>
.chat-page {
  height: 100vh;
  background: #f7f8fa;
}
</style>
```

---

## 八、功能验证清单
| 需求 | 验证点 | 实现方式 |
|------|--------|----------|
| 思考过程 | 可折叠、流式输出 | `<t-thinking>` 组件 |
| 工具调用 | 不显示函数名 | `<t-tool-call show-function-name="false">` |
| 选项按钮 | 在折叠块下方显示 | `<t-chat-suggestion>` 组件 |
| 图片嵌入 | Markdown语法、点击预览 | 自定义 `markdown-it` 渲染器 + `<t-image>` |
| 参考引用 | 悬停显示信息源 | `markdown-it-footnote` + `<t-popover>` |
| 股票ID | 悬停显示K线和信息 | `markdown-it-regexp` + `<t-popover>` + `<t-tag>` |
