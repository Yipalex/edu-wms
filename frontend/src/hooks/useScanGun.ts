import { useEffect, useRef } from 'react';
import { extractBarcode } from '@/utils/barcode';

interface UseScanGunOptions {
  /** 收到一次完整扫码（已提取 8~14 位数字）后回调 */
  onScan: (code: string) => void;
  /** 是否启用（仅在扫码类页面开启，避免在普通表单页抢焦点/误触发） */
  enabled?: boolean;
  /** 判定扫码结束的静默时长 ms，默认 30ms（契约第 7 节） */
  idleMs?: number;
  /** 同码去重窗口 ms，默认 500ms（契约第 7 节） */
  dedupeMs?: number;
}

/**
 * 扫码枪监听（契约第 7 节，Mac Dvorak 乱码坑已处理）：
 * - document 级 keydown 监听，累积可打印字符；
 * - Enter 或 idleMs 内无新字符 → 判定一次扫码结束；
 * - 只提取 ^[0-9]{8,14}$ 的连续数字段（防前缀后缀污染与输入法乱码）；
 * - 同码 dedupeMs 内去重；
 * - 事件目标是 input/textarea/select/contenteditable 时不处理（用户正常填表单时不抢），
 *   扫码页自己的大输入框除外（它自带 onScan 提交逻辑，这里跳过避免重复触发）。
 */
export function useScanGun({ onScan, enabled = true, idleMs = 30, dedupeMs = 500 }: UseScanGunOptions) {
  const bufferRef = useRef('');
  const timerRef = useRef<number | null>(null);
  const lastCodeRef = useRef<{ code: string; at: number }>({ code: '', at: 0 });
  const onScanRef = useRef(onScan);
  onScanRef.current = onScan;

  useEffect(() => {
    if (!enabled) return;

    const finish = () => {
      if (timerRef.current != null) {
        window.clearTimeout(timerRef.current);
        timerRef.current = null;
      }
      const raw = bufferRef.current;
      bufferRef.current = '';
      if (!raw) return;
      const code = extractBarcode(raw);
      if (!code) return;
      const now = Date.now();
      if (lastCodeRef.current.code === code && now - lastCodeRef.current.at < dedupeMs) {
        return; // 500ms 内同码去重
      }
      lastCodeRef.current = { code, at: now };
      onScanRef.current(code);
    };

    const onKeyDown = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      if (target) {
        const tag = target.tagName;
        if (
          tag === 'INPUT' ||
          tag === 'TEXTAREA' ||
          tag === 'SELECT' ||
          target.isContentEditable
        ) {
          return; // 用户正在输入框内打字，不抢
        }
      }
      if (e.key === 'Enter') {
        e.preventDefault();
        finish();
        return;
      }
      // 只累积单字符按键（扫码枪逐字符发送），忽略 Shift/Ctrl 等修饰键本身
      if (e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) {
        bufferRef.current += e.key;
        if (timerRef.current != null) window.clearTimeout(timerRef.current);
        timerRef.current = window.setTimeout(finish, idleMs);
      }
    };

    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('keydown', onKeyDown);
      if (timerRef.current != null) window.clearTimeout(timerRef.current);
    };
  }, [enabled, idleMs, dedupeMs]);
}
