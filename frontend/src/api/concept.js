/**
 * 概念评分相关 API
 */
import apiClient from './index.js'

export const getConceptList = () =>
  apiClient.get('/concept/scores/concepts')

export const getConceptDetail = (conceptTsCode) =>
  apiClient.get(`/concept/scores/concepts/${conceptTsCode}`)

export const getStockScores = (limit = 100, offset = 0) =>
  apiClient.get('/concept/scores/stocks', { params: { limit, offset } })

export const getStockScore = (tsCode) =>
  apiClient.get(`/concept/scores/stocks/${tsCode}`)

export const triggerScoreCalculation = () =>
  apiClient.post('/concept/scores/calculate')
