import { useEffect, useState } from 'react';
import { Button, Empty, InputNumber, Select, Space, Table, Typography, message } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { DeleteOutlined } from '@ant-design/icons';
import { useQuery } from '@tanstack/react-query';
import { scanResolve } from '@/api/scan';
import { listItems } from '@/api/items';
import { useScanGun } from '@/hooks/useScanGun';
import ScanInput from '@/components/ScanInput';

/** 明细行 UI 态：下划线字段仅用于展示，提交前剥离为 DocLineInput */
export interface DocLineUI {
  item_id: number;
  qty: number;
  purchase_price?: number | null;
  sale_price?: number | null;
  _name: string;
  _barcode: string | null;
  _spec: string;
}

interface AddableItem {
  id: number;
  barcode: string | null;
  name: string;
  spec: string;
  suggest_price: number | null;
}

interface Props {
  lines: DocLineUI[];
  onChange: (lines: DocLineUI[]) => void;
  /** 入库单=true，显示采购价/售卖价列 */
  withPrice?: boolean;
  /** 是否监听扫码枪（默认 true；抽屉关闭组件卸载后自然失效） */
  enabled?: boolean;
}

/**
 * 单据明细行编辑器（入库/出库/退库共用）：
 * 扫码枪全局扫入加行（同物品数量 +1）+ 手动搜索加行 + 行内数量/价格编辑 + 删行。
 */
export default function DocLinesEditor({ lines, onChange, withPrice = false, enabled = true }: Props) {
  const [scanText, setScanText] = useState('');
  const [searchText, setSearchText] = useState('');
  const [debounced, setDebounced] = useState('');

  useEffect(() => {
    const t = window.setTimeout(() => setDebounced(searchText), 300);
    return () => window.clearTimeout(t);
  }, [searchText]);

  const { data: searchResult, isFetching: searching } = useQuery({
    queryKey: ['doc-lines-item-search', debounced],
    queryFn: () => listItems({ q: debounced || undefined, page: 1, page_size: 20 }),
  });

  const addItem = (item: AddableItem) => {
    const idx = lines.findIndex((l) => l.item_id === item.id);
    if (idx >= 0) {
      const next = lines.slice();
      next[idx] = { ...next[idx], qty: next[idx].qty + 1 };
      onChange(next);
      message.success(`「${item.name}」数量 +1`);
    } else {
      onChange([
        ...lines,
        {
          item_id: item.id,
          qty: 1,
          purchase_price: null,
          sale_price: item.suggest_price,
          _name: item.name,
          _barcode: item.barcode,
          _spec: item.spec,
        },
      ]);
    }
  };

  const handleCode = async (code: string) => {
    try {
      let res = await scanResolve(code);
      // 旧码停用/已合并：按后端指引自动追扫一次现用码
      if (!res.resolved && (res.new_barcode || res.redirect_barcode)) {
        res = await scanResolve((res.new_barcode || res.redirect_barcode) as string);
      }
      if (res.resolved && res.item) {
        addItem(res.item);
      } else {
        message.warning(res.hint ?? `未识别条码：${code}`);
      }
    } catch {
      // 后端中文错误已由 axios 拦截器自动弹出
    }
  };

  useScanGun({ onScan: (code) => void handleCode(code), enabled });

  const updateLine = (index: number, patch: Partial<DocLineUI>) => {
    const next = lines.slice();
    next[index] = { ...next[index], ...patch };
    onChange(next);
  };

  const columns: ColumnsType<DocLineUI> = [
    {
      title: '物品',
      key: 'item',
      render: (_, r) => (
        <div>
          <div>{r._name}</div>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {r._barcode ?? '无条码'}
            {r._spec ? ` · ${r._spec}` : ''}
          </Typography.Text>
        </div>
      ),
    },
    {
      title: '数量',
      key: 'qty',
      width: 120,
      render: (_, r, index) => (
        <InputNumber
          min={1}
          precision={0}
          value={r.qty}
          onChange={(v) => updateLine(index, { qty: v ?? 1 })}
          style={{ width: 100 }}
        />
      ),
    },
    ...(withPrice
      ? ([
          {
            title: '采购单价',
            key: 'purchase_price',
            width: 140,
            render: (_: unknown, r: DocLineUI, index: number) => (
              <InputNumber
                min={0}
                precision={2}
                prefix="¥"
                value={r.purchase_price ?? null}
                onChange={(v) => updateLine(index, { purchase_price: v })}
                style={{ width: 120 }}
              />
            ),
          },
          {
            title: '售卖单价',
            key: 'sale_price',
            width: 140,
            render: (_: unknown, r: DocLineUI, index: number) => (
              <InputNumber
                min={0}
                precision={2}
                prefix="¥"
                value={r.sale_price ?? null}
                onChange={(v) => updateLine(index, { sale_price: v })}
                style={{ width: 120 }}
              />
            ),
          },
        ] as ColumnsType<DocLineUI>)
      : []),
    {
      title: '操作',
      key: 'actions',
      width: 70,
      render: (_, __, index) => (
        <Button
          type="text"
          danger
          icon={<DeleteOutlined />}
          aria-label="删除行"
          onClick={() => onChange(lines.filter((_, i) => i !== index))}
        />
      ),
    },
  ];

  return (
    <div>
      <Space direction="vertical" style={{ width: '100%', marginBottom: 12 }} size={8}>
        <ScanInput
          value={scanText}
          onChange={setScanText}
          onSubmit={(code) => {
            setScanText('');
            void handleCode(code);
          }}
          placeholder="扫码枪扫入或手动输入条码，回车加行"
          size="middle"
        />
        <Select
          showSearch
          filterOption={false}
          loading={searching}
          value={null as never}
          placeholder="手动添加物品：输入名称或条码搜索"
          style={{ width: '100%' }}
          onSearch={setSearchText}
          onChange={(id: number) => {
            const item = searchResult?.list.find((i) => i.id === id);
            if (item) addItem(item);
          }}
          options={(searchResult?.list ?? []).map((i) => ({
            value: i.id,
            label: `${i.name}${i.spec ? `（${i.spec}）` : ''}${i.barcode ? ` ${i.barcode}` : ''}`,
          }))}
          notFoundContent={searching ? '搜索中…' : '未找到物品'}
        />
      </Space>
      <Table<DocLineUI>
        rowKey="item_id"
        columns={columns}
        dataSource={lines}
        pagination={false}
        size="small"
        scroll={{ x: withPrice ? 640 : 400 }}
        locale={{ emptyText: <Empty description="请扫码或手动添加物品" /> }}
      />
    </div>
  );
}
