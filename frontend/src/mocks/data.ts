/**
 * Mock 数据 —— 取自真实名录 barcode-tool/output/final/items_from_minglu.csv（127 行中选 40+ 条），
 * 库位为真实 6 个（总部仓库 + 5 校区），类目为真实 6 类。
 */
import type {
  BarcodeHistoryEntry,
  BarcodeRules,
  Category,
  Item,
  Location,
  StockMovement,
  User,
} from '@/api/types';

export const MOCK_LOCATIONS: Location[] = [
  { id: 1, code: 'HQ', name: '总部仓库', type: 'warehouse', is_front_warehouse: true, sort_order: 0, is_active: true },
  { id: 2, code: 'JC', name: '城东校区', type: 'campus', is_front_warehouse: false, sort_order: 1, is_active: true },
  { id: 3, code: 'ST', name: '城西校区', type: 'campus', is_front_warehouse: false, sort_order: 2, is_active: true },
  { id: 4, code: 'HD', name: '城南校区', type: 'campus', is_front_warehouse: false, sort_order: 3, is_active: true },
  { id: 5, code: 'MZ', name: '城北校区', type: 'campus', is_front_warehouse: false, sort_order: 4, is_active: true },
  { id: 6, code: 'KFQ', name: '高新区校区', type: 'campus', is_front_warehouse: false, sort_order: 5, is_active: true },
];

export const MOCK_CATEGORIES: Category[] = [
  { id: 1, digit: '1', name: '教材', sort_order: 1, is_active: true },
  { id: 2, digit: '2', name: '书籍', sort_order: 2, is_active: true },
  { id: 3, digit: '3', name: '辅材', sort_order: 3, is_active: true },
  { id: 4, digit: '4', name: '耗材', sort_order: 4, is_active: true },
  { id: 5, digit: '5', name: '礼品', sort_order: 5, is_active: true },
  { id: 6, digit: '9', name: '其他', sort_order: 6, is_active: true },
];

export const MOCK_RULES: BarcodeRules = {
  prefix: '2',
  region_code: '10',
  seq_width: 4,
  total_length: 8,
  allow_external: true,
};

export const MOCK_USERS: User[] = [
  {
    id: 1, username: 'admin', display_name: '系统管理员', role: 'admin',
    home_location_id: 1, is_active: true, last_login_at: '2026-10-19T08:30:00+08:00',
  },
  {
    id: 2, username: 'zhangsan', display_name: '张三', role: 'operator',
    home_location_id: 1, is_active: true, last_login_at: '2026-10-18T17:02:00+08:00',
  },
  {
    id: 3, username: 'lisi', display_name: '李四', role: 'operator',
    home_location_id: 2, is_active: true, last_login_at: '2026-10-17T09:41:00+08:00',
  },
  {
    id: 4, username: 'wangwu', display_name: '王五', role: 'operator',
    home_location_id: 5, is_active: false, last_login_at: null,
  },
];

