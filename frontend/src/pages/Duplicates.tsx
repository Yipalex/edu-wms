import { useMemo, useState } from 'react';
import {
  Alert,
  Avatar,
  Button,
  Card,
  Checkbox,
  Empty,
  Image,
  Input,
  List,
  Modal,
  Popconfirm,
  Progress,
  Radio,
  Slider,
  Space,
  Table,
  Tabs,
  Tag,
  Typography,
  message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import * as itemsApi from '@/api/items';
import type { DuplicateGroup, DuplicateMatchType, DuplicateMember, ItemMergeLogEntry } from '@/api/types';
import PageContainer from '@/components/PageContainer';
import { usePagination } from '@/hooks/usePagination';
import { fmtDateTime, fmtMoney, fmtQty } from '@/utils/format';

const MATCH_TYPE_META: Record<DuplicateMatchType, { label: string; color: string }> = {
  space_variant: { label: '空格变体', color: 'green' },
  same_name: { label: '同名不同码', color: 'gold' },
  code_conflict: { label: '同码不同名', color: 'red' },
  fuzzy: { label: '名称相似', color: 'blue' },
};

const MATCH_TYPE_OPTIONS = (Object.entries(MATCH_TYPE_META) as [DuplicateMatchType, { label: string }][]).map(
  ([value, meta]) => ({ value, label: meta.label }),
);

interface MemberSelection {
  keeperId: number;
  mergedIds: number[];
}

/** 默认保留项 = 总库存最大者，其余默认被合并 */
function defaultSelection(group: DuplicateGroup): MemberSelection {
  let keeperId = group.members[0]?.id ?? 0;
  for (const m of group.members) {
    if (m.total_qty > (group.members.find((x) => x.id === keeperId)?.total_qty ?? -1)) keeperId = m.id;
  }
  return { keeperId, mergedIds: group.members.filter((m) => m.id !== keeperId).map((m) => m.id) };
}

// ========== 相似分组卡片 ==========

function GroupCard({ group }: { group: DuplicateGroup }) {
  const queryClient = useQueryClient();
  const [selection, setSelection] = useState<MemberSelection>(() => defaultSelection(group));
  const [modalOpen, setModalOpen] = useState(false);
  const [reason, setReason] = useState('');

  const isKeeper = (id: number) => selection.keeperId === id;
  const isMerged = (id: number) => selection.mergedIds.includes(id);

  const toggleMerged = (id: number) => {
    if (isKeeper(id)) return; // 保留项与被合并互斥
    setSelection((s) => ({
      ...s,
      mergedIds: s.mergedIds.includes(id) ? s.mergedIds.filter((x) => x !== id) : [...s.mergedIds, id],
    }));
  };

  const switchKeeper = (id: number) => {
    setSelection((s) => ({
      keeperId: id,
      mergedIds: s.keeperId === id ? s.mergedIds : [...s.mergedIds.filter((x) => x !== id), s.keeperId],
    }));
  };

  const mergeMutation = useMutation({
    mutationFn: () => itemsApi.mergeItems(selection.keeperId, selection.mergedIds, reason.trim()),
    onSuccess: (r) => {
      message.success(r.message || '合并完成');
      setModalOpen(false);
      setReason('');
      queryClient.invalidateQueries({ queryKey: ['duplicate-groups'] });
      queryClient.invalidateQueries({ queryKey: ['merge-logs'] });
    },
  });

  const meta = MATCH_TYPE_META[group.match_type];
  const keeper = group.members.find((m) => m.id === selection.keeperId);
  const mergedMembers = group.members.filter((m) => isMerged(m.id));
  const canMerge = mergedMembers.length > 0;

  return (
    <Card
      size="small"
      style={{ marginBottom: 12 }}
      title={
        <Space wrap>
          <Typography.Text strong>{group.suggested_name}</Typography.Text>
          <Tag color={meta.color}>{meta.label}</Tag>
        </Space>
      }
      extra={
        <Space>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            置信度
          </Typography.Text>
          <Progress
            percent={Math.round(group.confidence * 100)}
            size="small"
            style={{ width: 120 }}
            strokeColor={meta.color}
          />
        </Space>
      }
    >
      {group.match_type === 'code_conflict' && (
        <Alert
          type="error"
          showIcon
          style={{ marginBottom: 12 }}
          message="同码不同名冲突，请人工确认保留哪个名称后再合并"
        />
      )}
      <List
        size="small"
        dataSource={group.members}
        renderItem={(m: DuplicateMember) => (
          <List.Item>
            <Space wrap size={12}>
              {m.photo_url ? (
                <Image src={m.photo_url} width={40} height={40} style={{ objectFit: 'cover', borderRadius: 4 }} preview={false} />
              ) : (
                <Avatar shape="square" size={40}>
                  无图
                </Avatar>
              )}
              <div>
                <Typography.Text strong>{m.name}</Typography.Text>
                <div style={{ fontSize: 12, color: '#8A847B' }}>
                  {m.barcode ?? '（无码）'} · {m.spec || '—'} · {m.category_name ?? '—'}
                </div>
              </div>
              <Typography.Text style={{ fontSize: 13 }}>
                库存 <Typography.Text strong>{fmtQty(m.total_qty)}</Typography.Text>
              </Typography.Text>
              <Typography.Text type="secondary" style={{ fontSize: 13 }}>
                别名 {fmtQty(m.alias_count)}
              </Typography.Text>
              <Typography.Text type="secondary" style={{ fontSize: 13 }}>
                {fmtMoney(m.suggest_price)}
              </Typography.Text>
            </Space>
            <Space>
              <Radio checked={isKeeper(m.id)} onChange={() => switchKeeper(m.id)}>
                保留项
              </Radio>
              <Checkbox checked={isMerged(m.id)} disabled={isKeeper(m.id)} onChange={() => toggleMerged(m.id)}>
                被合并
              </Checkbox>
            </Space>
          </List.Item>
        )}
      />
      <div style={{ textAlign: 'right', marginTop: 8 }}>
        <Button type="primary" disabled={!canMerge} onClick={() => setModalOpen(true)}>
          预览并合并
        </Button>
      </div>
      <Modal
        title="确认合并"
        open={modalOpen}
        confirmLoading={mergeMutation.isPending}
        okText="确认合并"
        cancelText="取消"
        onCancel={() => setModalOpen(false)}
        onOk={() => {
          if (!reason.trim()) {
            message.warning('请填写合并原因');
            return;
          }
          mergeMutation.mutate();
        }}
      >
        <Typography.Paragraph>
          保留项：<Typography.Text strong>{keeper?.name}</Typography.Text>（{keeper?.barcode ?? '无码'}）
        </Typography.Paragraph>
        <Typography.Paragraph>
          被合并 {mergedMembers.length} 项：
          <ul style={{ margin: '4px 0', paddingLeft: 20 }}>
            {mergedMembers.map((m) => (
              <li key={m.id}>
                {m.name}（{m.barcode ?? '无码'}）
              </li>
            ))}
          </ul>
        </Typography.Paragraph>
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 12 }}
          message="合并后：库存并入保留项、历史单据改指保留项、被合并条码停用且不再复用、原名称进别名可搜索。操作可回滚。"
        />
        <Input.TextArea
          rows={2}
          placeholder="合并原因（必填）"
          value={reason}
          onChange={(e) => setReason(e.target.value)}
        />
      </Modal>
    </Card>
  );
}

