import { useState } from 'react';
import {
  Button,
  Card,
  DatePicker,
  Form,
  Input,
  Modal,
  Select,
  Space,
  Table,
  message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import dayjs, { type Dayjs } from 'dayjs';
import { useNavigate } from 'react-router-dom';
import { PlusOutlined } from '@ant-design/icons';
import * as docsApi from '@/api/docs';
import type { Stocktake } from '@/api/types';
import * as categoriesApi from '@/api/categories';
import PageContainer from '@/components/PageContainer';
import DocStatusTag from '@/components/DocStatusTag';
import { usePagination } from '@/hooks/usePagination';
import { fmtDate, fmtDateTime } from '@/utils/format';

const { RangePicker } = DatePicker;

interface CreateForm {
  location_id: number;
  category_id?: number | null;
  stocktake_date?: Dayjs;
  remark?: string;
}

/** 盘点单列表：筛选 + 新建（创建成功后直接进执行页） */
export default function Stocktakes() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { page, pageSize, makeTablePagination, reset } = usePagination(20);
  const [state, setState] = useState<string | undefined>();
  const [locationId, setLocationId] = useState<number | undefined>();
  const [categoryId, setCategoryId] = useState<number | undefined>();
  const [range, setRange] = useState<[Dayjs | null, Dayjs | null] | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [form] = Form.useForm<CreateForm>();

  const { data: locations } = useQuery({
    queryKey: ['locations'],
    queryFn: () => categoriesApi.listLocations(),
  });
  const { data: categories } = useQuery({
    queryKey: ['categories'],
    queryFn: () => categoriesApi.listCategories(),
  });

  const { data, isFetching } = useQuery({
    queryKey: [
      'stocktakes',
      page,
      pageSize,
      state,
      locationId,
      categoryId,
      range?.[0]?.valueOf(),
      range?.[1]?.valueOf(),
    ],
    queryFn: () =>
      docsApi.listStocktakes({
        page,
        page_size: pageSize,
        state,
        location_id: locationId,
        category_id: categoryId,
        start: range?.[0] ? range[0].format('YYYY-MM-DD') : undefined,
        end: range?.[1] ? range[1].format('YYYY-MM-DD') : undefined,
      }),
  });

  const createMutation = useMutation({
    mutationFn: (payload: docsApi.StocktakeCreatePayload) => docsApi.createStocktake(payload),
    onSuccess: (detail) => {
      message.success(`盘点单 ${detail.doc_no} 已创建`);
      queryClient.invalidateQueries({ queryKey: ['stocktakes'] });
      setModalOpen(false);
      form.resetFields();
      navigate(`/stocktakes/${detail.id}`);
    },
    onError: () => {
      // 后端中文错误已由拦截器弹出
    },
  });

  const locationOptions = (locations ?? []).map((l) => ({ value: l.id, label: l.name }));
  const categoryOptions = (categories ?? []).map((c) => ({ value: c.id, label: c.name }));

  const submitCreate = async () => {
    const values = await form.validateFields();
    createMutation.mutate({
      location_id: values.location_id,
      category_id: values.category_id ?? null,
      stocktake_date: values.stocktake_date ? values.stocktake_date.format('YYYY-MM-DD') : undefined,
      remark: values.remark?.trim() || undefined,
    });
  };

  const columns: ColumnsType<Stocktake> = [
    {
      title: '单号',
      dataIndex: 'doc_no',
      width: 170,
      render: (v: string) => <span style={{ fontFamily: 'monospace' }}>{v}</span>,
    },
    { title: '库位', dataIndex: 'location_name', width: 140, render: (v: string | null) => v ?? '—' },
    {
      title: '状态',
      dataIndex: 'state',
      width: 100,
      render: (v: string) => <DocStatusTag state={v} />,
    },
    {
      title: '盘点日期',
      dataIndex: 'stocktake_date',
      width: 110,
      render: (v: string) => fmtDate(v),
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      width: 140,
      render: (v: string) => fmtDateTime(v),
    },
    {
      title: '备注',
      dataIndex: 'remark',
      ellipsis: true,
      render: (v: string) => v || '—',
    },
    {
      title: '操作',
      key: 'action',
      width: 110,
      fixed: 'right',
      render: (_, r) => (
        <Button type="link" size="small" onClick={() => navigate(`/stocktakes/${r.id}`)}>
          进入盘点
        </Button>
      ),
    },
  ];

  return (
    <PageContainer
      title="盘点单"
      description="按库位/类目生成盘点任务，扫码录入实盘数，完成后过账校正库存"
      extra={
        <Button
          type="primary"
          icon={<PlusOutlined />}
          onClick={() => {
            form.resetFields();
            form.setFieldsValue({ stocktake_date: dayjs() });
            setModalOpen(true);
          }}
        >
          新建盘点单
        </Button>
      }
    >
      <Card size="small" style={{ marginBottom: 12 }}>
        <Space wrap>
          <Select
            allowClear
            style={{ width: 130 }}
            placeholder="状态"
            value={state}
            onChange={(v) => {
              setState(v);
              reset();
            }}
            options={[
              { value: 'draft', label: '草稿' },
              { value: 'counting', label: '盘点中' },
              { value: 'done', label: '已完成' },
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
          <Select
            allowClear
            style={{ width: 150 }}
            placeholder="类目（全类目可不选）"
            value={categoryId}
            onChange={(v) => {
              setCategoryId(v);
              reset();
            }}
            options={categoryOptions}
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
        <Table<Stocktake>
          rowKey="id"
          columns={columns}
          dataSource={data?.list ?? []}
          loading={isFetching}
          size="middle"
          pagination={makeTablePagination(data?.meta.total ?? 0)}
          scroll={{ x: 860 }}
        />
      </Card>

      <Modal
        title="新建盘点单"
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        onOk={() => void submitCreate()}
        confirmLoading={createMutation.isPending}
        okText="创建并进入盘点"
        cancelText="取消"
        destroyOnClose
      >
        <Form form={form} layout="vertical" requiredMark={false} preserve={false}>
          <Form.Item name="location_id" label="盘点库位" rules={[{ required: true, message: '请选择盘点库位' }]}>
            <Select
              size="large"
              placeholder="选择要盘点的库位"
              options={locationOptions}
              showSearch
              optionFilterProp="label"
            />
          </Form.Item>
          <Form.Item
            name="category_id"
            label="类目（留空 = 全类目盘点）"
          >
            <Select
              size="large"
              allowClear
              placeholder="留空盘点该库位全部物品"
              options={categoryOptions}
            />
          </Form.Item>
          <Form.Item name="stocktake_date" label="盘点日期">
            <DatePicker size="large" style={{ width: '100%' }} placeholder="默认今天" />
          </Form.Item>
          <Form.Item name="remark" label="备注">
            <Input.TextArea rows={2} maxLength={200} placeholder="可填写盘点说明（选填）" />
          </Form.Item>
        </Form>
      </Modal>
    </PageContainer>
  );
}
