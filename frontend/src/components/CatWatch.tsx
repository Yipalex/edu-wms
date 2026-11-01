import { useEffect, useRef } from 'react';
import catUrl from '@/assets/login-cat.png';

interface Props {
  /** 登录表单容器：输入框聚焦时，猫盯向该输入框；失焦后回到跟随鼠标 */
  formRef: React.RefObject<HTMLElement>;
}

/** 图是 1024×942（底部已裁掉水印），viewBox 与图像像素 1:1 */
const W = 1024;
const H = 942;
/** 两只眼睛瞳孔中心（按生成图实测，原图像素坐标） */
const EYE_L = { x: 443, y: 388 };
const EYE_R = { x: 612, y: 372 };
const MAX_PUPIL = 13; // 瞳孔最大位移（图像像素）

/**
 * 登录页陪伴猫（AI 生成的橘猫插画 + SVG 动态眼珠叠加）：
 * - 60fps：requestAnimationFrame + lerp 惯性平滑，瞳孔跟随鼠标指针
 * - 输入框聚焦时盯着你填；失焦后回到跟随鼠标
 * - 每 2.2~5.2 秒随机眨眼一次（眼皮盖下 140ms）
 * - 呼吸感：CSS 轻微缩放
 */
export default function CatWatch({ formRef }: Props) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const pupilL = useRef<SVGGElement>(null);
  const pupilR = useRef<SVGGElement>(null);
  const lidL = useRef<SVGGElement>(null);
  const lidR = useRef<SVGGElement>(null);

  useEffect(() => {
    const wrap = wrapRef.current;
    if (!wrap) return;

    const mouse = { x: window.innerWidth / 2, y: window.innerHeight / 3 };
    const cur = { ...mouse }; // 平滑后的当前注视点（屏幕坐标）

    const onMove = (e: MouseEvent) => {
      mouse.x = e.clientX;
      mouse.y = e.clientY;
    };
    window.addEventListener('mousemove', onMove);

    // 眨眼：随机间隔，闭 140ms
    let blinkTimer = 0;
    let openTimer = 0;
    const blink = () => {
      lidL.current?.classList.add('shut');
      lidR.current?.classList.add('shut');
      openTimer = window.setTimeout(() => {
        lidL.current?.classList.remove('shut');
        lidR.current?.classList.remove('shut');
      }, 140);
      blinkTimer = window.setTimeout(blink, 2200 + Math.random() * 3000);
    };
    blinkTimer = window.setTimeout(blink, 1800);

    let raf = 0;
    const tick = () => {
      // 目标点：输入框聚焦 → 输入框中心；否则鼠标位置
      let tx = mouse.x;
      let ty = mouse.y;
      const form = formRef.current;
      const ae = document.activeElement as HTMLElement | null;
      if (
        form &&
        ae &&
        (ae.tagName === 'INPUT' || ae.tagName === 'TEXTAREA') &&
        form.contains(ae)
      ) {
        const r = ae.getBoundingClientRect();
        tx = r.left + r.width / 2;
        ty = r.top + r.height / 2;
      }

      // lerp 惯性平滑（每帧走 14%，看起来是「转瞳孔」而不是瞬移）
      cur.x += (tx - cur.x) * 0.14;
      cur.y += (ty - cur.y) * 0.14;

      // 屏幕坐标 → 图像像素坐标
      const rect = wrap.getBoundingClientRect();
      if (rect.width > 0) {
        const sx = (W / rect.width) * (cur.x - rect.left);
        const sy = (H / rect.height) * (cur.y - rect.top);

        const eyes: Array<[{ x: number; y: number }, React.RefObject<SVGGElement>]> = [
          [EYE_L, pupilL],
          [EYE_R, pupilR],
        ];
        for (const [eye, ref] of eyes) {
          const dx = sx - eye.x;
          const dy = sy - eye.y;
          const len = Math.hypot(dx, dy);
          if (len > 0.5 && ref.current) {
            const k = Math.min(len * 0.09, MAX_PUPIL) / len;
            ref.current.style.transform = `translate(${(dx * k).toFixed(2)}px, ${(dy * k).toFixed(2)}px)`;
          }
        }
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);

    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener('mousemove', onMove);
      window.clearTimeout(blinkTimer);
      window.clearTimeout(openTimer);
    };
  }, [formRef]);

  const pupil = (cx: number, cy: number) => (
    <>
      {/* 深色瞳孔（略大于图中原瞳孔，盖住所到之处） */}
      <ellipse cx={cx} cy={cy} rx={34} ry={36} fill="#241812" />
      {/* 主高光（随瞳孔移动） */}
      <circle cx={cx - 9} cy={cy - 12} r={8} fill="#ffffff" opacity={0.95} />
      {/* 次高光 */}
      <circle cx={cx + 8} cy={cy + 9} r={3.5} fill="#ffffff" opacity={0.4} />
    </>
  );

  return (
    <div ref={wrapRef} className="cat-watch" role="img" aria-label="盯着你的橘猫">
      <img className="cat-img" src={catUrl} alt="" draggable={false} />
      <svg viewBox={`0 0 ${W} ${H}`} className="cat-eyes" aria-hidden>
        {/* 动态瞳孔 */}
        <g ref={pupilL}>{pupil(EYE_L.x, EYE_L.y)}</g>
        <g ref={pupilR}>{pupil(EYE_R.x, EYE_R.y)}</g>
        {/* 眼皮：眨眼时从上方盖下（fur 色渐变近似周围毛色） */}
        <defs>
          <linearGradient id="lidFur" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#efc39a" />
            <stop offset="100%" stopColor="#dfa06a" />
          </linearGradient>
        </defs>
        <g ref={lidL} className="cat-lid">
          <ellipse cx={EYE_L.x} cy={EYE_L.y} rx={52} ry={54} fill="url(#lidFur)" />
        </g>
        <g ref={lidR} className="cat-lid">
          <ellipse cx={EYE_R.x} cy={EYE_R.y} rx={52} ry={54} fill="url(#lidFur)" />
        </g>
      </svg>
    </div>
  );
}
