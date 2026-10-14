import { strict as assert } from 'node:assert'
import { test } from 'node:test'
import { evCiteTransform, evIdFromTarget, evIdOf, isFullEvId } from './ev-cite.ts'

test('evIdOf accepts canonical and short ids', () => {
  assert.equal(evIdOf('EV:3fe7ff02'), 'EV:3fe7ff02')
  assert.equal(evIdOf(' EV:c2162ae848cc32706670f57a4af482e73b7518901ef522833b03248babb8c422 '), 'EV:c2162ae848cc32706670f57a4af482e73b7518901ef522833b03248babb8c422')
  assert.equal(evIdOf('EV:abc'), undefined)
  assert.equal(evIdOf('FD:c2162ae848cc32706670f57a4af482e73b7518901ef522833b03248babb'), undefined)
  assert.equal(evIdOf('https://example/EV:abcdef'), undefined)
})

test('isFullEvId matches 64-hex form only', () => {
  assert.equal(isFullEvId('EV:3fe7ff02'), false)
  assert.equal(isFullEvId('EV:c2162ae848cc32706670f57a4af482e73b7518901ef522833b03248babb8c422'), true)
  assert.equal(isFullEvId('EV:C2162AE848CC32706670F57A4AF482E73B7518901EF522833B03248BABB8C422'), true)
})

test('transform wraps plain citations, keeps prose bytes otherwise', () => {
  const src = '主矛盾是供给过剩（Yole 口径“短期去库存、长期高增长”，EV:3fe7ff02）'
  assert.equal(
    evCiteTransform(src),
    '主矛盾是供给过剩（Yole 口径“短期去库存、长期高增长”，`EV:3fe7ff02`）',
  )
})

test('transform handles several citations and table rows', () => {
  const src = [
    '| 601012.SH | 703.47 亿元 | ✓ 口径 | EV:c2162ae848cc32706670f57a4af482e73b7518901ef522833b03248babb8c422 |',
    '若口径不符 EV:9ec2d8bc7e3e0bf03227f5307a747c645d8733984196037b49d135daf1166209 与 EV:f29aab3249d94b0be9729811a51270b1f50d313d6426916e16a08d87d08cb9b。',
  ].join('\n')
  const out = evCiteTransform(src)
  assert.ok(out.includes('| `EV:c2162ae848cc32706670f57a4af482e73b7518901ef522833b03248babb8c422` |'))
  assert.ok(out.includes('`EV:9ec2d8bc7e3e0bf03227f5307a747c645d8733984196037b49d135daf1166209` 与 `EV:f29aab3249d94b0be9729811a51270b1f50d313d6426916e16a08d87d08cb9b`。'))
})

test('transform skips fenced code blocks', () => {
  const src = [
    '前面 EV:3fe7ff02 结束',
    '```',
    'EV:3fe7ff02 inside fence',
    '```',
    '后面 EV:abcdef01',
  ].join('\n')
  const out = evCiteTransform(src)
  assert.ok(out.includes('`EV:3fe7ff02` 结束'))
  assert.ok(out.includes('EV:3fe7ff02 inside fence'))
  assert.ok(out.includes('`EV:abcdef01`'))
})

test('transform skips existing inline code spans and is idempotent', () => {
  const src = '引用 `EV:3fe7ff02` 已在代码内；正文 EV:abcdef01'
  const once = evCiteTransform(src)
  assert.equal(once, '引用 `EV:3fe7ff02` 已在代码内；正文 `EV:abcdef01`')
  assert.equal(evCiteTransform(once), once)
})

test('transform leaves text without EV: untouched', () => {
  assert.equal(evCiteTransform('普通文本 FD:abcdef 与 JOB:1234'), '普通文本 FD:abcdef 与 JOB:1234')
})
