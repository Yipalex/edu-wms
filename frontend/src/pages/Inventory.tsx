import { useState } from 'react';
import {
  Button,
  Card,
  Checkbox,
  Col,
  Input,
  InputNumber,
  Modal,
  Row,
  Select,
  Space,
  Statistic,
  Table,
  Tabs,
  Tag,
  Typography,
  message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { DownloadOutlined, EditOutlined } from '@ant-design/icons';
import * as categoriesApi from '@/api/categories';
import * as inventoryApi from '@/api/inventory';
import type { InventoryListRow, InventorySummaryGroup } from '@/api/types';
import PageContainer from '@/components/PageContainer';
import { useAuth } from '@/hooks/useAuth';
import { usePagination } from '@/hooks/usePagination';
import { fmtDateTime, fmtMoney, fmtQty } from '@/utils/format';

function summaryColumns(
  nameTitle: string,
): ColumnsType<InventorySummaryGroup> {
  return [
    {
      title: nameTitle,
      key: 'name',
      render: (_, g) => g.location_name ?? g.category_name ?? '—',
    },
    {
      title: 'SKU 数',
      dataIndex: 'sku_count',
      width: 100,
      align: 'right',
      render: (v: number) => fmtQty(v),
    },
    {
      title: '总件数',
      dataIndex: 'total_qty',
      width: 100,
      align: 'right',
      render: (v: number) => fmtQty(v),
    },
    {
      title: '总金额',
      dataIndex: 'total_value',
      width: 130,
      align: 'right',
      render: (v: number) => fmtMoney(v),
    },
  ];
}

/** 库存查询：汇总看板 + 多维筛选 + 行内编辑（admin）+ 快速调整（admin）+ CSV 导出 */
export default function Inventory() {
  const { isAdmin, isTeacher } = useAuth();
  const queryClient = useQueryClient();
  const { page, pageSize, makeTablePagination, reset } = usePagination(20);
  const [categoryId, setCategoryId] = useState<number | undefined>();
  const [locationId, setLocationId] = useState<number | undefined>();
  const [q, setQ] = useState('');
  const [qInput, setQInput] = useState('');
  const [belowSafety, setBelowSafety] = useState(false);
  const [editRow, setEditRow] = useState<InventoryListRow | null>(null);
  const [editSafety, setEditSafety] = useState<number>(0);
  const [editReserved, setEditReserved] = useState<number>(0);
  /** 快速调整目标行（admin）：直接把库存校正为实盘数 */
  const [adjustRow, setAdjustRow] = useState<InventoryListRow | null>(null);
  const [adjustQty, setAdjustQty] = useState<number>(0);
  const [adjustReason, setAdjustReason] = useState('');
  const [exporting, setExporting] = useState(false);

  const { data: locations } = useQuery({
    queryKey: ['locations'],
    queryFn: () => categoriesApi.listLocations(),
  });
  const { data: categories } = useQuery({
    queryKey: ['categories'],
    queryFn: () => categoriesApi.listCategories(),
  });
  // 汇总含全校金额，教师不可用（后端 403，这里直接不请求）
  const { data: summary } = useQuery({
    queryKey: ['inventory-summary'],
    queryFn: () => inventoryApi.getInventorySummary(),
    enabled: !isTeacher,
  });

  const { data, isFetching } = useQuery({
    queryKey: ['inventory', page, pageSize, categoryId, locationId, q, belowSafety],
    queryFn: () =>
      inventoryApi.listInventory({
        page,
        page_size: pageSize,
        category_id: categoryId,
        location_id: locationId,
        q: q || undefined,
        below_safety: belowSafety || undefined,
      }),
  });

  const adjustMutation = useMutation({
    mutationFn: (payload: { item_id: number; location_id: number; qty_actual: number; reason?: string }) =>
      inventoryApi.adjustInventory(payload),
    onSuccess: (res) => {
      message.success(res.message || '库存已调整');
      setAdjustRow(null);
      setAdjustReason('');
      void queryClient.invalidateQueries({ queryKey: ['inventory'] });
      void queryClient.invalidateQueries({ queryKey: ['inventory-summary'] });
    },
    onError: () => {
      // 拦截器已提示
    },
  });

  const patchMutation = useMutation({
    mutationFn: (payload: { id: number; safety_stock?: number; qty_reserved?: number }) =>
      inventoryApi.patchInventory(payload.id, {
        safety_stock: payload.safety_stock,
        qty_reserved: payload.qty_reserved,
      }),
    onSuccess: () => {
      message.success('库存参数已更新');
      setEditRow(null);
      void queryClient.invalidateQueries({ queryKey: ['inventory'] });
      void queryClient.invalidateQueries({ queryKey: ['inventory-summary'] });
    },
    onError: () => {
      // 拦截器已提示
    },
  });

  const doExport = async () => {
    setExporting(true);
    try {
      await inventoryApi.exportInventoryCsv({
        category_id: categoryId,
        location_id: locationId,
        q: q || undefined,
        below_safety: belowSafety || undefined,
      });
    } catch {
      message.error('导出失败，请稍后重试');
    } finally {
      setExporting(false);
    }
  };

  const columns: ColumnsType<InventoryListRow> = [
    {
      title: '条码',
      dataIndex: 'barcode',
      width: 120,
      render: (v: string | null) =>
        v ? <Typography.Text code style={{ fontSize: 12 }}>{v}</Typography.Text> : '—',
    },
    {
      title: '名称',
      dataIndex: 'item_name',
      width: 200,
      ellipsis: true,
      render: (v: string | null) => v ?? '—',
    },
    { title: '类目', dataIndex: 'category_name', width: 90, render: (v: string | null) => v ?? '—' },
    { title: '规格', dataIndex: 'spec', width: 110, ellipsis: true, render: (v: string) => v || '—' },
    { title: '库位', dataIndex: 'location_name', width: 130, render: (v: string | null) => v ?? '—' },
    {
      title: '当前库存',
      dataIndex: 'qty_on_hand',
      width: 120,
      align: 'right',
      render: (v: number, r) => (
        <Space size={4}>
          <Typography.Text strong type={r.below_safety ? 'danger' : undefined}>
            {fmtQty(v)}
          </Typography.Text>
          {r.below_safety && <Tag color="red">低于安全库存</Tag>}
        </Space>
      ),
    },
    {
      title: '待领取',
      dataIndex: 'qty_reserved',
      width: 80,
      align: 'right',
      render: (v: number) => fmtQty(v),
    },
    {
      title: '安全库存',
      dataIndex: 'safety_stock',
      width: 90,
      align: 'right',
      render: (v: number) => fmtQty(v),
    },
    {
      title: '单价',
      dataIndex: 'suggest_price',
      width: 100,
      align: 'right',
      render: (v: number | null) => fmtMoney(v),
    },
    {
      title: '库存金额',
      dataIndex: 'stock_value',
      width: 110,
      align: 'right',
      render: (v: number) => fmtMoney(v),
    },
    {
      title: '更新时间',
      dataIndex: 'updated_at',
      width: 140,
      render: (v: string | null) => fmtDateTime(v),
    },
    ...(isAdmin
      ? [
          {
            title: '操作',
            key: 'action',
            width: 140,
            fixed: 'right' as const,
            render: (_: unknown, r: InventoryListRow) => (
              <Space size={0}>
                <Button
                  type="link"
                  size="small"
                  icon={<EditOutlined />}
                  onClick={() => {
                    setEditRow(r);
                    setEditSafety(r.safety_stock);
                    setEditReserved(r.qty_reserved);
                  }}
                >
                  编辑
                </Button>
                <Button
                  type="link"
                  size="small"
                  onClick={() => {
                    setAdjustRow(r);
                    setAdjustQty(r.qty_on_hand);
                    setAdjustReason('');
                  }}
                >
                  调整
                </Button>
              </Space>
            ),
          },
        ]
      : []),
  ];

  return (
    <PageContainer
      title="库存查询"
      description="按库位/类目/关键词查询实时库存，低于安全库存自动标红"
      extra={
        isTeacher ? undefined : (
          <Button icon={<DownloadOutlined />} loading={exporting} onClick={() => void doExport()}>
            导出 CSV
          </Button>
        )
      }
    >
      {/* 汇总看板（含全校金额，教师不可见） */}
      {!isTeacher && (
      <Card size="small" style={{ marginBottom: 12 }}>
        <Row gutter={[12, 12]}>
          <Col xs={8} sm={8}>
            <Statistic title="总 SKU" value={summary?.total_sku ?? 0} />
          </Col>
          <Col xs={8} sm={8}>
            <Statistic title="总件数" value={summary?.total_qty ?? 0} />
          </Col>
          <Col xs={8} sm={8}>
            <Statistic title="总金额" value={summary?.total_value ?? 0} precision={2} prefix="¥" />
          </Col>
        </Row>
        <Tabs
          style={{ marginTop: 12 }}
          size="small"
          items={[
            {
              key: 'location',
              label: '按库位汇总',
              children: (
                <Table<InventorySummaryGroup>
                  rowKey={(g) => g.location_id ?? 'unknown'}
                  columns={summaryColumns('库位')}
                  dataSource={summary?.by_location ?? []}
                  size="small"
                  pagination={false}
                />
              ),
            },
            {
              key: 'category',
              label: '按类目汇总',
              children: (
                <Table<InventorySummaryGroup>
                  rowKey={(g) => g.category_id ?? 'unknown'}
                  columns={summaryColumns('类目')}
                  dataSource={summary?.by_category ?? []}
                  size="small"
                  pagination={false}
                />
              ),
            },
          ]}
        />
      </Card>
      )}

      {/* 筛选 */}
      <Card size="small" style={{ marginBottom: 12 }}>
        <Space wrap>
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
          {!isTeacher && (
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
          )}
          <Input.Search
            style={{ width: 220 }}
            placeholder="名称或条码"
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
          <Checkbox
            checked={belowSafety}
            onChange={(e) => {
              setBelowSafety(e.target.checked);
              reset();
            }}
          >
            只看低于安全库存
          </Checkbox>
        </Space>
      </Card>

      <Card size="small" styles={{ body: { padding: 0 } }}>
        <Table<InventoryListRow>
          rowKey="id"
          columns={columns}
          dataSource={data?.list ?? []}
          loading={isFetching}
          size="middle"
          pagination={makeTablePagination(data?.meta.total ?? 0)}
          scroll={{ x: 1500 }}
          onRow={(r) =>
            r.below_safety ? { style: { background: '#F3E2DE' } } : {}
          }
        />
      </Card>

      {/* admin 快速库存调整：直接填实盘数，差额写 adjust 流水 */}
      <Modal
        title={adjustRow ? `调整库存 · ${adjustRow.item_name ?? ''}` : ''}
        open={!!adjustRow}
        onCancel={() => setAdjustRow(null)}
        onOk={() => {
          if (!adjustRow) return;
          adjustMutation.mutate({
            item_id: adjustRow.item_id,
            location_id: adjustRow.location_id,
            qty_actual: adjustQty,
            reason: adjustReason.trim() || undefined,
          });
        }}
        confirmLoading={adjustMutation.isPending}
        okText="确认调整"
        cancelText="取消"
        destroyOnClose
      >
        <Space direction="vertical" style={{ width: '100%' }} size={12}>
          <Typography.Text type="secondary">
            库位：{adjustRow?.location_name ?? '—'}　条码：{adjustRow?.barcode ?? '—'}
          </Typography.Text>
          <Typography.Text>
            当前账面库存：<Typography.Text strong>{fmtQty(adjustRow?.qty_on_hand ?? 0)}</Typography.Text>
          </Typography.Text>
          <InputNumber
            addonBefore="实盘数量"
            min={0}
            precision={0}
            style={{ width: '100%' }}
            value={adjustQty}
            onChange={(v) => setAdjustQty(v ?? 0)}
          />
          {adjustRow && adjustQty !== adjustRow.qty_on_hand && (
            <Typography.Text type={adjustQty > adjustRow.qty_on_hand ? 'success' : 'warning'}>
              将把库存从 {fmtQty(adjustRow.qty_on_hand)} 调整为 {fmtQty(adjustQty)}（
              {adjustQty > adjustRow.qty_on_hand ? '+' : ''}
              {adjustQty - adjustRow.qty_on_hand} 件）
            </Typography.Text>
          )}
          <Input
            placeholder="调整原因（可选，如：期初建账补录、盘点校正）"
            maxLength={300}
            value={adjustReason}
            onChange={(e) => setAdjustReason(e.target.value)}
          />
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            调整会产生一条库存流水（账面 → 实盘的差额），历史出入库单据不受影响，可在「库存流水」中查询。
          </Typography.Text>
        </Space>
      </Modal>

      {/* admin 行内编辑 */}
      <Modal
        title={editRow ? `编辑库存参数 · ${editRow.item_name ?? ''}` : ''}
        open={!!editRow}
        onCancel={() => setEditRow(null)}
        onOk={() => {
          if (!editRow) return;
          patchMutation.mutate({
            id: editRow.id,
            safety_stock: editSafety,
            qty_reserved: editReserved,
          });
        }}
        confirmLoading={patchMutation.isPending}
        okText="保存"
        cancelText="取消"
        destroyOnClose
      >
        <Space direction="vertical" style={{ width: '100%' }} size={12}>
          <Typography.Text type="secondary">
            库位：{editRow?.location_name ?? '—'}　条码：{editRow?.barcode ?? '—'}
          </Typography.Text>
          <InputNumber
            addonBefore="安全库存"
            min={0}
            precision={0}
            style={{ width: '100%' }}
            value={editSafety}
            onChange={(v) => setEditSafety(v ?? 0)}
          />
          <InputNumber
            addonBefore="待领取数量"
            min={0}
            precision={0}
            style={{ width: '100%' }}
            value={editReserved}
            onChange={(v) => setEditReserved(v ?? 0)}
          />
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            当前库存只能由入库/出库/盘点等单据变动，此处不可修改。
          </Typography.Text>
        </Space>
      </Modal>

    </PageContainer>
  );
}
