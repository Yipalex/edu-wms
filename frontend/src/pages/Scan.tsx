import { useCallback, useEffect, useRef, useState } from 'react';
import type { MouseEvent } from 'react';
import {
  Alert,
  Button,
  Card,
  Col,
  Descriptions,
  Drawer,
  Form,
  Image,
  Input,
  InputNumber,
  Result,
  Row,
  Select,
  Space,
  Spin,
  Tag,
  Timeline,
  Typography,
  Upload,
  message,
} from 'antd';
import {
  CameraOutlined,
  LoginOutlined,
  RollbackOutlined,
  ScanOutlined,
  SwapOutlined,
  PlusOutlined,
  InboxOutlined,
  ExportOutlined,
  AuditOutlined,
} from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import * as scanApi from '@/api/scan';
import * as categoriesApi from '@/api/categories';
import * as itemsApi from '@/api/items';
import type { ScanResolveResult } from '@/api/types';
import ScanInput from '@/components/ScanInput';
import StockTable from '@/components/StockTable';
import { useScanGun } from '@/hooks/useScanGun';
import { useCameraScan } from '@/hooks/useCameraScan';
import { useScanStore } from '@/stores/scanStore';
import { DOC_TYPE_LABELS, fmtChangeQty, fmtDateTime, fmtMoney } from '@/utils/format';

/**
 * 扫码工作台（移动优先，契约第 7 节）。
 * - 顶部大输入框自动聚焦（扫码枪直接打入）+ 打开摄像头按钮
 * - 解析结果卡片：照片大图/名称/条码/类目/规格/售价/各库位库存表/最近流水
 * - 未命中三分支：已合并→跳转；旧码停用→一键重查；未登记→登记新物品抽屉
 * - 底部固定操作栏：入库/出库/退库/盘点 四个大按钮（带物品上下文跳转）
 */
