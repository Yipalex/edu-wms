import { forwardRef } from 'react';
import { Button, Input } from 'antd';
import { SearchOutlined } from '@ant-design/icons';
import { extractBarcode } from '@/utils/barcode';

interface Props {
  value: string;
  onChange: (v: string) => void;
  onSubmit: (code: string) => void;
  loading?: boolean;
  placeholder?: string;
  size?: 'large' | 'middle';
}

/**
 * 手动输入兜底扫码框：永远保留（契约第 7 节）。
 * 扫码枪直接打进本框（Input 内 keydown，useScanGun 对 input 目标不抢焦点），
 * Enter 或点「查询」提交；提交前提取 8~14 位连续数字段。
 */
const ScanInput = forwardRef<HTMLInputElement, Props>(function ScanInput(
  { value, onChange, onSubmit, loading, placeholder = '扫码或输入条码，回车查询', size = 'large' },
  ref,
) {
  const submit = () => {
    const code = extractBarcode(value.trim());
    if (code) onSubmit(code);
    else onSubmit(value.trim());
  };

  return (
    <Input.Search
      ref={ref as never}
      size={size}
      value={value}
      placeholder={placeholder}
      allowClear
      enterButton={
        <Button type="primary" icon={<SearchOutlined />} loading={loading}>
          查询
        </Button>
      }
      onChange={(e) => onChange(e.target.value)}
      onSearch={submit}
      aria-label="条码输入框"
      autoComplete="off"
    />
  );
});

export default ScanInput;
