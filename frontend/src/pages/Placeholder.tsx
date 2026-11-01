import { Empty, Card } from 'antd';
import PageContainer from '@/components/PageContainer';

interface Props {
  title: string;
  note?: string;
}

/** 占位页：第二轮实现 */
export default function Placeholder({ title, note }: Props) {
  return (
    <PageContainer title={title}>
      <Card>
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description={note ?? '该功能即将上线，敬请期待'}
        />
      </Card>
    </PageContainer>
  );
}
