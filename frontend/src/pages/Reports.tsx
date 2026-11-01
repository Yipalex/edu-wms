import { useState } from 'react';
import {
  Button,
  Card,
  Checkbox,
  DatePicker,
  Input,
  Radio,
  Select,
  Space,
  Table,
  Tabs,
  Typography,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { useQuery } from '@tanstack/react-query';
import dayjs, { type Dayjs } from 'dayjs';
import * as reportsApi from '@/api/reports';
import type {
  InventorySummaryGroup,
  MovementsReportRow,
  StockReportItemRow,
} from '@/api/types';
import { listCategories, listLocations } from '@/api/categories';
import { exportInventoryCsv, exportMovementsCsv } from '@/api/inventory';
import PageContainer from '@/components/PageContainer';
import { usePagination } from '@/hooks/usePagination';
import { DOC_TYPE_LABELS, fmtMoney, fmtQty } from '@/utils/format';

const { RangePicker } = DatePicker;

type StockGroupBy = 'item' | 'location' | 'category';
type MovementsGroupBy = 'doc_type' | 'date' | 'item' | 'location';

/** 入库/净增红色，出库/净减绿色 */
function qtyColor(v: number): string | undefined {
  if (v > 0) return '#B03A2A';
  if (v < 0) return '#3E7C4F';
  return undefined;
}

// ========== 库存报表 ==========

function StockReport() {
  const { page, pageSize, makeTablePagination, reset } = usePagination(20);
  const [groupBy, setGroupBy] = useState<StockGroupBy>('item');
  const [locationId, setLocationId] = useState<number | undefined>();
  const [categoryId, setCategoryId] = useState<number | undefined>();
  const [belowSafety, setBelowSafety] = useState(false);
  const [keyword, setKeyword] = useState('');

  const { data: locations } = useQuery({ queryKey: ['locations'], queryFn: listLocations });
  const { data: categories } = useQuery({ queryKey: ['categories'], queryFn: listCategories });

  const itemParams = {
    page,
    page_size: pageSize,
    location_id: locationId,
    category_id: categoryId,
    below_safety: belowSafety || undefined,
    q: keyword.trim() || undefined,
  };

  const itemQuery = useQuery({
    queryKey: ['stock-report', 'item', page, pageSize, locationId, categoryId, belowSafety, keyword],
    queryFn: () => reportsApi.getStockReportByItem(itemParams),
    enabled: groupBy === 'item',
  });

  const summaryQuery = useQuery({
    queryKey: ['stock-report', groupBy],
    queryFn: () =>
      reportsApi.getStockReportSummary(groupBy as 'location' | 'category'),
    enabled: groupBy !== 'item',
  });

  const summaryColumns: ColumnsType<InventorySummaryGroup> = [
    {
      title: groupBy === 'location' ? '库位' : '类目',
      key: 'group_name',
      render: (_, r) => r.location_name ?? r.category_name ?? '—',
    },
    { title: 'SKU 数', dataIndex: 'sku_count', align: 'right', width: 120, render: (v: number) => fmtQty(v) },
    { title: '总件数', dataIndex: 'total_qty', align: 'right', width: 140, render: (v: number) => fmtQty(v) },
    {
      title: '总金额',
      dataIndex: 'total_value',
      align: 'right',
      width: 160,
      render: (v: number) => <Typography.Text style={{ color: qtyColor(1) }}>{fmtMoney(v)}</Typography.Text>,
    },
  ];

  const itemColumns: ColumnsType<StockReportItemRow> = [
    { title: '条码', dataIndex: 'barcode', width: 110, render: (v: string | null) => v ?? '—' },
    { title: '名称', dataIndex: 'item_name', ellipsis: true },
    { title: '类目', dataIndex: 'category_name', width: 90, render: (v: string | null) => v ?? '—' },
    { title: '库位', dataIndex: 'location_name', width: 120, render: (v: string | null) => v ?? '—' },
    {
      title: '库存',
      dataIndex: 'qty_on_hand',
      align: 'right',
      width: 90,
      render: (v: number) => fmtQty(v),
    },
    { title: '待领取', dataIndex: 'qty_reserved', align: 'right', width: 90, render: (v: number) => fmtQty(v) },
    { title: '安全库存', dataIndex: 'safety_stock', align: 'right', width: 100, render: (v: number) => fmtQty(v) },
    { title: '单价', dataIndex: 'suggest_price', align: 'right', width: 110, render: (v: number | null) => fmtMoney(v) },
    {
      title: '金额',
      dataIndex: 'stock_value',
      align: 'right',
      width: 130,
      render: (v: number) => <Typography.Text style={{ color: qtyColor(1) }}>{fmtMoney(v)}</Typography.Text>,
    },
  ];

  return (
    <>
      <Card size="small" style={{ marginBottom: 12 }}>
        <Space wrap>
          <Radio.Group
            value={groupBy}
            onChange={(e) => setGroupBy(e.target.value as StockGroupBy)}
            options={[
              { value: 'item', label: '按物品' },
              { value: 'location', label: '按库位' },
              { value: 'category', label: '按类目' },
            ]}
            optionType="button"
          />
          {groupBy === 'item' && (
            <>
              <Select
                allowClear
                style={{ width: 160 }}
                placeholder="库位"
                value={locationId}
                onChange={(v) => {
                  setLocationId(v);
                  reset();
                }}
                options={(locations ?? []).map((l) => ({ value: l.id, label: l.name }))}
              />
              <Select
                allowClear
                style={{ width: 140 }}
                placeholder="类目"
                value={categoryId}
                onChange={(v) => {
                  setCategoryId(v);
                  reset();
                }}
                options={(categories ?? []).map((c) => ({ value: c.id, label: c.name }))}
              />
              <Checkbox
                checked={belowSafety}
                onChange={(e) => {
                  setBelowSafety(e.target.checked);
                  reset();
                }}
              >
                低于安全库存
              </Checkbox>
              <Input.Search
                allowClear
                style={{ width: 200 }}
                placeholder="名称 / 条码关键词"
                onSearch={(v) => {
                  setKeyword(v);
                  reset();
                }}
              />
              <Button
                onClick={() =>
                  exportInventoryCsv({
                    location_id: locationId,
                    category_id: categoryId,
                    below_safety: belowSafety || undefined,
                    q: keyword.trim() || undefined,
                  })
                }
              >
                导出 CSV
              </Button>
            </>
          )}
        </Space>
      </Card>
      <Card size="small" styles={{ body: { padding: 0 } }}>
        {groupBy === 'item' ? (
          <Table<StockReportItemRow>
            rowKey={(r) => `${r.item_id}-${r.location_id}`}
            columns={itemColumns}
            dataSource={itemQuery.data?.list ?? []}
            loading={itemQuery.isFetching}
            size="middle"
            pagination={makeTablePagination(itemQuery.data?.meta.total ?? 0)}
            onRow={(r) =>
              r.below_safety ? { style: { backgroundColor: '#F3E2DE' } } : {}
            }
            scroll={{ x: 1080 }}
          />
        ) : (
          <Table<InventorySummaryGroup>
            rowKey={(r) => String(r.location_id ?? r.category_id ?? r.location_name ?? r.category_name)}
            columns={summaryColumns}
            dataSource={summaryQuery.data ?? []}
            loading={summaryQuery.isFetching}
            size="middle"
            pagination={false}
            scroll={{ x: 520 }}
          />
        )}
      </Card>
    </>
  );
}

// ========== 出入库统计 ==========

function MovementsReport() {
  const [groupBy, setGroupBy] = useState<MovementsGroupBy>('doc_type');
  const [range, setRange] = useState<[Dayjs | null, Dayjs | null] | null>([
    dayjs().subtract(30, 'day'),
    dayjs(),
  ]);
  const [locationId, setLocationId] = useState<number | undefined>();

  const { data: locations } = useQuery({ queryKey: ['locations'], queryFn: listLocations });

  const start = range?.[0] ? range[0].format('YYYY-MM-DD') : undefined;
  const end = range?.[1] ? range[1].format('YYYY-MM-DD') : undefined;

  const { data, isFetching } = useQuery({
    queryKey: ['movements-report', groupBy, start, end, locationId],
    queryFn: () =>
      reportsApi.getMovementsReport({ group_by: groupBy, start, end, location_id: locationId }),
  });

  const columns: ColumnsType<MovementsReportRow> = [
    {
      title:
        groupBy === 'doc_type'
          ? '单据类型'
          : groupBy === 'date'
            ? '日期'
            : groupBy === 'item'
              ? '物品'
              : '库位',
      key: 'group_name',
      ellipsis: true,
      render: (_, r) => {
        if (groupBy === 'doc_type') return DOC_TYPE_LABELS[r.doc_type ?? ''] ?? r.doc_type ?? '—';
        if (groupBy === 'date') return r.date ?? '—';
        if (groupBy === 'item') return `${r.item_name ?? '—'}${r.barcode ? `（${r.barcode}）` : ''}`;
        return r.location_name ?? '—';
      },
    },
    { title: '笔数', dataIndex: 'movement_count', align: 'right', width: 100, render: (v: number) => fmtQty(v) },
    {
      title: '入库量',
      dataIndex: 'in_qty',
      align: 'right',
      width: 110,
      render: (v: number) => <Typography.Text style={{ color: qtyColor(v) }}>{fmtQty(v)}</Typography.Text>,
    },
    {
      title: '出库量',
      dataIndex: 'out_qty',
      align: 'right',
      width: 110,
      render: (v: number) => <Typography.Text style={{ color: qtyColor(-v) }}>{fmtQty(v)}</Typography.Text>,
    },
    {
      title: '净变动',
      dataIndex: 'net_qty',
      align: 'right',
      width: 110,
      render: (v: number) => (
        <Typography.Text strong style={{ color: qtyColor(v) }}>
          {v > 0 ? `+${fmtQty(v)}` : fmtQty(v)}
        </Typography.Text>
      ),
    },
  ];

  const overall = data?.overall;

  return (
    <>
      <Card size="small" style={{ marginBottom: 12 }}>
        <Space wrap>
          <Radio.Group
            value={groupBy}
            onChange={(e) => setGroupBy(e.target.value as MovementsGroupBy)}
            options={[
              { value: 'doc_type', label: '按单据类型' },
              { value: 'date', label: '按日' },
              { value: 'item', label: '按物品' },
              { value: 'location', label: '按库位' },
            ]}
            optionType="button"
          />
          <RangePicker
            value={range as never}
            onChange={(v) => setRange(v as [Dayjs | null, Dayjs | null] | null)}
            placeholder={['开始日期', '结束日期']}
            presets={[
              { label: '最近7天', value: [dayjs().subtract(7, 'day'), dayjs()] },
              { label: '最近30天', value: [dayjs().subtract(30, 'day'), dayjs()] },
              { label: '最近90天', value: [dayjs().subtract(90, 'day'), dayjs()] },
            ]}
          />
          <Select
            allowClear
            style={{ width: 160 }}
            placeholder="库位"
            value={locationId}
            onChange={setLocationId}
            options={(locations ?? []).map((l) => ({ value: l.id, label: l.name }))}
          />
          <Button onClick={() => exportMovementsCsv({ start, end, location_id: locationId })}>
            导出明细 CSV
          </Button>
        </Space>
      </Card>
      <Card size="small" styles={{ body: { padding: 0 } }}>
        <Table<MovementsReportRow>
          rowKey={(_, i) => String(i)}
          columns={columns}
          dataSource={data?.rows ?? []}
          loading={isFetching}
          size="middle"
          pagination={false}
          scroll={{ x: 640 }}
          summary={() =>
            overall ? (
              <Table.Summary.Row>
                <Table.Summary.Cell index={0}>总计</Table.Summary.Cell>
                <Table.Summary.Cell index={1} align="right">
                  {fmtQty(overall.movement_count)}
                </Table.Summary.Cell>
                <Table.Summary.Cell index={2} align="right">
                  <Typography.Text style={{ color: qtyColor(overall.in_qty) }}>
                    {fmtQty(overall.in_qty)}
                  </Typography.Text>
                </Table.Summary.Cell>
                <Table.Summary.Cell index={3} align="right">
                  <Typography.Text style={{ color: qtyColor(-overall.out_qty) }}>
                    {fmtQty(overall.out_qty)}
                  </Typography.Text>
                </Table.Summary.Cell>
                <Table.Summary.Cell index={4} align="right">
                  <Typography.Text strong style={{ color: qtyColor(overall.net_qty) }}>
                    {overall.net_qty > 0 ? `+${fmtQty(overall.net_qty)}` : fmtQty(overall.net_qty)}
                  </Typography.Text>
                </Table.Summary.Cell>
              </Table.Summary.Row>
            ) : null
          }
        />
      </Card>
    </>
  );
}

/** 报表中心：库存报表 + 出入库统计 */
export default function Reports() {
  return (
    <PageContainer title="报表" description="库存现状与出入库流水汇总，支持按库位 / 类目 / 物品多维度查看与导出">
      <Tabs
        items={[
          { key: 'stock', label: '库存报表', children: <StockReport /> },
          { key: 'movements', label: '出入库统计', children: <MovementsReport /> },
        ]}
      />
    </PageContainer>
  );
}
