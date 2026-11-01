import { Tag } from 'antd';
import { DOC_STATE_LABELS } from '@/utils/format';

const COLORS: Record<string, string> = {
  draft: 'default',
  posted: 'green',
  voided: 'red',
  pending: 'orange',
  accepted: 'green',
  rejected: 'red',
  counting: 'blue',
  done: 'green',
};

/** 单据状态标签（中文） */
export default function DocStatusTag({ state }: { state: string }) {
  return <Tag color={COLORS[state] ?? 'default'}>{DOC_STATE_LABELS[state] ?? state}</Tag>;
}
