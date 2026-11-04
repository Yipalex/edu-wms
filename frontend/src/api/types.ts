/**
 * 类型定义 —— 严格按 docs/DESIGN.md 契约（第 3/4/6 节）。
 * 后端字段命名为 snake_case，前端保持一致，不做转换。
 */

// ========== 通用 ==========

export interface PageMeta {
  page: number;
  page_size: number;
  total: number;
}

/** 统一响应格式：成功 { data, meta } */
export interface ApiResponse<T> {
  data: T;
  meta?: PageMeta;
}

/** 统一响应格式：失败 { detail, code } */
export interface ApiErrorBody {
  detail: string;
  code?: string;
}

export interface Paginated<T> {
  list: T[];
  meta: PageMeta;
}

// ========== 彻底删除物品档案（超级管理员，2026-11-04） ==========

/** 彻底删除的影响面统计 */
export interface PurgeImpact {
  stock_rows: number;
  stock_qty: number;
  movements: number;
  inbound_lines: number;
  outbound_lines: number;
  return_lines: number;
  stocktake_lines: number;
  photos: number;
  aliases: number;
  barcode_history: number;
  merge_logs: number;
  merged_children: number;
}

export interface PurgeResult {
  ok: boolean;
  deleted: {
    origin_item_id: number;
    barcode: string | null;
    name: string;
    archive_id: number;
    placeholder_item_id: number;
  };
  impact: PurgeImpact;
}

/** 已彻底删除的物品档案（归档记录） */
export interface DeletedItemArchive {
  id: number;
  origin_item_id: number;
  barcode: string | null;
  name: string;
  category_name: string | null;
  spec: string;
  unit: string;
  suggest_price: number | null;
  impact: Partial<PurgeImpact>;
  reason: string;
  operator_name: string | null;
  deleted_at: string | null;
  restored_at: string | null;
  restored_by: string | null;
}

export interface RestoreResult {
  ok: boolean;
  restored: {
    item_id: number;
    name: string;
    barcode: string | null;
    barcode_skipped: boolean;
    archive_id: number;
  };
}

// ========== 用户与权限 ==========

export type UserRole = 'admin' | 'superadmin' | 'operator';

export interface User {
  id: number;
  username: string;
  display_name: string;
  role: UserRole;
  home_location_id: number | null;
  is_active: boolean;
  last_login_at: string | null;
  created_at?: string;
  updated_at?: string;
  /** 头像：base64 PNG 存库；has_avatar=false 时前端显示名字首字兜底 */
  has_avatar?: boolean;
  avatar_url?: string | null;
}

export interface LoginResult {
  access_token: string;
  refresh_token: string;
  user: User;
}

export interface RefreshResult {
  access_token: string;
  refresh_token?: string;
}

// ========== 库位 ==========

export interface Location {
  id: number;
  code: string; // HQ / JC / ST / HD / MZ / KFQ
  name: string; // 总校办仓库 / 金城校区 ...
  type: 'warehouse' | 'campus';
  is_front_warehouse: boolean;
  sort_order: number;
  is_active: boolean;
}

// ========== 类目与编码规则 ==========

export interface Category {
  id: number;
  digit: string; // '1'/'2'/'3'/'4'/'5'/'9'，参与条码构成
  name: string; // 教材/书籍/辅材/耗材/礼品/其他
  sort_order: number;
  is_active: boolean;
}

export interface BarcodeRules {
  prefix: string; // '2'，必须纯数字
  region_code: string; // '10' 湛江
  seq_width: number; // 4
  total_length: number; // 8
  allow_external: boolean;
  updated_at?: string;
}

export interface BarcodePreviewResult {
  barcode: string;
  category_id?: number;
  category_digit?: string;
  next_seq?: number;
}

// ========== 物品档案 ==========

export type ItemStatus = 'active' | 'merged' | 'retired';
export type PrintMode = 'label' | 'scan_card';
export type BarcodeOrigin = 'internal' | 'external';

