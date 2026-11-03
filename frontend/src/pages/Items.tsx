import { useMemo, useState } from 'react';
import {
  Button,
  Card,
  Checkbox,
  Col,
  Image,
  Input,
  List,
  Modal,
  Pagination,
  Popconfirm,
  Row,
  Select,
  Space,
  Table,
  Tag,
  Typography,
  message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { DeleteOutlined, PlusOutlined, PrinterOutlined, SearchOutlined } from '@ant-design/icons';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import * as itemsApi from '@/api/items';
import * as categoriesApi from '@/api/categories';
import type { Item } from '@/api/types';
import PageContainer from '@/components/PageContainer';
import BarcodePreview from '@/components/BarcodePreview';
import { useAuthStore } from '@/stores/authStore';
import { useIsMobile } from '@/hooks/useIsMobile';
import { usePagination } from '@/hooks/usePagination';
import { ITEM_STATUS_LABELS, fmtMoney, fmtQty } from '@/utils/format';

/**
 * 物品档案：筛选 + 表格（窄屏自动转卡片列表）+ 批量打印标签。
 */
export default function Items() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const isMobile = useIsMobile();
  const { page, pageSize, setPage, setPageSize, makeTablePagination, reset } = usePagination(20);
  const isAdmin = useAuthStore((s) => s.user?.role === 'admin');
  const [filters, setFilters] = useState<{
    q?: string;
    category_id?: number;
    status?: string;
    need_label?: string;
    print_mode?: string;
    has_photo?: string;
  }>({});
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [previewCode, setPreviewCode] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<number | null>(null);

  /** 软删（仅管理员）：状态置为已停用，有库存/流水时后端返回 409 并提示 */
  const onDelete = async (r: Item) => {
    setDeletingId(r.id);
    try {
      await itemsApi.deleteItem(r.id);
      message.success(`已删除「${r.name}」（状态变为已停用，可用状态筛选查看）`);
      setSelectedIds((prev) => prev.filter((id) => id !== r.id));
      queryClient.invalidateQueries({ queryKey: ['items'] });
    } catch {
      // 拦截器已统一弹出中文错误（如：仍有库存/流水不能删除）
    } finally {
      setDeletingId(null);
    }
  };

  const { data: categories } = useQuery({
    queryKey: ['categories'],
    queryFn: () => categoriesApi.listCategories(),
  });

  const { data, isFetching } = useQuery({
    queryKey: ['items', page, pageSize, filters],
    queryFn: () =>
      itemsApi.listItems({
        page,
        page_size: pageSize,
        q: filters.q || undefined,
        category_id: filters.category_id,
        status: filters.status,
        need_label: filters.need_label === undefined || filters.need_label === '' ? undefined : filters.need_label === 'true',
        print_mode: filters.print_mode || undefined,
        has_photo: filters.has_photo === undefined || filters.has_photo === '' ? undefined : filters.has_photo === 'true',
      }),
  });

  const list = data?.list ?? [];
  const total = data?.meta.total ?? 0;

  const columns = useMemo<ColumnsType<Item>>(
    () => [
      {
        title: '条码',
        dataIndex: 'barcode',
        width: 130,
        render: (v: string | null) =>
          v ? (
            <Typography.Link onClick={() => setPreviewCode(v)} style={{ fontFamily: 'monospace' }}>
              {v}
            </Typography.Link>
          ) : (
            <Tag color="orange">待编码</Tag>
          ),
      },
      {
        title: '照片',
        dataIndex: 'primary_photo_url',
        width: 64,
        render: (v: string | null | undefined, r) =>
          v ? (
            <Image src={v} width={44} height={44} style={{ objectFit: 'cover', borderRadius: 4 }} alt={r.name} />
          ) : (
            <div style={{ width: 44, height: 44, background: '#F6F3EC', borderRadius: 4 }} />
          ),
      },
      { title: '名称', dataIndex: 'name', ellipsis: true },
      { title: '类目', dataIndex: 'category_name', width: 70 },
      { title: '规格', dataIndex: 'spec', width: 110, ellipsis: true, render: (v: string) => v || '—' },
      {
        title: '建议售价',
        dataIndex: 'suggest_price',
        width: 90,
        align: 'right',
        render: (v: number | null) => fmtMoney(v),
      },
      {
        title: '贴码',
        dataIndex: 'need_label',
        width: 60,
        render: (v: boolean) => (v ? <Tag color="blue">是</Tag> : <Tag>否</Tag>),
      },
      {
        title: '总库存',
        dataIndex: 'total_qty',
        width: 80,
        align: 'right',
        render: (v: number | undefined) => fmtQty(v ?? 0),
      },
      {
        title: '状态',
        dataIndex: 'status',
        width: 70,
        render: (v: string) => (
          <Tag color={v === 'active' ? 'green' : v === 'merged' ? 'orange' : 'default'}>
            {ITEM_STATUS_LABELS[v] ?? v}
          </Tag>
        ),
      },
      {
        title: '操作',
        key: 'actions',
        width: 240,
        render: (_, r) => (
          <Space size={4}>
            <Button type="link" size="small" onClick={() => navigate(`/items/${r.id}`)}>
              详情
            </Button>
            <Button type="link" size="small" onClick={() => navigate(`/items/${r.id}?edit=1`)}>
              编辑
            </Button>
            {r.barcode && (
              <Button
                type="link"
                size="small"
                icon={<PrinterOutlined />}
                onClick={() => navigate(`/labels?item_ids=${r.id}`)}
              >
                打印
              </Button>
            )}
            {isAdmin && r.status === 'active' && (
              <Popconfirm
                title={`删除物品「${r.name}」？`}
                description="软删除：状态变为「已停用」，可用状态筛选找回；有库存或流水的物品无法删除。"
                okText="删除"
                okButtonProps={{ danger: true }}
                cancelText="取消"
                onConfirm={() => onDelete(r)}
              >
                <Button
                  type="link"
                  size="small"
                  danger
                  icon={<DeleteOutlined />}
                  loading={deletingId === r.id}
                >
                  删除
                </Button>
              </Popconfirm>
            )}
          </Space>
        ),
      },
    ],
    [navigate, isAdmin, deletingId],
  );

  const updateFilter = (patch: Partial<typeof filters>) => {
    setFilters((f) => ({ ...f, ...patch }));
    reset();
  };

  return (
    <PageContainer
      title="物品档案"
      extra={
        <Space>
          {selectedIds.length > 0 && (
            <Button
              icon={<PrinterOutlined />}
              onClick={() => navigate(`/labels?item_ids=${selectedIds.join(',')}`)}
            >
              批量打印（{selectedIds.length}）
            </Button>
          )}
          <Button type="primary" icon={<PlusOutlined />} onClick={() => navigate('/items/new')}>
            新建物品
          </Button>
        </Space>
      }
    >
      {/* 筛选区 */}
      <Card size="small" style={{ marginBottom: 12 }}>
        <Row gutter={[8, 8]}>
          <Col xs={24} sm={12} md={6}>
            <Input
              allowClear
              prefix={<SearchOutlined />}
              placeholder="搜索名称 / 条码"
              onChange={(e) => updateFilter({ q: e.target.value })}
              aria-label="关键词搜索"
            />
          </Col>
          <Col xs={12} sm={6} md={3}>
            <Select
              allowClear
              style={{ width: '100%' }}
              placeholder="类目"
              options={(categories ?? []).map((c) => ({ value: c.id, label: c.name }))}
              onChange={(v) => updateFilter({ category_id: v })}
            />
          </Col>
          <Col xs={12} sm={6} md={3}>
            <Select
              allowClear
              style={{ width: '100%' }}
              placeholder="状态"
              options={[
                { value: 'active', label: '在用' },
                { value: 'merged', label: '已合并' },
                { value: 'retired', label: '已停用' },
              ]}
              onChange={(v) => updateFilter({ status: v })}
            />
          </Col>
          <Col xs={12} sm={6} md={3}>
            <Select
              allowClear
              style={{ width: '100%' }}
              placeholder="是否贴码"
              options={[
                { value: 'true', label: '贴码' },
                { value: 'false', label: '不贴码' },
              ]}
              onChange={(v) => updateFilter({ need_label: v })}
            />
          </Col>
          <Col xs={12} sm={6} md={3}>
            <Select
              allowClear
              style={{ width: '100%' }}
              placeholder="印刷方式"
              options={[
                { value: 'label', label: '贴标' },
                { value: 'scan_card', label: '扫码卡' },
              ]}
              onChange={(v) => updateFilter({ print_mode: v })}
            />
          </Col>
          <Col xs={12} sm={6} md={3}>
            <Select
              allowClear
              style={{ width: '100%' }}
              placeholder="有无照片"
              options={[
                { value: 'true', label: '有照片' },
                { value: 'false', label: '无照片' },
              ]}
              onChange={(v) => updateFilter({ has_photo: v })}
            />
          </Col>
        </Row>
      </Card>

      {/* 桌面：表格；移动：卡片列表 */}
      {isMobile ? (
        <Card size="small" styles={{ body: { padding: 8 } }}>
          {selectedIds.length > 0 && (
            <div style={{ padding: '4px 8px', fontSize: 13, color: '#55504A' }}>
              已选 {selectedIds.length} 项
            </div>
          )}
          <List
            loading={isFetching}
            dataSource={list}
            locale={{ emptyText: '没有符合条件的物品' }}
            renderItem={(r) => (
              <List.Item
                style={{ padding: '10px 4px' }}
                actions={[
                  <Button key="d" type="link" size="small" onClick={() => navigate(`/items/${r.id}`)}>
                    详情
                  </Button>,
                ]}
              >
                <List.Item.Meta
                  avatar={
                    <Checkbox
                      checked={selectedIds.includes(r.id)}
                      onChange={(e) =>
                        setSelectedIds((prev) =>
                          e.target.checked ? [...prev, r.id] : prev.filter((id) => id !== r.id),
                        )
                      }
                      aria-label={`选择 ${r.name}`}
                    />
                  }
                  title={
                    <Space size={6} wrap>
                      <span>{r.name}</span>
                      {r.status !== 'active' && <Tag>{ITEM_STATUS_LABELS[r.status]}</Tag>}
                    </Space>
                  }
                  description={
                    <Space direction="vertical" size={2}>
                      <Space size={6} wrap>
                        {r.barcode ? (
                          <Typography.Link
                            style={{ fontFamily: 'monospace' }}
                            onClick={() => setPreviewCode(r.barcode!)}
                          >
                            {r.barcode}
                          </Typography.Link>
                        ) : (
                          <Tag color="orange">待编码</Tag>
                        )}
                        <Tag>{r.category_name}</Tag>
                        <span>{fmtMoney(r.suggest_price)}</span>
                        <span>库存 {fmtQty(r.total_qty ?? 0)}</span>
                      </Space>
                      {r.primary_photo_url && (
                        <Image
                          src={r.primary_photo_url}
                          width={56}
                          height={56}
                          style={{ objectFit: 'cover', borderRadius: 4 }}
                          alt={r.name}
                        />
                      )}
                    </Space>
                  }
                />
              </List.Item>
            )}
          />
          <div style={{ padding: '12px 8px', textAlign: 'center' }}>
            <Pagination
              current={page}
              pageSize={pageSize}
              total={total}
              size="small"
              showSizeChanger
              showTotal={(t) => `共 ${t} 条`}
              onChange={(p, ps) => {
                setPage(p);
                setPageSize(ps);
              }}
            />
          </div>
        </Card>
      ) : (
        <Card size="small" styles={{ body: { padding: 0 } }}>
          <Table<Item>
            rowKey="id"
            columns={columns}
            dataSource={list}
            loading={isFetching}
            size="middle"
            rowSelection={{
              selectedRowKeys: selectedIds,
              onChange: (keys) => setSelectedIds(keys as number[]),
              getCheckboxProps: (r) => ({ disabled: !r.barcode }),
            }}
            pagination={makeTablePagination(total)}
            scroll={{ x: 900 }}
          />
        </Card>
      )}

      {/* 条码大图预览 */}
      <Modal
        open={!!previewCode}
        title="条码预览"
        footer={null}
        onCancel={() => setPreviewCode(null)}
        width={360}
      >
        {previewCode && (
          <div style={{ textAlign: 'center' }}>
            <BarcodePreview code={previewCode} width={300} height={90} />
          </div>
        )}
      </Modal>
    </PageContainer>
  );
}
