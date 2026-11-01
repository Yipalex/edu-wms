import { message } from 'antd';
import type { AxiosRequestConfig } from 'axios';
import { handleMock } from './handlers';

/** mock 统一入口：错误也按中文 detail 弹出（与真实拦截器行为一致） */
export async function mockRequest<T>(config: AxiosRequestConfig): Promise<T> {
  try {
    return await handleMock<T>(config);
  } catch (e) {
    const detail = e instanceof Error ? e.message : '请求失败';
    // 登录失败由页面自行展示，避免双弹
    if (!(config.url ?? '').startsWith('/auth/login')) {
      message.error(detail);
    }
    throw new Error(detail);
  }
}
