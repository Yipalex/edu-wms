import { useEffect, useRef } from 'react';
import JsBarcode from 'jsbarcode';

interface Props {
  code: string;
  /** 显示宽度 px，默认 260 */
  width?: number;
  height?: number;
}

/** 单枚条码即时预览（jsbarcode Code128 SVG，无需请求后端） */
export default function BarcodePreview({ code, width = 260, height = 70 }: Props) {
  const svgRef = useRef<SVGSVGElement>(null);

  useEffect(() => {
    if (!svgRef.current || !code) return;
    try {
      JsBarcode(svgRef.current, code, {
        format: 'CODE128',
        displayValue: true,
        fontSize: 14,
        height,
        width: 1.6,
        margin: 6,
      });
    } catch {
      // 非法字符时不渲染
    }
  }, [code, height]);

  return <svg ref={svgRef} style={{ maxWidth: width, width: '100%' }} role="img" aria-label={`条码 ${code}`} />;
}
