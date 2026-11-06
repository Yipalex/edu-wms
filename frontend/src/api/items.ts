import { request, requestPaged } from './client';
import type {
  DeletedItemArchive,
  DuplicateGroup,
  DuplicateIgnoreEntry,
  Item,
  ItemCreatePayload,
  ItemDetail,
  ItemMergeLogEntry,
  MergeResult,
  Paginated,
  PurgeResult,
  RestoreResult,
} from './types';

export interface ItemListParams {
  page?: number;
  page_size?: number;
  q?: string;
  category_id?: number;
  status?: string;
  need_label?: boolean;
  print_mode?: string;
  has_photo?: boolean;
  pending_code?: boolean; // true = 只查待编码（barcode 为空）
  sort?: string;
}

export function listItems(params: ItemListParams): Promise<Paginated<Item>> {
  return requestPaged<Item>({ method: 'GET', url: '/items', params });
}

export function getItem(id: number): Promise<ItemDetail> {
  return request<ItemDetail>({ method: 'GET', url: `/items/${id}` });
}

export function createItem(payload: ItemCreatePayload): Promise<Item> {
  return request<Item>({ method: 'POST', url: '/items', data: payload });
}

export function updateItem(id: number, payload: Partial<ItemCreatePayload>): Promise<Item> {
  return request<Item>({ method: 'PATCH', url: `/items/${id}`, data: payload });
}

export function deleteItem(id: number): Promise<null> {
  return request<null>({ method: 'DELETE', url: `/items/${id}` });
}

/**
 * 彻底删除物品档案（仅超级管理员）。
 * 不受「有库存/流水」拦截：物品档案从名录移除、条码释放可再分配；
 * 库存行归零、流水与已过账单据明细全部保留（改指占位档案，快照仍是原值）；
 * 原始快照进归档表，可恢复。
 */
export function purgeItem(
  id: number,
  payload: { confirm_name: string; reason?: string },
): Promise<PurgeResult> {
  return request<PurgeResult>({ method: 'POST', url: `/items/${id}/purge`, data: payload });
}

/** 已彻底删除的物品档案列表（仅超级管理员） */
export function listDeletedItems(params?: {
  page?: number;
  page_size?: number;
  q?: string;
}): Promise<Paginated<DeletedItemArchive>> {
  return requestPaged<DeletedItemArchive>({
    method: 'GET',
    url: '/items/deleted/list',
    params,
  });
}

/** 恢复已彻底删除的物品档案（仅超级管理员） */
export function restoreDeletedItem(archiveId: number): Promise<RestoreResult> {
  return request<RestoreResult>({
    method: 'POST',
    url: `/items/deleted/${archiveId}/restore`,
    data: {},
  });
}

/** 上传照片（multipart；手机拍照直传同用此接口） */
export function uploadPhoto(id: number, file: File, source: 'upload' | 'camera' = 'upload') {
  const form = new FormData();
  form.append('file', file);
  form.append('source', source);
  return request<{ id: number; url: string }>({
    method: 'POST',
    url: `/items/${id}/photos`,
    data: form,
  });
}

export function deletePhoto(id: number, photoId: number) {
  return request<null>({ method: 'DELETE', url: `/items/${id}/photos/${photoId}` });
}

export function setPrimaryPhoto(id: number, photoId: number) {
  return request<null>({ method: 'PATCH', url: `/items/${id}/photos/${photoId}`, data: { is_primary: true } });
}

// ========== 去重合并（契约第 5 节，仅 admin） ==========

/** 相似分组（默认展示全部待人工复核，按置信度降序；已忽略组不出现） */
export function getDuplicateGroups(threshold = 0.7) {
  return request<DuplicateGroup[]>({
    method: 'GET',
    url: '/items/duplicates',
    params: { threshold },
  });
}

/** 忽略一个相似分组：人工判定不是重复，后续检测不再出现（幂等） */
export function ignoreDuplicateGroup(payload: {
  group_key: string;
  match_type?: string;
  suggested_name?: string;
  members?: { id: number; name: string; barcode: string | null }[];
  reason?: string;
}) {
  return request<{ id: number; group_key: string; message: string }>({
    method: 'POST',
    url: '/items/duplicates/ignore',
    data: payload,
  });
}

/** 已忽略的相似分组列表 */
export function listDuplicateIgnores() {
  return request<DuplicateIgnoreEntry[]>({ method: 'GET', url: '/items/duplicates/ignores' });
}

/** 恢复（取消忽略）：该分组重新出现在检测结果中 */
export function restoreDuplicateIgnore(ignoreId: number) {
  return request<{ message: string }>({
    method: 'DELETE',
    url: `/items/duplicates/ignores/${ignoreId}`,
  });
}

/** 合并：把 merged_ids 合并进 keeper（库存相加/单据改指/条码退役/写别名，同事务） */
export function mergeItems(keeperId: number, mergedIds: number[], reason: string) {
  return request<MergeResult>({
    method: 'POST',
    url: `/items/${keeperId}/merge`,
    data: { merged_ids: mergedIds, reason },
  });
}

/** 合并记录（含已回滚） */
export function listMergeLogs(params?: { page?: number; page_size?: number }) {
  return requestPaged<ItemMergeLogEntry>({ method: 'GET', url: '/items/merges', params });
}

/** 回滚合并（仅 admin，且 keeper 未被再次合并） */
export function rollbackMerge(logId: number) {
  return request<{ message: string }>({
    method: 'POST',
    url: `/items/merges/${logId}/rollback`,
  });
}
