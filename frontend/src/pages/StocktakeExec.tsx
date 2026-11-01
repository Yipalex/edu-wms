import { useEffect, useRef, useState } from 'react';
import {
  Button,
  Card,
  Descriptions,
  Input,
  InputNumber,
  Popconfirm,
  Progress,
  Result,
  Space,
  Spin,
  Table,
  Tag,
  Typography,
  message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate, useParams } from 'react-router-dom';
import { ArrowLeftOutlined, CheckCircleOutlined } from '@ant-design/icons';
import * as docsApi from '@/api/docs';
import type { StocktakeRow } from '@/api/types';
import PageContainer from '@/components/PageContainer';
import DocStatusTag from '@/components/DocStatusTag';
import ScanInput from '@/components/ScanInput';
import { useScanGun } from '@/hooks/useScanGun';
import { fmtQty } from '@/utils/format';

/** 差异颜色：盘盈（多）红、盘亏（少）绿、相符灰 */
function varianceColor(v: number | null): string {
  if (v == null || v === 0) return '#8A847B';
  return v > 0 ? '#B03A2A' : '#3E7C4F';
}

function varianceText(v: number | null): string {
  if (v == null) return '—';
  if (v > 0) return `+${fmtQty(v)}`;
  if (v < 0) return fmtQty(v);
  return '0';
}

const DIFF_TAG: Record<string, { color: string; label: string }> = {
  相符: { color: 'default', label: '相符' },
  盘盈: { color: 'red', label: '盘盈' },
  盘亏: { color: 'green', label: '盘亏' },
};

