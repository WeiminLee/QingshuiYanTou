/**
 * Sub-Project 1: 用户与持仓 API 封装
 * 所有请求带 withCredentials 让 cookie 自动收发
 */
import axios from "axios";

const http = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || "/api/v1",
  withCredentials: true,
  timeout: 15000,
});

export async function login(password) {
  const { data } = await http.post("/auth/login", { password });
  return data;
}

export async function logout() {
  const { data } = await http.post("/auth/logout");
  return data;
}

export async function switchUser(userId) {
  const { data } = await http.post("/auth/switch-user", { user_id: userId });
  return data;
}

export async function whoami() {
  const { data } = await http.get("/auth/whoami");
  return data;
}

export async function listUsers() {
  const { data } = await http.get("/users");
  return data;
}

export async function listPortfolio() {
  const { data } = await http.get("/account/portfolio");
  return data;
}

export async function addPortfolio(tsCode) {
  const { data } = await http.post("/account/portfolio", { ts_code: tsCode });
  return data;
}

export async function removePortfolio(tsCode) {
  const { data } = await http.delete(`/account/portfolio/${encodeURIComponent(tsCode)}`);
  return data;
}

export async function searchStocks(q, limit = 10) {
  const { data } = await http.get("/account/stocks/search", { params: { q, limit } });
  return data;
}

http.interceptors.response.use(
  (r) => r,
  (err) => {
    if (err.response && err.response.status === 401) {
      window.dispatchEvent(new CustomEvent("account:unauthorized"));
    }
    return Promise.reject(err);
  },
);

export default http;
