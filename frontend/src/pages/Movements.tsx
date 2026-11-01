import { useState } from 'react';
import {
  Button,
  Card,
  DatePicker,
  Input,
  Select,
  Space,
  Table,
  Tag,
  Typography,
  message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { useQuery } from '@tanstack/react-query';
import dayjs, { type Dayjs } from 'dayjs';
import { DownloadOutlined } from '@ant-design/icons';
import * as categoriesApi from '@/api/categories';
import * as inventoryApi from '@/api/inventory';
import type { StockMovement } from '@/api/types';
import PageContainer from '@/components/PageContainer';
import { usePagination } from '@/hooks/usePagination';
import { DOC_TYPE_LABELS, fmtChangeQty, fmtDateTime, fmtQty } from '@/utils/format';

const { RangePicker } = DatePicker;

const TYPE_COLORS: Record<string, string> = {
  inbound: 'green',
  outbound: 'red',
  return: 'blue',
  transfer: 'purple',
  stocktake: 'orange',
  adjust: 'cyan',
};

/** 库存流水（只读）：全部出入库/盘点/调整流水，支持多维筛选与 CSV 导出 */
export default function Movements() {
  const { page, pageSize, makeTablePagination, reset } = usePagination(20);
  const [docType, setDocType] = useState<string | undefined>();
  const [locationId, setLocationId] = useState<number | undefined>();
  const [range, setRange] = useState<[Dayjs | null, Dayjs | null] | null>(null);
  const [q, setQ] = useState('');
  const [qInput, setQInput] = useState('');
  const [exporting, setExporting] = useState(false);

  const { data: locations } = useQuery({
    queryKey: ['locations'],
    queryFn: () => categoriesApi.listLocations(),
  });

  const { data, isFetching } = useQuery({
    queryKey: [
      'movements',
      page,
      pageSize,
      docType,
      locationId,
      q,
      range?.[0]?.valueOf(),
      range?.[1]?.valueOf(),
    ],
    queryFn: () =>
      inventoryApi.listMovements({
        page,
        page_size: pageSize,
        doc_type: docType,
        location_id: locationId,
        q: q || undefined,
        start: range?.[0] ? range[0].format('YYYY-MM-DD') : undefined,
        end: range?.[1] ? range[1].format('YYYY-MM-DD') : undefined,
      }),
  });

  const doExport = async () => {
    setExporting(true);
    try {
      await inventoryApi.exportMovementsCsv({
        doc_type: docType,
        location_id: locationId,
        q: q || undefined,
        start: range?.[0] ? range[0].format('YYYY-MM-DD') : undefined,
        end: range?.[1] ? range[1].format('YYYY-MM-DD') : undefined,
      });
    } catch {
      message.error('导出失败，请稍后重试');
    } finally {
      setExporting(false);
    }
  };

  const columns: ColumnsType<StockMovement> = [
    {
      title: '时间',
      dataIndex: 'created_at',
      width: 140,
      render: (v: string) => fmtDateTime(v),
    },
    {
      title: '类型',
      dataIndex: 'doc_type',
      width: 80,
      render: (v: string) => <Tag color={TYPE_COLORS[v] ?? 'default'}>{DOC_TYPE_LABELS[v] ?? v}</Tag>,
    },
    {
      title: '单号',
      dataIndex: 'doc_no',
      width: 160,
      render: (v: string | null) =>
        v ? <span style={{ fontFamily: 'monospace', fontSize: 12 }}>{v}</span> : '—',
    },
    {
      title: '物品',
      key: 'item',
      ellipsis: true,
      render: (_, r) => (
        <span>
          {r.item_name ?? '—'}
          {r.barcode && (
            <Typography.Text type="secondary" code style={{ fontSize: 11, marginInlineStart: 6 }}>
              {r.barcode}
            </Typography.Text>
          )}
        </span>
      ),
    },
    { title: '库位', dataIndex: 'location_name', width: 130, render: (v: string | null) => v ?? '—' },
    {
      title: '变动数量',
      dataIndex: 'change_qty',
      width: 100,
      align: 'right',
      render: (v: number) => (
        <Typography.Text strong style={{ color: v >= 0 ? '#B03A2A' : '#3E7C4F', fontSize: 14 }}>
          {fmtChangeQty(v)}
        </Typography.Text>
      ),
    },
    {
      title: '变动前 → 变动后',
      key: 'qty_change',
      width: 150,
      align: 'right',
      render: (_, r) => (
        <span>
          {fmtQty(r.qty_before)} <Typography.Text type="secondary">→</Typography.Text>{' '}
          {fmtQty(r.qty_after)}
        </span>
      ),
    },
    { title: '操作人', dataIndex: 'operator_name', width: 100, render: (v: string | null) => v ?? '—' },
    { title: '备注', dataIndex: 'note', ellipsis: true, render: (v: string) => v || '—' },
  ];

  return (
    <PageContainer
      title="库存流水"
      description="全部出入库/退库/调拨/盘点/调整流水留痕，正数为入库、负数为出库"
      extra={
        <Button icon={<DownloadOutlined />} loading={exporting} onClick={() => void doExport()}>
          导出 CSV
        </Button>
      }
    >
      <Card size="small" style={{ marginBottom: 12 }}>
        <Space wrap>
          <Select
            allowClear
            style={{ width: 130 }}
            placeholder="单据类型"
            value={docType}
            onChange={(v) => {
              setDocType(v);
              reset();
            }}
            options={Object.entries(DOC_TYPE_LABELS).map(([value, label]) => ({ value, label }))}
          />
          <Select
            allowClear
            showSearch
            optionFilterProp="label"
            style={{ width: 160 }}
            placeholder="库位"
            value={locationId}
            onChange={(v) => {
              setLocationId(v);
              reset();
            }}
            options={(locations ?? []).map((l) => ({ value: l.id, label: l.name }))}
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
          <Input.Search
            style={{ width: 220 }}
            placeholder="单号 / 物品 / 条码 / 备注"
            allowClear
            value={qInput}
            onChange={(e) => {
              setQInput(e.target.value);
              if (!e.target.value) {
                setQ('');
                reset();
              }
            }}
            onSearch={(v) => {
              setQ(v.trim());
              reset();
            }}
          />
        </Space>
      </Card>

      <Card size="small" styles={{ body: { padding: 0 } }}>
        <Table<StockMovement>
          rowKey="id"
          columns={columns}
          dataSource={data?.list ?? []}
          loading={isFetching}
          size="middle"
          pagination={makeTablePagination(data?.meta.total ?? 0)}
          scroll={{ x: 1060 }}
        />
      </Card>
    </PageContainer>
  );
}
