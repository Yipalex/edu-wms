import { useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import * as authApi from '@/api/auth';
import { useAuthStore, ROLE_LABELS } from '@/stores/authStore';

export function useAuth() {
  const navigate = useNavigate();
  const { user, accessToken, setAuth, clear } = useAuthStore();

  const login = useCallback(
    async (username: string, password: string) => {
      const res = await authApi.login(username, password);
      setAuth(res.access_token, res.refresh_token, res.user);
      return res.user;
    },
    [setAuth],
  );

  const logout = useCallback(async () => {
    try {
      await authApi.logout();
    } catch {
      // 忽略登出接口失败，本地一定清
    }
    clear();
    navigate('/login', { replace: true });
  }, [clear, navigate]);

  return {
    user,
    isAuthenticated: !!accessToken,
    // 超级管理员拥有管理员的全部能力
    isAdmin: user?.role === 'admin' || user?.role === 'superadmin',
    isSuperAdmin: user?.role === 'superadmin',
    roleLabel: user ? ROLE_LABELS[user.role] : '',
    login,
    logout,
  };
}
