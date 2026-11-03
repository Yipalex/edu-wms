import { useState } from 'react';
import {
  Alert, Button, Card, Empty, Input, Popconfirm, Space, Table, Tag, Tooltip, Typography, message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { UndoOutlined } from '@ant-design/icons';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import * as itemsApi from '@/api/items';
import type { DeletedItemArchive } from '@/api/types';
import PageContainer from '@/components/PageContainer';
import { usePagination } from '@/hooks/usePagination';
import { fmtDateTime } from '@/utils/format';

/**
 * 已彻底删除的物品档案（仅超级管理员）。
 *
 * 彻底删除 = 物品档案从名录移除、条码释放，但历史单据与流水全部保留。
 * 本页列出归档记录，可一键恢复（条码若已被占用则恢复为「待编码」）。
 */
export default function DeletedItems() {
  const queryClient = useQueryClient();
  const { page, pageSize, makeTablePagination, reset } = usePagination(20);
  const [q, setQ] = useState('');
  const [restoringId, setRestoringId] = useState<number | null>(null);

  const { data, isFetching } = useQuery({
    queryKey: ['items-deleted', page, pageSize, q],
    queryFn: () =>
      itemsApi.listDeletedItems({
        page, page_size: pageSize, q: q || undefined,
      }),
  });

  const list = data?.list ?? [];
  const total = data?.meta.total ?? 0;

  const onRestore = async (row: DeletedItemArchive) => {
    setRestoringId(row.id);
    try {
      const res = await itemsApi.restoreDeletedItem(row.id);
      const r = res.restored;
      message.success(
        `已恢复「${r.name}」` +
          (r.barcode_skipped ? '（条码已被占用，恢复为待编码）' : r.barcode ? `，条码 ${r.barcode}` : ''),
        4,
      );
      queryClient.invalidateQueries({ queryKey: ['items-deleted'] });
      queryClient.invalidateQueries({ queryKey: ['items'] });
    } catch {
      // 拦截器已统一弹出中文错误
    } finally {
      setRestoringId(null);
    }
  };

  const columns: ColumnsType<DeletedItemArchive> = [
    {
      title: '物品名称',
      dataIndex: 'name',
      width: 200,
      render: (v: string, r) => (
        <Space direction="vertical" size={0}>
          <span style={{ fontWeight: 600 }}>{v}</span>
          {r.spec && (
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              {r.spec}
            </Typography.Text>
          )}
        </Space>
      ),
    },
    {
      title: '条码',
      dataIndex: 'barcode',
      width: 110,
      render: (v: string | null) =>
        v ? <Typography.Text code>{v}</Typography.Text> : <Typography.Text type="secondary">无</Typography.Text>,
    },
    { title: '类目', dataIndex: 'category_name', width: 100, render: (v) => v ?? '—' },
    {
      title: '删除时影响',
      dataIndex: 'impact',
      width: 230,
      render: (v) => {
        const im = (v ?? {}) as Record<string, number>;
        const parts: string[] = [];
        if (im.stock_qty) parts.push(`库存 ${im.stock_qty}`);
        if (im.stock_rows) parts.push(`库存行 ${im.stock_rows}`);
        if (im.movements) parts.push(`流水 ${im.movements}`);
        const docs =
          (im.inbound_lines ?? 0) + (im.outbound_lines ?? 0) +
          (im.return_lines ?? 0) + (im.stocktake_lines ?? 0);
        if (docs) parts.push(`单据明细 ${docs}`);
        if (im.photos) parts.push(`照片 ${im.photos}`);
        return parts.length ? (
          <Typography.Text style={{ fontSize: 12 }}>{parts.join(' · ')}</Typography.Text>
        ) : (
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>无</Typography.Text>
        );
      },
    },
    {
      title: '删除原因',
      dataIndex: 'reason',
      width: 200,
      ellipsis: true,
      render: (v: string) =>
        v ? (
          <Tooltip title={v}>
            <span>{v}</span>
          </Tooltip>
        ) : (
          <Typography.Text type="secondary">—</Typography.Text>
        ),
    },
    {
      title: '操作人',
      dataIndex: 'operator_name',
      width: 110,
      render: (v: string | null) => v ?? '—',
    },
    {
      title: '删除时间',
      dataIndex: 'deleted_at',
      width: 160,
      render: (v: string | null) => fmtDateTime(v),
    },
    {
      title: '操作',
      key: 'act',
      width: 100,
      fixed: 'right',
      render: (_, r) =>
        r.restored_at ? (
          <Tag color="default">
            已恢复 {r.restored_by ? `· ${r.restored_by}` : ''}
          </Tag>
        ) : (
          <Popconfirm
            title={`恢复物品「${r.name}」？`}
            description={
              r.barcode
                ? `将恢复条码 ${r.barcode}（若已被其他物品占用则恢复为待编码）`
                : '该物品原本没有条码，恢复后需重新编码'
            }
            okText="恢复"
            cancelText="取消"
            onConfirm={() => onRestore(r)}
          >
            <Button type="link" size="small" icon={<UndoOutlined />} loading={restoringId === r.id}>
              恢复
            </Button>
          </Popconfirm>
        ),
    },
  ];

  return (
    <PageContainer
      title="已删除档案"
      description="彻底删除的物品档案。历史出入库单据与流水完整保留，恢复后可重新使用条码。"
    >
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 12 }}
        message="彻底删除只移除物品档案，不删除任何历史单据与库存流水"
        description="删除时物品的库存会清零，出入库单据、盘点记录、库存流水全部保留（单据展示不受影响）。如需找回，点「恢复」即可回到档案名录。"
      />

      <Card size="small" styles={{ body: { paddingBottom: 8 } }}>
        <Input.Search
          allowClear
          placeholder="搜索名称或条码"
          defaultValue={q}
          onSearch={(v) => {
            setQ(v.trim());
            reset();
          }}
          style={{ maxWidth: 320, marginBottom: 12 }}
        />
        {list.length === 0 && !isFetching ? (
          <Empty description="暂无已删除的物品档案" />
        ) : (
          <Table<DeletedItemArchive>
            rowKey="id"
            columns={columns}
            dataSource={list}
            loading={isFetching}
            size="middle"
            pagination={makeTablePagination(total)}
            scroll={{ x: 1200 }}
          />
        )}
      </Card>
    </PageContainer>
  );
}
