<template>
  <div class="markdown-body" ref="markdownRef">
    <div v-html="sanitizedContent"></div>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, nextTick, h, render } from 'vue'
import MarkdownIt from 'markdown-it'
import footnote from 'markdown-it-footnote'
import { sanitize } from '@/utils/sanitize'
import { ElImage, ElPopover, ElTag } from 'element-plus'

const props = defineProps({
  content: {
    type: String,
    default: ''
  },
  references: {
    type: Object,
    default: () => {}
  },
  stockInfo: {
    type: Object,
    default: () => {}
  }
})

const markdownRef = ref(null)

// 自定义股票ID正则替换规则（不使用 markdown-it-regexp）
// 匹配 600519.SH, 000001.SZ 格式
const STOCK_ID_REGEX = /(\d{6}\.(SH|SZ))/g

// 自定义股票ID渲染规则
const stockIdRule = (md) => {
  md.core.ruler.push('stock_id_replace', (state) => {
    state.TokenStream = state.tokens
    for (let i = 0; i < state.tokens.length; i++) {
      const token = state.tokens[i]
      if (token.type === 'inline' && token.content) {
        // 检查是否包含股票ID
        if (STOCK_ID_REGEX.test(token.content)) {
          // 重置正则（因为 test 会更新 lastIndex）
          STOCK_ID_REGEX.lastIndex = 0
          // 创建新的 children tokens
          const newChildren = []
          let lastIndex = 0
          let match
          const content = token.content

          while ((match = STOCK_ID_REGEX.exec(content)) !== null) {
            // 添加匹配前的文本
            if (match.index > lastIndex) {
              const textToken = new state.Token('text', '', 0)
              textToken.content = content.slice(lastIndex, match.index)
              newChildren.push(textToken)
            }
            // 添加股票ID token
            const stockToken = new state.Token('stock_id', '', 0)
            stockToken.content = match[0]
            stockToken.meta = { stockId: match[0] }
            newChildren.push(stockToken)
            lastIndex = match.index + match[0].length
          }
          // 添加剩余文本
          if (lastIndex < content.length) {
            const textToken = new state.Token('text', '', 0)
            textToken.content = content.slice(lastIndex)
            newChildren.push(textToken)
          }
          token.children = newChildren
        }
      }
    }
    return true
  })

  // 渲染股票ID token
  md.renderer.rules.stock_id = (tokens, idx) => {
    const token = tokens[idx]
    const stockId = token.meta.stockId
    return `<span class="stock-tag" data-stock-id="${stockId}" title="股票代码: ${stockId}">${stockId}</span>`
  }
}

// 初始化 markdown-it
const md = new MarkdownIt({
  html: true,
  linkify: true,
  breaks: true
})
.use(footnote)
.use(stockIdRule)

// 自定义图片渲染器 - 使用 Element Plus Image 组件
md.renderer.rules.image = (tokens, idx) => {
  const token = tokens[idx]
  const src = token.attrGet('src') || ''
  const alt = token.content || ''

  // 生成 el-image 组件的 HTML placeholder
  return `<span class="markdown-image-wrapper" data-src="${src}" data-alt="${alt}"></span>`
}

// 自定义引用标记渲染器
md.renderer.rules.footnote_ref = (tokens, idx) => {
  const token = tokens[idx]
  const id = token.meta.id || token.meta.label || idx + 1
  return `<span class="reference-tag" data-ref-id="${id}" title="参考文献 ${id}">[${id}]</span>`
}

// 隐藏底部默认的 footnote 列表
md.renderer.rules.footnote_block_open = () => '<div style="display:none">'
md.renderer.rules.footnote_block_close = () => '</div>'

// 渲染 Markdown 内容
const renderedContent = computed(() => {
  if (!props.content) return ''
  return md.render(props.content)
})

// XSS 防护
const sanitizedContent = computed(() => {
  return sanitize(renderedContent.value)
})