function DuplicateGroups() {
  const [threshold, setThreshold] = useState(0.7);
  const [appliedThreshold, setAppliedThreshold] = useState(0.7);
  const [matchTypes, setMatchTypes] = useState<DuplicateMatchType[]>(MATCH_TYPE_OPTIONS.map((o) => o.value));

  const { data, isFetching } = useQuery({
    queryKey: ['duplicate-groups', appliedThreshold],
    queryFn: () => itemsApi.getDuplicateGroups(appliedThreshold),
  });

  const groups = useMemo(
    () => (data ?? []).filter((g) => matchTypes.includes(g.match_type)),
    [data, matchTypes],
  );

  return (
    <>
      <Card size="small" style={{ marginBottom: 12 }}>
        <Space wrap>
          <Checkbox.Group
            options={MATCH_TYPE_OPTIONS}
            value={matchTypes}
            onChange={(v) => setMatchTypes(v as DuplicateMatchType[])}
          />
          <Typography.Text type="secondary">置信度 ≥ {threshold.toFixed(2)}</Typography.Text>
          <Slider
            min={0.6}
            max={0.95}
            step={0.05}
            value={threshold}
            onChange={setThreshold}
            onChangeComplete={(v) => setAppliedThreshold(v)}
            style={{ width: 200 }}
          />
        </Space>
      </Card>
      {isFetching ? (
        <Card loading size="small" />
      ) : groups.length === 0 ? (
        <Empty description="未发现相似物品，档案很干净" style={{ padding: '60px 0' }} />
      ) : (
        groups.map((g) => <GroupCard key={g.group_key} group={g} />)
      )}
    </>
  );
}

