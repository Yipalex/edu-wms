import { useEffect, useState } from 'react';
import {
  Button,
  Card,
  DatePicker,
  Descriptions,
  Drawer,
  Form,
  Grid,
  Input,
  Popconfirm,
  Select,
  Space,
  Table,
  Typography,
  message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { PlusOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import dayjs, { type Dayjs } from 'dayjs';
import * as docsApi from '@/api/docs';
import type { DocLineInput, InboundLine, InboundOrder } from '@/api/types';
import { listLocations } from '@/api/categories';
import PageContainer from '@/components/PageContainer';
import DocStatusTag from '@/components/DocStatusTag';
import DocLinesEditor, { type DocLineUI } from '@/components/docs/DocLinesEditor';
import { usePagination } from '@/hooks/usePagination';
import { useAuth } from '@/hooks/useAuth';
import { DOC_STATE_LABELS, fmtDate, fmtDateTime, fmtMoney, fmtQty } from '@/utils/format';

const { RangePicker } = DatePicker;

type DrawerState = { mode: 'create' } | { mode: 'detail' | 'edit'; id: number } | null;

interface InboundFormValues {
  supplier?: string;
  location_id: number;
  order_date: Dayjs;
  remark?: string;
}

function lineToUI(l: InboundLine): DocLineUI {
  return {
    item_id: l.item_id,
    qty: l.qty,
    purchase_price: l.purchase_price,
    sale_price: l.sale_price,
    _name: l.name_snapshot ?? '',
    _barcode: l.barcode_snapshot,
    _spec: l.spec_snapshot ?? '',
  };
}

/** 入库单：列表筛选 + 新建/编辑（扫码明细）+ 详情（过账/作废/导出易知鸟） */
export default function Inbound() {
  const screens = Grid.useBreakpoint();
  const { page, pageSize, makeTablePagination, reset } = usePagination(20);
  const [stateFilter, setStateFilter] = useState<string | undefined>();
  const [locationId, setLocationId] = useState<number | undefined>();
  const [range, setRange] = useState<[Dayjs | null, Dayjs | null] | null>(null);
  const [q, setQ] = useState('');
  const [drawer, setDrawer] = useState<DrawerState>(null);
  const [lines, setLines] = useState<DocLineUI[]>([]);
  const [form] = Form.useForm<InboundFormValues>();
  const qc = useQueryClient();
  const { isAdmin } = useAuth();

  const { data, isFetching } = useQuery({
    queryKey: [
      'inbound-orders',
      page,
      pageSize,
      stateFilter,
      locationId,
      range?.[0]?.valueOf(),
      range?.[1]?.valueOf(),
      q,
    ],
    queryFn: () =>
      docsApi.listInboundOrders({
        page,
        page_size: pageSize,
        state: stateFilter,
        location_id: locationId,
        start: range?.[0] ? range[0].format('YYYY-MM-DD') : undefined,
        end: range?.[1] ? range[1].format('YYYY-MM-DD') : undefined,
        q: q || undefined,
      }),
  });

  const { data: locations } = useQuery({ queryKey: ['locations'], queryFn: listLocations });
  const locationOptions = (locations ?? []).map((l) => ({ value: l.id, label: l.name }));

  const detailId = drawer && drawer.mode !== 'create' ? drawer.id : undefined;
  const { data: detail, isFetching: detailLoading } = useQuery({
    queryKey: ['inbound-order', detailId],
    queryFn: () => docsApi.getInboundOrder(detailId as number),
    enabled: detailId != null,
  });

  // 打开编辑抽屉时用详情回填表单与明细
  useEffect(() => {
    if (drawer?.mode === 'edit' && detail) {
      form.setFieldsValue({
        supplier: detail.supplier,
        location_id: detail.location_id,
        order_date: dayjs(detail.order_date),
        remark: detail.remark,
      });
      setLines(detail.items.map(lineToUI));
    }
  }, [drawer, detail, form]);

  const invalidateAll = () => {
    void qc.invalidateQueries({ queryKey: ['inbound-orders'] });
    void qc.invalidateQueries({ queryKey: ['inbound-order'] });
  };

  const createMut = useMutation({
    mutationFn: (payload: docsApi.InboundCreatePayload) => docsApi.createInboundOrder(payload),
    onSuccess: () => {
      message.success('入库单已创建');
      setDrawer(null);
      invalidateAll();
    },
  });
  const updateMut = useMutation({
    mutationFn: (vars: { id: number; payload: docsApi.InboundCreatePayload }) =>
      docsApi.patchInboundOrder(vars.id, vars.payload),
    onSuccess: () => {
      message.success('保存成功');
      setDrawer(null);
      invalidateAll();
    },
  });
  const postMut = useMutation({
    mutationFn: (id: number) => docsApi.postInboundOrder(id),
    onSuccess: () => {
      message.success('过账成功，库存已更新');
      invalidateAll();
    },
  });
  const voidMut = useMutation({
    mutationFn: (id: number) => docsApi.voidInboundOrder(id),
    onSuccess: () => {
      message.success('已作废并冲销库存');
      invalidateAll();
    },
  });

  const openCreate = () => {
    form.resetFields();
    setLines([]);
    form.setFieldsValue({
      location_id: locations?.find((l) => l.is_front_warehouse)?.id,
      order_date: dayjs(),
    });
    setDrawer({ mode: 'create' });
  };

  const submit = async () => {
    let values: InboundFormValues;
    try {
      values = await form.validateFields();
    } catch {
      return;
    }
    if (lines.length === 0) {
      message.warning('请先扫码或手动添加明细行');
      return;
    }
    const items: DocLineInput[] = lines.map((l) => ({
      item_id: l.item_id,
      qty: l.qty,
      purchase_price: l.purchase_price ?? null,
      sale_price: l.sale_price ?? null,
    }));
    const payload: docsApi.InboundCreatePayload = {
      supplier: values.supplier,
      location_id: values.location_id,
      order_date: values.order_date.format('YYYY-MM-DD'),
      remark: values.remark,
      items,
    };
    if (drawer?.mode === 'edit') updateMut.mutate({ id: drawer.id, payload });
    else createMut.mutate(payload);
  };

  const columns: ColumnsType<InboundOrder> = [
    {
      title: '单号',
      dataIndex: 'doc_no',
      width: 170,
      render: (v: string) => <Typography.Text style={{ fontFamily: 'monospace' }}>{v}</Typography.Text>,
    },
    { title: '库位', dataIndex: 'location_name', width: 120, render: (v?: string | null) => v ?? '—' },
    { title: '状态', dataIndex: 'state', width: 90, render: (v: string) => <DocStatusTag state={v} /> },
    { title: '业务日期', dataIndex: 'order_date', width: 110, render: (v: string) => fmtDate(v) },
    { title: '金额', dataIndex: 'total_amount', width: 120, align: 'right', render: (v: number) => fmtMoney(v) },
    { title: '创建时间', dataIndex: 'created_at', width: 150, render: (v: string) => fmtDateTime(v) },
    {
      title: '操作',
      key: 'actions',
      width: 80,
      fixed: 'right',
      render: (_, r) => (
        <Button type="link" size="small" onClick={() => setDrawer({ mode: 'detail', id: r.id })}>
          查看
        </Button>
      ),
    },
  ];

  const detailItemsColumns: ColumnsType<InboundLine> = [
    {
      title: '条码',
      dataIndex: 'barcode_snapshot',
      width: 130,
      render: (v: string | null) => v ?? '—',
    },
    { title: '物品名称', dataIndex: 'name_snapshot', ellipsis: true },
    { title: '规格', dataIndex: 'spec_snapshot', width: 120, render: (v: string | null) => v ?? '—' },
    { title: '数量', dataIndex: 'qty', width: 80, align: 'right', render: (v: number) => fmtQty(v) },
    {
      title: '采购单价',
      dataIndex: 'purchase_price',
      width: 110,
      align: 'right',
      render: (v: number | null) => fmtMoney(v),
    },
    {
      title: '售卖单价',
      dataIndex: 'sale_price',
      width: 110,
      align: 'right',
      render: (v: number | null) => fmtMoney(v),
    },
  ];

  const detailActions =
    detail && drawer?.mode === 'detail' ? (
      <Space wrap>
        {detail.state === 'draft' && (
          <>
            <Popconfirm
              title="确认过账？"
              description="过账后将写入库存流水，不可再编辑"
              onConfirm={() => postMut.mutate(detail.id)}
            >
              <Button type="primary" loading={postMut.isPending}>
                过账
              </Button>
            </Popconfirm>
            <Button onClick={() => setDrawer({ mode: 'edit', id: detail.id })}>编辑</Button>
          </>
        )}
        {detail.state === 'posted' && (
          <>
            <Button onClick={() => docsApi.exportInboundYizhiniao(detail.id, detail.doc_no)}>
              导出易知鸟模板
            </Button>
            {isAdmin && (
              <Popconfirm
                title="确认作废？"
                description="作废将冲销本次入库的库存，操作留痕"
                onConfirm={() => voidMut.mutate(detail.id)}
              >
                <Button danger loading={voidMut.isPending}>
                  作废
                </Button>
              </Popconfirm>
            )}
          </>
        )}
      </Space>
    ) : null;

  return (
    <PageContainer
      title="入库单"
      description="采购入库登记：扫码/搜索加明细，草稿可编辑，过账后写入库存"
      extra={
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
          新建入库单
        </Button>
      }
    >
      <Card size="small" style={{ marginBottom: 12 }}>
        <Space wrap>
          <Select
            allowClear
            style={{ width: 130 }}
            placeholder="状态"
            value={stateFilter}
            onChange={(v) => {
              setStateFilter(v);
              reset();
            }}
            options={['draft', 'posted', 'voided'].map((s) => ({ value: s, label: DOC_STATE_LABELS[s] }))}
          />
          <Select
            allowClear
            showSearch
            optionFilterProp="label"
            style={{ width: 170 }}
            placeholder="库位"
            value={locationId}
            onChange={(v) => {
              setLocationId(v);
              reset();
            }}
            options={locationOptions}
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
            allowClear
            style={{ width: 240 }}
            placeholder="单号 / 供应商 / 备注"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onSearch={(v) => {
              setQ(v);
              reset();
            }}
          />
        </Space>
      </Card>
      <Card size="small" styles={{ body: { padding: 0 } }}>
        <Table<InboundOrder>
          rowKey="id"
          columns={columns}
          dataSource={data?.list ?? []}
          loading={isFetching}
          size="middle"
          pagination={makeTablePagination(data?.meta.total ?? 0)}
          scroll={{ x: 940 }}
        />
      </Card>

      <Drawer
        title={
          drawer?.mode === 'create'
            ? '新建入库单'
            : drawer?.mode === 'edit'
              ? `编辑入库单 ${detail?.doc_no ?? ''}`
              : `入库单 ${detail?.doc_no ?? ''}`
        }
        open={drawer !== null}
        width={screens.md ? 760 : '100%'}
        onClose={() => setDrawer(null)}
        footer={
          drawer?.mode === 'detail'
            ? detailActions
            : drawer && (
                <Space>
                  <Button onClick={() => setDrawer(null)}>取消</Button>
                  <Button
                    type="primary"
                    loading={createMut.isPending || updateMut.isPending}
                    onClick={() => void submit()}
                  >
                    保存
                  </Button>
                </Space>
              )
        }
      >
        {drawer?.mode === 'detail' ? (
          detailLoading && !detail ? (
            <div>加载中…</div>
          ) : detail ? (
            <>
              <Descriptions
                size="small"
                column={{ xs: 1, md: 2 }}
                items={[
                  { key: 'doc_no', label: '单号', children: detail.doc_no },
                  { key: 'state', label: '状态', children: <DocStatusTag state={detail.state} /> },
                  { key: 'location', label: '入库库位', children: detail.location_name ?? '—' },
                  { key: 'supplier', label: '供应商', children: detail.supplier || '—' },
                  { key: 'order_date', label: '业务日期', children: fmtDate(detail.order_date) },
                  { key: 'posted_at', label: '过账时间', children: fmtDateTime(detail.posted_at) },
                  { key: 'remark', label: '备注', children: detail.remark || '—', span: 2 },
                  { key: 'created_at', label: '创建时间', children: fmtDateTime(detail.created_at) },
                ]}
              />
              <Table<InboundLine>
                style={{ marginTop: 16 }}
                rowKey="id"
                columns={detailItemsColumns}
                dataSource={detail.items}
                pagination={false}
                size="small"
                scroll={{ x: 660 }}
                locale={{ emptyText: '暂无明细' }}
              />
            </>
          ) : null
        ) : (
          <Form form={form} layout="vertical">
            <Form.Item
              name="location_id"
              label="入库库位"
              rules={[{ required: true, message: '请选择入库库位' }]}
            >
              <Select options={locationOptions} placeholder="选择入库库位" showSearch optionFilterProp="label" />
            </Form.Item>
            <Form.Item
              name="order_date"
              label="业务日期"
              rules={[{ required: true, message: '请选择业务日期' }]}
            >
              <DatePicker style={{ width: '100%' }} />
            </Form.Item>
            <Form.Item name="supplier" label="供应商">
              <Input placeholder="选填" allowClear maxLength={100} />
            </Form.Item>
            <Form.Item name="remark" label="备注">
              <Input.TextArea rows={2} placeholder="选填" maxLength={200} />
            </Form.Item>
            <Form.Item label="明细" required style={{ marginBottom: 0 }}>
              <DocLinesEditor lines={lines} onChange={setLines} withPrice enabled={drawer !== null} />
            </Form.Item>
          </Form>
        )}
      </Drawer>
    </PageContainer>
  );
}
