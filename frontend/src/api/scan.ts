import { request } from './client';
import type { ScanResolveResult } from './types';

/** 扫码解析统一入口（契约第 4 节） */
export function scanResolve(code: string) {
  return request<ScanResolveResult>({
    method: 'GET',
    url: '/scan/resolve',
    params: { code },
  });
}
