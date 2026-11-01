import { useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Button,
  Card,
  Col,
  Empty,
  Input,
  InputNumber,
  List,
  Radio,
  Row,
  Select,
  Space,
  Steps,
  Tag,
  Typography,
  message,
} from 'antd';
import {
  DownloadOutlined,
  DeleteOutlined,
  EyeOutlined,
  PrinterOutlined,
  SearchOutlined,
} from '@ant-design/icons';
import { useQuery } from '@tanstack/react-query';
import { useSearchParams } from 'react-router-dom';
import * as itemsApi from '@/api/items';
import * as categoriesApi from '@/api/categories';
import * as labelsApi from '@/api/labels';
import type { Item, LabelLayout, LabelMode } from '@/api/types';
import PageContainer from '@/components/PageContainer';
import BarcodePreview from '@/components/BarcodePreview';
import { downloadUrl } from '@/utils/download';
import { isMockMode } from '@/api/client';

/**
 * 标签打印（契约第 8 节版式参数）：三步式
 * ① 选物品（多选/按类目/按筛选/从待编码页带入）
 * ② 选版式（3col/4col、贴标/扫码卡、份数、A4；文字+示意图说明差异，3col 默认）
 * ③ 预览与下载（后端出 PDF；jsbarcode 单枚即时预览）
 */
