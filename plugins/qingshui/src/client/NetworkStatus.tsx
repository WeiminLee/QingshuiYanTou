/**
 * Data-plane connectivity badge: fixed top-right, shown only when the
 * Knowledge API is unreachable (SSH tunnel dropped / backend stopped).
 * Hardcoded zh to match its shell siblings (SignalBoard / NewsTape /
 * QuoteStrip); the toolviews are the i18n'd layer.
 *
 * Polls the same-origin /qingshui/health proxy every 30s; requires two
 * consecutive failures before surfacing so a single transient miss does not
 * flash the badge, and clears on the first success.
 */
import { useEffect, useRef, useState } from 'react'

const POLL_MS = 30_000
const FAIL_THRESHOLD = 2

export function NetworkStatus() {
  const [down, setDown] = useState<{ error: string } | null>(null)
  const failures = useRef(0)
  const [nonce, setNonce] = useState(0)

  useEffect(() => {
    if (typeof window === 'undefined') return
    let cancelled = false
    const probe = (): void => {
      void fetch('/qingshui/health', { headers: { accept: 'application/json' } })
        .then(async (res) => {
          const body = (await res.json().catch(() => ({}))) as { ok?: boolean; error?: string }
          if (res.ok && body.ok === true) return null
          return body.error ?? `HTTP ${res.status}`
        })
        .catch((err: unknown) => (err instanceof Error ? err.message : '网络不可达'))
        .then((error) => {
          if (cancelled) return
          if (error === null) {
            failures.current = 0
            setDown(null)
          } else {
            failures.current += 1
            if (failures.current >= FAIL_THRESHOLD) setDown({ error })
          }
        })
    }
    probe()
    const timer = setInterval(probe, POLL_MS)
    return () => {
      cancelled = true
      clearInterval(timer)
    }
  }, [nonce])

  if (down === null) return null

  return (
    <div className="qs-net" role="status" aria-live="polite">
      <span className="qs-net-icon" aria-hidden="true">⚠</span>
      <span className="qs-net-text">数据通道已断开</span>
      <span className="qs-net-error" title={down.error}>{down.error}</span>
      <button
        type="button"
        className="qs-net-retry"
        onClick={() => { failures.current = 0; setDown(null); setNonce(n => n + 1) }}
      >
        重试
      </button>
    </div>
  )
}
