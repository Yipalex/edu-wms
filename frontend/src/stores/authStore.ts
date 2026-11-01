import { create } from 'zustand';
import type { User, UserRole } from '@/api/types';

const LS_ACCESS = 'wms_access_token';
const LS_REFRESH = 'wms_refresh_token';
const LS_USER = 'wms_user';

function loadUser(): User | null {
  try {
    const raw = localStorage.getItem(LS_USER);
    return raw ? (JSON.parse(raw) as User) : null;
  } catch {
    return null;
  }
}

interface AuthState {
  accessToken: string | null;
  refreshToken: string | null;
  user: User | null;
  setAuth: (access: string, refresh: string, user: User) => void;
  setTokens: (access: string, refresh?: string) => void;
  setUser: (user: User) => void;
  clear: () => void;
}

/** 认证状态：token + 用户，持久化到 localStorage（刷新页面保持登录） */
export const useAuthStore = create<AuthState>((set) => ({
  accessToken: localStorage.getItem(LS_ACCESS),
  refreshToken: localStorage.getItem(LS_REFRESH),
  user: loadUser(),
  setAuth: (access, refresh, user) => {
    localStorage.setItem(LS_ACCESS, access);
    localStorage.setItem(LS_REFRESH, refresh);
    localStorage.setItem(LS_USER, JSON.stringify(user));
    set({ accessToken: access, refreshToken: refresh, user });
  },
  setTokens: (access, refresh) => {
    localStorage.setItem(LS_ACCESS, access);
    if (refresh) {
      localStorage.setItem(LS_REFRESH, refresh);
      set({ accessToken: access, refreshToken: refresh });
    } else {
      set({ accessToken: access });
    }
  },
  setUser: (user) => {
    localStorage.setItem(LS_USER, JSON.stringify(user));
    set({ user });
  },
  clear: () => {
    localStorage.removeItem(LS_ACCESS);
    localStorage.removeItem(LS_REFRESH);
    localStorage.removeItem(LS_USER);
    set({ accessToken: null, refreshToken: null, user: null });
  },
}));

export const ROLE_LABELS: Record<UserRole, string> = {
  admin: '管理员',
  operator: '仓库操作员',
};
