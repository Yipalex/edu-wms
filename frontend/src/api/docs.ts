/**
 * 单据 API（入库/出库/退库/盘点）——路径严格按契约第 6 节。
 * 列表行与详情均由后端返回 *_name 冗余字段与 *_snapshot 快照，前端不做二次拼接。
 */
import { downloadBlob, request, requestPaged } from './client';
import type {
  DocLineInput,
  InboundOrder,
  InboundOrderDetail,
  OutboundOrder,
  OutboundOrderDetail,
  ReturnOrder,
  ReturnOrderDetail,
  Stocktake,
  StocktakeDetail,
  StocktakeRow,
  StocktakeScanResult,
} from './types';

// ========== 通用筛选参数 ==========

export interface DocListParams {
  page?: number;
  page_size?: number;
  state?: string;
  location_id?: number;
  start?: string; // YYYY-MM-DD
  end?: string;
  q?: string;
}

// ========== 入库单 ==========

export interface InboundCreatePayload {
  supplier?: string;
  location_id: number;
  is_for_sale?: boolean;
  order_date?: string;
  remark?: string;
  items?: DocLineInput[];
}

export function listInboundOrders(params: DocListParams) {
  return requestPaged<InboundOrder>({ method: 'GET', url: '/inbound-orders', params });
}

export function getInboundOrder(id: number) {
  return request<InboundOrderDetail>({ method: 'GET', url: `/inbound-orders/${id}` });
}

export function createInboundOrder(payload: InboundCreatePayload) {
  return request<InboundOrderDetail>({ method: 'POST', url: '/inbound-orders', data: payload });
}

export function patchInboundOrder(id: number, payload: Partial<InboundCreatePayload>) {
  return request<InboundOrderDetail>({ method: 'PATCH', url: `/inbound-orders/${id}`, data: payload });
}

export function postInboundOrder(id: number) {
  return request<InboundOrderDetail>({ method: 'POST', url: `/inbound-orders/${id}/post` });
}

export function voidInboundOrder(id: number) {
  return request<InboundOrderDetail>({ method: 'POST', url: `/inbound-orders/${id}/void` });
}

/** 导出易知鸟 9 列库存导入模板 xlsx */
export function exportInboundYizhiniao(id: number, docNo: string) {
  return downloadBlob(
    { method: 'GET', url: `/inbound-orders/${id}/yizhiniao-export` },
    `yizhiniao-${docNo}.xlsx`,
  );
}

// ========== 出库 / 调拨单 ==========

export interface OutboundListParams extends DocListParams {
  kind?: 'transfer' | 'issue';
}

export interface OutboundCreatePayload {
  kind?: 'transfer' | 'issue';
  from_location_id: number;
  to_location_id?: number | null;
  order_date?: string;
  remark?: string;
  items?: DocLineInput[];
}

export function listOutboundOrders(params: OutboundListParams) {
  return requestPaged<OutboundOrder>({ method: 'GET', url: '/outbound-orders', params });
}

export function getOutboundOrder(id: number) {
  return request<OutboundOrderDetail>({ method: 'GET', url: `/outbound-orders/${id}` });
}

export function createOutboundOrder(payload: OutboundCreatePayload) {
  return request<OutboundOrderDetail>({ method: 'POST', url: '/outbound-orders', data: payload });
}

export function patchOutboundOrder(id: number, payload: Partial<OutboundCreatePayload>) {
  return request<OutboundOrderDetail>({ method: 'PATCH', url: `/outbound-orders/${id}`, data: payload });
}

export function postOutboundOrder(id: number) {
  return request<OutboundOrderDetail>({ method: 'POST', url: `/outbound-orders/${id}/post` });
}

export function voidOutboundOrder(id: number) {
  return request<OutboundOrderDetail>({ method: 'POST', url: `/outbound-orders/${id}/void` });
}

// ========== 退库单 ==========

export interface ReturnListParams extends DocListParams {
  item_condition?: 'sealed' | 'opened';
}

export interface ReturnCreatePayload {
  from_location_id: number;
  to_location_id: number;
  item_condition?: 'sealed' | 'opened';
  order_date?: string;
  remark?: string;
  items?: DocLineInput[];
}

export function listReturnOrders(params: ReturnListParams) {
  return requestPaged<ReturnOrder>({ method: 'GET', url: '/return-orders', params });
}

export function getReturnOrder(id: number) {
  return request<ReturnOrderDetail>({ method: 'GET', url: `/return-orders/${id}` });
}

export function createReturnOrder(payload: ReturnCreatePayload) {
  return request<ReturnOrderDetail>({ method: 'POST', url: '/return-orders', data: payload });
}

export function patchReturnOrder(id: number, payload: Partial<ReturnCreatePayload>) {
  return request<ReturnOrderDetail>({ method: 'PATCH', url: `/return-orders/${id}`, data: payload });
}

/** 验收通过并过账（仅 admin；opened 会被后端按制度第十五条拒绝） */
export function acceptReturnOrder(id: number) {
  return request<ReturnOrderDetail>({ method: 'POST', url: `/return-orders/${id}/accept` });
}

/** 拒收（仅 admin，不动库存） */
export function rejectReturnOrder(id: number) {
  return request<ReturnOrderDetail>({ method: 'POST', url: `/return-orders/${id}/reject` });
}

/** 作废冲销（仅 admin，仅已过账） */
export function voidReturnOrder(id: number) {
  return request<ReturnOrderDetail>({ method: 'POST', url: `/return-orders/${id}/void` });
}

// ========== 盘点单 ==========

export interface StocktakeListParams extends DocListParams {
  category_id?: number;
}

export interface StocktakeCreatePayload {
  location_id: number;
  category_id?: number | null; // 留空=全类目
  stocktake_date?: string;
  remark?: string;
}

export function listStocktakes(params: StocktakeListParams) {
  return requestPaged<Stocktake>({ method: 'GET', url: '/stocktakes', params });
}

export function getStocktake(id: number) {
  return request<StocktakeDetail>({ method: 'GET', url: `/stocktakes/${id}` });
}

export function createStocktake(payload: StocktakeCreatePayload) {
  return request<StocktakeDetail>({ method: 'POST', url: '/stocktakes', data: payload });
}

/** 扫码录入实盘数（条码不在单内会自动加行；重复扫码=覆盖该行实盘数） */
export function scanStocktake(id: number, barcode: string, qtyCounted: number) {
  return request<StocktakeScanResult>({
    method: 'POST',
    url: `/stocktakes/${id}/scan`,
    data: { barcode, qty_counted: qtyCounted },
  });
}

/** 改实盘数/处理结果/备注 */
export function patchStocktakeRow(
  id: number,
  rowId: number,
  payload: { qty_counted?: number | null; handle_result?: string; remark?: string },
) {
  return request<StocktakeRow>({
    method: 'PATCH',
    url: `/stocktakes/${id}/items/${rowId}`,
    data: payload,
  });
}

/** 过账：按差异写 adjust 流水校正库存（幂等） */
export function postStocktake(id: number) {
  return request<StocktakeDetail>({ method: 'POST', url: `/stocktakes/${id}/post` });
}
