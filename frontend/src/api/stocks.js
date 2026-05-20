/**
 * 股票相关 API
 */
import apiClient from './index.js'

export const searchStocks = (q, limit = 20) =>
  apiClient.get('/stocks/search', { params: { q, limit } })

export const getStockList = (limit = 100, offset = 0) =>
  apiClient.get('/stocks/list', { params: { limit, offset } })

export const getStock = (tsCode) =>
  apiClient.get(`/stocks/${tsCode}`)

export const getWatchlist = () =>
  apiClient.get('/stocks/watchlist')

export const addToWatchlist = (tsCode, note = '') =>
  apiClient.post('/stocks/watchlist', { ts_code: tsCode, note })

export const removeFromWatchlist = (tsCode) =>
  apiClient.delete(`/stocks/watchlist/${tsCode}`)

export const getDeerflowPackage = (tsCode) =>
  apiClient.get(`/stocks/package/${tsCode}/markdown`, { responseType: 'text' })

export const getDeerflowMaterial = (tsCode) =>
  apiClient.get(`/stocks/material/${tsCode}/markdown`, { responseType: 'text' })

/**
 * Fetch K-line (OHLCV) data for a given stock.
 * @param {string} ts_code
 * @param {number} limit
 * @returns {Promise<Array>} periods: [{date, open, high, low, close, vol, pct_chg}]
 */
/**
 * Fetch capital flow data for sankey visualization.
 * @param {string} period - 'D' | 'W' | 'M'
 * @param {number} limit
 * @returns {Promise<{nodes: [], links: [], period: string}>}
 */
export const getCapitalFlow = (period = 'D', limit = 20) => {
  return apiClient
    .get('/stocks/capital-flow', { params: { period, limit } })
    .catch(err => {
      console.error('[stocksAPI] getCapitalFlow failed', err)
      return { nodes: [], links: [], period }
    })
}

/**
 * Fetch K-line (OHLCV) data for a given stock.
 * @param {string} ts_code
 * @param {number} limit
 * @returns {Promise<Array>} periods: [{date, open, high, low, close, vol, pct_chg}]
 */
export const getKlineData = (ts_code, limit = 60) => {
  return apiClient
    .get('/stocks/kline', { params: { ts_code, limit } })
    .then(resp => resp.periods || [])
    .catch(err => {
      console.error('[stocksAPI] getKlineData failed', err)
      return []
    })
}