export interface ItemPhoto {
  id: number;
  item_id: number;
  file_path: string; // 相对 uploads/ 的路径
  file_size?: number | null;
  sort_order: number;
  is_primary: boolean;
  source: 'upload' | 'camera' | 'migrated';
  /** 完整可访问 URL（后端拼 /api/uploads/ 或 /uploads/；mock 为 data URI） */
  url?: string;
}

export interface Item {
  id: number;
  barcode: string | null; // null = 待编码
  name: string;
  category_id: number;
  category_name?: string;
  spec: string;
  suggest_price: number | null;
  unit: string;
  need_label: boolean;
  print_mode: PrintMode;
  status: ItemStatus;
  merged_into_id: number | null;
  barcode_origin: BarcodeOrigin;
  remark: string;
  primary_photo_url?: string | null;
  total_qty?: number;
  created_at?: string;
  updated_at?: string;
}

export interface ItemAlias {
  id: number;
  item_id: number;
  alias: string;
  source?: string;
}

export interface ItemDetail extends Item {
  photos: ItemPhoto[];
  inventory: InventoryRow[];
  recent_movements: StockMovement[];
  aliases: ItemAlias[];
  barcode_history: BarcodeHistoryEntry[];
}

export interface ItemCreatePayload {
  barcode?: string | null;
  name: string;
  category_id: number;
  spec?: string;
  suggest_price?: number | null;
  unit?: string;
  need_label?: boolean;
  print_mode?: PrintMode;
  remark?: string;
}

// ========== 条码历史 ==========

export type BarcodeChangeType = 'assign' | 'reassign' | 'merge_retire' | 'manual_fix' | 'import';

export interface BarcodeHistoryEntry {
  id: number;
  item_id: number;
  item_name?: string;
  old_barcode: string | null;
  new_barcode: string | null;
  change_type: BarcodeChangeType;
  reason: string;
  operator_id: number | null;
  operator_name?: string;
  created_at: string;
}

// ========== 库存 ==========

export interface InventoryRow {
  id?: number;
  item_id: number;
  item_name?: string;
  barcode?: string | null;
  location_id: number;
  location_name: string;
  qty_on_hand: number;
  qty_reserved: number;
  safety_stock: number;
  updated_at?: string;
}

// ========== 库存流水 ==========

export type DocType = 'inbound' | 'outbound' | 'return' | 'transfer' | 'stocktake' | 'adjust';

export interface StockMovement {
  id: number;
  item_id: number;
  item_name?: string;
  barcode?: string | null;
  location_id: number;
  location_name?: string;
  change_qty: number; // 正=入，负=出
  qty_before: number;
  qty_after: number;
  doc_type: DocType;
  doc_id: number | null;
  doc_no: string | null;
  operator_id: number | null;
  operator_name?: string;
  note: string;
  created_at: string;
}

// ========== 扫码解析（契约第 4 节，照抄返回体结构） ==========

export interface ScanResolveItem {
  id: number;
  barcode: string | null;
  name: string;
  category: string;
  spec: string;
  suggest_price: number | null;
  need_label: boolean;
  photo_url: string | null;
}

export interface ScanResolveInventory {
  location_id: number;
  location_name: string;
  qty_on_hand: number;
  qty_reserved: number;
  safety_stock: number;
}

export interface ScanResolveResult {
  resolved: boolean;
  code: string;
  code_type: 'internal' | 'external' | 'unknown';
  item: ScanResolveItem | null;
  inventory: ScanResolveInventory[] | null;
  total_qty: number | null;
  hint: string | null;
  /** 已合并时指向保留项条码（契约 4.2） */
  redirect_barcode?: string | null;
  /** 旧码停用时指向现用码（契约 4.3，从 hint 同源提供便于前端一键重查） */
  new_barcode?: string | null;
  /** 最近流水（页面展示用，契约未列出——已在报告中提请后端确认补充） */
  recent_movements?: StockMovement[];
}

// ========== 单据 ==========

