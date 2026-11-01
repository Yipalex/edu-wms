import { useState } from 'react';
import {
  Alert,
  Button,
  Card,
  Checkbox,
  Col,
  Image,
  Modal,
  Row,
  Select,
  Space,
  Spin,
  Tag,
  Typography,
  message,
} from 'antd';
import { PrinterOutlined, TagsOutlined } from '@ant-design/icons';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import * as itemsApi from '@/api/items';
import * as categoriesApi from '@/api/categories';
import * as barcodeApi from '@/api/barcode';
import PageContainer from '@/components/PageContainer';
import EmptyHint from '@/components/EmptyHint';

/**
 * 待编码物品：barcode 为空的物品，多选 → 批量分配条码（选类目）→ 直接打印标签。
 * 现场盘点后统一补码的流程。
 */
export default function PendingCode() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [selected, setSelected] = useState<{ id: number; category_id: number }[]>([]);
  const [allocOpen, setAllocOpen] = useState(false);
  const [allocCategoryId, setAllocCategoryId] = useState<number | null>(null);
  const [allocating, setAllocating] = useState(false);
  const [allocatedCodes, setAllocatedCodes] = useState<{ item_id: number; barcode: string }[] | null>(null);

  const { data: categories } = useQuery({
    queryKey: ['categories'],
    queryFn: () => categoriesApi.listCategories(),
  });

  const { data, isLoading } = useQuery({
    queryKey: ['items', 'pending-code'],
    queryFn: () => itemsApi.listItems({ pending_code: true, page: 1, page_size: 200 }),
  });

  const list = data?.list ?? [];

  const toggle = (id: number, category_id: number, checked: boolean) => {
    setSelected((prev) =>
      checked ? [...prev, { id, category_id }] : prev.filter((s) => s.id !== id),
    );
  };

  const doAllocate = async () => {
    if (!selected.length) return;
    setAllocating(true);
    try {
      const res = await barcodeApi.allocateBarcode({
        item_ids: selected.map((s) => s.id),
        category_id: allocCategoryId ?? undefined,
      });
      setAllocatedCodes(res.allocated);
      queryClient.invalidateQueries({ queryKey: ['items'] });
      message.success(`已为 ${res.allocated.length} 个物品分配条码`);
    } catch {
      // 拦截器已提示
    } finally {
      setAllocating(false);
    }
  };

  if (isLoading) {
    return (
      <div style={{ textAlign: 'center', padding: 80 }}>
        <Spin size="large" />
      </div>
    );
  }

  return (
    <PageContainer
      title="待编码物品"
      description="现场登记时未填条码的物品，选中后批量分配条码，再统一打印标签"
      extra={
        <Space>
          <Button
            type="primary"
            icon={<TagsOutlined />}
            disabled={!selected.length}
            onClick={() => {
              setAllocatedCodes(null);
              setAllocCategoryId(null);
              setAllocOpen(true);
            }}
          >
            批量分配条码{selected.length ? `（${selected.length}）` : ''}
          </Button>
        </Space>
      }
    >
      {list.length === 0 ? (
        <Card>
          <EmptyHint description="没有待编码的物品，全部物品都已分配条码">
            <Button onClick={() => navigate('/items')}>去物品档案</Button>
          </EmptyHint>
        </Card>
      ) : (
        <Row gutter={[12, 12]}>
          {list.map((item) => {
            const checked = selected.some((s) => s.id === item.id);
            return (
              <Col xs={12} sm={8} md={6} key={item.id}>
                <Card
                  size="small"
                  hoverable
                  onClick={() => toggle(item.id, item.category_id, !checked)}
                  style={checked ? { borderColor: '#B03A2A', boxShadow: '0 0 0 2px rgba(176,58,42,.15)' } : undefined}
                >
                  <Space direction="vertical" style={{ width: '100%' }} size={8}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <Checkbox
                        checked={checked}
                        onChange={(e) => toggle(item.id, item.category_id, e.target.checked)}
                        onClick={(e) => e.stopPropagation()}
                        aria-label={`选择 ${item.name}`}
                      />
                      <Tag color="orange">待编码</Tag>
                    </div>
                    {item.primary_photo_url ? (
                      <Image
                        src={item.primary_photo_url}
                        height={96}
                        style={{ width: '100%', objectFit: 'cover', borderRadius: 6 }}
                        preview={false}
                        alt={item.name}
                      />
                    ) : (
                      <div
                        style={{
                          height: 96,
                          background: '#F6F3EC',
                          borderRadius: 6,
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                          color: '#ccc',
                        }}
                      >
                        暂无照片
                      </div>
                    )}
                    <Typography.Text strong ellipsis style={{ width: '100%' }}>
                      {item.name}
                    </Typography.Text>
                    <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                      {item.category_name}
                      {item.spec ? ` · ${item.spec}` : ''}
                    </Typography.Text>
                  </Space>
                </Card>
              </Col>
            );
          })}
        </Row>
      )}

      {/* 分配条码弹窗 */}
      <Modal
        open={allocOpen}
        title="批量分配条码"
        onCancel={() => setAllocOpen(false)}
        footer={
          allocatedCodes ? (
            <Space>
              <Button onClick={() => setAllocOpen(false)}>关闭</Button>
              <Button
                type="primary"
                icon={<PrinterOutlined />}
                onClick={() => {
                  setAllocOpen(false);
                  setSelected([]);
                  navigate(`/labels?item_ids=${allocatedCodes.map((a) => a.item_id).join(',')}`);
                }}
              >
                直接打印标签
              </Button>
            </Space>
          ) : (
            <Space>
              <Button onClick={() => setAllocOpen(false)}>取消</Button>
              <Button type="primary" loading={allocating} onClick={doAllocate}>
                确认分配
              </Button>
            </Space>
          )
        }
      >
        {allocatedCodes ? (
          <div>
            <Alert
              type="success"
              showIcon
              message={`分配完成，共 ${allocatedCodes.length} 个条码`}
              style={{ marginBottom: 12 }}
            />
            {allocatedCodes.map((a) => (
              <div key={a.item_id} style={{ fontFamily: 'monospace', padding: '2px 0' }}>
                {list.find((i) => i.id === a.item_id)?.name ?? `物品#${a.item_id}`} → {a.barcode}
              </div>
            ))}
          </div>
        ) : (
          <Space direction="vertical" style={{ width: '100%' }}>
            <Alert
              type="info"
              showIcon
              message={`将为 ${selected.length} 个待编码物品按其所属类目分配 8 位机构码（按分类流水递增，不影响已有条码）`}
            />
            <div>
              指定统一类目（可选，默认按各物品档案类目分配）：
              <Select
                allowClear
                style={{ width: '100%', marginTop: 8 }}
                placeholder="不指定则按物品自身类目"
                value={allocCategoryId ?? undefined}
                onChange={(v) => setAllocCategoryId(v ?? null)}
                options={(categories ?? []).map((c) => ({ value: c.id, label: c.name }))}
              />
            </div>
          </Space>
        )}
      </Modal>
    </PageContainer>
  );
}
