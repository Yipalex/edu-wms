import { useState } from 'react';
import type { TablePaginationConfig } from 'antd';

/** 分页状态 + antd Table pagination 配置生成 */
export function usePagination(defaultPageSize = 20) {
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(defaultPageSize);

  const reset = () => setPage(1);

  const makeTablePagination = (total: number): TablePaginationConfig => ({
    current: page,
    pageSize,
    total,
    showSizeChanger: true,
    showTotal: (t) => `共 ${t} 条`,
    onChange: (p, ps) => {
      setPage(p);
      setPageSize(ps);
    },
  });

  return { page, pageSize, setPage, setPageSize, reset, makeTablePagination };
}