export type DocState = 'draft' | 'posted' | 'voided';
export type StocktakeState = 'draft' | 'counting' | 'done';
export type ReturnState = 'pending' | 'accepted' | 'rejected';

export interface InboundOrder {
  id: number;
  doc_no: string;
  supplier: string;
  location_id: number;
  location_name?: string | null;
  is_for_sale: boolean;
  state: DocState;
  order_date: string;
  total_amount: number;
  remark: string;
  operator_id: number | null;
  posted_at: string | null;
  created_at: string;
  updated_at?: string;
}

export interface OutboundOrder {
  id: number;
  doc_no: string;
  kind: 'transfer' | 'issue';
  from_location_id: number;
  from_location_name?: string | null;
  to_location_id: number | null;
  to_location_name?: string | null;
  state: DocState;
  order_date: string;
  remark: string;
  operator_id: number | null;
  posted_at: string | null;
  created_at: string;
  updated_at?: string;
}

export interface ReturnOrder {
  id: number;
  doc_no: string;
  from_location_id: number;
  from_location_name?: string | null;
  to_location_id: number;
  to_location_name?: string | null;
  item_condition: 'sealed' | 'opened';
  state: ReturnState;
  accept_state: DocState;
  order_date: string;
  remark: string;
  operator_id: number | null;
  accepted_by: number | null;
  posted_at: string | null;
  created_at: string;
  updated_at?: string;
}

export interface Stocktake {
  id: number;
  doc_no: string;
  location_id: number;
  location_name?: string | null;
  category_id: number | null;
  state: StocktakeState;
  stocktake_date: string;
  remark: string;
  operator_id: number | null;
  posted_at: string | null;
  created_at: string;
  updated_at?: string;
}

// ========== 单据明细行与详情（后端 *_snapshot 快照字段，历史不失真） ==========

export interface InboundLine {
  id: number;
  item_id: number;
  barcode_snapshot: string | null;
  name_snapshot: string | null;
  spec_snapshot: string | null;
  qty: number;
  purchase_price: number | null;
  sale_price: number | null;
  sort_order: number;
}

export interface OutboundLine {
  id: number;
  item_id: number;
  barcode_snapshot: string | null;
  name_snapshot: string | null;
  qty: number;
  sort_order: number;
}

export interface ReturnLine {
  id: number;
  item_id: number;
  barcode_snapshot: string | null;
  name_snapshot: string | null;
  qty: number;
  sort_order: number;
}

export interface InboundOrderDetail extends InboundOrder {
  items: InboundLine[];
}

export interface OutboundOrderDetail extends OutboundOrder {
  items: OutboundLine[];
}

export interface ReturnOrderDetail extends ReturnOrder {
  items: ReturnLine[];
}

/** 新建/改草稿时的明细行输入（前端扫码加行后一次性提交全量行） */
export interface DocLineInput {
  item_id: number;
  qty: number;
  purchase_price?: number | null;
  sale_price?: number | null;
}

// ========== 盘点 ==========

export interface StocktakeRow {
  id: number;
  stocktake_id: number;
  item_id: number;
  barcode_snapshot: string | null;
  name_snapshot: string | null;
  qty_book: number;
  qty_counted: number | null;
  variance: number | null; // 数据库生成列，只读
  diff_state: string; // ''=未盘 / 相符 / 盘盈 / 盘亏
  handle_result: string;
  remark: string;
  sort_order: number;
}

export interface StocktakeStats {
  row_count: number;
  counted_count: number;
  uncounted_count: number;
  variance_count: number;
}

export interface StocktakeDetail extends Stocktake {
  items: StocktakeRow[];
  stats: StocktakeStats;
}

export interface StocktakeScanResult {
  created_row: boolean;
  item_name: string;
  row: StocktakeRow;
}

// ========== 库存查询（list 行比 InventoryRow 更丰富） ==========

