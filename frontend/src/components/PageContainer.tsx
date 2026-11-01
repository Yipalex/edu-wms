import type { ReactNode } from 'react';
import { Typography } from 'antd';

interface Props {
  title: ReactNode;
  extra?: ReactNode;
  children: ReactNode;
  /** 页面副标题/说明 */
  description?: string;
}

/** 页面容器：统一标题区 + 内容区（移动端自动收紧内边距） */
export default function PageContainer({ title, description, extra, children }: Props) {
  return (
    <div className="page-container">
      <div className="page-header">
        <div>
          <Typography.Title level={4} style={{ margin: 0 }}>
            {title}
          </Typography.Title>
          {description && (
            <Typography.Text type="secondary" style={{ fontSize: 13 }}>
              {description}
            </Typography.Text>
          )}
        </div>
        {extra && <div className="page-header-extra">{extra}</div>}
      </div>
      {children}
    </div>
  );
}
