import { Button, Result } from 'antd';
import { useNavigate } from 'react-router-dom';
import { useAuthStore } from '@/stores/authStore';
import type { ReactNode } from 'react';
import type { UserRole } from '@/api/types';

/**
 * 角色路由：不满足角色直接访问时显示「无权限」页。
 *
 * role 可传单个或多个角色，任一命中即放行。
 * 注意：superadmin 视为所有角色的超集（超级管理员拥有管理员的全部能力）。
 */
export default function RoleRoute({
  role,
  children,
}: {
  role: UserRole | UserRole[];
  children: ReactNode;
}) {
  const user = useAuthStore((s) => s.user);
  const navigate = useNavigate();
  const allowed = Array.isArray(role) ? role : [role];
  const ok =
    !!user &&
    (allowed.includes(user.role) ||
      (user.role === 'superadmin' && allowed.includes('admin')));
  if (!ok) {
    return (
      <Result
        status="403"
        title="无权限"
        subTitle="该功能仅管理员可用，如需操作请联系管理员。"
        extra={
          <Button type="primary" onClick={() => navigate('/')}>
            返回首页
          </Button>
        }
      />
    );
  }
  return <>{children}</>;
}