/** 生成占位照片（内联 SVG data URI，无需外部图片） */
export function mockPhoto(name: string, hue: number): string {
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="240" height="240"><rect width="240" height="240" fill="hsl(${hue},45%,88%)"/><text x="120" y="128" font-size="22" fill="hsl(${hue},50%,35%)" text-anchor="middle" font-family="sans-serif">${name.slice(0, 8)}</text></svg>`;
  return `data:image/svg+xml;utf8,${encodeURIComponent(svg)}`;
}

interface SeedItem {
  barcode: string | null;
  name: string;
  cat: number; // category id
  spec?: string;
  price?: number | null;
  external?: boolean;
}

/** 名录真实数据（节选 42 条）+ 2 条待编码 + 1 条已合并演示 */
const SEED: SeedItem[] = [
  { barcode: '21010001', name: '偏旁部首上', cat: 1, price: 5.7 },
  { barcode: '21010005', name: '基本笔画上', cat: 1, price: 5.7 },
  { barcode: '21010007', name: '基本笔画下', cat: 1, price: 5.7 },
  { barcode: '21010009', name: '字根归类', cat: 1, price: 6.0 },
  { barcode: '21010012', name: '实用性书写教材上', cat: 1, price: 5.7 },
  { barcode: '21010013', name: '实用性书写教材下', cat: 1, price: 5.7 },
  { barcode: '21010014', name: '幼小衔接上', cat: 1, price: 8.0 },
  { barcode: '21010016', name: '幼小衔接下', cat: 1, price: 8.0 },
  { barcode: '21010018', name: '正姿.教材', cat: 1, price: 12.0 },
  { barcode: '21010019', name: '毛笔60课包教材', cat: 1, price: 60.0 },
  { barcode: '21010020', name: '间架结构复合字', cat: 1, price: 9.0 },
  { barcode: '21010023', name: '正姿教材下', cat: 1, price: 12.0 },
  { barcode: '21030001', name: '专用练习本', cat: 3, spec: 'A4', price: 3.5 },
  { barcode: '21030003', name: '偏旁部首上配套练习本', cat: 3, price: 4.0 },
  { barcode: '21030013', name: '收据本', cat: 3, price: 2.0 },
  { barcode: '21030014', name: '横线本', cat: 3, price: 2.5 },
  { barcode: '21030015', name: '正品红星墨汁500ml书法专用毛笔墨水国画练习初学者学生书画墨汁', cat: 3, spec: '500ml', price: 18.0 },
  { barcode: '21030016', name: '毛笔回家使用材料包', cat: 3, price: 25.0 },
  { barcode: '21030019', name: '积分存折', cat: 3, price: 1.5 },
  { barcode: '21030030', name: '米字格练字本', cat: 3, price: 3.0 },
  { barcode: '21040001', name: '入学通知书', cat: 4, price: 1.0 },
  { barcode: '21040002', name: '坐姿垫', cat: 4, price: 15.0 },
  { barcode: '21040004', name: '墨水', cat: 4, spec: '瓶装', price: 8.0 },
  { barcode: '21040005', name: '墨碟', cat: 4, price: 5.0 },
  { barcode: '21040007', name: '橡皮', cat: 4, price: 1.0 },
  { barcode: '21040008', name: '毛笔', cat: 4, spec: '兼毫中楷', price: 12.0 },
  { barcode: '21040012', name: '教培机构毛边纸', cat: 4, spec: '100张/包', price: 6.0 },
  { barcode: '21040013', name: '教培机构铅笔', cat: 4, price: 1.5 },
  { barcode: '21040015', name: '教培资料袋', cat: 4, price: 3.0 },
  { barcode: '21040025', name: '铅笔', cat: 4, price: 1.5 },
  { barcode: '21040026', name: '镇尺', cat: 4, price: 20.0 },
  { barcode: '21040032', name: '同步套盒', cat: 4, price: 45.0 },
  { barcode: '21040042', name: '进步之星奖状', cat: 4, price: 0.8 },
  { barcode: '21040047', name: '一次性纸杯', cat: 4, spec: '50只/包', price: 6.5 },
  { barcode: '21050001', name: '教培定制书包', cat: 5, price: 88.0 },
  { barcode: '21050002', name: '黑色双肩包', cat: 5, price: 79.0 },
  { barcode: '21050007', name: '行李箱', cat: 5, price: 199.0 },
  { barcode: '21050008', name: '惊喜盲盒', cat: 5, price: 29.9 },
  { barcode: '21090001', name: '合同本', cat: 6, price: 5.0 },
  { barcode: '21090007', name: '黑色工衣短袖', cat: 6, spec: 'M/L/XL', price: 45.0 },
  { barcode: '6950898000191', name: '北太墨汁', cat: 3, spec: '一得阁 500g', price: 26.0, external: true },
  // 待编码（现场只填名称+拍照，barcode 为空）
  { barcode: null, name: '新采购书法毡垫（待编码）', cat: 4, price: 18.0 },
  { barcode: null, name: '定制笔帘（待编码）', cat: 4, price: 9.0 },
];

export const MOCK_ITEMS: Item[] = SEED.map((s, i) => {
  const cat = MOCK_CATEGORIES.find((c) => c.id === s.cat)!;
  return {
    id: i + 1,
    barcode: s.barcode,
    name: s.name,
    category_id: s.cat,
    category_name: cat.name,
    spec: s.spec ?? '',
    suggest_price: s.price ?? null,
    unit: '件',
    need_label: true,
    print_mode: 'label',
    status: 'active',
    merged_into_id: null,
    barcode_origin: s.external ? 'external' : 'internal',
    remark: '',
    primary_photo_url: mockPhoto(s.name, (i * 47) % 360),
    created_at: '2026-09-01T10:00:00+08:00',
    updated_at: '2026-10-10T10:00:00+08:00',
  };
});

/** 已合并演示项：21010002「偏旁部首上教材」已合并至 21010001「偏旁部首上」 */
export const MERGED_ITEM: Item = {
  id: 900,
  barcode: null,
  name: '[已合并] 偏旁部首上教材',
  category_id: 1,
  category_name: '教材',
  spec: '',
  suggest_price: null,
  unit: '件',
  need_label: true,
  print_mode: 'label',
  status: 'merged',
  merged_into_id: 1,
  barcode_origin: 'internal',
  remark: '与「偏旁部首上」同物多名，已合并',
  primary_photo_url: null,
  created_at: '2026-09-01T10:00:00+08:00',
};

/** 旧码停用演示：21040024「铅 笔」重分配为 21040025 后旧码停用 */
export const MOCK_BARCODE_HISTORY: BarcodeHistoryEntry[] = [
  {
    id: 1, item_id: 30, item_name: '铅笔', old_barcode: '21040024', new_barcode: '21040025',
    change_type: 'reassign', reason: '名称含空格脏数据，重分配并归并', operator_id: 1,
    operator_name: '系统管理员', created_at: '2026-10-12T14:22:00+08:00',
  },
  {
    id: 2, item_id: 1, item_name: '偏旁部首上', old_barcode: '21010002', new_barcode: null,
    change_type: 'merge_retire', reason: '与 21010001 同物多名，合并至「偏旁部首上」', operator_id: 1,
    operator_name: '系统管理员', created_at: '2026-10-10T09:15:00+08:00',
  },
  {
    id: 3, item_id: 2, item_name: '基本笔画上', old_barcode: null, new_barcode: '21010005',
    change_type: 'assign', reason: '首次分配', operator_id: 2,
    operator_name: '张三', created_at: '2026-09-02T11:00:00+08:00',
  },
  {
    id: 4, item_id: 41, item_name: '北太墨汁', old_barcode: null, new_barcode: '6950898000191',
    change_type: 'import', reason: '迁移导入，沿用商品原装 EAN-13 外部码', operator_id: 1,
    operator_name: '系统管理员', created_at: '2026-09-01T10:30:00+08:00',
  },
];

/** 各物品库存（确定性伪随机，避免每次刷新跳动） */
function pseudo(seed: number): number {
  const x = Math.sin(seed * 9973) * 10000;
  return x - Math.floor(x);
}

export interface MockInventoryRow {
  item_id: number;
  location_id: number;
  qty_on_hand: number;
  qty_reserved: number;
  safety_stock: number;
}

export const MOCK_INVENTORY: MockInventoryRow[] = (() => {
  const rows: MockInventoryRow[] = [];
  MOCK_ITEMS.forEach((item, idx) => {
    if (!item.barcode && pseudo(idx) < 0.5) return; // 部分待编码物品暂无库存行
    MOCK_LOCATIONS.forEach((loc, li) => {
      const r = pseudo(idx * 10 + li);
      const isHQ = loc.id === 1;
      const qty = isHQ ? Math.floor(r * 800) : Math.floor(r * 120);
      const safety = li === 0 ? 50 : 20;
      rows.push({
        item_id: item.id,
        location_id: loc.id,
        qty_on_hand: qty,
        qty_reserved: pseudo(idx * 31 + li) < 0.3 ? Math.floor(pseudo(idx * 17 + li) * 10) : 0,
        safety_stock: safety,
      });
    });
  });
  return rows;
})();

const DOC_TYPES: StockMovement['doc_type'][] = ['inbound', 'outbound', 'return', 'transfer', 'stocktake', 'adjust'];
const DOC_PREFIX: Record<string, string> = {
  inbound: 'IN', outbound: 'OUT', return: 'RET', transfer: 'OUT', stocktake: 'STK', adjust: 'ADJ',
};

export const MOCK_MOVEMENTS: StockMovement[] = (() => {
  const list: StockMovement[] = [];
  let id = 1;
  for (let i = 0; i < 60; i++) {
    const item = MOCK_ITEMS[Math.floor(pseudo(i * 3 + 1) * MOCK_ITEMS.length)];
    const loc = MOCK_LOCATIONS[Math.floor(pseudo(i * 7 + 2) * MOCK_LOCATIONS.length)];
    const dt = DOC_TYPES[Math.floor(pseudo(i * 11 + 3) * DOC_TYPES.length)];
    const isIn = dt === 'inbound' || dt === 'return' || (dt === 'transfer' && loc.id !== 1) || (dt === 'adjust' && pseudo(i * 13) > 0.5);
    const qty = (1 + Math.floor(pseudo(i * 5 + 4) * 40)) * (isIn ? 1 : -1);
    const before = 50 + Math.floor(pseudo(i * 19 + 5) * 300);
    const day = 19 - Math.floor(i / 4);
    list.push({
      id: id++,
      item_id: item.id,
      item_name: item.name,
      barcode: item.barcode,
      location_id: loc.id,
      location_name: loc.name,
      change_qty: qty,
      qty_before: before,
      qty_after: before + qty,
      doc_type: dt,
      doc_id: 100 + i,
      doc_no: `${DOC_PREFIX[dt]}-202610${String(Math.max(day, 1)).padStart(2, '0')}-${String(i + 1).padStart(3, '0')}`,
      operator_id: 2,
      operator_name: '张三',
      note: '',
      created_at: `2026-10-${String(Math.max(day, 1)).padStart(2, '0')}T${String(9 + (i % 9)).padStart(2, '0')}:${String((i * 7) % 60).padStart(2, '0')}:00+08:00`,
    });
  }
  return list;
})();

export function findItemByBarcode(code: string): Item | undefined {
  return MOCK_ITEMS.find((i) => i.barcode === code);
}

export function categoryName(catId: number): string {
  return MOCK_CATEGORIES.find((c) => c.id === catId)?.name ?? '';
}

export function locationName(locId: number): string {
  return MOCK_LOCATIONS.find((l) => l.id === locId)?.name ?? '';
}
