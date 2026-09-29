/**
 * streamAnimation.js — 可扩展流式动画插件系统
 *
 * 参考 persona/widget: stream-animation.ts
 *
 * 插件类型:
 *   loading  — 加载中动画（shimmer-color / pulse / shimmer / rainbow）
 *   stream   — 流式内容动画（word-fade / typewriter）
 *
 * 用法:
 *   import { registerStreamAnimation, getStreamAnimation, applyLoadingAnimation } from '@/utils/streamAnimation.js'
 */

// ─────────────────────────────────────────────────────────────────────────────
// 注册表
// ─────────────────────────────────────────────────────────────────────────────

/** @type {Map<string, object>} */
const _plugins = new Map();

// ─────────────────────────────────────────────────────────────────────────────
// 内置加载动画（thinking / tool 面板标题使用）
// ─────────────────────────────────────────────────────────────────────────────

registerStreamAnimation({
  name: "shimmer-color",
  type: "loading",
  containerClass: "persona-shimmer-color",
  apply(el) {
    el.classList.add("persona-shimmer-color");
    return () => el.classList.remove("persona-shimmer-color");
  },
});

registerStreamAnimation({
  name: "shimmer",
  type: "loading",
  containerClass: "persona-shimmer",
  apply(el) {
    el.classList.add("persona-shimmer");
    return () => el.classList.remove("persona-shimmer");
  },
});

registerStreamAnimation({
  name: "pulse",
  type: "loading",
  containerClass: "persona-pulse",
  apply(el) {
    el.classList.add("persona-pulse");
    return () => el.classList.remove("persona-pulse");
  },
});

registerStreamAnimation({
  name: "rainbow",
  type: "loading",
  containerClass: "persona-rainbow",
  apply(el) {
    el.classList.add("persona-rainbow");
    return () => el.classList.remove("persona-rainbow");
  },
});

// ─────────────────────────────────────────────────────────────────────────────
// 内置流式动画
// ─────────────────────────────────────────────────────────────────────────────

registerStreamAnimation({
  name: "word-fade",
  type: "stream",
  containerClass: "persona-stream-word-fade",
  wrap: "word",
  skipTags: new Set(["pre", "code", "a", "script", "style", "img", "table"]),
  useCaret: true,
  wrapContent(html, messageId, opts = {}) {
    return wrapStreamAnimation(html, "word", messageId, opts);
  },
});

registerStreamAnimation({
  name: "typewriter",
  type: "stream",
  containerClass: "persona-stream-typewriter",
  wrap: "char",
  skipTags: new Set(["pre", "code"]),
  useCaret: true,
  wrapContent(html, messageId, opts = {}) {
    return wrapStreamAnimation(html, "char", messageId, opts);
  },
});

// ─────────────────────────────────────────────────────────────────────────────
// 核心 API
// ─────────────────────────────────────────────────────────────────────────────

/**
 * 注册一个动画插件
 * @param {object} plugin
 * @param {string} plugin.name - 插件名（唯一标识）
 * @param {'loading'|'stream'} plugin.type
 * @param {string} [plugin.containerClass] - 容器 CSS class
 * @param {string} [plugin.wrap] - 包裹方式：'word' | 'char' | 'none'
 * @param {Set<string>} [plugin.skipTags] - 不包裹的标签名集合
 * @param {boolean} [plugin.useCaret]
 * @param {function} [plugin.apply] - loading 动画 apply(el) → cleanupFn
 * @param {function} [plugin.wrapContent] - stream 动画 wrapContent(html, id, opts)
 */
export function registerStreamAnimation(plugin) {
  if (!plugin.name) throw new Error("[streamAnimation] plugin.name is required");
  _plugins.set(plugin.name, plugin);
}

/**
 * 获取已注册的动画插件
 * @param {string} name
 * @returns {object|undefined}
 */
export function getStreamAnimation(name) {
  return _plugins.get(name);
}

/**
 * 获取所有已注册的插件（按 type 过滤）
 * @param {'loading'|'stream'|null} type
 */
export function getAllAnimations(type = null) {
  const all = [..._plugins.values()];
  if (!type) return all;
  return all.filter((p) => p.type === type);
}

/**
 * 应用加载动画到 DOM 元素
 * @param {Element} el
 * @param {string} name - 插件名
 * @param {object} [context]
 * @returns {function|null} cleanup 函数
 */
export function applyLoadingAnimation(el, name, context) {
  const plugin = _plugins.get(name);
  if (!plugin || plugin.type !== "loading") {
    console.warn(`[streamAnimation] Unknown loading animation: ${name}`);
    return null;
  }
  if (typeof plugin.apply !== "function") return null;
  return plugin.apply(el, context);
}

/**
 * 创建闪烁光标 caret 元素
 * @returns {HTMLElement}
 */
export function createStreamCaret() {
  const span = document.createElement("span");
  span.className = "persona-stream-caret";
  span.setAttribute("aria-hidden", "true");
  return span;
}

/**
 * 流式动画包裹：将 HTML 中的文本节点包裹为动画 span
 *
 * @param {string} html - 原始 HTML
 * @param {'word'|'char'} wrap - 包裹方式
 * @param {string} messageId - 消息 ID（用于生成唯一 class）
 * @param {object} [opts]
 * @param {Set<string>} [opts.skipTags] - 不包裹的标签名集合
 * @param {boolean} [opts.useCaret]
 * @returns {string} 包裹后的 HTML
 */