export default function Scan() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const inputRef = useRef<HTMLInputElement>(null);
  const [code, setCode] = useState('');
  const [result, setResult] = useState<ScanResolveResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [registerOpen, setRegisterOpen] = useState(false);
  const setLastResult = useScanStore((s) => s.setLastResult);
  const setScanPageActive = useScanStore((s) => s.setScanPageActive);

  useEffect(() => {
    setScanPageActive(true);
    // 进入页面自动聚焦大输入框，扫码枪可直接打入
    inputRef.current?.focus();
    return () => setScanPageActive(false);
  }, [setScanPageActive]);

  /** 点击页面任意非交互处 → 重新聚焦扫码框（契约第 7 节） */
  const onContainerClick = (e: MouseEvent<HTMLDivElement>) => {
    const target = e.target as HTMLElement;
    if (target.closest('input, textarea, button, a, .ant-select, .ant-modal, .ant-drawer')) return;
    inputRef.current?.focus();
  };

  const doResolve = useCallback(
    async (raw: string) => {
      const trimmed = raw.trim();
      if (!trimmed) return;
      setLoading(true);
      try {
        const res = await scanApi.scanResolve(trimmed);
        setResult(res);
        setLastResult(res);
      } catch {
        // 错误已由拦截器/message 提示
      } finally {
        setLoading(false);
        setCode('');
        // 重新聚焦，方便连续扫码
        setTimeout(() => inputRef.current?.focus(), 50);
      }
    },
    [setLastResult],
  );

  // 扫码枪常驻监听（在本页启用；输入框内打字时 hook 自动不抢）
  useScanGun({ onScan: (c) => void doResolve(c), enabled: !registerOpen });

  const cameraStopRef = useRef<() => Promise<void>>(async () => {
    /* 初始空实现，camera 挂载后覆盖 */
  });
  const camera = useCameraScan({
    onScan: (c) => {
      void cameraStopRef.current();
      void doResolve(c);
    },
  });
  cameraStopRef.current = camera.stop;

  const { data: categories } = useQuery({
    queryKey: ['categories'],
    queryFn: () => categoriesApi.listCategories(),
  });

  // 底部操作栏：带当前物品上下文跳转到对应单据新建页（本轮单据页为占位，先携带参数跳转）
  const goWithItem = (path: string) => {
    if (!result?.resolved || !result.item) {
      message.info('请先扫码选中一个物品');
      return;
    }
    navigate(`${path}?item_id=${result.item.id}&barcode=${result.item.barcode ?? ''}`);
  };

  const item = result?.resolved ? result.item : null;

  return (
    <div style={{ maxWidth: 720, margin: '0 auto', paddingBottom: 8 }} onClick={onContainerClick}>
      {/* 扫码输入区 */}
      <Card size="small" style={{ marginBottom: 12 }}>
        <Space direction="vertical" style={{ width: '100%' }} size={10}>
          <ScanInput
            ref={inputRef}
            value={code}
            onChange={setCode}
            onSubmit={(c) => void doResolve(c)}
            loading={loading}
            placeholder="扫码枪扫码，或手动输入条码后回车"
          />
          <Space wrap>
            {!camera.scanning ? (
              <Button
                icon={<CameraOutlined />}
                onClick={() =>
                  camera.start().catch((e: Error) => message.error(e.message))
                }
                disabled={!camera.secureOk}
                aria-label="打开摄像头扫码"
              >
                打开摄像头
              </Button>
            ) : (
              <Space>
                <Button danger onClick={() => void camera.stop()} aria-label="关闭摄像头">
                  关闭摄像头
                </Button>
                <Button icon={<SwapOutlined />} onClick={() => void camera.toggleFacing()} aria-label="切换前后摄像头">
                  翻转
                </Button>
              </Space>
            )}
            <Button
              icon={<PlusOutlined />}
              onClick={() => setRegisterOpen(true)}
              aria-label="登记新物品"
            >
              登记新物品
            </Button>
          </Space>
          {!camera.secureOk && camera.insecureHint && (
            <Alert type="warning" showIcon message={camera.insecureHint} />
          )}
          {camera.scanning && (
            <div
              id={camera.videoRegionId}
              style={{ width: '100%', minHeight: 220, background: '#000', borderRadius: 8, overflow: 'hidden' }}
            />
          )}
        </Space>
      </Card>

      {loading && (
        <div style={{ textAlign: 'center', padding: 32 }}>
          <Spin size="large" />
          <div style={{ marginTop: 12, color: '#8A847B' }}>解析条码中…</div>
        </div>
      )}

      {/* ===== 命中：物品卡片 ===== */}
      {!loading && item && result && (
        <Card
          size="small"
          title={
            <Space>
              <ScanOutlined style={{ color: '#3E7C4F' }} />
              <span>{item.name}</span>
              <Tag color="green">已找到</Tag>
            </Space>
          }
          style={{ marginBottom: 12 }}
        >
          <Row gutter={12}>
            <Col xs={24} sm={8}>
              {item.photo_url ? (
                <Image
                  src={item.photo_url}
                  alt={item.name}
                  style={{ width: '100%', maxHeight: 200, objectFit: 'contain', background: '#F6F3EC', borderRadius: 8 }}
                />
              ) : (
                <div
                  style={{
                    width: '100%',
                    height: 140,
                    background: '#F6F3EC',
                    borderRadius: 8,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    color: '#8A847B',
                  }}
                >
                  暂无照片
                </div>
              )}
            </Col>
            <Col xs={24} sm={16}>
              <Descriptions column={1} size="small">
                <Descriptions.Item label="条码">
                  <Typography.Text copyable code style={{ fontSize: 15 }}>
                    {item.barcode ?? '待编码'}
                  </Typography.Text>
                  {result.code_type === 'external' && <Tag style={{ marginInlineStart: 8 }}>外部码</Tag>}
                </Descriptions.Item>
                <Descriptions.Item label="类目">{item.category}</Descriptions.Item>
                {item.spec && <Descriptions.Item label="规格">{item.spec}</Descriptions.Item>}
                <Descriptions.Item label="建议售价">{fmtMoney(item.suggest_price)}</Descriptions.Item>
                <Descriptions.Item label="是否贴码">
                  {item.need_label ? <Tag color="blue">贴标</Tag> : <Tag>不贴码</Tag>}
                </Descriptions.Item>
                <Descriptions.Item label="总库存">
                  <Typography.Text strong style={{ fontSize: 16 }}>
                    {result.total_qty ?? 0}
                  </Typography.Text>
                </Descriptions.Item>
              </Descriptions>
              <Space>
                <Button size="small" onClick={() => navigate(`/items/${item.id}`)}>
                  查看完整档案
                </Button>
              </Space>
            </Col>
          </Row>

          <Typography.Title level={5} style={{ marginTop: 12 }}>
            各库位库存
          </Typography.Title>
          <StockTable rows={result.inventory ?? []} />

          {!!result.recent_movements?.length && (
            <>
              <Typography.Title level={5} style={{ marginTop: 12 }}>
                最近流水
              </Typography.Title>
              <Timeline
                items={result.recent_movements.map((m) => ({
                  color: m.change_qty >= 0 ? 'green' : 'red',
                  children: (
                    <span style={{ fontSize: 13 }}>
                      <Tag>{DOC_TYPE_LABELS[m.doc_type] ?? m.doc_type}</Tag>
                      <span style={{ color: m.change_qty >= 0 ? '#3E7C4F' : '#B03A2A', fontWeight: 600 }}>
                        {fmtChangeQty(m.change_qty)}
                      </span>{' '}
                      {m.location_name ?? ''} · {fmtDateTime(m.created_at)}
                      {m.doc_no ? <Typography.Text type="secondary"> （{m.doc_no}）</Typography.Text> : null}
                    </span>
                  ),
                }))}
              />
            </>
          )}
        </Card>
      )}

      {/* ===== 未命中三分支 ===== */}
      {!loading && result && !result.resolved && (
        <Card size="small" style={{ marginBottom: 12 }}>
          {/* 分支①：已合并 */}
          {result.redirect_barcode && (
            <Result
              status="warning"
              title="该物品已合并"
              subTitle={result.hint}
              extra={
                <Button
                  type="primary"
                  icon={<LoginOutlined />}
                  onClick={() => void doResolve(result.redirect_barcode!)}
                >
                  查看保留物品（{result.redirect_barcode}）
                </Button>
              }
            />
          )}
          {/* 分支②：旧码停用 */}
          {!result.redirect_barcode && result.new_barcode && (
            <Result
              status="warning"
              title="该条码已停用"
              subTitle={result.hint}
              extra={
                <Button
                  type="primary"
                  icon={<RollbackOutlined />}
                  onClick={() => void doResolve(result.new_barcode!)}
                >
                  用现用码 {result.new_barcode} 重查
                </Button>
              }
            />
          )}
          {/* 分支③：完全未登记 */}
          {!result.redirect_barcode && !result.new_barcode && (
            <Result
              status="info"
              title="未登记的条码"
              subTitle={`扫到的条码 ${result.code} 还没有物品档案，可以现场登记新物品（拍照 + 名称，条码可留空稍后统一分配）`}
              extra={
                <Button type="primary" size="large" icon={<PlusOutlined />} onClick={() => setRegisterOpen(true)}>
                  登记新物品
                </Button>
              }
            />
          )}
        </Card>
      )}

      {!loading && !result && (
        <Card size="small">
          <div style={{ textAlign: 'center', padding: '32px 16px', color: '#8A847B' }}>
            <ScanOutlined style={{ fontSize: 48, color: '#E4DFD3' }} />
            <p style={{ marginTop: 12 }}>
              用扫码枪扫物品条码，或点「打开摄像头」对准条码，也可以手动输入后回车。
            </p>
          </div>
        </Card>
      )}

      {/* ===== 底部固定操作栏（移动端固定在 TabBar 之上） ===== */}
      <div className="scan-action-bar">
        <Button
          className="scan-big-btn"
          type="primary"
          icon={<InboxOutlined />}
          disabled={!item}
          onClick={() => goWithItem('/inbound')}
          aria-label="入库"
        >
          入库
        </Button>
        <Button
          className="scan-big-btn"
          icon={<ExportOutlined />}
          disabled={!item}
          onClick={() => goWithItem('/outbound')}
          aria-label="出库"
        >
          出库
        </Button>
        <Button
          className="scan-big-btn"
          icon={<RollbackOutlined />}
          disabled={!item}
          onClick={() => goWithItem('/returns')}
          aria-label="退库"
        >
          退库
        </Button>
        <Button
          className="scan-big-btn"
          icon={<AuditOutlined />}
          disabled={!item}
          onClick={() => goWithItem('/stocktakes')}
          aria-label="盘点"
        >
          盘点
        </Button>
      </div>

      {/* ===== 登记新物品抽屉 ===== */}
      <RegisterDrawer
        open={registerOpen}
        defaultBarcode={result && !result.resolved && !result.new_barcode && !result.redirect_barcode ? result.code : ''}
        categories={categories ?? []}
        onClose={() => setRegisterOpen(false)}
        onSaved={(newItem) => {
          setRegisterOpen(false);
          queryClient.invalidateQueries({ queryKey: ['items'] });
          message.success('登记成功');
          if (newItem.barcode) void doResolve(newItem.barcode);
          else navigate(`/items/${newItem.id}`);
        }}
      />
    </div>
  );
}

