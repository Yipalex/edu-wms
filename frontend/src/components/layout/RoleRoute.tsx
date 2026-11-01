import { Button, Result } from 'antd';
import { useNavigate } from 'react-router-dom';
import { useAuthStore } from '@/stores/authStore';
import type { ReactNode } from 'react';
import type { UserRole } from '@/api/types';

/** 角色路由：不满足角色直接访问时显示「无权限」页 */
export default function RoleRoute({ role, children }: { role: UserRole; children: ReactNode }) {
  const user = useAuthStore((s) => s.user);
  const navigate = useNavigate();
  if (user?.role !== role) {
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
