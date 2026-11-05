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
  Radio,
  Select,
  Space,
  Table,
  Tag,
  Typography,
  message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { PlusOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import dayjs, { type Dayjs } from 'dayjs';
import * as docsApi from '@/api/docs';
import type { DocLineInput, OutboundLine, OutboundOrder } from '@/api/types';
import { listLocations } from '@/api/categories';
import PageContainer from '@/components/PageContainer';
import DocStatusTag from '@/components/DocStatusTag';
import DocLinesEditor, { type DocLineUI } from '@/components/docs/DocLinesEditor';
import { usePagination } from '@/hooks/usePagination';
import { useAuth } from '@/hooks/useAuth';
import { DOC_STATE_LABELS, fmtDate, fmtDateTime, fmtQty } from '@/utils/format';

const { RangePicker } = DatePicker;

type DrawerState = { mode: 'create' } | { mode: 'detail' | 'edit'; id: number } | null;

const KIND_LABELS: Record<string, string> = { transfer: '调拨', issue: '领用' };

interface OutboundFormValues {
  kind: 'transfer' | 'issue';
  from_location_id: number;
  to_location_id?: number;
  order_date: Dayjs;
  remark?: string;
}

function lineToUI(l: OutboundLine): DocLineUI {
  return {
    item_id: l.item_id,
    qty: l.qty,
    _name: l.name_snapshot ?? '',
    _barcode: l.barcode_snapshot,
    _spec: '',
  };
}

/** 出库 / 调拨单：kind=transfer 校区间调拨（必选调入库位），kind=issue 领用出库 */
export default function Outbound() {
  const screens = Grid.useBreakpoint();
  const { page, pageSize, makeTablePagination, reset } = usePagination(20);
  const [stateFilter, setStateFilter] = useState<string | undefined>();
  const [kindFilter, setKindFilter] = useState<'transfer' | 'issue' | undefined>();
  const [locationId, setLocationId] = useState<number | undefined>();
  const [range, setRange] = useState<[Dayjs | null, Dayjs | null] | null>(null);
  const [q, setQ] = useState('');
  const [drawer, setDrawer] = useState<DrawerState>(null);
  const [lines, setLines] = useState<DocLineUI[]>([]);
  const [form] = Form.useForm<OutboundFormValues>();
  const qc = useQueryClient();
  const { isAdmin, isTeacher, user } = useAuth();

  const { data, isFetching } = useQuery({
    queryKey: [
      'outbound-orders',
      page,
      pageSize,
      stateFilter,
      kindFilter,
      locationId,
      range?.[0]?.valueOf(),
      range?.[1]?.valueOf(),
      q,
    ],
    queryFn: () =>
      docsApi.listOutboundOrders({
        page,
        page_size: pageSize,
        state: stateFilter,
        kind: isTeacher ? undefined : kindFilter,
        location_id: isTeacher ? undefined : locationId,
        start: range?.[0] ? range[0].format('YYYY-MM-DD') : undefined,
        end: range?.[1] ? range[1].format('YYYY-MM-DD') : undefined,
        q: q || undefined,
      }),
  });

  const { data: locations } = useQuery({ queryKey: ['locations'], queryFn: listLocations });
  const locationOptions = (locations ?? []).map((l) => ({ value: l.id, label: l.name }));

  const detailId = drawer && drawer.mode !== 'create' ? drawer.id : undefined;
  const { data: detail, isFetching: detailLoading } = useQuery({
    queryKey: ['outbound-order', detailId],
    queryFn: () => docsApi.getOutboundOrder(detailId as number),
    enabled: detailId != null,
  });

  // 打开编辑抽屉时用详情回填表单与明细
  useEffect(() => {
    if (drawer?.mode === 'edit' && detail) {
      form.setFieldsValue({
        kind: detail.kind,
        from_location_id: detail.from_location_id,
        to_location_id: detail.to_location_id ?? undefined,
        order_date: dayjs(detail.order_date),
        remark: detail.remark,
      });
      setLines(detail.items.map(lineToUI));
    }
  }, [drawer, detail, form]);

  const invalidateAll = () => {
    void qc.invalidateQueries({ queryKey: ['outbound-orders'] });
    void qc.invalidateQueries({ queryKey: ['outbound-order'] });
  };

  const createMut = useMutation({
    mutationFn: (payload: docsApi.OutboundCreatePayload) => docsApi.createOutboundOrder(payload),
    onSuccess: () => {
      message.success('出库单已创建');
      setDrawer(null);
      invalidateAll();
    },
  });
  const updateMut = useMutation({
    mutationFn: (vars: { id: number; payload: docsApi.OutboundCreatePayload }) =>
      docsApi.patchOutboundOrder(vars.id, vars.payload),
    onSuccess: () => {
      message.success('保存成功');
      setDrawer(null);
      invalidateAll();
    },
  });
  const postMut = useMutation({
    mutationFn: (id: number) => docsApi.postOutboundOrder(id),
    onSuccess: () => {
      message.success('过账成功，库存已更新');
      invalidateAll();
    },
  });
  const voidMut = useMutation({
    mutationFn: (id: number) => docsApi.voidOutboundOrder(id),
    onSuccess: () => {
      message.success('已作废并冲销库存');
      invalidateAll();
    },
  });

  const openCreate = () => {
    form.resetFields();
    setLines([]);
    // 教师：只能是「领用出库」，且从自己校区出（后端同样强制）
    form.setFieldsValue({
      kind: isTeacher ? 'issue' : 'transfer',
      from_location_id: isTeacher ? (user?.home_location_id ?? undefined) : undefined,
      order_date: dayjs(),
    });
    setDrawer({ mode: 'create' });
  };

  const submit = async () => {
    let values: OutboundFormValues;
    try {
      values = await form.validateFields();
    } catch {
      return;
    }
    if (lines.length === 0) {
      message.warning('请先扫码或手动添加明细行');
      return;
    }
    const items: DocLineInput[] = lines.map((l) => ({ item_id: l.item_id, qty: l.qty }));
    const payload: docsApi.OutboundCreatePayload = {
      kind: values.kind,
      from_location_id: values.from_location_id,
      to_location_id: values.kind === 'transfer' ? values.to_location_id : null,
      order_date: values.order_date.format('YYYY-MM-DD'),
      remark: values.remark,
      items,
    };
    if (drawer?.mode === 'edit') updateMut.mutate({ id: drawer.id, payload });
    else createMut.mutate(payload);
  };

  const columns: ColumnsType<OutboundOrder> = [
    {
      title: '单号',
      dataIndex: 'doc_no',
      width: 170,
      render: (v: string) => <Typography.Text style={{ fontFamily: 'monospace' }}>{v}</Typography.Text>,
    },
    {
      title: '类型',
      dataIndex: 'kind',
      width: 80,
      render: (v: string) => <Tag color={v === 'transfer' ? 'blue' : 'purple'}>{KIND_LABELS[v] ?? v}</Tag>,
    },
    { title: '调出库位', dataIndex: 'from_location_name', width: 120, render: (v?: string | null) => v ?? '—' },
    { title: '调入库位', dataIndex: 'to_location_name', width: 120, render: (v?: string | null) => v ?? '—' },
    { title: '状态', dataIndex: 'state', width: 90, render: (v: string) => <DocStatusTag state={v} /> },
    { title: '业务日期', dataIndex: 'order_date', width: 110, render: (v: string) => fmtDate(v) },
    { title: '备注', dataIndex: 'remark', ellipsis: true, render: (v: string) => v || '—' },
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

  const detailItemsColumns: ColumnsType<OutboundLine> = [
    {
      title: '条码',
      dataIndex: 'barcode_snapshot',
      width: 130,
      render: (v: string | null) => v ?? '—',
    },
    { title: '物品名称', dataIndex: 'name_snapshot', ellipsis: true },
    { title: '数量', dataIndex: 'qty', width: 100, align: 'right', render: (v: number) => fmtQty(v) },
  ];

  const detailActions =
    detail && drawer?.mode === 'detail' ? (
      <Space wrap>
        {detail.state === 'draft' && (
          <>
            <Popconfirm
              title="确认过账？"
              description={
                detail.kind === 'transfer'
                  ? '过账后将从调出库位扣减并调入指定库位，不可再编辑'
                  : '过账后将从调出库位扣减库存，不可再编辑'
              }
              onConfirm={() => postMut.mutate(detail.id)}
            >
              <Button type="primary" loading={postMut.isPending}>
                过账
              </Button>
            </Popconfirm>
            <Button onClick={() => setDrawer({ mode: 'edit', id: detail.id })}>编辑</Button>
          </>
        )}
        {detail.state === 'posted' && isAdmin && (
          <Popconfirm
            title="确认作废？"
            description="作废将冲销本次出库/调拨的库存变动，操作留痕"
            onConfirm={() => voidMut.mutate(detail.id)}
          >
            <Button danger loading={voidMut.isPending}>
              作废
            </Button>
          </Popconfirm>
        )}
      </Space>
    ) : null;

  return (
    <PageContainer
      title="出库 / 调拨单"
      description="校区间调拨或领用出库：草稿可编辑，过账后扣减调出库位库存"
      extra={
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
          新建出库单
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
            style={{ width: 110 }}
            placeholder="单据类型"
            value={kindFilter}
            onChange={(v) => {
              setKindFilter(v);
              reset();
            }}
            options={[
              { value: 'transfer', label: '调拨' },
              { value: 'issue', label: '领用' },
            ]}
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
            style={{ width: 220 }}
            placeholder="单号 / 备注"
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
        <Table<OutboundOrder>
          rowKey="id"
          columns={columns}
          dataSource={data?.list ?? []}
          loading={isFetching}
          size="middle"
          pagination={makeTablePagination(data?.meta.total ?? 0)}
          scroll={{ x: 1060 }}
        />
      </Card>

      <Drawer
        title={
          drawer?.mode === 'create'
            ? '新建出库单'
            : drawer?.mode === 'edit'
              ? `编辑出库单 ${detail?.doc_no ?? ''}`
              : `出库单 ${detail?.doc_no ?? ''}`
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
                  {
                    key: 'kind',
                    label: '类型',
                    children: <Tag color={detail.kind === 'transfer' ? 'blue' : 'purple'}>{KIND_LABELS[detail.kind]}</Tag>,
                  },
                  { key: 'order_date', label: '业务日期', children: fmtDate(detail.order_date) },
                  { key: 'from', label: '调出库位', children: detail.from_location_name ?? '—' },
                  { key: 'to', label: '调入库位', children: detail.to_location_name ?? '—' },
                  { key: 'posted_at', label: '过账时间', children: fmtDateTime(detail.posted_at) },
                  { key: 'remark', label: '备注', children: detail.remark || '—', span: 2 },
                  { key: 'created_at', label: '创建时间', children: fmtDateTime(detail.created_at) },
                ]}
              />
              <Table<OutboundLine>
                style={{ marginTop: 16 }}
                rowKey="id"
                columns={detailItemsColumns}
                dataSource={detail.items}
                pagination={false}
                size="small"
                scroll={{ x: 400 }}
                locale={{ emptyText: '暂无明细' }}
              />
            </>
          ) : null
        ) : (
          <Form form={form} layout="vertical">
            <Form.Item
              name="kind"
              label="单据类型"
              rules={[{ required: true, message: '请选择单据类型' }]}
              tooltip={isTeacher ? '教师只能进行领用出库；校区间调拨由总校办操作' : undefined}
            >
              <Radio.Group
                disabled={isTeacher}
                options={[
                  { value: 'transfer', label: '调拨（校区间转移）' },
                  { value: 'issue', label: '领用（出库）' },
                ]}
              />
            </Form.Item>
            <Form.Item
              name="from_location_id"
              label="调出库位"
              rules={[{ required: true, message: '请选择调出库位' }]}
            >
              <Select
                options={locationOptions}
                placeholder="选择调出库位"
                showSearch
                optionFilterProp="label"
                disabled={isTeacher}
              />
            </Form.Item>
            <Form.Item
              noStyle
              shouldUpdate={(prev, cur) => prev.kind !== cur.kind || prev.from_location_id !== cur.from_location_id}
            >
              {({ getFieldValue }) => (
                <Form.Item
                  name="to_location_id"
                  label="调入库位"
                  rules={[
                    {
                      required: getFieldValue('kind') === 'transfer',
                      message: '调拨单必须选择调入库位',
                    },
                    {
                      validator: (_, v) => {
                        if (v && v === getFieldValue('from_location_id')) {
                          return Promise.reject(new Error('调入库位不能与调出库位相同'));
                        }
                        return Promise.resolve();
                      },
                    },
                  ]}
                >
                  <Select
                    options={locationOptions}
                    placeholder={getFieldValue('kind') === 'transfer' ? '选择调入库位' : '领用单无需调入库位'}
                    disabled={getFieldValue('kind') !== 'transfer'}
                    allowClear
                    showSearch
                    optionFilterProp="label"
                  />
                </Form.Item>
              )}
            </Form.Item>
            <Form.Item
              name="order_date"
              label="业务日期"
              rules={[{ required: true, message: '请选择业务日期' }]}
            >
              <DatePicker style={{ width: '100%' }} />
            </Form.Item>
            <Form.Item name="remark" label="备注">
              <Input.TextArea rows={2} placeholder="选填" maxLength={200} />
            </Form.Item>
            <Form.Item label="明细" required style={{ marginBottom: 0 }}>
              <DocLinesEditor lines={lines} onChange={setLines} enabled={drawer !== null} />
            </Form.Item>
          </Form>
        )}
      </Drawer>
    </PageContainer>
  );
}
