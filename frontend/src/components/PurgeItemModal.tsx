import { useEffect, useState } from 'react';
import {
  Alert, Form, Input, Modal, Space, Typography, message,
} from 'antd';
import { DeleteOutlined } from '@ant-design/icons';
import { useQueryClient } from '@tanstack/react-query';
import * as itemsApi from '@/api/items';
import type { Item } from '@/api/types';

interface Props {
  /** 待删除的物品；null 表示不显示弹窗 */
  item: Item | null;
  onClose: () => void;
  onDone?: () => void;
}

/**
 * 彻底删除物品档案确认弹窗（仅超级管理员）。
 *
 * 设计要点：
 * 1. 必须手输物品名称完全一致才允许提交（防误触，这是不可逆操作）
 * 2. 明确列出将发生什么：库存清零、流水与单据保留、条码释放
 * 3. 删除原因写入归档表与审计日志，便于事后追溯
 */
export default function PurgeItemModal({ item, onClose, onDone }: Props) {
  const [form] = Form.useForm();
  const [submitting, setSubmitting] = useState(false);
  const queryClient = useQueryClient();

  useEffect(() => {
    if (item) {
      form.setFieldsValue({ confirm_name: '', reason: '' });
    }
  }, [item, form]);

  if (!item) return null;

  const submit = async () => {
    // validateFields 失败会抛异常（名称不匹配），必须自己吞掉，
    // 否则会产生未捕获的 Promise rejection（浏览器控制台报错）
    let values: { confirm_name: string; reason?: string };
    try {
      values = await form.validateFields();
    } catch {
      return;
    }
    setSubmitting(true);
    try {
      const res = await itemsApi.purgeItem(item.id, {
        confirm_name: values.confirm_name,
        reason: values.reason || '',
      });
      const im = res.impact || ({} as Record<string, number>);
      message.success(
        `已彻底删除「${item.name}」` +
          (im.stock_qty ? `，原库存 ${im.stock_qty} 已清零` : '') +
          '，条码已释放',
        4,
      );
      queryClient.invalidateQueries({ queryKey: ['items'] });
      onDone?.();
      onClose();
    } catch {
      // 拦截器已统一弹出中文错误
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal
      open
      title={
        <Space>
          <DeleteOutlined style={{ color: '#cf1322' }} />
          <span>彻底删除物品档案</span>
        </Space>
      }
      okText="确认彻底删除"
      cancelText="取消"
      okButtonProps={{ danger: true, loading: submitting }}
      onOk={submit}
      onCancel={onClose}
      width={520}
      destroyOnHidden
    >
      <Alert
        type="error"
        showIcon
        message="此操作不可撤销（但可从「已删除档案」恢复）"
        description={
          <div style={{ fontSize: 13, lineHeight: 1.9 }}>
            <div>· 物品「<b>{item.name}</b>」将从档案名录中消失</div>
            <div>· 条码 <b>{item.barcode || '（无）'}</b> 释放，可重新分配给其他物品</div>
            <div>· 该物品的库存数量将被清零</div>
            <div>· 历史出入库单据与库存流水<strong>全部保留</strong>（单据展示不变）</div>
          </div>
        }
        style={{ marginBottom: 16 }}
      />
      <Form form={form} layout="vertical" requiredMark={false}>
        <Form.Item
          name="confirm_name"
          label={
            <span>
              请输入物品名称 <code style={{ fontSize: 13 }}>{item.name}</code> 以确认
            </span>
          }
          rules={[
            { required: true, message: '请输入物品名称以确认' },
            {
              validator: (_, v) =>
                v === item.name
                  ? Promise.resolve()
                  : Promise.reject(new Error('名称与物品不一致，无法确认')),
            },
          ]}
        >
          <Input placeholder={item.name} autoFocus autoComplete="off" />
        </Form.Item>
        <Form.Item
          name="reason"
          label="删除原因（选填，写入归档与审计日志）"
        >
          <Input.TextArea
            rows={2}
            maxLength={300}
            showCount
            placeholder="如：库存数据胡乱填写，该物品实际不存在"
          />
        </Form.Item>
      </Form>
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
        提示：若只是想把物品从名录里隐藏、保留完整库存记录，请改用「删除」（停用）。
      </Typography.Text>
    </Modal>
  );
}
