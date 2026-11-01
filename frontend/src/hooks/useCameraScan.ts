import { useCallback, useEffect, useRef, useState } from 'react';
import { Html5Qrcode } from 'html5-qrcode';
import { extractBarcode } from '@/utils/barcode';

interface UseCameraScanOptions {
  onScan: (code: string) => void;
  /** 扫码成功提示（震动），默认开启 */
  vibrate?: boolean;
}

interface UseCameraScanReturn {
  /** 摄像头预览容器 id（渲染一个 <div id={videoRegionId}>） */
  videoRegionId: string;
  scanning: boolean;
  /** 当前环境是否支持摄像头扫码（HTTPS/localhost） */
  secureOk: boolean;
  /** 不安全上下文时的中文提示 */
  insecureHint: string | null;
  facingMode: 'environment' | 'user';
  /** 必须由用户手势调用（iOS Safari getUserMedia 限制） */
  start: () => Promise<void>;
  stop: () => Promise<void>;
  toggleFacing: () => Promise<void>;
}

let regionSeq = 0;

/**
 * 摄像头扫码（契约第 1/7 节）：
 * - 优先 window.BarcodeDetector（性能好），不存在降级 html5-qrcode（内含 zxing，iOS Safari 可用）；
 * - 必须 HTTPS 或 localhost，不安全上下文返回中文提示，UI 引导改用扫码枪/手动输入；
 * - iOS Safari 要求用户手势触发 getUserMedia → start() 只能由按钮点击调用，不自动开；
 * - 支持前后摄像头切换；扫到后震动提示（若设备支持）。
 */
export function useCameraScan({ onScan, vibrate = true }: UseCameraScanOptions): UseCameraScanReturn {
  const videoRegionId = useRef(`camera-scan-region-${++regionSeq}`).current;
  const [scanning, setScanning] = useState(false);
  const [facingMode, setFacingMode] = useState<'environment' | 'user'>('environment');
  const detectorScannerRef = useRef<{
    stream: MediaStream;
    raf: number;
    video: HTMLVideoElement;
  } | null>(null);
  const html5Ref = useRef<Html5Qrcode | null>(null);
  const lastCodeRef = useRef<{ code: string; at: number }>({ code: '', at: 0 });
  const onScanRef = useRef(onScan);
  onScanRef.current = onScan;

  const secureOk =
    typeof window !== 'undefined' &&
    (window.isSecureContext ||
      location.hostname === 'localhost' ||
      location.hostname === '127.0.0.1');
  const insecureHint = secureOk
    ? null
    : '摄像头扫码需要 HTTPS，请通过域名访问，或改用扫码枪/手动输入';

  const emit = useCallback(
    (raw: string) => {
      const code = extractBarcode(raw);
      if (!code) return;
      const now = Date.now();
      if (lastCodeRef.current.code === code && now - lastCodeRef.current.at < 500) return;
      lastCodeRef.current = { code, at: now };
      if (vibrate && 'vibrate' in navigator) {
        try {
          navigator.vibrate(80);
        } catch {
          /* 忽略 */
        }
      }
      onScanRef.current(code);
    },
    [vibrate],
  );

  const stopInternal = useCallback(async () => {
    if (detectorScannerRef.current) {
      const s = detectorScannerRef.current;
      cancelAnimationFrame(s.raf);
      s.stream.getTracks().forEach((t) => t.stop());
      s.video.remove();
      detectorScannerRef.current = null;
    }
    if (html5Ref.current) {
      try {
        if (html5Ref.current.isScanning) await html5Ref.current.stop();
      } catch {
        /* 忽略 */
      }
      try {
        html5Ref.current.clear();
      } catch {
        /* 忽略 */
      }
      html5Ref.current = null;
    }
    setScanning(false);
  }, []);

  const startWithDetector = useCallback(
    async (facing: 'environment' | 'user'): Promise<boolean> => {
      if (!('BarcodeDetector' in window) || !window.BarcodeDetector) return false;
      try {
        const stream = await navigator.mediaDevices.getUserMedia({
          video: { facingMode: facing },
        });
        const container = document.getElementById(videoRegionId);
        if (!container) {
          stream.getTracks().forEach((t) => t.stop());
          return false;
        }
        const video = document.createElement('video');
        video.srcObject = stream;
        video.setAttribute('playsinline', 'true'); // iOS 必须
        video.style.width = '100%';
        video.style.borderRadius = '8px';
        container.innerHTML = '';
        container.appendChild(video);
        await video.play();

        const detector = new window.BarcodeDetector({ formats: ['code_128', 'ean_13', 'code_39'] });
        const tick = async () => {
          if (!detectorScannerRef.current) return;
          try {
            const codes = await detector.detect(video);
            for (const c of codes) {
              emit(c.rawValue);
            }
          } catch {
            /* 单帧识别失败忽略 */
          }
          detectorScannerRef.current.raf = requestAnimationFrame(tick);
        };
        detectorScannerRef.current = {
          stream,
          raf: requestAnimationFrame(tick),
          video,
        };
        return true;
      } catch {
        return false; // 权限拒绝或不支持 → 降级
      }
    },
    [emit, videoRegionId],
  );

  const startWithHtml5 = useCallback(
    async (facing: 'environment' | 'user') => {
      const scanner = new Html5Qrcode(videoRegionId, { verbose: false });
      html5Ref.current = scanner;
      await scanner.start(
        { facingMode: facing },
        { fps: 10, qrbox: { width: 260, height: 140 } },
        (decoded) => emit(decoded),
        () => {
          /* 单帧未识别，忽略 */
        },
      );
    },
    [emit, videoRegionId],
  );

  const start = useCallback(async () => {
    if (scanning) return;
    if (!secureOk) return;
    setScanning(true); // 先置位让容器渲染出来
    // 等一帧让容器挂载
    await new Promise((r) => requestAnimationFrame(() => r(null)));
    const ok = await startWithDetector(facingMode);
    if (ok) return;
    try {
      await startWithHtml5(facingMode);
    } catch {
      setScanning(false);
      html5Ref.current = null;
      throw new Error('无法打开摄像头，请检查浏览器权限，或改用扫码枪/手动输入');
    }
  }, [scanning, secureOk, facingMode, startWithDetector, startWithHtml5]);

  const stop = useCallback(async () => {
    await stopInternal();
  }, [stopInternal]);

  const toggleFacing = useCallback(async () => {
    const next = facingMode === 'environment' ? 'user' : 'environment';
    await stopInternal();
    setFacingMode(next);
    // 先让预览容器重新挂载，再启动对应摄像头
    setScanning(true);
    await new Promise((r) => requestAnimationFrame(() => r(null)));
    const ok = await startWithDetector(next);
    if (!ok) {
      try {
        await startWithHtml5(next);
      } catch {
        setScanning(false);
      }
    }
  }, [facingMode, stopInternal, startWithDetector, startWithHtml5]);

  useEffect(() => {
    return () => {
      void stopInternal();
    };
  }, [stopInternal]);

  return {
    videoRegionId,
    scanning,
    secureOk,
    insecureHint,
    facingMode,
    start,
    stop,
    toggleFacing,
  };
}
