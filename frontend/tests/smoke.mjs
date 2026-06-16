/**
 * Frontend rendering smoke test — capture 404 details
 */
import { chromium } from 'playwright'

const BASE = 'http://localhost:3000'

async function run() {
  const browser = await chromium.launch({ args: ['--no-sandbox'] })
  const page = await browser.newPage()

  const errors = []
  const failed = []
  page.on('console', msg => { if (msg.type() === 'error') errors.push(msg.text()) })
  page.on('pageerror', err => errors.push(`PAGE ERROR: ${err.message}`))
  page.on('response', resp => {
    if (resp.status() === 404) failed.push(resp.url())
  })

  await page.goto(BASE, { waitUntil: 'networkidle', timeout: 20000 })

  // Check key elements
  const checks = [
    ['.layout', 'Layout'],
    ['.sidebar', 'Sidebar'],
    ['.welcome', 'Welcome section'],
  ]
  console.log('--- Elements ---')
  for (const [sel, label] of checks) {
    const el = await page.$(sel)
    console.log(`${el ? '✓' : '✗'} ${label}`)
  }

  // Screenshot
  await page.screenshot({ path: '/tmp/frontend-smoke.png', fullPage: true })

  console.log('\n--- Failed resources (404) ---')
  failed.forEach(u => console.log('  404:', u))

  console.log('\n--- Console errors ---')
  errors.forEach(e => console.log('  ', e))

  if (errors.length === 0 && failed.length === 0) {
    console.log('✓ All clean')
  }

  await browser.close()
  process.exit(errors.length > 0 ? 1 : 0)
}

run().catch(e => { console.error(e); process.exit(1) })