// 渲染交互元素（添加 title 属性用于悬停提示）
const renderInteractiveElements = async () => {
  await nextTick()
  if (!markdownRef.value) return

  // 渲染图片预览组件
  const imageWrappers = markdownRef.value.querySelectorAll('.markdown-image-wrapper')
  imageWrappers.forEach(wrapper => {
    const src = wrapper.getAttribute('data-src')
    const alt = wrapper.getAttribute('data-alt')

    // 创建 el-image VNode
    const vnode = h(ElImage, {
      src: src,
      alt: alt,
      previewSrcList: [src],
      initialIndex: 0,
      fit: 'contain',
      style: 'max-width: 100%; max-height: 300px; margin: 8px 0; border-radius: 4px; cursor: pointer;'
    })

    const container = document.createElement('div')
    render(vnode, container)
    wrapper.parentNode?.replaceChild(container.firstElementChild || container, wrapper)
  })

  // 渲染股票 Popover
  const stockTags = markdownRef.value.querySelectorAll('.stock-tag')
  stockTags.forEach(tag => {
    const stockId = tag.getAttribute('data-stock-id')
    const stockData = props.stockInfo?.[stockId]

    // 构建 Popover 内容
    const popoverContent = h('div', { class: 'stock-popover-content' }, [
      h('div', { class: 'stock-header' }, [
        h('span', { class: 'stock-name' }, stockData?.name || stockId),
        h('span', { class: 'stock-id' }, `(${stockId})`)
      ]),
      h('div', { class: 'stock-price' }, [
        h('span', { class: 'price-value', style: { color: stockData?.change >= 0 ? '#e34d59' : '#00a870' } },
          `¥${(stockData?.price || 0).toFixed(2)}`),
        h('span', { class: 'price-change', style: { color: stockData?.change >= 0 ? '#e34d59' : '#00a870' } },
          `${stockData?.change >= 0 ? '+' : ''}${(stockData?.change || 0).toFixed(2)}%`)
      ])
    ])

    // 渲染 Popover + Tag
    const vnode = h(ElPopover, {
      placement: 'top',
      trigger: 'hover',
      width: 200
    }, {
      reference: () => h(ElTag, { type: 'warning', effect: 'plain' }, { default: () => stockId }),
      default: () => popoverContent
    })

    const container = document.createElement('div')
    render(vnode, container)
    tag.parentNode?.replaceChild(container.firstElementChild || container, tag)
  })

  // 渲染引用 Popover
  const refTags = markdownRef.value.querySelectorAll('.reference-tag')
  refTags.forEach(tag => {
    const refId = tag.getAttribute('data-ref-id')
    const refData = props.references?.[refId]

    // 构建 Popover 内容
    const popoverContent = h('div', { class: 'ref-popover-content' }, [
      h('div', { class: 'ref-title' }, refData?.title || `参考文献 ${refId}`),
      h('div', { class: 'ref-source' }, `来源: ${refData?.source || '未知'}`),
      refData?.url ? h('a', { href: refData.url, target: '_blank', class: 'ref-link' }, '查看原文') : null
    ])

    // 渲染 Popover
    const vnode = h(ElPopover, {
      placement: 'top',
      trigger: 'hover',
      width: 180
    }, {
      reference: () => h('span', { class: 'ref-tag-text' }, `[${refId}]`),
      default: () => popoverContent
    })

    const container = document.createElement('div')
    render(vnode, container)
    tag.parentNode?.replaceChild(container.firstElementChild || container, tag)
  })
}

// 监听内容变化
watch(() => props.content, renderInteractiveElements, { immediate: true })
watch(() => props.references, renderInteractiveElements, { deep: true })
watch(() => props.stockInfo, renderInteractiveElements, { deep: true })
onMounted(renderInteractiveElements)
</script>

<style scoped>
.markdown-body {
  line-height: 1.6;
  font-size: 14px;
}

.markdown-body :deep(h1),
.markdown-body :deep(h2) {
  margin-top: 16px;
  margin-bottom: 8px;
  font-weight: 600;
  border-bottom: 1px solid var(--ledger-rule);
  padding-bottom: 6px;
}
.markdown-body :deep(h1) {
  border-bottom-width: 2px;
}
.markdown-body :deep(h3) {
  margin-top: 16px;
  margin-bottom: 8px;
  font-weight: 600;
}

