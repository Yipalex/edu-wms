import { useEffect, useState } from 'react';
import {
  Alert,
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
import type { DocLineInput, ReturnLine, ReturnOrder } from '@/api/types';
import { listLocations } from '@/api/categories';
import PageContainer from '@/components/PageContainer';
import DocStatusTag from '@/components/DocStatusTag';
import DocLinesEditor, { type DocLineUI } from '@/components/docs/DocLinesEditor';
import { usePagination } from '@/hooks/usePagination';
import { useAuth } from '@/hooks/useAuth';
import { DOC_STATE_LABELS, fmtDate, fmtDateTime, fmtQty } from '@/utils/format';

const { RangePicker } = DatePicker;

type DrawerState = { mode: 'create' } | { mode: 'detail' | 'edit'; id: number } | null;

const CONDITION_LABELS: Record<string, string> = { sealed: '未拆封', opened: '已拆封' };

interface ReturnFormValues {
  from_location_id: number;
  to_location_id: number;
  item_condition: 'sealed' | 'opened';
  order_date: Dayjs;
  remark?: string;
}

function lineToUI(l: ReturnLine): DocLineUI {
  return {
    item_id: l.item_id,
    qty: l.qty,
    _name: l.name_snapshot ?? '',
    _barcode: l.barcode_snapshot,
    _spec: '',
  };
}

/** 退库单：校区退回总校办仓库，admin 验收/拒收；已拆封按制度第十五条拒收 */
export default function Returns() {
  const screens = Grid.useBreakpoint();
  const { page, pageSize, makeTablePagination, reset } = usePagination(20);
  const [stateFilter, setStateFilter] = useState<string | undefined>();
  const [conditionFilter, setConditionFilter] = useState<'sealed' | 'opened' | undefined>();
  const [locationId, setLocationId] = useState<number | undefined>();
  const [range, setRange] = useState<[Dayjs | null, Dayjs | null] | null>(null);
  const [q, setQ] = useState('');
  const [drawer, setDrawer] = useState<DrawerState>(null);
  const [lines, setLines] = useState<DocLineUI[]>([]);
  const [form] = Form.useForm<ReturnFormValues>();
  const itemCondition = Form.useWatch('item_condition', form);
  const qc = useQueryClient();
  const { isAdmin, isTeacher, user } = useAuth();

  const { data, isFetching } = useQuery({
    queryKey: [
      'return-orders',
      page,
      pageSize,
      stateFilter,
      conditionFilter,
      locationId,
      range?.[0]?.valueOf(),
      range?.[1]?.valueOf(),
      q,
    ],
    queryFn: () =>
      docsApi.listReturnOrders({
        page,
        page_size: pageSize,
        state: stateFilter,
        item_condition: conditionFilter,
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
    queryKey: ['return-order', detailId],
    queryFn: () => docsApi.getReturnOrder(detailId as number),
    enabled: detailId != null,
  });

  // 打开编辑抽屉时用详情回填表单与明细
  useEffect(() => {
    if (drawer?.mode === 'edit' && detail) {
      form.setFieldsValue({
        from_location_id: detail.from_location_id,
        to_location_id: detail.to_location_id,
        item_condition: detail.item_condition,
        order_date: dayjs(detail.order_date),
        remark: detail.remark,
      });
      setLines(detail.items.map(lineToUI));
    }
  }, [drawer, detail, form]);

  const invalidateAll = () => {
    void qc.invalidateQueries({ queryKey: ['return-orders'] });
    void qc.invalidateQueries({ queryKey: ['return-order'] });
  };

  const createMut = useMutation({
    mutationFn: (payload: docsApi.ReturnCreatePayload) => docsApi.createReturnOrder(payload),
    onSuccess: () => {
      message.success('退库单已创建，待仓库验收');
      setDrawer(null);
      invalidateAll();
    },
  });
  const updateMut = useMutation({
    mutationFn: (vars: { id: number; payload: docsApi.ReturnCreatePayload }) =>
      docsApi.patchReturnOrder(vars.id, vars.payload),
    onSuccess: () => {
      message.success('保存成功');
      setDrawer(null);
      invalidateAll();
    },
  });
  const acceptMut = useMutation({
    mutationFn: (id: number) => docsApi.acceptReturnOrder(id),
    onSuccess: () => {
      message.success('验收通过，库存已退回');
      invalidateAll();
    },
  });
  const rejectMut = useMutation({
    mutationFn: (id: number) => docsApi.rejectReturnOrder(id),
    onSuccess: () => {
      message.success('已拒收');
      invalidateAll();
    },
  });
  const voidMut = useMutation({
    mutationFn: (id: number) => docsApi.voidReturnOrder(id),
    onSuccess: () => {
      message.success('已作废并冲销库存');
      invalidateAll();
    },
  });

  const openCreate = () => {
    form.resetFields();
    setLines([]);
    // 教师：从本校区退回总校办仓库（后端同样强制）
    form.setFieldsValue({
      item_condition: 'sealed',
      from_location_id: isTeacher ? (user?.home_location_id ?? undefined) : undefined,
      to_location_id: isTeacher ? undefined : locations?.find((l) => l.is_front_warehouse)?.id,
      order_date: dayjs(),
    });
    setDrawer({ mode: 'create' });
  };

  const submit = async () => {
    let values: ReturnFormValues;
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
    const payload: docsApi.ReturnCreatePayload = {
      from_location_id: values.from_location_id,
      to_location_id: values.to_location_id,
      item_condition: values.item_condition,
      order_date: values.order_date.format('YYYY-MM-DD'),
      remark: values.remark,
      items,
    };
    if (drawer?.mode === 'edit') updateMut.mutate({ id: drawer.id, payload });
    else createMut.mutate(payload);
  };

  const columns: ColumnsType<ReturnOrder> = [
    {
      title: '单号',
      dataIndex: 'doc_no',
      width: 170,
      render: (v: string) => <Typography.Text style={{ fontFamily: 'monospace' }}>{v}</Typography.Text>,
    },
    { title: '退回校区', dataIndex: 'from_location_name', width: 120, render: (v?: string | null) => v ?? '—' },
    { title: '接收仓库', dataIndex: 'to_location_name', width: 120, render: (v?: string | null) => v ?? '—' },
    {
      title: '拆封状态',
      dataIndex: 'item_condition',
      width: 90,
      render: (v: string) => (
        <Tag color={v === 'sealed' ? 'green' : 'orange'}>{CONDITION_LABELS[v] ?? v}</Tag>
      ),
    },
    {
      title: '状态',
      key: 'state',
      width: 150,
      render: (_, r) => (
        <Space size={4}>
          <DocStatusTag state={r.state} />
          {r.accept_state !== 'draft' && <DocStatusTag state={r.accept_state} />}
        </Space>
      ),
    },
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

  const detailItemsColumns: ColumnsType<ReturnLine> = [
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
        {detail.accept_state === 'draft' && (
          <Button onClick={() => setDrawer({ mode: 'edit', id: detail.id })}>编辑</Button>
        )}
        {detail.state === 'pending' && isAdmin && (
          <>
            <Popconfirm
              title="确认验收通过？"
              description="验收后物品退回接收仓库并写入库存流水"
              onConfirm={() => acceptMut.mutate(detail.id)}
            >
              <Button type="primary" loading={acceptMut.isPending}>
                验收通过
              </Button>
            </Popconfirm>
            <Popconfirm
              title="确认拒收？"
              description="拒收不影响库存，单据标记为已拒收"
              onConfirm={() => rejectMut.mutate(detail.id)}
            >
              <Button danger loading={rejectMut.isPending}>
                拒收
              </Button>
            </Popconfirm>
          </>
        )}
        {detail.accept_state === 'posted' && isAdmin && (
          <Popconfirm
            title="确认作废？"
            description="作废将冲销本次退库已入库的库存，操作留痕"
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
      title="退库单"
      description="校区物品退回总校办仓库：未拆封可验收，已拆封按制度第十五条拒收"
      extra={
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
          新建退库单
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
            options={['pending', 'accepted', 'rejected'].map((s) => ({ value: s, label: DOC_STATE_LABELS[s] }))}
          />
          <Select
            allowClear
            style={{ width: 120 }}
            placeholder="拆封状态"
            value={conditionFilter}
            onChange={(v) => {
              setConditionFilter(v);
              reset();
            }}
            options={[
              { value: 'sealed', label: '未拆封' },
              { value: 'opened', label: '已拆封' },
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
        <Table<ReturnOrder>
          rowKey="id"
          columns={columns}
          dataSource={data?.list ?? []}
          loading={isFetching}
          size="middle"
          pagination={makeTablePagination(data?.meta.total ?? 0)}
          scroll={{ x: 1140 }}
        />
      </Card>

      <Drawer
        title={
          drawer?.mode === 'create'
            ? '新建退库单'
            : drawer?.mode === 'edit'
              ? `编辑退库单 ${detail?.doc_no ?? ''}`
              : `退库单 ${detail?.doc_no ?? ''}`
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
                  {
                    key: 'state',
                    label: '验收状态',
                    children: <DocStatusTag state={detail.state} />,
                  },
                  {
                    key: 'accept_state',
                    label: '单据状态',
                    children: <DocStatusTag state={detail.accept_state} />,
                  },
                  { key: 'from', label: '退回校区', children: detail.from_location_name ?? '—' },
                  { key: 'to', label: '接收仓库', children: detail.to_location_name ?? '—' },
                  {
                    key: 'condition',
                    label: '拆封状态',
                    children: (
                      <Tag color={detail.item_condition === 'sealed' ? 'green' : 'orange'}>
                        {CONDITION_LABELS[detail.item_condition]}
                      </Tag>
                    ),
                  },
                  { key: 'order_date', label: '业务日期', children: fmtDate(detail.order_date) },
                  { key: 'posted_at', label: '过账时间', children: fmtDateTime(detail.posted_at) },
                  { key: 'remark', label: '备注', children: detail.remark || '—', span: 2 },
                  { key: 'created_at', label: '创建时间', children: fmtDateTime(detail.created_at) },
                ]}
              />
              <Table<ReturnLine>
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
              name="from_location_id"
              label="退回校区"
              rules={[{ required: true, message: '请选择退回校区' }]}
            >
              <Select disabled={isTeacher} options={locationOptions} placeholder="选择退回校区" showSearch optionFilterProp="label" />
            </Form.Item>
            <Form.Item
              name="to_location_id"
              label="接收仓库"
              rules={[{ required: true, message: '请选择接收仓库' }]}
            >
              <Select disabled={isTeacher} options={locationOptions} placeholder="选择接收仓库" showSearch optionFilterProp="label" />
            </Form.Item>
            <Form.Item
              name="item_condition"
              label="物品拆封状态"
              rules={[{ required: true, message: '请选择拆封状态' }]}
            >
              <Radio.Group
                options={[
                  { value: 'sealed', label: '未拆封' },
                  { value: 'opened', label: '已拆封' },
                ]}
              />
            </Form.Item>
            {itemCondition === 'opened' && (
              <Alert
                type="warning"
                showIcon
                style={{ marginBottom: 16 }}
                message="按《仓库管理制度》第十五条，已拆封物品不得退库，提交后将被拒绝验收"
              />
            )}
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
