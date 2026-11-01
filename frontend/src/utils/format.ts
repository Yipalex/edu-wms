import dayjs from 'dayjs';

/** 金额：¥ 前缀 + 千分位 + 两位小数 */
export function fmtMoney(v: number | null | undefined): string {
  if (v == null || Number.isNaN(Number(v))) return '—';
  return `¥${Number(v).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

/** 数量：千分位整数 */
export function fmtQty(v: number | null | undefined): string {
  if (v == null || Number.isNaN(Number(v))) return '—';
  return Number(v).toLocaleString('zh-CN');
}

/** 日期时间：YYYY-MM-DD HH:mm */
export function fmtDateTime(v: string | null | undefined): string {
  if (!v) return '—';
  const d = dayjs(v);
  return d.isValid() ? d.format('YYYY-MM-DD HH:mm') : '—';
}

/** 日期：YYYY-MM-DD */
export function fmtDate(v: string | null | undefined): string {
  if (!v) return '—';
  const d = dayjs(v);
  return d.isValid() ? d.format('YYYY-MM-DD') : '—';
}

/** 单据类型中文 */
export const DOC_TYPE_LABELS: Record<string, string> = {
  inbound: '入库',
  outbound: '出库',
  return: '退库',
  transfer: '调拨',
  stocktake: '盘点',
  adjust: '调整',
};

/** 单据状态中文 */
export const DOC_STATE_LABELS: Record<string, string> = {
  draft: '草稿',
  posted: '已过账',
  voided: '已作废',
  pending: '待验收',
  accepted: '已验收',
  rejected: '已拒收',
  counting: '盘点中',
  done: '已完成',
};

/** 条码变更类型中文 */
export const CHANGE_TYPE_LABELS: Record<string, string> = {
  assign: '首次分配',
  reassign: '重新分配',
  merge_retire: '合并停用',
  manual_fix: '人工修正',
  import: '迁移导入',
};

/** 物品状态中文 */
export const ITEM_STATUS_LABELS: Record<string, string> = {
  active: '在用',
  merged: '已合并',
  retired: '已停用',
};

/** 印刷方式中文 */
export const PRINT_MODE_LABELS: Record<string, string> = {
  label: '贴标',
  scan_card: '扫码卡',
};

/** 库存流水变动方向中文（带符号） */
export function fmtChangeQty(v: number): string {
  return v >= 0 ? `+${fmtQty(v)}` : fmtQty(v);
}
