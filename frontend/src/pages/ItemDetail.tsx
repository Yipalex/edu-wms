import { useEffect, useState } from 'react';
import {
  Button,
  Card,
  Col,
  Descriptions,
  Form,
  Input,
  InputNumber,
  Popconfirm,
  Row,
  Select,
  Space,
  Spin,
  Switch,
  Table,
  Tag,
  Timeline,
  Typography,
  message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { ArrowLeftOutlined, DeleteOutlined, PrinterOutlined, SaveOutlined, ThunderboltOutlined } from '@ant-design/icons';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import * as itemsApi from '@/api/items';
import * as categoriesApi from '@/api/categories';
import type { InventoryRow, ItemCreatePayload, StockMovement } from '@/api/types';
import PageContainer from '@/components/PageContainer';
import ItemPhotoWall from '@/components/ItemPhotoWall';
import BarcodePreview from '@/components/BarcodePreview';
import PurgeItemModal from '@/components/PurgeItemModal';
import { useAuthStore } from '@/stores/authStore';
import {
  CHANGE_TYPE_LABELS,
  DOC_TYPE_LABELS,
  fmtChangeQty,
  fmtDateTime,
  fmtMoney,
  fmtQty,
} from '@/utils/format';

/**
 * 物品详情 / 新建 / 编辑（/items/new 与 /items/:id 共用）。
 * 档案表单 + 照片墙 + 各库位库存 + 条码变更历史时间线 + 别名 + 最近流水。
 */
export default function ItemDetail() {
  const { id } = useParams();
  const isNew = !id;
  const itemId = id ? Number(id) : null;
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const queryClient = useQueryClient();
  const [form] = Form.useForm();
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [editing, setEditing] = useState(searchParams.get('edit') === '1');
  const isAdmin = useAuthStore((s) => s.user?.role === 'admin' || s.user?.role === 'superadmin');
  const isSuperAdmin = useAuthStore((s) => s.user?.role === 'superadmin');
  const [purgeOpen, setPurgeOpen] = useState(false);

  const { data: categories } = useQuery({
    queryKey: ['categories'],
    queryFn: () => categoriesApi.listCategories(),
  });

  const { data: detail, isLoading } = useQuery({
    queryKey: ['item', itemId],
    queryFn: () => itemsApi.getItem(itemId!),
    enabled: !isNew && !!itemId,
  });

  useEffect(() => {
    if (detail) {
      form.setFieldsValue({
        name: detail.name,
        category_id: detail.category_id,
        barcode: detail.barcode ?? '',
        spec: detail.spec,
        suggest_price: detail.suggest_price,
        unit: detail.unit,
        need_label: detail.need_label,
        print_mode: detail.print_mode,
        remark: detail.remark,
      });
    }
  }, [detail, form]);

  const invColumns: ColumnsType<InventoryRow> = [
    { title: '库位', dataIndex: 'location_name', ellipsis: true },
    {
      title: '在手',
      dataIndex: 'qty_on_hand',
      align: 'right',
      render: (v: number, r) => {
        const low = r.safety_stock > 0 && v < r.safety_stock;
        return <span style={low ? { color: '#B03A2A', fontWeight: 600 } : undefined}>{fmtQty(v)}</span>;
      },
    },
    { title: '待领取', dataIndex: 'qty_reserved', align: 'right', render: (v: number) => fmtQty(v) },
    { title: '安全库存', dataIndex: 'safety_stock', align: 'right', render: (v: number) => fmtQty(v) },
  ];

  const mvColumns: ColumnsType<StockMovement> = [
    { title: '时间', dataIndex: 'created_at', width: 140, render: (v: string) => fmtDateTime(v) },
    { title: '库位', dataIndex: 'location_name', width: 100 },
    {
      title: '类型',
      dataIndex: 'doc_type',
      width: 70,
      render: (v: string) => <Tag>{DOC_TYPE_LABELS[v] ?? v}</Tag>,
    },
    {
      title: '变动',
      dataIndex: 'change_qty',
      width: 80,
      align: 'right',
      render: (v: number) => (
        <span style={{ color: v >= 0 ? '#3E7C4F' : '#B03A2A', fontWeight: 600 }}>{fmtChangeQty(v)}</span>
      ),
    },
    { title: '单据号', dataIndex: 'doc_no', ellipsis: true, render: (v: string | null) => v ?? '—' },
  ];

  /** 软删（仅管理员）：状态置为已停用；有库存/流水时后端 409 并提示 */
  const onDelete = async () => {
    if (!itemId) return;
    setDeleting(true);
    try {
      await itemsApi.deleteItem(itemId);
      message.success('已删除该物品（状态变为已停用，可在物品档案按状态筛选查看）');
      queryClient.invalidateQueries({ queryKey: ['items'] });
      navigate('/items', { replace: true });
    } catch {
      // 拦截器已统一弹出中文错误
    } finally {
      setDeleting(false);
    }
  };

  const submit = async () => {
    const values = await form.validateFields();
    const payload: ItemCreatePayload = {
      name: String(values.name).trim(),
      category_id: values.category_id,
      barcode: values.barcode ? String(values.barcode).trim() : null,
      spec: values.spec ?? '',
      suggest_price: values.suggest_price ?? null,
      unit: values.unit ?? '件',
      need_label: !!values.need_label,
      print_mode: values.print_mode ?? 'label',
      remark: values.remark ?? '',
    };
    if (payload.barcode && !/^[0-9]{8,14}$/.test(payload.barcode)) {
      message.error('条码必须是 8~14 位纯数字');
      return;
    }
    setSaving(true);
    try {
      if (isNew) {
        const created = await itemsApi.createItem(payload);
        message.success('物品已创建');
        queryClient.invalidateQueries({ queryKey: ['items'] });
        navigate(`/items/${created.id}`, { replace: true });
      } else {
        await itemsApi.updateItem(itemId!, payload);
        message.success('已保存');
        setEditing(false);
        queryClient.invalidateQueries({ queryKey: ['item', itemId] });
        queryClient.invalidateQueries({ queryKey: ['items'] });
      }
    } catch {
      // 拦截器已提示中文错误
    } finally {
      setSaving(false);
    }
  };

  if (!isNew && isLoading) {
    return (
      <div style={{ textAlign: 'center', padding: 80 }}>
        <Spin size="large" />
      </div>
    );
  }

  const formDisabled = !isNew && !editing;

  return (
    <PageContainer
      title={isNew ? '新建物品' : `物品档案${editing ? '（编辑中）' : ''}`}
      extra={
        <Space wrap>
          <Button icon={<ArrowLeftOutlined />} onClick={() => navigate(-1)}>
            返回
          </Button>
          {!isNew && detail?.barcode && (
            <Button
              icon={<PrinterOutlined />}
              onClick={() => navigate(`/labels?item_ids=${detail.id}`)}
            >
              打印标签
            </Button>
          )}
          {!isNew && !editing ? (
            <Button type="primary" onClick={() => setEditing(true)}>
              编辑档案
            </Button>
          ) : (
            <Button type="primary" icon={<SaveOutlined />} loading={saving} onClick={submit}>
              {isNew ? '创建' : '保存'}
            </Button>
          )}
          {isAdmin && !isNew && detail?.status === 'active' && (
            <Popconfirm
              title={`删除物品「${detail.name}」？`}
              description="软删除：状态变为「已停用」，可用状态筛选找回；有库存或流水的物品无法删除。"
              okText="删除"
              okButtonProps={{ danger: true }}
              cancelText="取消"
              onConfirm={onDelete}
            >
              <Button danger icon={<DeleteOutlined />} loading={deleting}>
                删除档案
              </Button>
            </Popconfirm>
          )}
          {isSuperAdmin && !isNew && detail && detail.status !== 'merged' && (
            <Button danger icon={<ThunderboltOutlined />} onClick={() => setPurgeOpen(true)}>
              彻底删除
            </Button>
          )}
        </Space>
      }
    >
      <Row gutter={[12, 12]}>
        <Col xs={24} lg={14}>
          <Card size="small" title="基本信息">
            <Form
              form={form}
              layout="vertical"
              disabled={formDisabled}
              initialValues={{ unit: '件', need_label: true, print_mode: 'label' }}
            >
              <Row gutter={12}>
                <Col xs={24} sm={12}>
                  <Form.Item
                    name="name"
                    label="物品名称"
                    rules={[{ required: true, message: '请输入物品名称' }]}
                  >
                    <Input placeholder="如：米字格练字本" maxLength={200} />
                  </Form.Item>
                </Col>
                <Col xs={24} sm={12}>
                  <Form.Item
                    name="category_id"
                    label="类目"
                    rules={[{ required: true, message: '请选择类目' }]}
                  >
                    <Select
                      placeholder="选择类目"
                      options={(categories ?? []).map((c) => ({ value: c.id, label: c.name }))}
                    />
                  </Form.Item>
                </Col>
                <Col xs={24} sm={12}>
                  <Form.Item
                    name="barcode"
                    label="条码（留空 = 待编码）"
                    rules={[{ pattern: /^[0-9]{8,14}$/, message: '条码必须是 8~14 位纯数字' }]}
                  >
                    <Input placeholder="8~14 位纯数字，留空稍后分配" maxLength={14} />
                  </Form.Item>
                </Col>
                <Col xs={12} sm={6}>
                  <Form.Item name="spec" label="规格">
                    <Input placeholder="如 500ml" maxLength={100} />
                  </Form.Item>
                </Col>
                <Col xs={12} sm={6}>
                  <Form.Item name="suggest_price" label="建议售价（元）">
                    <InputNumber style={{ width: '100%' }} min={0} step={0.1} precision={2} placeholder="0.00" />
                  </Form.Item>
                </Col>
                <Col xs={12} sm={6}>
                  <Form.Item name="unit" label="单位">
                    <Input maxLength={20} />
                  </Form.Item>
                </Col>
                <Col xs={12} sm={6}>
                  <Form.Item name="need_label" label="是否贴码" valuePropName="checked">
                    <Switch checkedChildren="贴码" unCheckedChildren="不贴" />
                  </Form.Item>
                </Col>
                <Col xs={12} sm={6}>
                  <Form.Item name="print_mode" label="印刷方式">
                    <Select
                      options={[
                        { value: 'label', label: '贴标' },
                        { value: 'scan_card', label: '扫码卡' },
                      ]}
                    />
                  </Form.Item>
                </Col>
                <Col xs={24}>
                  <Form.Item name="remark" label="备注">
                    <Input.TextArea rows={2} maxLength={500} showCount placeholder="选填" />
                  </Form.Item>
                </Col>
              </Row>
            </Form>
            {!isNew && detail?.barcode && !editing && (
              <div style={{ textAlign: 'center', padding: '8px 0' }}>
                <BarcodePreview code={detail.barcode} width={280} height={70} />
              </div>
            )}
          </Card>

          {!isNew && (
            <Card size="small" title="各库位库存" style={{ marginTop: 12 }}>
              <Table<InventoryRow>
                rowKey="location_id"
                columns={invColumns}
                dataSource={detail?.inventory ?? []}
                size="small"
                pagination={false}
                scroll={{ x: 480 }}
              />
            </Card>
          )}

          {!isNew && (
            <Card size="small" title="最近库存流水" style={{ marginTop: 12 }}>
              <Table<StockMovement>
                rowKey="id"
                columns={mvColumns}
                dataSource={detail?.recent_movements ?? []}
                size="small"
                pagination={false}
                scroll={{ x: 560 }}
                locale={{ emptyText: '暂无流水' }}
              />
            </Card>
          )}
        </Col>

        <Col xs={24} lg={10}>
          {!isNew && (
            <Card size="small" title="物品照片">
              <ItemPhotoWall itemId={itemId!} photos={detail?.photos ?? []} />
            </Card>
          )}
          {isNew && (
            <Card size="small" title="物品照片">
              <Typography.Text type="secondary">
                创建物品后即可上传照片（支持手机拍照直传）。
              </Typography.Text>
            </Card>
          )}

          {!isNew && (
            <Card size="small" title="条码变更历史" style={{ marginTop: 12 }}>
              {detail?.barcode_history?.length ? (
                <Timeline
                  items={detail.barcode_history.map((h) => ({
                    children: (
                      <div style={{ fontSize: 13 }}>
                        <Tag color="blue">{CHANGE_TYPE_LABELS[h.change_type] ?? h.change_type}</Tag>
                        <span style={{ fontFamily: 'monospace' }}>
                          {h.old_barcode ?? '（无）'} → {h.new_barcode ?? '（停用）'}
                        </span>
                        <div>
                          <Typography.Text type="secondary">
                            {fmtDateTime(h.created_at)} · {h.operator_name ?? '系统'}
                            {h.reason ? ` · ${h.reason}` : ''}
                          </Typography.Text>
                        </div>
                      </div>
                    ),
                  }))}
                />
              ) : (
                <Typography.Text type="secondary">暂无条码变更记录</Typography.Text>
              )}
            </Card>
          )}

          {!isNew && (
            <Card size="small" title="别名（历史叫法）" style={{ marginTop: 12 }}>
              {detail?.aliases?.length ? (
                <Space wrap>
                  {detail.aliases.map((a) => (
                    <Tag key={a.id}>{a.alias}</Tag>
                  ))}
                </Space>
              ) : (
                <Typography.Text type="secondary">暂无别名</Typography.Text>
              )}
            </Card>
          )}

          {!isNew && detail && (
            <Card size="small" title="档案信息" style={{ marginTop: 12 }}>
              <Descriptions column={1} size="small">
                <Descriptions.Item label="状态">
                  <Tag color={detail.status === 'active' ? 'green' : 'orange'}>
                    {detail.status === 'active' ? '在用' : detail.status === 'merged' ? '已合并' : '已停用'}
                  </Tag>
                </Descriptions.Item>
                <Descriptions.Item label="条码来源">
                  {detail.barcode_origin === 'external' ? '商品原装码' : '本机构码'}
                </Descriptions.Item>
                <Descriptions.Item label="建议售价">{fmtMoney(detail.suggest_price)}</Descriptions.Item>
                <Descriptions.Item label="创建时间">{fmtDateTime(detail.created_at)}</Descriptions.Item>
              </Descriptions>
            </Card>
          )}
        </Col>
      </Row>

      {/* 彻底删除确认（仅超级管理员） */}
      <PurgeItemModal
        item={purgeOpen && detail ? detail : null}
        onClose={() => setPurgeOpen(false)}
        onDone={() => {
          setPurgeOpen(false);
          queryClient.invalidateQueries({ queryKey: ['items'] });
          navigate('/items', { replace: true });
        }}
      />
    </PageContainer>
  );
}
