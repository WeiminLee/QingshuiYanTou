import assert from 'node:assert/strict'
import { test } from 'node:test'
import { formatNewsTime, newsAnalysisPrompt, newsSourceLabel, shapeNewsFeed } from './news-tape.ts'

test('shapeNewsFeed keeps titled rows and labels 财联社', () => {
  const items = shapeNewsFeed({
    items: [
      { event_id: 'EV:abc', title: ' 存储芯片局部异动 ', source: 'tushare', publish_at: '2026-10-19 01:41:00+00:00' },
      { event_id: '', title: '丢掉' },
      { event_id: 'EV:def', title: '东财一条', source: 'eastmoney_flash', publish_at: '' },
    ],
  })
  assert.equal(items.length, 2)
  assert.equal(items[0]?.source, '财联社')
  assert.equal(items[0]?.title, '存储芯片局部异动')
  assert.equal(items[0]?.timeLabel, '10-19 09:41')
  assert.equal(items[1]?.source, '东财')
  assert.equal(items[1]?.timeLabel, '')
})

test('newsAnalysisPrompt names the event and refuses a headline conclusion', () => {
  const text = newsAnalysisPrompt({ eventId: 'EV:abc', title: '存储芯片局部异动', source: '财联社' })
  assert.match(text, /财联社快讯的预期差：存储芯片局部异动/)
  assert.match(text, /EV:abc/)
  assert.match(text, /get_event_detail/)
  assert.match(text, /不要把标题复述成结论/)
})

test('newsSourceLabel falls back to the raw source', () => {
  assert.equal(newsSourceLabel('cls'), '财联社')
  assert.equal(newsSourceLabel('wallstreetcn'), '华尔街见闻')
  assert.equal(newsSourceLabel('ths'), '同花顺')
  assert.equal(newsSourceLabel('sina'), '新浪')
  assert.equal(newsSourceLabel(''), '快讯')
  assert.equal(formatNewsTime('not-a-date'), 'not-a-date')
})