// ========== 登记新物品抽屉 ==========

interface RegisterForm {
  name: string;
  category_id: number;
  barcode?: string;
  spec?: string;
  suggest_price?: number | null;
}

function RegisterDrawer({
  open,
  defaultBarcode,
  categories,
  onClose,
  onSaved,
}: {
  open: boolean;
  defaultBarcode: string;
  categories: { id: number; name: string }[];
  onClose: () => void;
  onSaved: (item: { id: number; barcode: string | null }) => void;
}) {
  const [form] = Form.useForm<RegisterForm>();
  const [saving, setSaving] = useState(false);
  const [photoFiles, setPhotoFiles] = useState<{ uid: string; file: File }[]>([]);

  useEffect(() => {
    if (open) {
      form.resetFields();
      if (defaultBarcode && /^[0-9]{8,14}$/.test(defaultBarcode)) {
        form.setFieldsValue({ barcode: defaultBarcode });
      }
      setPhotoFiles([]);
    }
  }, [open, defaultBarcode, form]);

  const submit = async () => {
    const values = await form.validateFields();
    if (values.barcode && !/^[0-9]{8,14}$/.test(values.barcode)) {
      message.error('条码必须是 8~14 位纯数字');
      return;
    }
    setSaving(true);
    try {
      const created = await itemsApi.createItem({
        name: values.name.trim(),
        category_id: values.category_id,
        barcode: values.barcode?.trim() || null,
        spec: values.spec ?? '',
        suggest_price: values.suggest_price ?? null,
      });
      // 现场照片稍后补传（新建物品后上传）
      for (const p of photoFiles) {
        try {
          await itemsApi.uploadPhoto(created.id, p.file, 'camera');
        } catch {
          message.warning(`照片「${p.file.name}」上传失败，可稍后在物品档案中补传`);
        }
      }
      onSaved({ id: created.id, barcode: created.barcode });
    } catch {
      // 拦截器已提示
    } finally {
      setSaving(false);
    }
  };

  return (
    <Drawer
      title="登记新物品"
      open={open}
      onClose={onClose}
      width="min(480px, 100%)"
      destroyOnClose
      extra={
        <Button type="primary" loading={saving} onClick={submit}>
          保存
        </Button>
      }
    >
      <Form form={form} layout="vertical" requiredMark={false}>
        <Form.Item
          name="name"
          label="物品名称"
          rules={[{ required: true, message: '请输入物品名称' }]}
        >
          <Input size="large" placeholder="如：米字格练字本" maxLength={200} />
        </Form.Item>
        <Form.Item
          name="category_id"
          label="类目"
          rules={[{ required: true, message: '请选择类目' }]}
        >
          <Select
            size="large"
            placeholder="选择类目"
            options={categories.map((c) => ({ value: c.id, label: c.name }))}
          />
        </Form.Item>
        <Form.Item
          name="barcode"
          label="条码（可留空 = 待编码，稍后统一分配；也可沿用商品原装码）"
          rules={[
            {
              pattern: /^[0-9]{8,14}$/,
              message: '条码必须是 8~14 位纯数字',
            },
          ]}
        >
          <Input size="large" placeholder="留空则稍后批量分配" maxLength={14} />
        </Form.Item>
        <Form.Item name="spec" label="规格">
          <Input placeholder="如：500ml / A4 / 100张每包" maxLength={100} />
        </Form.Item>
        <Form.Item name="suggest_price" label="建议售价（元）">
          <InputNumber style={{ width: '100%' }} size="large" min={0} step={0.1} precision={2} placeholder="0.00" />
        </Form.Item>
        <Form.Item label="照片（可多张，手机可直接拍照）">
          <Upload
            accept="image/*"
            listType="picture"
            multiple
            beforeUpload={(file) => {
              const f = file as unknown as File;
              setPhotoFiles((prev) => [
                ...prev,
                { uid: `${f.name}-${f.size}-${prev.length}`, file: f },
              ]);
              return false;
            }}
            onRemove={(file) => {
              setPhotoFiles((prev) => prev.filter((p) => p.uid !== file.uid));
              return true;
            }}
            fileList={photoFiles.map((p) => ({
              uid: p.uid,
              name: p.file.name,
              status: 'done' as const,
            }))}
          >
            <Button icon={<CameraOutlined />}>选择照片 / 拍照</Button>
          </Upload>
        </Form.Item>
      </Form>
    </Drawer>
  );
}
