import { request, requestPaged } from './client';
import type {
  BarcodeHistoryEntry,
  BarcodePreviewResult,
  BarcodeRules,
  Paginated,
} from './types';

export function getBarcodeRules() {
  return request<BarcodeRules>({ method: 'GET', url: '/barcode-rules' });
}

export function updateBarcodeRules(payload: Partial<BarcodeRules>) {
  return request<BarcodeRules>({ method: 'PUT', url: '/barcode-rules', data: payload });
}

/** 试算下一个可用码（不占用） */
export function previewBarcode(category_id: number) {
  return request<BarcodePreviewResult>({
    method: 'POST',
    url: '/barcode/preview',
    data: { category_id },
  });
}

/** 分配条码：给单个物品，或按类目批量分配 count 个 */
export function allocateBarcode(payload: { item_ids?: number[]; item_id?: number; category_id?: number; count?: number }) {
  return request<{ allocated: { item_id: number; barcode: string }[] }>({
    method: 'POST',
    url: '/barcode/allocate',
    data: payload,
  });
}

/** 全局条码变更历史（仅管理员） */
export interface BarcodeHistoryParams {
  page?: number;
  page_size?: number;
  change_type?: string;
  start_date?: string;
  end_date?: string;
  operator_id?: number;
}

export function listBarcodeHistory(
  params: BarcodeHistoryParams,
): Promise<Paginated<BarcodeHistoryEntry>> {
  return requestPaged<BarcodeHistoryEntry>({ method: 'GET', url: '/barcode/history', params });
}

export function listItemBarcodeHistory(itemId: number) {
  return request<BarcodeHistoryEntry[]>({
    method: 'GET',
    url: `/items/${itemId}/barcode-history`,
  });
}

/** 重分配条码（仅管理员） */
export function reassignBarcode(itemId: number, payload: { new_barcode?: string; reason: string }) {
  return request<{ barcode: string }>({
    method: 'POST',
    url: `/items/${itemId}/reassign-barcode`,
    data: payload,
  });
}
