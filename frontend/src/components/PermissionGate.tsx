import type { ReactNode } from 'react';
import { useAuthStore } from '@/stores/authStore';
import type { UserRole } from '@/api/types';

interface Props {
  role: UserRole;
  children: ReactNode;
  /** 无权限时的替代内容，默认不渲染 */
  fallback?: ReactNode;
}

/** 按角色控制渲染：如 <PermissionGate role="admin"> */
export default function PermissionGate({ role, children, fallback = null }: Props) {
  const user = useAuthStore((s) => s.user);
  if (user?.role !== role) return <>{fallback}</>;
  return <>{children}</>;
}
