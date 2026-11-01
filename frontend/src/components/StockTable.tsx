import { Table, Tag } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import type { ScanResolveInventory } from '@/api/types';
import { fmtQty } from '@/utils/format';

interface Props {
  rows: ScanResolveInventory[];
  loading?: boolean;
  size?: 'small' | 'middle';
}

/** 各库位库存表：低于安全库存标红（移动端也保持窄表，不横向滚动） */
export default function StockTable({ rows, loading, size = 'small' }: Props) {
  const columns: ColumnsType<ScanResolveInventory> = [
    {
      title: '库位',
      dataIndex: 'location_name',
      key: 'location_name',
      ellipsis: true,
    },
    {
      title: '在手',
      dataIndex: 'qty_on_hand',
      key: 'qty_on_hand',
      align: 'right',
      render: (v: number, row) => {
        const low = row.safety_stock > 0 && v < row.safety_stock;
        return <span style={low ? { color: '#B03A2A', fontWeight: 600 } : undefined}>{fmtQty(v)}</span>;
      },
    },
    {
      title: '待领',
      dataIndex: 'qty_reserved',
      key: 'qty_reserved',
      align: 'right',
      render: (v: number) => fmtQty(v),
    },
    {
      title: '安全库存',
      dataIndex: 'safety_stock',
      key: 'safety_stock',
      align: 'right',
      render: (v: number) => (v > 0 ? fmtQty(v) : <Tag>未设置</Tag>),
    },
  ];

  return (
    <Table<ScanResolveInventory>
      rowKey={(r) => `${r.location_id}`}
      columns={columns}
      dataSource={rows}
      loading={loading}
      size={size}
      pagination={false}
    />
  );
}