export interface InventoryListRow {
  id: number;
  item_id: number;
  item_name: string | null;
  barcode: string | null;
  category_id: number | null;
  category_name: string | null;
  spec: string;
  unit: string | null;
  suggest_price: number | null;
  location_id: number;
  location_name: string | null;
  location_code: string | null;
  qty_on_hand: number;
  qty_reserved: number;
  safety_stock: number;
  stock_value: number;
  below_safety: boolean;
  updated_at: string | null;
}

export interface InventorySummaryGroup {
  location_id?: number;
  location_name?: string | null;
  location_code?: string | null;
  category_id?: number;
  category_name?: string | null;
  sku_count: number;
  total_qty: number;
  total_value: number;
}

export interface InventorySummary {
  by_location: InventorySummaryGroup[];
  by_category: InventorySummaryGroup[];
  total_sku: number;
  total_qty: number;
  total_value: number;
}

// ========== 报表 ==========

/** /reports/stock group_by=item 的行（无库存行 id 与 updated_at） */
export type StockReportItemRow = Omit<InventoryListRow, 'id' | 'updated_at'>;

export interface MovementsReportRow {
  doc_type?: string;
  date?: string;
  item_id?: number;
  item_name?: string | null;
  barcode?: string | null;
  location_id?: number;
  location_name?: string | null;
  location_code?: string | null;
  movement_count: number;
  in_qty: number;
  out_qty: number;
  net_qty: number;
}

export interface MovementsReport {
  group_by: string;
  rows: MovementsReportRow[];
  overall: {
    movement_count: number;
    in_qty: number;
    out_qty: number;
    net_qty: number;
  };
}

// ========== 去重合并（契约第 5 节） ==========

export type DuplicateMatchType = 'space_variant' | 'same_name' | 'code_conflict' | 'fuzzy';

export interface DuplicateMember {
  id: number;
  barcode: string | null;
  name: string;
  spec: string;
  category_name: string | null;
  suggest_price: number | null;
  total_qty: number;
  photo_url: string | null;
  alias_count: number;
}

export interface DuplicateGroup {
  group_key: string;
  match_type: DuplicateMatchType;
  confidence: number; // 0~1
  suggested_name: string;
  members: DuplicateMember[];
}

export interface MergeResult {
  keeper_id: number;
  merged_ids: number[];
  log_ids: number[];
  message: string;
}

export interface ItemMergeLogEntry {
  id: number;
  keeper_id: number;
  keeper_name?: string | null;
  merged_id: number;
  merged_barcode: string | null;
  merged_name: string | null;
  reason: string;
  operator_id: number | null;
  operator_name?: string | null;
  rolled_back_at: string | null;
  created_at: string;
}

// ========== 销售扣减（供 yj.zexishuhua.com 对接） ==========

export interface SalesDeductResult {
  doc_no: string;
  item_id: number;
  item_name: string;
  barcode: string;
  location_id: number;
  location_name: string;
  qty: number;
  qty_after: number;
  duplicated: boolean; // true=同一 sale_ref 已扣过，本次为幂等重放
}

// ========== 报表 / 仪表盘 ==========

export interface DashboardLocationValue {
  location_id: number;
  location_name: string;
  location_code?: string | null;
  sku_count: number;
  total_qty: number;
  total_value: number;
}

export interface DashboardLowStock {
  item_id: number;
  item_name: string;
  barcode: string | null;
  location_id: number;
  location_name: string;
  qty_on_hand: number;
  safety_stock: number;
}

export interface DashboardData {
  item_count: number;
  total_qty: number;
  total_reserved: number;
  stocktake_count: number;
  pending_stocktakes?: number;
  today_in_count?: number;
  today_out_count?: number;
  by_location: DashboardLocationValue[];
  low_stock: DashboardLowStock[];
  recent_movements: StockMovement[];
}

// ========== 标签打印（契约第 8 节） ==========

export type LabelLayout = '3col' | '4col';
export type LabelMode = PrintMode; // label=贴标 / scan_card=扫码卡
export type LabelPaper = 'a4';

export interface LabelPdfParams {
  item_ids: number[];
  mode: LabelMode;
  layout: LabelLayout;
  copies: number;
  paper: LabelPaper;
}
