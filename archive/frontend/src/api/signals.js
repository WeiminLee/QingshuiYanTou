/**
 * 预期差信号 API
 */
import apiClient from "./index.js";

export const listSignals = async (params = {}) => {
  const resp = await apiClient.get("/signals", { params });
  return {
    items: Array.isArray(resp?.items) ? resp.items : [],
    total: Number(resp?.total || 0),
  };
};

export const getSignalDetail = async (signalId) => {
  if (!signalId) return null;
  return apiClient.get(`/signals/${encodeURIComponent(signalId)}`);
};

export const updateSignalStatus = async (signalId, status) => {
  if (!signalId) return null;
  return apiClient.post(`/signals/${encodeURIComponent(signalId)}/status`, { status });
};
