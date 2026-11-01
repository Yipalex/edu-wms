import { Empty } from 'antd';
import type { ReactNode } from 'react';

interface Props {
  description?: string;
  children?: ReactNode;
}

/** 空态：带引导文案 */
export default function EmptyHint({ description = '暂无数据', children }: Props) {
  return (
    <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={description}>
      {children}
    </Empty>
  );
}
