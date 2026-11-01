import { request, requestPaged } from './client';
import type {
  DashboardData,
  InventorySummaryGroup,
  MovementsReport,
  Paginated,
  StockReportItemRow,
} from './types';

export function getDashboard() {
  return request<DashboardData>({ method: 'GET', url: '/reports/dashboard' });
}

// ========== 库存报表 ==========

export interface StockReportParams {
  group_by?: 'item' | 'location' | 'category';
  location_id?: number;
  category_id?: number;
  below_safety?: boolean;
  q?: string;
  page?: number;
  page_size?: number;
}

/** group_by=item：物品 × 库位明细（分页） */
export function getStockReportByItem(
  params: Omit<StockReportParams, 'group_by'>,
): Promise<Paginated<StockReportItemRow>> {
  return requestPaged<StockReportItemRow>({
    method: 'GET',
    url: '/reports/stock',
    params: { ...params, group_by: 'item' },
  });
}

/** group_by=location/category：汇总（不分页，data 为数组） */
export function getStockReportSummary(groupBy: 'location' | 'category') {
  return request<InventorySummaryGroup[]>({
    method: 'GET',
    url: '/reports/stock',
    params: { group_by: groupBy },
  });
}

// ========== 流水汇总 ==========

export interface MovementsReportParams {
  group_by?: 'doc_type' | 'date' | 'item' | 'location';
  start?: string; // YYYY-MM-DD
  end?: string;
  location_id?: number;
  doc_type?: string;
  operator_id?: number;
}

export function getMovementsReport(params: MovementsReportParams) {
  return request<MovementsReport>({ method: 'GET', url: '/reports/movements', params });
}