// ========== 合并记录 ==========

function MergeLogs() {
  const { page, pageSize, makeTablePagination } = usePagination(20);
  const queryClient = useQueryClient();

  const { data, isFetching } = useQuery({
    queryKey: ['merge-logs', page, pageSize],
    queryFn: () => itemsApi.listMergeLogs({ page, page_size: pageSize }),
  });

  const rollbackMutation = useMutation({
    mutationFn: (logId: number) => itemsApi.rollbackMerge(logId),
    onSuccess: (r) => {
      message.success(r.message || '已回滚');
      queryClient.invalidateQueries({ queryKey: ['merge-logs'] });
      queryClient.invalidateQueries({ queryKey: ['duplicate-groups'] });
    },
  });

  const columns: ColumnsType<ItemMergeLogEntry> = [
    { title: '时间', dataIndex: 'created_at', width: 150, render: (v: string) => fmtDateTime(v) },
    { title: '保留项', dataIndex: 'keeper_name', width: 180, ellipsis: true, render: (v: string | null) => v ?? '—' },
    {
      title: '被合并',
      key: 'merged',
      ellipsis: true,
      render: (_, r) =>
        r.merged_name ? `${r.merged_name}（${r.merged_barcode ?? '无码'}）` : (r.merged_barcode ?? '—'),
    },
    { title: '原因', dataIndex: 'reason', ellipsis: true, render: (v: string) => v || '—' },
    { title: '操作人', dataIndex: 'operator_name', width: 100, render: (v: string | null) => v ?? '—' },
    {
      title: '状态',
      key: 'state',
      width: 90,
      render: (_, r) =>
        r.rolled_back_at ? <Tag color="default">已回滚</Tag> : <Tag color="green">生效中</Tag>,
    },
    {
      title: '操作',
      key: 'action',
      width: 90,
      render: (_, r) =>
        r.rolled_back_at ? null : (
          <Popconfirm
            title="确认回滚该合并？"
            description="库存与单据将恢复合并前状态"
            okText="回滚"
            cancelText="取消"
            onConfirm={() => rollbackMutation.mutate(r.id)}
          >
            <Button type="link" size="small" danger>
              回滚
            </Button>
          </Popconfirm>
        ),
    },
  ];

  return (
    <Card size="small" styles={{ body: { padding: 0 } }}>
      <Table<ItemMergeLogEntry>
        rowKey="id"
        columns={columns}
        dataSource={data?.list ?? []}
        loading={isFetching || rollbackMutation.isPending}
        size="middle"
        pagination={makeTablePagination(data?.meta.total ?? 0)}
        scroll={{ x: 900 }}
      />
    </Card>
  );
}

/** 去重合并（仅管理员）：相似物品分组复核、合并与回滚 */
export default function Duplicates() {
  return (
    <PageContainer title="去重合并" description="系统自动检测相似物品，人工复核后合并，全部操作留痕可回滚">
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 12 }}
        message="系统自动检测相似物品。合并后：库存并入保留项、历史单据改指保留项、被合并条码停用且不再复用、原名称进别名可搜索。操作可回滚。"
      />
      <Tabs
        items={[
          { key: 'groups', label: '相似分组', children: <DuplicateGroups /> },
          { key: 'logs', label: '合并记录', children: <MergeLogs /> },
        ]}
      />
    </PageContainer>
  );
}
