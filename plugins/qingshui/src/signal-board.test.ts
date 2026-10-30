import assert from 'node:assert/strict'
import { test } from 'node:test'
import { SIGNAL_LANES, loadSignalBoard, mergeSignals, shapeSignalItems, signalAnalysisPrompt } from './signal-board.ts'

const announcement = SIGNAL_LANES.find(lane => lane.id === 'announcement')!

test('shapeSignalItems reads a processed announcement and drops blanks', () => {
  const items = shapeSignalItems({
    items: [
      { signal_id: 'LLM:1', summary: '营收上台阶', subject_name: '德明利', polarity: 'positive', value_score: 80 },
      { signal_id: '', summary: '丢掉' },
      { signal_id: 'LLM:2', title: '只有标题', polarity: 'risk', value_score: 10 },
    ],
  }, announcement, '')
  assert.equal(items.length, 2)
  assert.equal(items[0]?.mark, '正')
  assert.equal(items[0]?.direction, 'up')
  assert.equal(items[1]?.summary, '只有标题')
  assert.equal(items[1]?.mark, '负')
})

test('mergeSignals ranks by value and keeps one copy', () => {
  const lane = announcement
  const low = shapeSignalItems({ items: [{ signal_id: 'LLM:a', summary: '低', polarity: 'positive', value_score: 1 }] }, lane, '')
  const high = shapeSignalItems({ items: [{ signal_id: 'LLM:a', summary: '高', polarity: 'positive', value_score: 9 }, { signal_id: 'LLM:b', summary: '中', polarity: 'risk', value_score: 4 }] }, lane, '')
  const merged = mergeSignals([...low, ...high], 2)
  assert.deepEqual(merged.map(item => item.summary), ['高', '中'])
})

test('signalAnalysisPrompt names the lane and refuses a summary conclusion', () => {
  const text = signalAnalysisPrompt({
    label: '公告',
    tag: '',
    summary: '营收上台阶',
    subject: '德明利',
    signalId: 'LLM:1',
  })
  assert.match(text, /公告信号的预期差：营收上台阶/)
  assert.match(text, /主体 德明利/)
  assert.match(text, /LLM:1/)
  assert.match(text, /不要把摘要复述成结论/)
  const mapped = signalAnalysisPrompt({ label: '美股 / 台股', tag: '美股', summary: '隔夜映射', subject: '', signalId: 'US:1' })
  assert.match(mapped, /美股映射信号/)
})

test('event lane reads irm together with event rows', () => {
  const sources = SIGNAL_LANES.find(lane => lane.id === 'event')!.sources.map(source => source.sourceType)
  assert.ok(sources.includes('event'))
  assert.ok(sources.includes('irm'))
  assert.ok(sources.includes('irm:llm'))
})

test('loadSignalBoard fills four lanes and marks a failed lane absent', async () => {
  const eventTypes = new Set(
    SIGNAL_LANES.find(lane => lane.id === 'event')!.sources.map(source => source.sourceType),
  )
  const board = await loadSignalBoard(async (sourceType) => {
    if (eventTypes.has(sourceType)) throw new Error('down')
    if (sourceType === 'announcement:llm') {
      return { items: [{ signal_id: 'LLM:1', summary: '营收上台阶', polarity: 'positive', value_score: 3 }] }
    }
    return { items: [] }
  })
  assert.deepEqual(board.map(lane => lane.id), ['news', 'announcement', 'event', 'mapping'])
  assert.equal(board[1]?.items[0]?.summary, '营收上台阶')
  assert.equal(board[2]?.absent, true)
  assert.equal(board[0]?.absent, false)
  assert.equal(board[0]?.items.length, 0)
  assert.equal(board[3]?.items.length, 0)
})

test('laneScrollRows duplicates overflowing lanes and respects reduced motion', async () => {
  const { laneScrollRows } = await import('./signal-board.ts')
  assert.deepEqual(laneScrollRows([1, 2, 3], 2, false), { rows: [1, 2, 3, 1, 2, 3], roll: true })
  assert.deepEqual(laneScrollRows([1, 2, 3], 2, true), { rows: [1, 2], roll: false })
  assert.deepEqual(laneScrollRows([1], 2, false), { rows: [1], roll: false })
  assert.deepEqual(laneScrollRows([1, 2, 3], undefined, false), { rows: [1, 2, 3], roll: false })
})
