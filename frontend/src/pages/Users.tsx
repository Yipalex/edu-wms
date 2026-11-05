import { useState } from 'react';
import {
  Button,
  Card,
  Form,
  Input,
  Modal,
  Popconfirm,
  Select,
  Space,
  Switch,
  Table,
  Tag,
  message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { PlusOutlined } from '@ant-design/icons';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import * as usersApi from '@/api/users';
import * as categoriesApi from '@/api/categories';
import type { User, UserRole } from '@/api/types';
import PageContainer from '@/components/PageContainer';
import { ROLE_LABELS } from '@/stores/authStore';
import { fmtDateTime } from '@/utils/format';

interface UserFormValues {
  username: string;
  password?: string;
  display_name: string;
  role: UserRole;
  home_location_id?: number | null;
  is_active?: boolean;
}

/** 用户与权限（仅管理员） */
export default function Users() {
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState<User | null>(null);
  const [creating, setCreating] = useState(false);
  const [form] = Form.useForm<UserFormValues>();
  const [saving, setSaving] = useState(false);

  const { data: users, isLoading } = useQuery({
    queryKey: ['users'],
    queryFn: () => usersApi.listUsers(),
  });

  const { data: locations } = useQuery({
    queryKey: ['locations'],
    queryFn: () => categoriesApi.listLocations(),
  });

  const openCreate = () => {
    setEditing(null);
    setCreating(true);
    form.resetFields();
    form.setFieldsValue({ role: 'operator', is_active: true });
  };

  const openEdit = (u: User) => {
    setCreating(false);
    setEditing(u);
    form.setFieldsValue({
      username: u.username,
      display_name: u.display_name,
      role: u.role,
      home_location_id: u.home_location_id,
      is_active: u.is_active,
    });
  };

  const close = () => {
    setEditing(null);
    setCreating(false);
  };

  const submit = async () => {
    const values = await form.validateFields();
    setSaving(true);
    try {
      if (creating) {
        await usersApi.createUser({
          username: values.username,
          password: values.password!,
          display_name: values.display_name,
          role: values.role,
          home_location_id: values.home_location_id ?? null,
        });
        message.success('用户已创建');
      } else if (editing) {
        await usersApi.updateUser(editing.id, {
          display_name: values.display_name,
          role: values.role,
          home_location_id: values.home_location_id ?? null,
          is_active: values.is_active,
          ...(values.password ? { password: values.password } : {}),
        });
        message.success('已保存');
      }
      close();
      queryClient.invalidateQueries({ queryKey: ['users'] });
    } catch {
      // 拦截器已提示
    } finally {
      setSaving(false);
    }
  };

  const columns: ColumnsType<User> = [
    { title: '用户名', dataIndex: 'username', width: 120 },
    { title: '姓名', dataIndex: 'display_name', width: 120 },
    {
      title: '角色',
      dataIndex: 'role',
      width: 110,
      render: (v: UserRole) => (
        <Tag color={v === 'superadmin' ? 'red' : v === 'admin' ? 'gold' : 'blue'}>
          {ROLE_LABELS[v]}
        </Tag>
      ),
    },
    {
      title: '默认库位',
      dataIndex: 'home_location_id',
      width: 120,
      render: (v: number | null) => locations?.find((l) => l.id === v)?.name ?? '—',
    },
    {
      title: '状态',
      dataIndex: 'is_active',
      width: 80,
      render: (v: boolean) => (v ? <Tag color="green">正常</Tag> : <Tag color="red">已停用</Tag>),
    },
    {
      title: '最近登录',
      dataIndex: 'last_login_at',
      width: 150,
      render: (v: string | null) => fmtDateTime(v),
    },
    {
      title: '操作',
      key: 'actions',
      width: 140,
      render: (_, u) => (
        <Space size={4}>
          <Button type="link" size="small" onClick={() => openEdit(u)}>
            编辑
          </Button>
          {u.is_active ? (
            <Popconfirm title={`确定停用「${u.display_name}」？`} onConfirm={async () => {
              await usersApi.updateUser(u.id, { is_active: false });
              message.success('已停用');
              queryClient.invalidateQueries({ queryKey: ['users'] });
            }}>
              <Button type="link" size="small" danger>
                停用
              </Button>
            </Popconfirm>
          ) : (
            <Button
              type="link"
              size="small"
              onClick={async () => {
                await usersApi.updateUser(u.id, { is_active: true });
                message.success('已启用');
                queryClient.invalidateQueries({ queryKey: ['users'] });
              }}
            >
              启用
            </Button>
          )}
        </Space>
      ),
    },
  ];

  return (
    <PageContainer
      title="用户与权限"
      description="管理员可配置类目/编码规则/条码历史/合并；仓库操作员负责日常出入库与盘点"
      extra={
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
          新建用户
        </Button>
      }
    >
      <Card size="small" styles={{ body: { padding: 0 } }}>
        <Table<User>
          rowKey="id"
          columns={columns}
          dataSource={users ?? []}
          loading={isLoading}
          size="middle"
          pagination={false}
          scroll={{ x: 800 }}
        />
      </Card>

      <Modal
        open={creating || !!editing}
        title={creating ? '新建用户' : `编辑用户「${editing?.username ?? ''}」`}
        onOk={() => void submit()}
        onCancel={close}
        okText="保存"
        cancelText="取消"
        confirmLoading={saving}
        destroyOnClose
      >
        <Form form={form} layout="vertical" preserve={false}>
          <Form.Item
            name="username"
            label="用户名"
            rules={[{ required: true, message: '请输入用户名' }]}
          >
            <Input disabled={!creating} placeholder="登录用，建议拼音" maxLength={50} />
          </Form.Item>
          <Form.Item
            name="password"
            label={creating ? '初始密码' : '重置密码（留空则不修改）'}
            rules={creating ? [{ required: true, message: '请输入初始密码' }, { min: 6, message: '密码至少 6 位' }] : [{ min: 6, message: '密码至少 6 位' }]}
          >
            <Input.Password placeholder="至少 6 位" autoComplete="new-password" />
          </Form.Item>
          <Form.Item
            name="display_name"
            label="姓名"
            rules={[{ required: true, message: '请输入姓名' }]}
          >
            <Input maxLength={50} />
          </Form.Item>
          <Form.Item name="role" label="角色" rules={[{ required: true }]} tooltip="教师：只能看到自己校区的库存数量与建议售价，只能进行出库/入库/退库；所属校区在下方「默认库位」绑定">
            <Select
              options={[
                { value: 'superadmin', label: '超级管理员（含彻底删除物品档案）' },
                { value: 'admin', label: '管理员' },
                { value: 'operator', label: '仓库操作员' },
                { value: 'teacher', label: '教师（仅本校区出入库）' },
              ]}
            />
          </Form.Item>
          <Form.Item name="home_location_id" label="所属校区 / 默认库位" tooltip="教师角色必填：决定该教师能看到哪个校区的库存与单据">
            <Select
              allowClear
              placeholder="选择校区/库位"
              options={(locations ?? []).map((l) => ({ value: l.id, label: l.name }))}
            />
          </Form.Item>
          {!creating && (
            <Form.Item name="is_active" label="启用状态" valuePropName="checked">
              <Switch checkedChildren="正常" unCheckedChildren="停用" />
            </Form.Item>
          )}
        </Form>
      </Modal>
    </PageContainer>
  );
}