/** 盘点执行页（移动优先）：扫码录入实盘数 → 完成后过账校正库存 */
export default function StocktakeExec() {
  const { id } = useParams<{ id: string }>();
  const stocktakeId = Number(id);
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const scanRef = useRef<HTMLInputElement>(null);
  const qtyRef = useRef<HTMLInputElement>(null);
  const [code, setCode] = useState('');
  const [qty, setQty] = useState<number | null>(1);

  const { data, isFetching, isError } = useQuery({
    queryKey: ['stocktake', stocktakeId],
    queryFn: () => docsApi.getStocktake(stocktakeId),
    enabled: Number.isFinite(stocktakeId),
  });

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['stocktake', stocktakeId] });

  // 进入页面/状态变化时聚焦条码框，方便扫码枪直接作业
  useEffect(() => {
    if (data && data.state !== 'done') {
      setTimeout(() => scanRef.current?.focus(), 50);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data?.state]);

  const scanMutation = useMutation({
    mutationFn: ({ barcode, qtyCounted }: { barcode: string; qtyCounted: number }) =>
      docsApi.scanStocktake(stocktakeId, barcode, qtyCounted),
    onSuccess: (res) => {
      message.success(`已录入「${res.item_name}」×${fmtQty(res.row.qty_counted ?? 0)}`);
      if (res.created_row) {
        message.info('该物品不在待盘清单，已自动加行');
      }
      setCode('');
      setQty(1);
      void invalidate();
      setTimeout(() => scanRef.current?.focus(), 50);
    },
    onError: () => {
      // 404 未登记 / 409 停用 已由拦截器提示
      setCode('');
      setTimeout(() => scanRef.current?.focus(), 50);
    },
  });

  const patchRowMutation = useMutation({
    mutationFn: ({
      rowId,
      payload,
    }: {
      rowId: number;
      payload: { qty_counted?: number | null; handle_result?: string; remark?: string };
    }) => docsApi.patchStocktakeRow(stocktakeId, rowId, payload),
    onSuccess: () => {
      void invalidate();
    },
    onError: () => {
      // 拦截器已提示
    },
  });

  const postMutation = useMutation({
    mutationFn: () => docsApi.postStocktake(stocktakeId),
    onSuccess: () => {
      message.success('盘点已完成后过账，库存已按差异校正');
      void invalidate();
      void queryClient.invalidateQueries({ queryKey: ['stocktakes'] });
      void queryClient.invalidateQueries({ queryKey: ['inventory'] });
      void queryClient.invalidateQueries({ queryKey: ['movements'] });
    },
    onError: () => {
      // 拦截器已提示
    },
  });

  const readonly = data?.state === 'done';

  /** 提交一次扫码：条码必填，数量默认 1 */
  const submitScan = (barcode: string) => {
    if (readonly) return;
    const trimmed = barcode.trim();
    if (!trimmed) return;
    const qtyCounted = qty ?? 1;
    scanMutation.mutate({ barcode: trimmed, qtyCounted });
  };

  // 扫码枪全局监听：数量框有值直接提交；无值则聚焦数量框等待输入
  useScanGun({
    enabled: !!data && !readonly,
    onScan: (c) => {
      if (scanMutation.isPending) return;
      if (qty != null) {
        submitScan(c);
      } else {
        setCode(c);
        qtyRef.current?.focus();
      }
    },
  });

  const columns: ColumnsType<StocktakeRow> = [
    {
      title: '条码',
      dataIndex: 'barcode_snapshot',
      width: 130,
      render: (v: string | null) =>
        v ? <Typography.Text code style={{ fontSize: 12 }}>{v}</Typography.Text> : '—',
    },
    {
      title: '名称',
      dataIndex: 'name_snapshot',
      ellipsis: true,
      render: (v: string | null) => v ?? '—',
    },
    {
      title: '账面',
      dataIndex: 'qty_book',
      width: 80,
      align: 'right',
      render: (v: number) => fmtQty(v),
    },
    {
      title: '实盘',
      dataIndex: 'qty_counted',
      width: 110,
      align: 'right',
      render: (_, r) =>
        readonly ? (
          <span>{r.qty_counted == null ? '未盘' : fmtQty(r.qty_counted)}</span>
        ) : (
          <InputNumber
            size="small"
            min={0}
            precision={0}
            style={{ width: 96 }}
            placeholder="未盘"
            value={r.qty_counted}
            disabled={patchRowMutation.isPending}
            onBlur={(e) => {
              const next = e.target.value === '' ? null : Number(e.target.value);
              if (next !== r.qty_counted) {
                patchRowMutation.mutate({ rowId: r.id, payload: { qty_counted: next } });
              }
            }}
            onPressEnter={(e) => {
              const next = (e.target as HTMLInputElement).value === '' ? null : Number((e.target as HTMLInputElement).value);
              if (next !== r.qty_counted) {
                patchRowMutation.mutate({ rowId: r.id, payload: { qty_counted: next } });
              }
            }}
          />
        ),
    },
    {
      title: '差异',
      dataIndex: 'variance',
      width: 90,
      align: 'right',
      render: (v: number | null, r) => (
        <Typography.Text strong style={{ color: varianceColor(v), fontSize: 14 }}>
          {varianceText(v)}
          {r.diff_state && DIFF_TAG[r.diff_state] && (
            <Tag style={{ marginInlineStart: 6 }} color={DIFF_TAG[r.diff_state].color}>
              {DIFF_TAG[r.diff_state].label}
            </Tag>
          )}
        </Typography.Text>
      ),
    },
    {
      title: '处理结果',
      dataIndex: 'handle_result',
      width: 160,
      render: (v: string, r) => {
        const hasDiff = r.variance != null && r.variance !== 0;
        if (readonly) return v || '—';
        if (!hasDiff) return <Typography.Text type="secondary">—</Typography.Text>;
        return (
          <Input
            size="small"
            defaultValue={v}
            maxLength={100}
            placeholder="如：破损报废 / 找到漏记"
            onBlur={(e) => {
              if (e.target.value !== v) {
                patchRowMutation.mutate({ rowId: r.id, payload: { handle_result: e.target.value } });
              }
            }}
          />
        );
      },
    },
    {
      title: '备注',
      dataIndex: 'remark',
      width: 150,
      render: (v: string, r) =>
        readonly ? (
          v || '—'
        ) : (
          <Input
            size="small"
            defaultValue={v}
            maxLength={200}
            placeholder="备注"
            onBlur={(e) => {
              if (e.target.value !== v) {
                patchRowMutation.mutate({ rowId: r.id, payload: { remark: e.target.value } });
              }
            }}
          />
        ),
    },
  ];

  if (!Number.isFinite(stocktakeId)) {
    return (
      <PageContainer title="盘点执行">
        <Result status="warning" title="无效的盘点单 ID" />
      </PageContainer>
    );
  }

  if (isError) {
    return (
      <PageContainer title="盘点执行">
        <Result
          status="404"
          title="盘点单不存在或已被删除"
          extra={
            <Button type="primary" onClick={() => navigate('/stocktakes')}>
              返回盘点单列表
            </Button>
          }
        />
      </PageContainer>
    );
  }

  if (!data) {
    return (
      <PageContainer title="盘点执行">
        <div style={{ textAlign: 'center', padding: 60 }}>
          <Spin size="large" />
        </div>
      </PageContainer>
    );
  }

  const stats = data.stats;
  const percent = stats.row_count > 0 ? Math.round((stats.counted_count / stats.row_count) * 100) : 0;

  return (
    <PageContainer
      title={
        <Space>
          <Button
            type="text"
            size="small"
            icon={<ArrowLeftOutlined />}
            onClick={() => navigate('/stocktakes')}
            aria-label="返回"
          />
          <span>盘点执行 · {data.doc_no}</span>
          <DocStatusTag state={data.state} />
          {readonly && <Tag color="green">已完成</Tag>}
        </Space>
      }
    >
      {/* 单信息 + 进度 */}
      <Card size="small" style={{ marginBottom: 12 }}>
        <Descriptions column={{ xs: 1, sm: 3 }} size="small">
          <Descriptions.Item label="库位">{data.location_name ?? '—'}</Descriptions.Item>
          <Descriptions.Item label="盘点日期">{data.stocktake_date}</Descriptions.Item>
          <Descriptions.Item label="备注">{data.remark || '—'}</Descriptions.Item>
        </Descriptions>
        <div style={{ marginTop: 8 }}>
          <Space split="·" style={{ marginBottom: 4 }}>
            <Typography.Text>
              已盘 <Typography.Text strong>{fmtQty(stats.counted_count)}</Typography.Text>
              {' / '}
              {fmtQty(stats.row_count)}
            </Typography.Text>
            <Typography.Text>
              未盘 <Typography.Text type="warning">{fmtQty(stats.uncounted_count)}</Typography.Text>
            </Typography.Text>
            <Typography.Text>
              差异{' '}
              <Typography.Text type="danger" strong>
                {fmtQty(stats.variance_count)}
              </Typography.Text>{' '}
              条
            </Typography.Text>
          </Space>
          <Progress percent={percent} size="small" status={readonly ? 'normal' : 'active'} />
        </div>
      </Card>

      {/* 扫码录入区（done 后隐藏） */}
      {!readonly && (
        <Card size="small" style={{ marginBottom: 12 }}>
          <Space direction="vertical" style={{ width: '100%' }} size={10}>
            <ScanInput
              ref={scanRef}
              value={code}
              onChange={setCode}
              onSubmit={submitScan}
              loading={scanMutation.isPending}
              placeholder="扫码枪扫码，或手动输入条码后回车"
            />
            <InputNumber
              ref={qtyRef as never}
              size="large"
              min={0}
              precision={0}
              style={{ width: '100%' }}
              addonBefore="实盘数量"
              placeholder="实盘数量（默认 1）"
              value={qty}
              onChange={(v) => setQty(v)}
              onPressEnter={() => {
                if (code.trim()) submitScan(code);
                else scanRef.current?.focus();
              }}
              disabled={scanMutation.isPending}
            />
            <Button
              type="primary"
              size="large"
              block
              loading={scanMutation.isPending}
              onClick={() => submitScan(code)}
              disabled={!code.trim()}
            >
              确认录入
            </Button>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              同一条码重复扫码将覆盖该行实盘数；不在清单内的条码会自动加行。
            </Typography.Text>
          </Space>
        </Card>
      )}

      {/* 行明细 */}
      <Card size="small" title={`盘点明细（${fmtQty(stats.row_count)} 行）`} styles={{ body: { padding: 0 } }}>
        <Table<StocktakeRow>
          rowKey="id"
          columns={columns}
          dataSource={data.items}
          loading={isFetching}
          size="small"
          pagination={false}
          scroll={{ x: 860 }}
          locale={{ emptyText: '暂无盘点行，扫码录入后会自动加行' }}
        />
      </Card>

      {/* 底部固定操作栏 */}
      {!readonly && (
        <div
          style={{
            position: 'sticky',
            bottom: 0,
            marginTop: 12,
            padding: '10px 0',
            background: '#F6F3EC',
            zIndex: 10,
          }}
        >
          <Popconfirm
            title="确认完成盘点并过账？"
            description={`未盘 ${fmtQty(stats.uncounted_count)} 行将按账面不变；差异 ${fmtQty(stats.variance_count)} 行将按差异校正库存。过账后不可修改。`}
            okText="确认过账"
            cancelText="再检查一下"
            onConfirm={() => postMutation.mutate()}
          >
            <Button
              type="primary"
              size="large"
              block
              icon={<CheckCircleOutlined />}
              loading={postMutation.isPending}
            >
              完成盘点并过账（已盘 {fmtQty(stats.counted_count)}/{fmtQty(stats.row_count)}）
            </Button>
          </Popconfirm>
        </div>
      )}
    </PageContainer>
  );
}
