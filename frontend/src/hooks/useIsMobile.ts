import { useEffect, useState } from 'react';

const MOBILE_BREAKPOINT = 768;

/** 响应式断点：<768px 视为移动端（与 AppLayout 底部 TabBar 一致） */
export function useIsMobile(): boolean {
  const [isMobile, setIsMobile] = useState(
    () => window.innerWidth < MOBILE_BREAKPOINT,
  );
  useEffect(() => {
    const onResize = () => setIsMobile(window.innerWidth < MOBILE_BREAKPOINT);
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, []);
  return isMobile;
}
