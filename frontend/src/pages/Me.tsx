import { Button, Card, Descriptions, Form, Input, Space, Tag, message } from 'antd';
import { LogoutOutlined, KeyOutlined } from '@ant-design/icons';
import { useState } from 'react';
import { useAuth } from '@/hooks/useAuth';
import { changePassword } from '@/api/auth';
import PageContainer from '@/components/PageContainer';
import { isMockMode } from '@/api/client';

/** 我的（移动端 Tab 第 5 项）：当前用户信息、改密码、退出登录 */
export default function Me() {
  const { user, roleLabel, logout, isAdmin } = useAuth();
  const [form] = Form.useForm();
  const [saving, setSaving] = useState(false);

  const submit = async () => {
    const values = await form.validateFields();
    if (values.new_password !== values.confirm_password) {
      message.error('两次输入的新密码不一致');
      return;
    }
    setSaving(true);
    try {
      await changePassword(values.old_password, values.new_password);
      message.success('密码已修改，请牢记新密码');
      form.resetFields();
    } catch {
      // 已提示
    } finally {
      setSaving(false);
    }
  };

  return (
    <PageContainer title="我的">
      <Card size="small" title="账号信息" style={{ marginBottom: 12 }}>
        <Descriptions column={1} size="small">
          <Descriptions.Item label="姓名">{user?.display_name ?? '—'}</Descriptions.Item>
          <Descriptions.Item label="用户名">{user?.username ?? '—'}</Descriptions.Item>
          <Descriptions.Item label="角色">
            <Tag color={isAdmin ? 'gold' : 'blue'}>{roleLabel}</Tag>
          </Descriptions.Item>
          {isMockMode && (
            <Descriptions.Item label="模式">
              <Tag color="purple">演示（Mock）模式</Tag>
            </Descriptions.Item>
          )}
        </Descriptions>
        <Space style={{ marginTop: 8 }}>
          <Button danger icon={<LogoutOutlined />} onClick={() => void logout()}>
            退出登录
          </Button>
        </Space>
      </Card>

      <Card size="small" title={<span><KeyOutlined /> 修改密码</span>}>
        <Form form={form} layout="vertical" style={{ maxWidth: 360 }} requiredMark={false}>
          <Form.Item
            name="old_password"
            label="当前密码"
            rules={[{ required: true, message: '请输入当前密码' }]}
          >
            <Input.Password autoComplete="current-password" placeholder="当前密码" />
          </Form.Item>
          <Form.Item
            name="new_password"
            label="新密码"
            rules={[
              { required: true, message: '请输入新密码' },
              { min: 6, message: '新密码至少 6 位' },
            ]}
          >
            <Input.Password autoComplete="new-password" placeholder="至少 6 位" />
          </Form.Item>
          <Form.Item
            name="confirm_password"
            label="确认新密码"
            rules={[{ required: true, message: '请再次输入新密码' }]}
          >
            <Input.Password autoComplete="new-password" placeholder="再次输入新密码" />
          </Form.Item>
          <Button type="primary" loading={saving} onClick={() => void submit()} block>
            确认修改
          </Button>
        </Form>
      </Card>
    </PageContainer>
  );
}
