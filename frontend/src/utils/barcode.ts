/** 条码解析工具（契约第 2 节编码规则） */

export const BARCODE_RE = /^[0-9]{8,14}$/;

export function isValidBarcode(code: string): boolean {
  return BARCODE_RE.test(code);
}

/** 是否本机构码：长度=total_length 且以 prefix 开头且全数字 */
export function isInternalCode(
  code: string,
  rules: { prefix: string; total_length: number },
): boolean {
  return (
    /^[0-9]+$/.test(code) &&
    code.length === rules.total_length &&
    code.startsWith(rules.prefix)
  );
}

export interface ParsedInternalCode {
  prefix: string;
  region: string;
  categoryDigit: string;
  seq: string;
}

/** 解析内部码分段：prefix(1) + region(2) + category(1) + seq(4) */
export function parseInternalCode(
  code: string,
  rules: { prefix: string; region_code: string; seq_width: number; total_length: number },
): ParsedInternalCode | null {
  if (!isInternalCode(code, rules)) return null;
  const p = rules.prefix.length;
  const r = rules.region_code.length;
  const s = rules.seq_width;
  return {
    prefix: code.slice(0, p),
    region: code.slice(p, p + r),
    categoryDigit: code.slice(p + r, p + r + 1),
    seq: code.slice(code.length - s),
  };
}

/** 从扫码枪原始串中提取 8~14 位连续数字段（防前缀后缀污染） */
export function extractBarcode(raw: string): string | null {
  const m = raw.match(/[0-9]{8,14}/);
  return m ? m[0] : null;
}
