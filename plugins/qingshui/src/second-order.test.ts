import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { describe, it } from 'node:test'
import { fileURLToPath } from 'node:url'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const persona = readFileSync(join(root, 'cordis.patch.yml'), 'utf8')
const expectedGap = readFileSync(join(root, 'skills/expected-gap/SKILL.md'), 'utf8')
const divergence = readFileSync(join(root, 'skills/divergence-mining/SKILL.md'), 'utf8')

const PHRASES = [
  '清单不封闭',
  '表面句',
  'a = d2 - d1',
  '二阶导不可计算',
  '点数不足只说明加速度算不出',
  '价、量、结构',
  '供给响应',
  '言数不符',
  '证伪',
  '变化的变化',
  '开放信息',
  '新闻表面',
]

describe('second-derivative analysis style', () => {
  it('puts the style in the main system prompt and keeps the two skill exceptions', () => {
    for (const phrase of [
      '只交付二阶导',
      ...PHRASES,
      '本库上一档披露',
      'session-review',
      'limit-up',
    ]) {
      assert.ok(persona.includes(phrase), `persona missing ${phrase}`)
    }
    assert.ok(persona.includes('不是「实际值 − 卖方一致预期」'))
    assert.ok(persona.includes('「没有新的一层」是合格结论'))
    assert.equal(persona.includes('五类都算'), false)
    const bodyStart = persona.indexOf('persona: |')
    assert.ok(bodyStart >= 0)
    const body = persona.slice(bodyStart)
    const bodyEnd = body.indexOf('\n- insert:')
    assert.ok(bodyEnd > 0)
    assert.equal(body.slice(0, bodyEnd).includes('{{'), false)
  })

  it('teaches expected-gap to lead with acceleration and park levels under 依据', () => {
    for (const phrase of PHRASES) {
      assert.ok(expectedGap.includes(phrase), `expected-gap missing ${phrase}`)
    }
    assert.ok(expectedGap.includes('依据'))
    assert.ok(expectedGap.includes('mcp__qingshui_data__pull_history'))
    assert.ok(expectedGap.includes('没有新的一层是合格结论'))
    assert.ok(expectedGap.includes('`acceleration`'))
    assert.ok(expectedGap.includes('不要心算'))
    assert.ok(expectedGap.includes('不铺水平表'))
    assert.ok(expectedGap.includes('实际值 − 卖方一致预期'))
    assert.equal(expectedGap.includes('五类都算'), false)
  })

  it('teaches divergence-mining the same lead and keeps evidence tables out of the conclusion', () => {
    for (const phrase of PHRASES) {
      assert.ok(divergence.includes(phrase), `divergence-mining missing ${phrase}`)
    }
    assert.ok(divergence.includes('## 二阶导'))
    assert.ok(divergence.includes('## 依据'))
    assert.ok(divergence.includes('没有新的一层是合格结论'))
    assert.ok(divergence.includes('`acceleration`'))
    assert.ok(divergence.includes('不要心算'))
    assert.ok(divergence.includes('不铺水平表'))
    assert.ok(divergence.includes('状态演进 / 边际变化'))
    assert.equal(divergence.includes('## 横向预期差：营业收入 × 硅片'), false)
    assert.equal(divergence.includes('五类都算'), false)
  })

  it('does not require session-review or limit-up to deliver a second derivative', () => {
    const sessionReview = readFileSync(join(root, 'skills/session-review/SKILL.md'), 'utf8')
    const limitUp = readFileSync(join(root, 'skills/limit-up/SKILL.md'), 'utf8')
    for (const text of [sessionReview, limitUp]) {
      assert.equal(text.includes('二阶导'), false)
      assert.equal(text.includes('acceleration'), false)
    }
  })
})
