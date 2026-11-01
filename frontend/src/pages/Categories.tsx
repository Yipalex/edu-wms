import { useState } from 'react';
import {
  Alert,
  Button,
  Card,
  Col,
  Form,
  Input,
  InputNumber,
  Modal,
  Row,
  Space,
  Spin,
  Switch,
  Table,
  Tag,
  Typography,
  message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { ArrowDownOutlined, ArrowUpOutlined, SaveOutlined } from '@ant-design/icons';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import * as categoriesApi from '@/api/categories';
import * as barcodeApi from '@/api/barcode';
import type { Category } from '@/api/types';
import PageContainer from '@/components/PageContainer';

/**
 * 类目与编码规则（仅管理员）：
 * - 6 大类目表格（改名/排序/启停；改数字位弹二次确认警告）
 * - 编码规则表单（前端校验纯数字）
 * - 编码结构图解（分段着色）
 * - 各类目「下一个可用码」预览
 */
export default function Categories() {
  const queryClient = useQueryClient();
  const [rulesForm] = Form.useForm();
  const [editingCat, setEditingCat] = useState<Category | null>(null);
  const [catForm] = Form.useForm();
  const [savingRules, setSavingRules] = useState(false);
  const [previews, setPreviews] = useState<Record<number, string>>({});

  const { data: categories, isLoading } = useQuery({
    queryKey: ['categories'],
    queryFn: () => categoriesApi.listCategories(),
  });

  const { data: rules, isLoading: rulesLoading } = useQuery({
    queryKey: ['barcode-rules'],
    queryFn: () => barcodeApi.getBarcodeRules(),
  });

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ['categories'] });
    queryClient.invalidateQueries({ queryKey: ['barcode-rules'] });
  };

  const previewNext = async (cat: Category) => {
    try {
      const res = await barcodeApi.previewBarcode(cat.id);
      setPreviews((p) => ({ ...p, [cat.id]: res.barcode }));
    } catch {
      // 已提示
    }
  };

  const moveSort = async (cat: Category, dir: -1 | 1) => {
    const list = [...(categories ?? [])].sort((a, b) => a.sort_order - b.sort_order);
    const idx = list.findIndex((c) => c.id === cat.id);
    const swapIdx = idx + dir;
    if (swapIdx < 0 || swapIdx >= list.length) return;
    const other = list[swapIdx];
    await categoriesApi.updateCategory(cat.id, { sort_order: other.sort_order });
    await categoriesApi.updateCategory(other.id, { sort_order: cat.sort_order });
    refresh();
  };

  const saveCategory = async () => {
    if (!editingCat) return;
    const values = await catForm.validateFields();
    const digitChanged = values.digit !== editingCat.digit;
    const doSave = async (confirmDigit: boolean) => {
      await categoriesApi.updateCategory(editingCat.id, values, confirmDigit);
      message.success('已保存');
      setEditingCat(null);
      setPreviews({});
      refresh();
    };
    if (digitChanged) {
      Modal.confirm({
        title: '确认修改数字位？',
        content: `数字位「${editingCat.digit}」参与条码构成，改为「${values.digit}」会影响后续新分配的条码（已有条码不受影响，但新旧码分类位将不一致）。请确认。`,
        okText: '确认修改',
        okButtonProps: { danger: true },
        cancelText: '取消',
        onOk: () => doSave(true),
      });
    } else {
      await doSave(false);
    }
  };

  const saveRules = async () => {
    const values = await rulesForm.validateFields();
    setSavingRules(true);
    try {
      await barcodeApi.updateBarcodeRules(values);
      message.success('编码规则已保存');
      setPreviews({});
      refresh();
    } catch {
      // 已提示
    } finally {
      setSavingRules(false);
    }
  };

  if (isLoading || rulesLoading || !categories || !rules) {
    return (
      <div style={{ textAlign: 'center', padding: 80 }}>
        <Spin size="large" />
      </div>
    );
  }

  const columns: ColumnsType<Category> = [
    {
      title: '数字位',
      dataIndex: 'digit',
      width: 90,
      render: (v: string) => <Tag color="blue" style={{ fontFamily: 'monospace', fontSize: 15 }}>{v}</Tag>,
    },
    { title: '类目名称', dataIndex: 'name' },
    { title: '排序', dataIndex: 'sort_order', width: 70, align: 'right' },
    {
      title: '状态',
      dataIndex: 'is_active',
      width: 80,
      render: (v: boolean) => (v ? <Tag color="green">启用</Tag> : <Tag>停用</Tag>),
    },
    {
      title: '下一个可用码',
      key: 'next',
      width: 180,
      render: (_, r) => (
        <Space>
          {previews[r.id] ? (
            <Typography.Text code style={{ fontSize: 14 }}>
              {previews[r.id]}
            </Typography.Text>
          ) : (
            <Typography.Text type="secondary">—</Typography.Text>
          )}
          <Button size="small" type="link" onClick={() => void previewNext(r)}>
            {previews[r.id] ? '刷新' : '试算'}
          </Button>
        </Space>
      ),
    },
    {
      title: '操作',
      key: 'actions',
      width: 160,
      render: (_, r) => (
        <Space size={2}>
          <Button
            type="text"
            size="small"
            icon={<ArrowUpOutlined />}
            aria-label="上移"
            onClick={() => void moveSort(r, -1)}
          />
          <Button
            type="text"
            size="small"
            icon={<ArrowDownOutlined />}
            aria-label="下移"
            onClick={() => void moveSort(r, 1)}
          />
          <Button
            type="link"
            size="small"
            onClick={() => {
              setEditingCat(r);
              catForm.setFieldsValue(r);
            }}
          >
            编辑
          </Button>
        </Space>
      ),
    },
  ];

  return (
    <PageContainer title="类目与编码规则" description="仅管理员可修改；数字位参与条码构成，请谨慎变更">
      <Row gutter={[12, 12]}>
        <Col xs={24} lg={14}>
          <Card size="small" title="六大类目">
            <Table<Category>
              rowKey="id"
              columns={columns}
              dataSource={[...categories].sort((a, b) => a.sort_order - b.sort_order)}
              size="small"
              pagination={false}
              scroll={{ x: 520 }}
            />
          </Card>
        </Col>
        <Col xs={24} lg={10}>
          <Card size="small" title="编码规则">
            <Form
              form={rulesForm}
              layout="vertical"
              initialValues={rules}
              onFinish={() => void saveRules()}
            >
              <Row gutter={12}>
                <Col span={12}>
                  <Form.Item
                    name="prefix"
                    label="前缀"
                    tooltip="易知鸟「条形编码」只接受纯数字，历史硬约束"
                    rules={[
                      { required: true, message: '请输入前缀' },
                      { pattern: /^[0-9]+$/, message: '前缀只允许数字（易知鸟硬约束）' },
                    ]}
                  >
                    <Input maxLength={4} style={{ fontFamily: 'monospace' }} />
                  </Form.Item>
                </Col>
                <Col span={12}>
                  <Form.Item
                    name="region_code"
                    label="地区码（10 = 湛江）"
                    rules={[
                      { required: true, message: '请输入地区码' },
                      { pattern: /^[0-9]+$/, message: '地区码只允许数字' },
                    ]}
                  >
                    <Input maxLength={4} style={{ fontFamily: 'monospace' }} />
                  </Form.Item>
                </Col>
                <Col span={8}>
                  <Form.Item name="seq_width" label="流水位数" rules={[{ required: true }]}>
                    <InputNumber min={1} max={8} style={{ width: '100%' }} />
                  </Form.Item>
                </Col>
                <Col span={8}>
                  <Form.Item name="total_length" label="条码总长度" rules={[{ required: true }]}>
                    <InputNumber min={8} max={14} style={{ width: '100%' }} />
                  </Form.Item>
                </Col>
                <Col span={8}>
                  <Form.Item
                    name="allow_external"
                    label="允许外部码"
                    valuePropName="checked"
                    tooltip="商品原装 EAN-13 直接沿用，不套本机构码"
                  >
                    <Switch checkedChildren="允许" unCheckedChildren="禁止" />
                  </Form.Item>
                </Col>
              </Row>
              <Button type="primary" htmlType="submit" icon={<SaveOutlined />} loading={savingRules} block>
                保存编码规则
              </Button>
            </Form>
          </Card>

          <Card size="small" title="编码结构图解" style={{ marginTop: 12 }}>
            <div style={{ textAlign: 'center', padding: '8px 0' }}>
              <div className="code-diagram">
                <span className="code-seg" style={{ background: '#31565E' }}>
                  {rules.prefix}
                </span>
                <span className="code-seg" style={{ background: '#3E7C4F' }}>
                  {rules.region_code}
                </span>
                <span className="code-seg" style={{ background: '#A9762B' }}>3</span>
                <span className="code-seg" style={{ background: '#B03A2A' }}>0042</span>
              </div>
              <div style={{ marginTop: 12, fontSize: 13, lineHeight: 2 }}>
                <Tag color="blue">前缀 {rules.prefix}</Tag> 国际店内码惯例，避开 EAN-13
                <br />
                <Tag color="cyan">地区码 {rules.region_code}</Tag> 湛江
                <br />
                <Tag color="orange">分类位 1 位</Tag> 1教材 / 2书籍 / 3辅材 / 4耗材 / 5礼品 / 9其他
                <br />
                <Tag color="purple">流水 {rules.seq_width} 位</Tag> 按分类独立递增，从 0001 起
              </div>
              <Alert
                style={{ marginTop: 8, textAlign: 'left' }}
                type="info"
                showIcon
                message="一物一码，不含校区；上例 21030042 = 前缀2 + 湛江10 + 辅材3 + 流水0042"
              />
            </div>
          </Card>
        </Col>
      </Row>

      {/* 类目编辑弹窗 */}
      <Modal
        open={!!editingCat}
        title={`编辑类目「${editingCat?.name ?? ''}」`}
        onOk={() => void saveCategory()}
        onCancel={() => setEditingCat(null)}
        okText="保存"
        cancelText="取消"
      >
        <Form form={catForm} layout="vertical">
          <Form.Item
            name="digit"
            label="数字位（参与条码构成）"
            rules={[
              { required: true, message: '请输入数字位' },
              { pattern: /^[0-9]$/, message: '只能是 1 位数字' },
            ]}
          >
            <Input maxLength={1} style={{ fontFamily: 'monospace', width: 80 }} />
          </Form.Item>
          <Form.Item
            name="name"
            label="类目名称"
            rules={[{ required: true, message: '请输入类目名称' }]}
          >
            <Input maxLength={30} />
          </Form.Item>
          <Form.Item name="sort_order" label="排序号">
            <InputNumber min={0} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="is_active" label="启用" valuePropName="checked">
            <Switch checkedChildren="启用" unCheckedChildren="停用" />
          </Form.Item>
        </Form>
      </Modal>
    </PageContainer>
  );
}
