import assert from 'node:assert/strict'
import { test } from 'node:test'
import { pickOverseasMarkets } from './overseas-strip.ts'

const PAYLOAD = {
  as_of: '20261030',
  markets: [
    {
      market: 'US',
      name: '美股',
      trade_date: '20261029',
      pct_chg: 0.8,
      symbols: [
        { ts_code: 'NVDA', name: '英伟达', close: 213.66, pct_chg: 1.2 },
        { ts_code: 'AMD', name: '超威半导体', close: 150, pct_chg: -0.5 },
      ],
    },
    {
      market: 'TW',
      name: '台股',
      trade_date: '20261030',
      pct_chg: 0,
      symbols: [{ ts_code: '2330.TW', name: '台积电', close: 2370, pct_chg: 0 }],
    },
  ],
}

test('pickOverseasMarkets normalizes pct and direction', () => {
  const markets = pickOverseasMarkets(PAYLOAD)
  assert.equal(markets.length, 2)
  assert.equal(markets[0]?.name, '美股')
  assert.equal(markets[0]?.pct, '+0.80%')
  assert.equal(markets[0]?.direction, 'up')
  assert.equal(markets[0]?.symbols[0]?.pct, '+1.20%')
  assert.equal(markets[0]?.symbols[1]?.direction, 'down')
  assert.equal(markets[1]?.direction, 'flat')
})

test('pickOverseasMarkets tolerates missing payload', () => {
  assert.deepEqual(pickOverseasMarkets(null), [])
  assert.deepEqual(pickOverseasMarkets({}), [])
})
