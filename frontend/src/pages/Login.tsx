import { useRef, useState } from 'react';
import { Button, Form, Input, Alert, Tag } from 'antd';
import { LockOutlined, UserOutlined } from '@ant-design/icons';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useAuth } from '@/hooks/useAuth';
import { isMockMode } from '@/api/client';
import CatWatch from '@/components/CatWatch';

interface LoginForm {
  username: string;
  password: string;
}

export default function Login() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { login } = useAuth();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  // 登录卡片容器引用：猫用来定位聚焦的输入框
  const cardRef = useRef<HTMLDivElement>(null);

  const onFinish = async (values: LoginForm) => {
    setLoading(true);
    setError(null);
    try {
      await login(values.username, values.password);
      const redirect = searchParams.get('redirect');
      navigate(redirect ? decodeURIComponent(redirect) : '/', { replace: true });
    } catch (e) {
      setError(e instanceof Error ? e.message : '登录失败，请重试');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="login-page">
      <div className="login-wrap">
        {/* 左：陪伴猫（眼珠跟随鼠标，聚焦输入框时盯向你） */}
        <div className="login-cat" aria-hidden>
          <div className="cat-bubble">喵，欢迎回来</div>
          <CatWatch formRef={cardRef} />
        </div>

        {/* 中：品牌标题（桌面在卡片上方；手机在猫上方） */}
        <div className="login-brand">
          <img src="/img/zexi-logo.png" alt="泽曦书画" className="login-brand__logo" />
          <h1>泽曦书画</h1>
          <p className="login-subtitle">仓储管理系统</p>
        </div>

        {/* 右：登录框（用户要求往右移） */}
        <div className="login-right" ref={cardRef}>
          <div className="login-card">
            {error && <Alert type="error" message={error} showIcon style={{ marginBottom: 16 }} />}
            {isMockMode && (
              <Alert
                type="info"
                showIcon
                style={{ marginBottom: 16 }}
                message={
                  <span>
                    演示模式 <Tag color="blue">mock</Tag> 账号：admin / 123456
                  </span>
                }
              />
            )}
            <Form<LoginForm> layout="vertical" onFinish={onFinish} size="large" requiredMark={false}>
              <Form.Item
                name="username"
                label="用户名"
                rules={[{ required: true, message: '请输入用户名' }]}
              >
                <Input prefix={<UserOutlined />} placeholder="请输入用户名" autoComplete="username" />
              </Form.Item>
              <Form.Item
                name="password"
                label="密码"
                rules={[{ required: true, message: '请输入密码' }]}
              >
                <Input.Password
                  prefix={<LockOutlined />}
                  placeholder="请输入密码"
                  autoComplete="current-password"
                />
              </Form.Item>
              <Form.Item style={{ marginBottom: 0 }}>
                <Button type="primary" htmlType="submit" block loading={loading} size="large">
                  登 录
                </Button>
              </Form.Item>
            </Form>
          </div>
        </div>
      </div>
    </div>
  );
}