export default function Labels() {
  const [searchParams] = useSearchParams();
  const [step, setStep] = useState(0);
  const [selected, setSelected] = useState<Item[]>([]);
  const [searchQ, setSearchQ] = useState('');
  const [catFilter, setCatFilter] = useState<number | undefined>();
  const [layout, setLayout] = useState<LabelLayout>('3col'); // 用户当前偏好默认
  const [mode, setMode] = useState<LabelMode>('label');
  const [copies, setCopies] = useState(1);
  const [pdfUrl, setPdfUrl] = useState<string | null>(null);
  const [generating, setGenerating] = useState(false);

  const { data: categories } = useQuery({
    queryKey: ['categories'],
    queryFn: () => categoriesApi.listCategories(),
  });

  const { data: searchResult, isFetching: searching } = useQuery({
    queryKey: ['labels-item-search', searchQ, catFilter],
    queryFn: () =>
      itemsApi.listItems({ q: searchQ || undefined, category_id: catFilter, page: 1, page_size: 50 }),
    enabled: step === 0,
  });

  // 从待编码页 / 物品页带入 item_ids
  useEffect(() => {
    const idsParam = searchParams.get('item_ids');
    if (!idsParam) return;
    const ids = idsParam.split(',').map(Number).filter(Boolean);
    if (!ids.length) return;
    void (async () => {
      const fetched: Item[] = [];
      for (const id of ids) {
        try {
          fetched.push(await itemsApi.getItem(id));
        } catch {
          /* 单个失败跳过 */
        }
      }
      setSelected((prev) => {
        const map = new Map(prev.map((p) => [p.id, p]));
        fetched.forEach((f) => map.set(f.id, f));
        return Array.from(map.values());
      });
      if (fetched.length) setStep(1); // 直接带到选版式步骤
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams]);

  const searchList = useMemo(
    () => (searchResult?.list ?? []).filter((i) => i.barcode && i.status === 'active'),
    [searchResult],
  );

  const toggleItem = (item: Item) => {
    setSelected((prev) =>
      prev.some((s) => s.id === item.id) ? prev.filter((s) => s.id !== item.id) : [...prev, item],
    );
  };

  const generate = async () => {
    if (!selected.length) {
      message.warning('请先选择要打印的物品');
      return;
    }
    setGenerating(true);
    try {
      const url = await labelsApi.generateLabelPdf({
        item_ids: selected.map((s) => s.id),
        mode,
        layout,
        copies,
        paper: 'a4',
      });
      setPdfUrl(url);
      setStep(2);
      if (url) window.open(url, '_blank', 'noopener');
    } catch {
      // 已提示
    } finally {
      setGenerating(false);
    }
  };

  const previewItem = selected[0];

  return (
    <PageContainer title="标签打印" description="选择不干胶版式，生成 PDF 交给印刷厂或自助打印">
      <Card size="small" style={{ marginBottom: 12 }}>
        <Steps
          current={step}
          size="small"
          items={[
            { title: '① 选物品' },
            { title: '② 选版式' },
            { title: '③ 预览下载' },
          ]}
          onChange={(s) => {
            if (s === 0) setStep(0);
            else if (s === 1 && selected.length) setStep(1);
            else if (s === 2 && pdfUrl) setStep(2);
          }}
        />
      </Card>

      {/* ===== 第一步：选物品 ===== */}
      {step === 0 && (
        <Row gutter={[12, 12]}>
          <Col xs={24} md={14}>
            <Card
              size="small"
              title="搜索并勾选物品（仅显示已分配条码的在用物品）"
              extra={
                <Button type="primary" disabled={!selected.length} onClick={() => setStep(1)}>
                  下一步：选版式（{selected.length}）
                </Button>
              }
            >
              <Space wrap style={{ marginBottom: 12, width: '100%' }}>
                <Input
                  allowClear
                  prefix={<SearchOutlined />}
                  placeholder="搜索名称 / 条码"
                  style={{ width: 220 }}
                  value={searchQ}
                  onChange={(e) => setSearchQ(e.target.value)}
                  aria-label="搜索物品"
                />
                <Select
                  allowClear
                  style={{ width: 140 }}
                  placeholder="按类目筛选"
                  value={catFilter}
                  onChange={setCatFilter}
                  options={(categories ?? []).map((c) => ({ value: c.id, label: c.name }))}
                />
              </Space>
              <List
                size="small"
                loading={searching}
                dataSource={searchList}
                locale={{ emptyText: <Empty description="没有符合条件的物品" image={Empty.PRESENTED_IMAGE_SIMPLE} /> }}
                renderItem={(item) => {
                  const checked = selected.some((s) => s.id === item.id);
                  return (
                    <List.Item
                      style={{ cursor: 'pointer', background: checked ? '#F3E2DE' : undefined, paddingInline: 8 }}
                      onClick={() => toggleItem(item)}
                      actions={[
                        <Tag key="c" color={checked ? 'blue' : 'default'}>
                          {checked ? '已选' : '选择'}
                        </Tag>,
                      ]}
                    >
                      <List.Item.Meta
                        title={item.name}
                        description={
                          <Space size={6}>
                            <Typography.Text code>{item.barcode}</Typography.Text>
                            <Tag>{item.category_name}</Tag>
                            {item.spec && <Typography.Text type="secondary">{item.spec}</Typography.Text>}
                          </Space>
                        }
                      />
                    </List.Item>
                  );
                }}
              />
            </Card>
          </Col>
          <Col xs={24} md={10}>
            <Card
              size="small"
              title={`已选清单（${selected.length}）`}
              extra={
                selected.length > 0 && (
                  <Button size="small" danger type="text" onClick={() => setSelected([])}>
                    清空
                  </Button>
                )
              }
            >
              {selected.length === 0 ? (
                <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="从左侧勾选物品，或从「待编码物品」页分配条码后带入" />
              ) : (
                <List
                  size="small"
                  dataSource={selected}
                  renderItem={(item) => (
                    <List.Item
                      actions={[
                        <Button
                          key="del"
                          type="text"
                          danger
                          size="small"
                          icon={<DeleteOutlined />}
                          aria-label={`移除 ${item.name}`}
                          onClick={() => setSelected((prev) => prev.filter((s) => s.id !== item.id))}
                        />,
                      ]}
                    >
                      <List.Item.Meta
                        title={<span style={{ fontSize: 13 }}>{item.name}</span>}
                        description={<Typography.Text code>{item.barcode}</Typography.Text>}
                      />
                    </List.Item>
                  )}
                />
              )}
            </Card>
          </Col>
        </Row>
      )}

      {/* ===== 第二步：选版式 ===== */}
      {step === 1 && (
        <Row gutter={[12, 12]}>
          <Col xs={24} md={12}>
            <Card size="small" title="版式参数（A4 纸，300dpi）">
              <Space direction="vertical" size={16} style={{ width: '100%' }}>
                <div>
                  <Typography.Text strong>每页排布</Typography.Text>
                  <Radio.Group
                    style={{ marginTop: 8, width: '100%' }}
                    value={layout}
                    onChange={(e) => setLayout(e.target.value as LabelLayout)}
                  >
                    <Space direction="vertical" style={{ width: '100%' }}>
                      <Radio.Button value="3col" style={{ width: '100%', height: 'auto', padding: '10px 12px', textAlign: 'left', whiteSpace: 'normal' }}>
                        <b>每行 3 枚</b>（3 列 × 6 行 = 18 枚/页）—— 当前偏好，标签更大更好扫
                        <Tag color="blue" style={{ marginInlineStart: 8 }}>默认</Tag>
                      </Radio.Button>
                      <Radio.Button value="4col" style={{ width: '100%', height: 'auto', padding: '10px 12px', textAlign: 'left', whiteSpace: 'normal' }}>
                        <b>每行 4 枚</b>（4 列 × 8 行 = 32 枚/页）—— 密集版，省纸但字更小
                      </Radio.Button>
                    </Space>
                  </Radio.Group>
                </div>
                <div>
                  <Typography.Text strong>标签类型</Typography.Text>
                  <div style={{ marginTop: 8 }}>
                    <Radio.Group value={mode} onChange={(e) => setMode(e.target.value as LabelMode)}>
                      <Radio.Button value="label">贴标（贴在物品上）</Radio.Button>
                      <Radio.Button value="scan_card">扫码卡（挂牌/立卡）</Radio.Button>
                    </Radio.Group>
                  </div>
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    贴标：小尺寸不干胶，条码+编码+名称+分类；扫码卡：大尺寸卡片，方便扫码枪远距离扫描
                  </Typography.Text>
                </div>
                <div>
                  <Typography.Text strong>每个物品打印份数</Typography.Text>
                  <div style={{ marginTop: 8 }}>
                    <InputNumber min={1} max={99} value={copies} onChange={(v) => setCopies(v ?? 1)} />
                    <Typography.Text type="secondary" style={{ marginInlineStart: 8 }}>
                      共 {selected.length} 个物品 × {copies} 份 = {selected.length * copies} 枚
                      {layout === '3col' ? '（18 枚/页）' : '（32 枚/页）'}
                    </Typography.Text>
                  </div>
                </div>
                <Alert
                  type="info"
                  showIcon
                  message="两种版式差异"
                  description={
                    <span>
                      3col：条码约 43×17mm，名称字号 4.5mm，间隙 5mm —— 标签大、扫码快，适合货架物品；
                      <br />
                      4col：间隙 2mm，名称字号 3.2/3.0mm —— 单页多 78% 枚数，适合小件耗材。
                    </span>
                  }
                />
                <Space>
                  <Button onClick={() => setStep(0)}>上一步</Button>
                  <Button
                    type="primary"
                    icon={<PrinterOutlined />}
                    loading={generating}
                    onClick={() => void generate()}
                  >
                    生成 PDF 并预览
                  </Button>
                </Space>
              </Space>
            </Card>
          </Col>
          <Col xs={24} md={12}>
            <Card size="small" title="单枚即时预览（jsbarcode，仅供确认内容，非打印精度）">
              {previewItem?.barcode ? (
                <div
                  style={{
                    border: '2px solid #ccc',
                    borderRadius: 8,
                    padding: 12,
                    textAlign: 'center',
                    maxWidth: layout === '3col' ? 300 : 230,
                    margin: '0 auto',
                  }}
                >
                  <BarcodePreview code={previewItem.barcode} width={layout === '3col' ? 260 : 190} height={60} />
                  <div style={{ fontWeight: 700, fontSize: layout === '3col' ? 15 : 12, marginTop: 4 }}>
                    {previewItem.name}
                  </div>
                  <div style={{ fontSize: layout === '3col' ? 12 : 10, color: '#55504A' }}>
                    {previewItem.category_name}
                    {previewItem.spec ? ` · ${previewItem.spec}` : ''}
                  </div>
                </div>
              ) : (
                <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="没有可预览的物品" />
              )}
              <Typography.Paragraph type="secondary" style={{ fontSize: 12, marginTop: 12, textAlign: 'center' }}>
                正式 PDF 由后端按 300dpi 渲染（中文字体 Noto Sans CJK），条码只缩不放保证可扫等级
              </Typography.Paragraph>
            </Card>
          </Col>
        </Row>
      )}

      {/* ===== 第三步：预览下载 ===== */}
      {step === 2 && (
        <Card
          size="small"
          title="生成结果"
          extra={
            <Space>
              <Button onClick={() => setStep(1)}>返回改参数</Button>
              <Button
                type="primary"
                icon={<DownloadOutlined />}
                disabled={!pdfUrl}
                onClick={() => pdfUrl && downloadUrl(pdfUrl, `标签-${layout}-${mode}-${Date.now()}.pdf`)}
              >
                下载 PDF
              </Button>
              <Button icon={<EyeOutlined />} disabled={!pdfUrl} onClick={() => pdfUrl && window.open(pdfUrl, '_blank', 'noopener')}>
                新窗口预览
              </Button>
            </Space>
          }
        >
          {isMockMode && (
            <Alert
              type="warning"
              showIcon
              style={{ marginBottom: 12 }}
              message="当前为演示（Mock）模式：生成的是 HTML 预览页，非真实 PDF。接入后端后此按钮将输出 300dpi 打印版 PDF。"
            />
          )}
          {pdfUrl ? (
            <iframe
              src={pdfUrl}
              title="标签 PDF 预览"
              style={{ width: '100%', height: 560, border: '1px solid #E4DFD3', borderRadius: 8 }}
            />
          ) : (
            <Empty description="尚未生成 PDF" />
          )}
        </Card>
      )}
    </PageContainer>
  );
}
