/**
 * 资讯/公告/研报 API
 */
import apiClient from "./index.js";

/**
 * Fetch news/announcement list for the info timeline.
 * @param {Object} params - { source?: string }
 * @returns {Promise<Array>}
 */
export const getNewsList = async (params = {}) => {
  try {
    const resp = await apiClient.get("/information/cls-news", { params });
    return Array.isArray(resp) ? resp : resp.items || resp.data || [];
  } catch (e) {
    console.error("[informationAPI] getNewsList failed", e);
    return [];
  }
};

/**
 * Fetch full detail for a single news item.
 * @param {string} id
 * @returns {Promise<Object|null>}
 */
export const getNewsDetail = async (id) => {
  console.warn("[informationAPI] getNewsDetail is not supported by the backend", id);
  return null;
};
