import {
  Avatar,
  Button,
  Card,
  Descriptions,
  Form,
  Input,
  Space,
  Tag,
  message,
} from 'antd';
import { LogoutOutlined, KeyOutlined, CameraOutlined } from '@ant-design/icons';
import { useRef, useState } from 'react';
import { useAuth } from '@/hooks/useAuth';
import { changePassword, updateProfile, uploadAvatar } from '@/api/auth';
import { useAuthStore } from '@/stores/authStore';
import PageContainer from '@/components/PageContainer';
import { isMockMode } from '@/api/client';
import AvatarCropModal from '@/pages/AvatarCropModal';

/** 我的（移动端 Tab 第 5 项）：圆形头像、基本资料、改密码、退出登录 */
export default function Me() {
  const { user, roleLabel, logout, isAdmin } = useAuth();
  const setUser = useAuthStore((s) => s.setUser);
  const [form] = Form.useForm();
  const [pwdForm] = Form.useForm();
  const [saving, setSaving] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [avatarSrc, setAvatarSrc] = useState<string | null>(null);
  const [cropFile, setCropFile] = useState<File | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const displayName = user?.display_name ?? '';
  const currentAvatar =
    avatarSrc ?? (user?.avatar_url ?? (user?.has_avatar ? `/api/auth/avatars/${user.id}` : null));

  const doUpload = async (blob: Blob) => {
    if (!user) return;
    setUploading(true);
    try {
      const res = await uploadAvatar(blob);
      const url = res?.avatar_url ?? `/api/auth/avatars/${user.id}?v=${Date.now()}`;
      setAvatarSrc(url);
      setUser({ ...user, has_avatar: true, avatar_url: url });
      message.success('头像已更新');
    } catch (e) {
      message.error((e as Error).message || '头像上传失败');
    } finally {
      setUploading(false);
    }
  };

  const saveProfile = async () => {
    const values = await form.validateFields();
    const phone = (values.username ?? '').trim();
    const cur = user?.username ?? '';
    const payload: { display_name?: string; username?: string; old_password?: string } = {
      display_name: (values.display_name ?? '').trim(),
    };
    if (phone && phone !== cur) {
      payload.username = phone;
      payload.old_password = values.old_password;
    }
    setSaving(true);
    try {
      const updated = await updateProfile(payload);
      if (updated) setUser(updated);
      message.success('资料已保存');
      form.setFieldValue('old_password', '');
    } catch {
      // 拦截器已提示
    } finally {
      setSaving(false);
    }
  };

  const submit = async () => {
    const values = await pwdForm.validateFields();
    if (values.new_password !== values.confirm_password) {
      message.error('两次输入的新密码不一致');
      return;
    }
    setSaving(true);
    try {
      await changePassword(values.old_password, values.new_password);
      message.success('密码已修改，请牢记新密码');
      pwdForm.resetFields();
    } catch {
      // 已提示
    } finally {
      setSaving(false);
    }
  };

  return (
    <PageContainer title="我的">
      <Card size="small" style={{ marginBottom: 12 }}>
        {/* 圆形头像 + 下方显示名字 */}
        <div style={{ textAlign: 'center', padding: '8px 0 4px' }}>
          <div style={{ position: 'relative', display: 'inline-block' }}>
            <Avatar
              size={96}
              src={currentAvatar ?? undefined}
              style={{ background: 'var(--zx-role-admin, var(--zx-seal))', fontSize: 38 }}
            >
              {displayName.slice(0, 1) || '?'}
            </Avatar>
            <Button
              shape="circle"
              size="small"
              icon={<CameraOutlined />}
              loading={uploading}
              onClick={() => fileRef.current?.click()}
              style={{ position: 'absolute', right: -4, bottom: -4, background: '#fff' }}
            />
            <input
              ref={fileRef}
              type="file"
              accept="image/*"
              hidden
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) setCropFile(f);
                e.target.value = '';
              }}
            />
            <AvatarCropModal
              file={cropFile}
              onCancel={() => setCropFile(null)}
              onOk={(blob) => {
                setCropFile(null);
                void doUpload(blob);
              }}
            />
          </div>
          <div style={{ marginTop: 8, fontSize: 16, fontWeight: 600 }}>{displayName}</div>
          <div style={{ marginTop: 2 }}>
            <Tag color={isAdmin ? 'gold' : 'blue'}>{roleLabel}</Tag>
          </div>
        </div>
      </Card>

      <Card size="small" title="账号信息" style={{ marginBottom: 12 }}>
        <Descriptions column={1} size="small">
          <Descriptions.Item label="姓名">{displayName || '—'}</Descriptions.Item>
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

      <Card size="small" title="基本资料" style={{ marginBottom: 12 }}>
        <Form
          form={form}
          layout="vertical"
          style={{ maxWidth: 360 }}
          requiredMark={false}
          initialValues={{ display_name: displayName, username: user?.username ?? '' }}
        >
          <Form.Item
            name="display_name"
            label="姓名"
            rules={[{ required: true, message: '请输入姓名' }]}
          >
            <Input placeholder="请输入姓名" maxLength={50} />
          </Form.Item>
          <Form.Item
            name="username"
            label="手机号（登录账号）"
            rules={[
              {
                validator: (_r, v) =>
                  !v || v === user?.username || /^1\d{10}$/.test(v)
                    ? Promise.resolve()
                    : Promise.reject(new Error('请输入正确的 11 位手机号')),
              },
            ]}
          >
            <Input placeholder="请输入 11 位手机号" maxLength={11} />
          </Form.Item>
          <Form.Item name="old_password" label="确认密码（修改手机号时需验证）">
            <Input.Password placeholder="仅修改手机号时需要填写" autoComplete="current-password" />
          </Form.Item>
          <Button type="primary" loading={saving} onClick={() => void saveProfile()} block>
            保存资料
          </Button>
          <div style={{ marginTop: 6, color: 'var(--zx-text-3, #999)', fontSize: 12 }}>
            手机号是登录账号。修改后需用新手机号登录，各业务系统同步生效。
          </div>
        </Form>
      </Card>

      <Card size="small" title={<span><KeyOutlined /> 修改密码</span>}>
        <Form form={pwdForm} layout="vertical" style={{ maxWidth: 360 }} requiredMark={false}>
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
