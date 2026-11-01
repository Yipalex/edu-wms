import axios, { AxiosError, type AxiosRequestConfig, type InternalAxiosRequestConfig } from 'axios';
import { message } from 'antd';
import { useAuthStore } from '@/stores/authStore';
import { mockRequest } from '@/mocks';
import type { ApiErrorBody, ApiResponse } from './types';

/**
 * Mock 模式：VITE_USE_MOCK=true 或 URL 带 ?mock=1（记忆到 localStorage，方便刷新保持）
 * URL 带 ?mock=0 可关闭。
 */
function detectMock(): boolean {
  const params = new URLSearchParams(window.location.search);
  const q = params.get('mock');
  if (q === '1') {
    localStorage.setItem('wms_mock', '1');
    return true;
  }
  if (q === '0') {
    localStorage.removeItem('wms_mock');
    return false;
  }
  if (localStorage.getItem('wms_mock') === '1') return true;
  return import.meta.env.VITE_USE_MOCK === 'true';
}

export const isMockMode = detectMock();

export const http = axios.create({
  baseURL: '/api',
  timeout: 30000,
});

// ========== 请求拦截：注入 Bearer ==========
http.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const token = useAuthStore.getState().accessToken;
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// ========== 401 自动 refresh（只做一次） ==========
let refreshPromise: Promise<string | null> | null = null;

async function tryRefresh(): Promise<string | null> {
  const { refreshToken, setTokens, clear } = useAuthStore.getState();
  if (!refreshToken) return null;
  try {
    // 用裸 axios，避免拦截器递归
    const resp = await axios.post<ApiResponse<{ access_token: string; refresh_token?: string }>>(
      '/api/auth/refresh',
      { refresh_token: refreshToken },
    );
    const body = (resp.data?.data ?? resp.data) as {
      access_token: string;
      refresh_token?: string;
    };
    setTokens(body.access_token, body.refresh_token);
    return body.access_token;
  } catch {
    clear();
    return null;
  }
}

function redirectToLogin() {
  const { pathname, search } = window.location;
  if (pathname !== '/login') {
    window.location.href = `/login?redirect=${encodeURIComponent(pathname + search)}`;
  }
}

// ========== 响应拦截：解包 { data, meta }、统一中文报错 ==========
http.interceptors.response.use(
  (response) => {
    // blob（PDF/xlsx 下载）不解包
    if (response.config.responseType === 'blob') return response;
    const body = response.data as ApiResponse<unknown> | undefined;
    if (body && typeof body === 'object' && 'data' in body) {
      // 把 meta 挂到 data 上返回（数组或对象均可），方便分页组件使用
      const payload = body.data as Record<string, unknown> | unknown[] | null;
      if (body.meta && payload && typeof payload === 'object') {
        (payload as Record<string, unknown>).__meta = body.meta;
      }
      response.data = body.data;
    }
    return response;
  },
  async (error: AxiosError<ApiErrorBody>) => {
    const original = error.config as (AxiosRequestConfig & { _retried?: boolean }) | undefined;
    if (error.response?.status === 401 && original && !original._retried) {
      original._retried = true;
      if (!refreshPromise) {
        refreshPromise = tryRefresh().finally(() => {
          refreshPromise = null;
        });
      }
      const newToken = await refreshPromise;
      if (newToken) {
        original.headers = original.headers ?? {};
        (original.headers as Record<string, string>).Authorization = `Bearer ${newToken}`;
        return http.request(original);
      }
      useAuthStore.getState().clear();
      redirectToLogin();
    }
    const detail =
      error.response?.data?.detail ??
      (error.code === 'ECONNABORTED' ? '请求超时，请检查网络后重试' : '网络异常，请稍后重试');
    // 401 已跳登录不再重复弹
    if (error.response?.status !== 401) {
      message.error(detail);
    }
    return Promise.reject(new Error(detail));
  },
);

// ========== 统一请求出口（mock 拦截 + 解包后的 data） ==========
export async function request<T>(config: AxiosRequestConfig): Promise<T> {
  if (isMockMode) {
    return mockRequest<T>(config);
  }
  const resp = await http.request<T>(config);
  return resp.data;
}

/** 分页响应：data 为数组，meta 从 __meta 或拦截器挂载处取 */
export async function requestPaged<T>(
  config: AxiosRequestConfig,
): Promise<{ list: T[]; meta: { page: number; page_size: number; total: number } }> {
  if (isMockMode) {
    return mockRequest<{ list: T[]; meta: { page: number; page_size: number; total: number } }>(
      config,
    );
  }
  const resp = await http.request<T[]>(config);
  const raw = resp.data as unknown as { __meta?: { page: number; page_size: number; total: number } };
  const meta = raw?.__meta ?? { page: 1, page_size: 20, total: Array.isArray(resp.data) ? resp.data.length : 0 };
  return { list: (resp.data ?? []) as T[], meta };
}

/** 文件下载（PDF/xlsx），mock 模式下由 mocks 模块处理 */
export async function downloadBlob(config: AxiosRequestConfig, filename: string): Promise<void> {
  if (isMockMode) {
    await mockRequest<unknown>({ ...config, responseType: 'blob' });
    return;
  }
  const resp = await http.request({ ...config, responseType: 'blob' });
  const url = URL.createObjectURL(resp.data as Blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

/** 返回 blob 的 objectURL（用于新窗口预览 PDF），mock 模式返回 null */
export async function fetchBlobUrl(config: AxiosRequestConfig): Promise<string | null> {
  if (isMockMode) {
    return mockRequest<string | null>({ ...config, responseType: 'blob' });
  }
  const resp = await http.request({ ...config, responseType: 'blob' });
  return URL.createObjectURL(resp.data as Blob);
}
