import { useEffect, useMemo, useRef, useState } from 'react';
import { Modal, Slider, Button } from 'antd';
import { MinusOutlined, PlusOutlined } from '@ant-design/icons';

/**
 * 圆形选区头像裁剪弹窗（与 yj/quan/zc 的 ZXAvatar.crop 体验一致）。
 * 选框固定为内切圆：拖动图片调整取景位置，滚轮 / 滑杆 / 按钮缩放。
 */
interface Props {
  file: File | null;
  onCancel: () => void;
  /** 确认裁剪，返回 256px PNG blob */
  onOk: (blob: Blob) => void;
}

const OUT = 256;
const SEAL = '#A34332';

export default function AvatarCropModal({ file, onCancel, onOk }: Props) {
  const [img, setImg] = useState<HTMLImageElement | null>(null);
  const [zoom, setZoom] = useState(1);
  const stageRef = useRef<HTMLDivElement>(null);
  const dragRef = useRef<{ sx: number; sy: number; ox: number; oy: number } | null>(null);
  const posRef = useRef({ ox: 0, oy: 0, z: 1 });

  // 读取图片
  useEffect(() => {
    if (!file) return;
    const url = URL.createObjectURL(file);
    const el = new Image();
    el.onload = () => setImg(el);
    el.src = url;
    return () => {
      URL.revokeObjectURL(url);
      setImg(null);
      setZoom(1);
      posRef.current = { ox: 0, oy: 0, z: 1 };
    };
  }, [file]);

  // 舞台尺寸：图片适配进最大 560×420 区域
  const stage = useMemo(() => {
    if (!img) return null;
    const MAX_W = Math.min(560, window.innerWidth - 96);
    const MAX_H = Math.min(420, window.innerHeight - 320);
    const fit = Math.min(MAX_W / img.width, MAX_H / img.height, 1);
    const w = Math.max(200, img.width * fit);
    const h = Math.max(200, img.height * fit);
    const f = Math.min(w / img.width, h / img.height);
    const D = Math.min(w, h);
    return { w, h, fit: f, D, cx: w / 2, cy: h / 2 };
  }, [img]);

  useEffect(() => {
    if (!img || !stage) return;
    const dispW = img.width * stage.fit * posRef.current.z;
    const dispH = img.height * stage.fit * posRef.current.z;
    posRef.current.ox = (stage.w - dispW) / 2;
    posRef.current.oy = (stage.h - dispH) / 2;
    apply();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stage]);

  if (!file || !img || !stage) {
    return (
      <Modal open={!!file} onCancel={onCancel} footer={null} width={320}>
        图片读取中…
      </Modal>
    );
  }

  const clampPan = () => {
    const { cx, cy, D } = stage;
    const dispW = img.width * stage.fit * posRef.current.z;
    const dispH = img.height * stage.fit * posRef.current.z;
    posRef.current.ox = Math.min(cx - D / 2, Math.max(cx + D / 2 - dispW, posRef.current.ox));
    posRef.current.oy = Math.min(cy - D / 2, Math.max(cy + D / 2 - dispH, posRef.current.oy));
  };

  /** 把状态写到 DOM（不经过 setState，拖动时更顺滑） */
  const apply = () => {
    const el = stageRef.current?.querySelector('img');
    if (!el || !img) return;
    const dispW = img.width * stage.fit * posRef.current.z;
    const dispH = img.height * stage.fit * posRef.current.z;
    el.style.left = `${posRef.current.ox}px`;
    el.style.top = `${posRef.current.oy}px`;
    el.style.width = `${dispW}px`;
    el.style.height = `${dispH}px`;
  };

  const changeZoom = (next: number) => {
    const z = Math.min(5, Math.max(1, next));
    if (z === posRef.current.z) return;
    const { cx, cy } = stage;
    posRef.current.ox = cx - (cx - posRef.current.ox) * (z / posRef.current.z);
    posRef.current.oy = cy - (cy - posRef.current.oy) * (z / posRef.current.z);
    posRef.current.z = z;
    setZoom(z);
    clampPan();
    apply();
  };

  const onPointerDown = (e: React.PointerEvent) => {
    dragRef.current = { sx: e.clientX, sy: e.clientY, ox: posRef.current.ox, oy: posRef.current.oy };
    (e.target as HTMLElement).setPointerCapture?.(e.pointerId);
  };
  const onPointerMove = (e: React.PointerEvent) => {
    const d = dragRef.current;
    if (!d) return;
    posRef.current.ox = d.ox + (e.clientX - d.sx);
    posRef.current.oy = d.oy + (e.clientY - d.sy);
    clampPan();
    apply();
  };
  const endDrag = () => {
    dragRef.current = null;
  };

  const ok = () => {
    const { cx, cy, D, fit } = stage;
    const scale = fit * posRef.current.z;
    const sx = (cx - D / 2 - posRef.current.ox) / scale;
    const sy = (cy - D / 2 - posRef.current.oy) / scale;
    const side = D / scale;
    const canvas = document.createElement('canvas');
    canvas.width = OUT;
    canvas.height = OUT;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.imageSmoothingQuality = 'high';
    ctx.drawImage(img, sx, sy, side, side, 0, 0, OUT, OUT);
    canvas.toBlob((blob) => {
      if (blob) onOk(blob);
    }, 'image/png');
  };

  const { D, cx, cy } = stage;
  return (
    <Modal
      open
      title="裁剪头像"
      onCancel={onCancel}
      onOk={ok}
      okText="确定"
      cancelText="取消"
      width="auto"
      okButtonProps={{ style: { background: SEAL } }}
      destroyOnClose
    >
      <div style={{ fontSize: 12, color: '#8a8378', marginBottom: 8 }}>
        圆形区域内即为头像。拖动图片调整位置，滚动或滑杆缩放。
      </div>
      <div
        ref={stageRef}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={endDrag}
        onPointerCancel={endDrag}
        onWheel={(e) => changeZoom(posRef.current.z * (e.deltaY < 0 ? 1.12 : 1 / 1.12))}
        style={{
          position: 'relative',
          overflow: 'hidden',
          background: '#3a352f',
          touchAction: 'none',
          cursor: 'grab',
          userSelect: 'none',
          width: stage.w,
          height: stage.h,
        }}
      >
        <img src={img.src} alt="" draggable={false} style={{ position: 'absolute', pointerEvents: 'none' }} />
        <div
          style={{
            position: 'absolute',
            left: cx,
            top: cy,
            width: D,
            height: D,
            transform: 'translate(-50%, -50%)',
            borderRadius: '50%',
            border: '2px solid #fff',
            boxSizing: 'border-box',
            boxShadow: '0 0 0 1px rgba(0,0,0,.35), 0 0 0 9999px rgba(21,18,16,.6)',
            pointerEvents: 'none',
          }}
        />
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 10 }}>
        <Button size="small" icon={<MinusOutlined />} onClick={() => changeZoom(posRef.current.z / 1.25)} />
        <Slider
          min={1}
          max={5}
          step={0.01}
          value={zoom}
          onChange={(v) => changeZoom(v)}
          style={{ flex: 1, margin: 0 }}
          tooltip={{ formatter: null }}
        />
        <Button size="small" icon={<PlusOutlined />} onClick={() => changeZoom(posRef.current.z * 1.25)} />
      </div>
    </Modal>
  );
}
