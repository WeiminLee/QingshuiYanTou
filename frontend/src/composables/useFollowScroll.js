/**
 * useFollowScroll — 自动滚动到底部 Composable
 *
 * 参考 persona auto-follow.ts
 *
 * 功能：
 * - 检测用户是否滚动到视口底部附近
 * - 用户滚动到底部 → auto-follow 开启
 * - 用户主动向上滚动 → auto-follow 暂停
 * - 内容更新且 auto-follow 开启 → 自动滚动到最新
 */
import { ref, onMounted, onUnmounted } from 'vue'

export function useFollowScroll(containerRef) {
  const isFollowing = ref(true)

  const NEAR_BOTTOM_THRESHOLD = 80

  function isNearBottom() {
    const el = containerRef.value
    if (!el) return true
    const { scrollTop, scrollHeight, clientHeight } = el
    return scrollHeight - scrollTop - clientHeight < NEAR_BOTTOM_THRESHOLD
  }

  function resolveFollowState() {
    isFollowing.value = isNearBottom()
  }

  function scrollToBottom(smooth = false) {
    const el = containerRef.value
    if (!el) return
    el.scrollTo({
      top: el.scrollHeight,
      behavior: smooth ? 'smooth' : 'auto',
    })
  }

  function handleWheel() {
    setTimeout(resolveFollowState, 300)
  }

  function handleScroll() {
    resolveFollowState()
  }

  function followIfNeeded() {
    if (isFollowing.value) {
      scrollToBottom(false)
    }
  }

  onMounted(() => {
    const el = containerRef.value
    if (!el) return
    el.addEventListener('wheel', handleWheel, { passive: true })
    el.addEventListener('scroll', handleScroll, { passive: true })
  })

  onUnmounted(() => {
    const el = containerRef.value
    if (!el) return
    el.removeEventListener('wheel', handleWheel)
    el.removeEventListener('scroll', handleScroll)
  })

  return {
    isFollowing,
    scrollToBottom,
    followIfNeeded,
  }
}
