import assert from 'node:assert/strict'
import { test } from 'node:test'
import { pickBoardQuotes, pickShanghaiQuote } from './quote-strip.ts'

test('pickShanghaiQuote reads the Shanghai composite', () => {
  const quote = pickShanghaiQuote({
    trade_date: '20261016',
    indices: [
      { ts_code: '399001.SZ', name: '深证成份指数', close: 100, pct_chg: -0.12 },
      { ts_code: '000001.SH', name: '上证综合指数', close: 3716.2842, pct_chg: 0.2376 },
    ],
  })
  assert.deepEqual(quote, {
    tsCode: '000001.SH',
    name: '上证综合指数',
    close: '3716.28',
    pct: '+0.24%',
    up: true,
    tradeDate: '20261016',
  })
})

test('pickShanghaiQuote returns null without the Shanghai row', () => {
  assert.equal(pickShanghaiQuote({ indices: [] }), null)
  assert.equal(pickShanghaiQuote(null), null)
  assert.equal(pickShanghaiQuote({ indices: [{ ts_code: '000001.SH', name: '', close: 1, pct_chg: 0 }] }), null)
})

test('pickBoardQuotes keeps four boards and marks the ones the snapshot lacks', () => {
  const quotes = pickBoardQuotes({
    trade_date: '20261016',
    indices: [
      { ts_code: '000001.SH', name: '上证综合指数', close: 3716.2842, pct_chg: 0.2376 },
      { ts_code: '399006.SZ', name: '创业板指', close: 2772.3836, pct_chg: -0.3877 },
    ],
  })
  assert.deepEqual(quotes.map(quote => quote.label), ['上证', '创业板', '科创板', '北交所'])
  assert.equal(quotes[0]?.pct, '+0.24%')
  assert.equal(quotes[0]?.direction, 'up')
  assert.equal(quotes[1]?.pct, '-0.39%')
  assert.equal(quotes[1]?.direction, 'down')
  assert.equal(quotes[2]?.direction, 'absent')
  assert.equal(quotes[2]?.pct, null)
  assert.equal(quotes[3]?.tsCode, '899050.BJ')
})
