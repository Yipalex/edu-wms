import { fetchBlobUrl } from './client';
import type { LabelPdfParams } from './types';

/** 生成标签 PDF，返回可预览/下载的 blob URL（契约第 6/8 节 GET /labels/pdf） */
export function generateLabelPdf(params: LabelPdfParams): Promise<string | null> {
  return fetchBlobUrl({
    method: 'GET',
    url: '/labels/pdf',
    params: {
      item_ids: params.item_ids.join(','),
      mode: params.mode,
      layout: params.layout,
      copies: params.copies,
      paper: params.paper,
    },
  });
}
