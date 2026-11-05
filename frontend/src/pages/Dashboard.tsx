import { Card, Col, Row, Statistic, Table, Tag, Spin, List, Typography, Empty } from 'antd';
import {
  AppstoreOutlined,
  InboxOutlined,
  TagsOutlined,
  AuditOutlined,
} from '@ant-design/icons';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import type { ColumnsType } from 'antd/es/table';
import * as reportsApi from '@/api/reports';
import type { DashboardLowStock, StockMovement } from '@/api/types';
import { DOC_TYPE_LABELS, fmtChangeQty, fmtDateTime, fmtMoney, fmtQty } from '@/utils/format';
import { useIsMobile } from '@/hooks/useIsMobile';
import PageContainer from '@/components/PageContainer';

/**
 * 仪表盘：4 张统计卡 + 各库位库存金额柱状图（纯 div 条形，不引入重型图表库）
 * + 低库存预警列表 + 最近库存流水。数据来自 GET /reports/dashboard。
 */
export default function Dashboard() {
  const isMobile = useIsMobile();
  const { data, isLoading } = useQuery({
    queryKey: ['dashboard'],
    queryFn: () => reportsApi.getDashboard(),
  });

  if (isLoading || !data) {
    return (
      <div style={{ textAlign: 'center', padding: '80px 0' }}>
        <Spin size="large" />
      </div>
    );
  }

  const byLocation = data.by_location ?? [];
  const lowStock = data.low_stock ?? [];
  const recentMovements = data.recent_movements ?? [];
  const maxValue = Math.max(...byLocation.map((v) => v.total_value), 1);

  const lowStockCols: ColumnsType<DashboardLowStock> = [
    { title: '物品', dataIndex: 'item_name', ellipsis: true },
    { title: '库位', dataIndex: 'location_name', width: 110 },
    {
      title: '在手 / 安全库存',
      key: 'qty',
      width: 130,
      align: 'right',
      render: (_, r) => (
        <span style={{ color: '#B03A2A', fontWeight: 600 }}>
          {fmtQty(r.qty_on_hand)} / {fmtQty(r.safety_stock)}
        </span>
      ),
    },
  ];

  const movementCols: ColumnsType<StockMovement> = [
    {
      title: '时间',
      dataIndex: 'created_at',
      width: 140,
      render: (v: string) => fmtDateTime(v),
    },
    { title: '物品', dataIndex: 'item_name', ellipsis: true },
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
        <span style={{ color: v >= 0 ? '#3E7C4F' : '#B03A2A', fontWeight: 600 }}>
          {fmtChangeQty(v)}
        </span>
      ),
    },
  ];

  return (
    <PageContainer title="仪表盘" description="总校办仓库与五校区库存总览">
      <Row gutter={[12, 12]}>
        <Col xs={12} md={6}>
          <Card size="small">
            <Statistic
              title="物品种数"
              value={data.item_count}
              prefix={<AppstoreOutlined />}
              valueStyle={{ color: '#31565E' }}
            />
          </Card>
        </Col>
        <Col xs={12} md={6}>
          <Card size="small">
            <Statistic
              title="库存总件数"
              value={data.total_qty}
              prefix={<InboxOutlined />}
              valueStyle={{ color: '#3E7C4F' }}
            />
          </Card>
        </Col>
        <Col xs={12} md={6}>
          <Card size="small">
            <Statistic
              title="待领取总数"
              value={data.total_reserved}
              prefix={<TagsOutlined />}
              valueStyle={{ color: '#A9762B' }}
            />
          </Card>
        </Col>
        <Col xs={12} md={6}>
          <Card size="small">
            <Statistic
              title="盘点次数"
              value={data.stocktake_count}
              prefix={<AuditOutlined />}
              valueStyle={{ color: '#B03A2A' }}
            />
          </Card>
        </Col>
      </Row>

      <Row gutter={[12, 12]} style={{ marginTop: 12 }}>
        <Col xs={24} md={12}>
          <Card size="small" title="各库位库存金额（建议售价 × 在手库存）">
            <div className="bar-chart">
              {byLocation.map((v) => (
                <div className="bar-row" key={v.location_id}>
                  <span title={v.location_name}>
                    {isMobile ? v.location_name.replace('仓库', '').replace('校区', '') : v.location_name}
                  </span>
                  <div className="bar-track" role="img" aria-label={`${v.location_name} 库存金额 ${fmtMoney(v.total_value)}`}>
                    <div
                      className="bar-fill"
                      style={{ width: `${(v.total_value / maxValue) * 100}%` }}
                    />
                  </div>
                  <span className="bar-value">{fmtMoney(v.total_value)}</span>
                </div>
              ))}
            </div>
          </Card>
        </Col>
        <Col xs={24} md={12}>
          <Card
            size="small"
            title={
              <span>
                低库存预警 <Tag color="red">{lowStock.length}</Tag>
              </span>
            }
          >
            {lowStock.length === 0 ? (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="库存充足，暂无预警" />
            ) : isMobile ? (
              <List
                size="small"
                dataSource={lowStock}
                renderItem={(r) => (
                  <List.Item>
                    <List.Item.Meta
                      title={<Link to={`/items/${r.item_id}`}>{r.item_name}</Link>}
                      description={
                        <span>
                          {r.location_name} · 在手{' '}
                          <span style={{ color: '#B03A2A', fontWeight: 600 }}>
                            {fmtQty(r.qty_on_hand)}
                          </span>{' '}
                          / 安全库存 {fmtQty(r.safety_stock)}
                        </span>
                      }
                    />
                  </List.Item>
                )}
              />
            ) : (
              <Table
                rowKey={(r) => `${r.item_id}-${r.location_id}`}
                columns={lowStockCols}
                dataSource={lowStock}
                size="small"
                pagination={false}
                scroll={{ y: 220 }}
              />
            )}
          </Card>
        </Col>
      </Row>

      <Card size="small" title="最近库存流水" style={{ marginTop: 12 }}>
        {isMobile ? (
          <List
            size="small"
            dataSource={recentMovements}
            renderItem={(m) => (
              <List.Item>
                <List.Item.Meta
                  title={
                    <span>
                      {m.item_name}{' '}
                      <Tag>{DOC_TYPE_LABELS[m.doc_type] ?? m.doc_type}</Tag>
                      <span style={{ color: m.change_qty >= 0 ? '#3E7C4F' : '#B03A2A', fontWeight: 600 }}>
                        {fmtChangeQty(m.change_qty)}
                      </span>
                    </span>
                  }
                  description={
                    <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                      {m.location_name} · {fmtDateTime(m.created_at)}
                    </Typography.Text>
                  }
                />
              </List.Item>
            )}
          />
        ) : (
          <Table
            rowKey="id"
            columns={movementCols}
            dataSource={recentMovements}
            size="small"
            pagination={false}
          />
        )}
      </Card>
    </PageContainer>
  );
}