export function wrapStreamAnimation(html, wrap, messageId, opts = {}) {
  const skipTags = opts.skipTags || new Set(["pre", "code"]);
  const useCaret = opts.useCaret !== undefined ? opts.useCaret : true;

  if (wrap === "none" || !html) return html;
  if (wrap === "word") return _wrapByWord(html, messageId, skipTags);
  if (wrap === "char") return _wrapByChar(html, messageId, skipTags);
  return html;
}

// ─────────────────────────────────────────────────────────────────────────────
// 内部实现
// ─────────────────────────────────────────────────────────────────────────────

function _wrapByWord(html, messageId, skipTags) {
  const tmpl = document.createElement("template");
  tmpl.innerHTML = html;
  const frag = tmpl.content;

  function walk(node) {
    if (node.nodeType === Node.ELEMENT_NODE) {
      const tag = node.tagName.toLowerCase();
      if (skipTags.has(tag)) return;
      Array.from(node.childNodes).forEach(walk);
      return;
    }
    if (node.nodeType !== Node.TEXT_NODE) return;
    const text = node.textContent;
    if (!text.trim()) return;

    const wrapper = document.createElement("span");
    wrapper.className = "persona-word-stream";
    wrapper.setAttribute("data-msg", messageId);

    const words = text.split(/(\s+)/);
    const docFrag = document.createDocumentFragment();
    words.forEach((word) => {
      if (/^\s+$/.test(word)) {
        docFrag.appendChild(document.createTextNode(word));
      } else {
        const span = document.createElement("span");
        span.className = "word-span";
        span.textContent = word;
        docFrag.appendChild(span);
      }
    });

    node.parentNode.replaceChild(wrapper, node);
    wrapper.appendChild(docFrag);
  }

  Array.from(frag.childNodes).forEach(walk);
  // 返回序列化后的 HTML
  const div = document.createElement("div");
  div.appendChild(frag);
  return div.innerHTML;
}

function _wrapByChar(html, messageId, skipTags) {
  // 字符级包裹：先提取标签，再包裹纯文本
  const parts = [];
  let lastIdx = 0;
  const regex = /<(\/?)([\w-]+)[^>]*>/g;
  let match;

  while ((match = regex.exec(html)) !== null) {
    // 包裹前面的纯文本
    const before = html.slice(lastIdx, match.index);
    if (before) {
      parts.push(_charWrapText(before, messageId));
    }
    parts.push(match[0]);
    lastIdx = match.index + match[0].length;
  }

  // 剩余文本
  const rest = html.slice(lastIdx);
  if (rest) parts.push(_charWrapText(rest, messageId));

  return parts.join("");
}

function _charWrapText(text, messageId) {
  let result = "";
  let inTag = false;
  let currentTag = "";

  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (ch === "<") {
      inTag = true;
      currentTag = ch;
      continue;
    }
    if (ch === ">") {
      inTag = false;
      currentTag += ch;
      result += currentTag;
      currentTag = "";
      continue;
    }

    if (inTag) {
      currentTag += ch;
      continue;
    }

    result += `<span class="char-span" data-msg="${messageId}">${_escapeHtml(ch)}</span>`;
  }
  return result;
}

function _escapeHtml(str) {
  return str
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

// ─────────────────────────────────────────────────────────────────────────────
// 导出 CSS 动画
// ─────────────────────────────────────────────────────────────────────────────

export const ANIMATION_CSS = `
/* Loading animations */
.persona-shimmer-color {
  background: linear-gradient(90deg, #c0c0c0, #e0e0e0, #c0c0c0);
  background-size: 200% 100%;
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  animation: shimmer-color 1.4s ease-in-out infinite;
}
@keyframes shimmer-color {
  0%   { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}

.persona-shimmer {
  animation: shimmer 1.4s ease-in-out infinite;
  opacity: 0.6;
}
@keyframes shimmer {
  0%, 100% { opacity: 0.4; }
  50%       { opacity: 1; }
}

.persona-pulse {
  animation: pulse 1.2s ease-in-out infinite;
}
@keyframes pulse {
  0%, 100% { opacity: 0.4; transform: scale(0.98); }
  50%       { opacity: 1;   transform: scale(1); }
}

.persona-rainbow {
  animation: rainbow 2s linear infinite;
}
@keyframes rainbow {
  0%   { color: #ff6b6b; }
  25%  { color: #ffd93d; }
  50%  { color: #6bcb77; }
  75%  { color: #4d96ff; }
  100% { color: #ff6b6b; }
}

/* Stream animations */
.persona-word-stream .word-span {
  display: inline;
  opacity: 0;
  animation: word-appear 0.25s ease forwards;
}
@keyframes word-appear {
  to { opacity: 1; }
}

.char-span {
  /* 字符动画由 useStreamingRenderer 的 typewriter timer 控制 */
}

.persona-stream-caret {
  display: inline-block;
  width: 2px;
  height: 1em;
  background: currentColor;
  margin-left: 1px;
  vertical-align: text-bottom;
  animation: caret-blink 0.8s step-end infinite;
}
@keyframes caret-blink {
  0%, 100% { opacity: 1; }
  50%       { opacity: 0; }
}
`;
