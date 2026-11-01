import { create } from 'zustand';
import type { ScanResolveResult } from '@/api/types';

interface ScanState {
  /** 当前扫码上下文：最近一次解析结果（跨页携带，如扫码→新建单据预填） */
  lastResult: ScanResolveResult | null;
  setLastResult: (r: ScanResolveResult | null) => void;
  /** 当前是否处于扫码页（useScanGun 据此决定是否抢焦点） */
  scanPageActive: boolean;
  setScanPageActive: (v: boolean) => void;
}

export const useScanStore = create<ScanState>((set) => ({
  lastResult: null,
  setLastResult: (r) => set({ lastResult: r }),
  scanPageActive: false,
  setScanPageActive: (v) => set({ scanPageActive: v }),
}));
