import { downloadBlob, request, requestPaged } from './client';
import type { InventoryListRow, InventorySummary, Paginated, StockMovement } from './types';

export interface InventoryParams {
  page?: number;
  page_size?: number;
  item_id?: number;
  category_id?: number;
  location_id?: number;
  q?: string;
  below_safety?: boolean;
  sort_by?: string;
  sort_dir?: 'asc' | 'desc';
}

export function listInventory(params: InventoryParams): Promise<Paginated<InventoryListRow>> {
  return requestPaged<InventoryListRow>({ method: 'GET', url: '/inventory', params });
}

/** 按库位与按类目两个维度汇总（SKU 数/件数/金额） */
export function getInventorySummary() {
  return request<InventorySummary>({ method: 'GET', url: '/inventory/summary' });
}

/** 改安全库存/待领取数量（仅 admin；qty_on_hand 只能走单据） */
export function patchInventory(
  id: number,
  payload: { safety_stock?: number; qty_reserved?: number },
) {
  return request<InventoryListRow>({ method: 'PATCH', url: `/inventory/${id}`, data: payload });
}

/** 快速库存调整（仅 admin）：把某库位某物品的库存直接校正为实盘数，差额写 adjust 流水 */
export function adjustInventory(payload: {
  item_id: number;
  location_id: number;
  qty_actual: number;
  reason?: string;
}) {
  return request<{ qty_before: number; qty_after: number; changed: boolean; message: string }>({
    method: 'POST',
    url: '/inventory/adjust',
    data: payload,
  });
}

export interface MovementParams {
  page?: number;
  page_size?: number;
  item_id?: number;
  location_id?: number;
  doc_type?: string;
  operator_id?: number;
  q?: string;
  start?: string; // YYYY-MM-DD
  end?: string;
}

export function listMovements(params: MovementParams): Promise<Paginated<StockMovement>> {
  return requestPaged<StockMovement>({ method: 'GET', url: '/movements', params });
}

export function getMovement(id: number) {
  return request<StockMovement>({ method: 'GET', url: `/movements/${id}` });
}

/** 导出库流水 CSV（与列表页同筛选口径；中文表头 + BOM） */
export function exportMovementsCsv(params: MovementParams) {
  return downloadBlob(
    { method: 'GET', url: '/exports/movements', params },
    `movements-${new Date().toISOString().slice(0, 10)}.csv`,
  );
}

/** 导出库存 CSV */
export function exportInventoryCsv(params: InventoryParams) {
  return downloadBlob(
    { method: 'GET', url: '/exports/inventory', params },
    `inventory-${new Date().toISOString().slice(0, 10)}.csv`,
  );
}