.markdown-body :deep(p) {
  margin-bottom: 12px;
}

.markdown-body :deep(code) {
  background: var(--ledger-entry);
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 13px;
  color: var(--ledger-gold);
  border: 1px solid var(--ledger-rule);
}

.markdown-body :deep(pre) {
  background: var(--ledger-spine);
  padding: 12px;
  border-radius: 4px;
  overflow-x: auto;
  border: 1px solid rgba(184,134,11,0.2);
}

.markdown-body :deep(pre code) {
  background: transparent;
  padding: 0;
  color: #D8C89A;
}

.markdown-body :deep(a) {
  color: var(--ledger-blue);
  text-decoration: none;
}

.markdown-body :deep(a:hover) {
  text-decoration: underline;
}

.markdown-body :deep(blockquote) {
  border-left: 3px solid var(--ledger-gold);
  padding: 8px 14px;
  background: var(--ledger-entry);
  border-radius: 0 4px 4px 0;
  margin: 14px 0;
  color: var(--text-main-2);
}

.markdown-body :deep(ul),
.markdown-body :deep(ol) {
  margin-left: 20px;
  margin-bottom: 12px;
}

.markdown-body :deep(li) {
  margin-bottom: 4px;
}

.markdown-body :deep(table) {
  width: 100%;
  border-collapse: collapse;
  margin-bottom: 12px;
}

.markdown-body :deep(th),
.markdown-body :deep(td) {
  border: 1px solid var(--ledger-rule);
  padding: 8px;
  text-align: left;
}

.markdown-body :deep(th) {
  background: var(--ledger-entry);
  font-weight: 600;
  border-bottom: 2px solid var(--ledger-rule);
}

/* 引用标记样式 */
.reference-tag {
  color: var(--ledger-blue);
  cursor: pointer;
  font-size: 12px;
  background: rgba(59,91,219,0.08);
  padding: 2px 6px;
  border-radius: 4px;
  margin: 0 2px;
  border: 1px solid rgba(59,91,219,0.3);
  transition: background 0.2s;
}

.reference-tag:hover {
  background: rgba(59,91,219,0.15);
}

/* 股票ID标记样式 */
.stock-tag {
  color: var(--ledger-blue);
  cursor: pointer;
  font-size: 12px;
  background: rgba(59,91,219,0.08);
  padding: 2px 6px;
  border-radius: 4px;
  margin: 0 2px;
  border: 1px solid var(--ledger-blue);
  transition: background 0.2s;
}

.stock-tag:hover {
  background: rgba(59,91,219,0.15);
}

/* 图片样式 */
.markdown-image {
  max-width: 100%;
  max-height: 300px;
  margin: 8px 0;
  border-radius: 4px;
  cursor: pointer;
  transition: transform 0.2s;
}

.markdown-image:hover {
  transform: scale(1.02);
}

/* Popover 内容样式 */
.stock-popover-content {
  padding: 8px;
}
.stock-header {
  display: flex;
  justify-content: space-between;
  margin-bottom: 8px;
}
.stock-name {
  font-weight: 600;
}
.stock-id {
  color: var(--ledger-gray);
  font-size: 12px;
}
.stock-price {
  display: flex;
  gap: 8px;
}
.price-value {
  font-weight: 600;
}
.price-change {
  font-size: 12px;
}

.ref-popover-content {
  padding: 8px;
}
.ref-title {
  font-weight: 600;
  margin-bottom: 4px;
}
.ref-source {
  color: var(--ledger-gray);
  font-size: 12px;
  margin-bottom: 4px;
}
.ref-link {
  color: var(--ledger-blue);
  font-size: 12px;
}

/* 引用标记文本样式 */
.ref-tag-text {
  color: var(--ledger-blue);
  cursor: pointer;
  font-size: 12px;
  background: rgba(59,91,219,0.08);
  padding: 2px 6px;
  border-radius: 4px;
  margin: 0 2px;
  border: 1px solid rgba(59,91,219,0.3);
  transition: background 0.2s;
}

.ref-tag-text:hover {
  background: rgba(59,91,219,0.15);
}
</style>