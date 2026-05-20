/**
 * API 客户端配置
 */
import axios from 'axios'

const apiClient = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '/api/v1',
  timeout: 30000,
  headers: { 'Content-Type': 'application/json' },
})

apiClient.interceptors.request.use((config) => {
  const apiKey = import.meta.env.VITE_API_KEY
  if (apiKey) {
    config.headers = config.headers || {}
    config.headers['x-api-key'] = apiKey
  }
  return config
})

// 响应拦截器：统一提取 data 字段
apiClient.interceptors.response.use(
  res => res.data,
  err => Promise.reject(err)
)

export default apiClient
