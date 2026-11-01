import { useState } from 'react';
import { Card, DatePicker, Select, Space, Table, Tag, Typography } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { useQuery } from '@tanstack/react-query';
import dayjs, { Dayjs } from 'dayjs';
import * as barcodeApi from '@/api/barcode';
import type { BarcodeHistoryEntry } from '@/api/types';
import PageContainer from '@/components/PageContainer';
import { usePagination } from '@/hooks/usePagination';
import { CHANGE_TYPE_LABELS, fmtDateTime } from '@/utils/format';

const { RangePicker } = DatePicker;

const TYPE_COLORS: Record<string, string> = {
  assign: 'green',
  reassign: 'blue',
  merge_retire: 'orange',
  manual_fix: 'purple',
  import: 'cyan',
};

/** 条码变更历史（仅管理员）：类型/时间段筛选 + 分页 */
export default function BarcodeHistory() {
  const { page, pageSize, makeTablePagination, reset } = usePagination(20);
  const [changeType, setChangeType] = useState<string | undefined>();
  const [range, setRange] = useState<[Dayjs | null, Dayjs | null] | null>(null);

  const { data, isFetching } = useQuery({
    queryKey: ['barcode-history', page, pageSize, changeType, range?.[0]?.valueOf(), range?.[1]?.valueOf()],
    queryFn: () =>
      barcodeApi.listBarcodeHistory({
        page,
        page_size: pageSize,
        change_type: changeType,
        start_date: range?.[0] ? range[0].format('YYYY-MM-DD') : undefined,
        end_date: range?.[1] ? range[1].format('YYYY-MM-DD') : undefined,
      }),
  });

  const columns: ColumnsType<BarcodeHistoryEntry> = [
    {
      title: '时间',
      dataIndex: 'created_at',
      width: 140,
      render: (v: string) => fmtDateTime(v),
    },
    { title: '物品', dataIndex: 'item_name', ellipsis: true, width: 180 },
    {
      title: '旧码 → 新码',
      key: 'codes',
      width: 220,
      render: (_, r) => (
        <Typography.Text style={{ fontFamily: 'monospace' }}>
          {r.old_barcode ?? '（无）'} <Typography.Text type="secondary">→</Typography.Text>{' '}
          {r.new_barcode ?? <Tag color="red">停用</Tag>}
        </Typography.Text>
      ),
    },
    {
      title: '变更类型',
      dataIndex: 'change_type',
      width: 100,
      render: (v: string) => <Tag color={TYPE_COLORS[v]}>{CHANGE_TYPE_LABELS[v] ?? v}</Tag>,
    },
    { title: '原因', dataIndex: 'reason', ellipsis: true, render: (v: string) => v || '—' },
    { title: '操作人', dataIndex: 'operator_name', width: 100, render: (v: string) => v ?? '—' },
  ];

  return (
    <PageContainer title="条码变更历史" description="条码重分配 / 合并停用 / 人工修正的全部留痕，旧码不释放复用">
      <Card size="small" style={{ marginBottom: 12 }}>
        <Space wrap>
          <Select
            allowClear
            style={{ width: 150 }}
            placeholder="变更类型"
            value={changeType}
            onChange={(v) => {
              setChangeType(v);
              reset();
            }}
            options={Object.entries(CHANGE_TYPE_LABELS).map(([value, label]) => ({ value, label }))}
          />
          <RangePicker
            value={range as never}
            onChange={(v) => {
              setRange(v as [Dayjs | null, Dayjs | null] | null);
              reset();
            }}
            placeholder={['开始日期', '结束日期']}
            presets={[
              { label: '最近7天', value: [dayjs().subtract(7, 'day'), dayjs()] },
              { label: '最近30天', value: [dayjs().subtract(30, 'day'), dayjs()] },
            ]}
          />
        </Space>
      </Card>
      <Card size="small" styles={{ body: { padding: 0 } }}>
        <Table<BarcodeHistoryEntry>
          rowKey="id"
          columns={columns}
          dataSource={data?.list ?? []}
          loading={isFetching}
          size="middle"
          pagination={makeTablePagination(data?.meta.total ?? 0)}
          scroll={{ x: 860 }}
        />
      </Card>
    </PageContainer>
  );
}
