import React, { Suspense } from 'react';
import { Navigate, Route, Routes } from 'react-router-dom';
import { Spin } from 'antd';
import AppLayout from '@/components/layout/AppLayout';
import RequireAuth from '@/components/layout/RequireAuth';
import RoleRoute from '@/components/layout/RoleRoute';
import { useAuthStore } from '@/stores/authStore';

const Login = React.lazy(() => import('@/pages/Login'));
const Dashboard = React.lazy(() => import('@/pages/Dashboard'));
const Scan = React.lazy(() => import('@/pages/Scan'));
const Items = React.lazy(() => import('@/pages/Items'));
const ItemDetail = React.lazy(() => import('@/pages/ItemDetail'));
const PendingCode = React.lazy(() => import('@/pages/PendingCode'));
const Categories = React.lazy(() => import('@/pages/Categories'));
const BarcodeHistory = React.lazy(() => import('@/pages/BarcodeHistory'));
const Labels = React.lazy(() => import('@/pages/Labels'));
const Users = React.lazy(() => import('@/pages/Users'));
const Me = React.lazy(() => import('@/pages/Me'));
const Inbound = React.lazy(() => import('@/pages/Inbound'));
const Outbound = React.lazy(() => import('@/pages/Outbound'));
const Returns = React.lazy(() => import('@/pages/Returns'));
const Stocktakes = React.lazy(() => import('@/pages/Stocktakes'));
const StocktakeExec = React.lazy(() => import('@/pages/StocktakeExec'));
const Inventory = React.lazy(() => import('@/pages/Inventory'));
const Movements = React.lazy(() => import('@/pages/Movements'));
const Reports = React.lazy(() => import('@/pages/Reports'));
const Duplicates = React.lazy(() => import('@/pages/Duplicates'));
const DeletedItems = React.lazy(() => import('@/pages/DeletedItems'));

function PageLoading() {
  return (
    <div style={{ textAlign: 'center', padding: '80px 0' }}>
      <Spin size="large" />
      <div style={{ marginTop: 12, color: '#8A847B' }}>页面加载中…</div>
    </div>
  );
}

/** 首页：教师角色的工作入口是扫码工作台（仪表盘含全校金额，对教师不可用） */
function HomeEntry() {
  const role = useAuthStore((s) => s.user?.role);
  if (role === 'teacher') return <Navigate to="/scan" replace />;
  return <Dashboard />;
}

/** 教师禁入页：直接访问时统一送回扫码工作台（菜单已隐藏，这里兜底深链） */
function NoTeacher({ children }: { children: React.ReactNode }) {
  const role = useAuthStore((s) => s.user?.role);
  if (role === 'teacher') return <Navigate to="/scan" replace />;
  return <>{children}</>;
}

export default function App() {
  return (
    <Suspense fallback={<PageLoading />}>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route
          element={
            <RequireAuth>
              <AppLayout />
            </RequireAuth>
          }
        >
          <Route path="/" element={<HomeEntry />} />
          <Route path="/scan" element={<Scan />} />
          <Route
            path="/items"
            element={<NoTeacher><Items /></NoTeacher>}
          />
          <Route
            path="/items/new"
            element={<NoTeacher><ItemDetail /></NoTeacher>}
          />
          <Route
            path="/items/pending-code"
            element={<NoTeacher><PendingCode /></NoTeacher>}
          />
          <Route
            path="/items/duplicates"
            element={
              <RoleRoute role="admin">
                <Duplicates />
              </RoleRoute>
            }
          />
          <Route
            path="/items/deleted"
            element={
              <RoleRoute role="superadmin">
                <DeletedItems />
              </RoleRoute>
            }
          />
          <Route
            path="/items/:id"
            element={<NoTeacher><ItemDetail /></NoTeacher>}
          />
          <Route
            path="/labels"
            element={<NoTeacher><Labels /></NoTeacher>}
          />
          <Route
            path="/categories"
            element={
              <RoleRoute role="admin">
                <Categories />
              </RoleRoute>
            }
          />
          <Route
            path="/barcode/history"
            element={
              <RoleRoute role="admin">
                <BarcodeHistory />
              </RoleRoute>
            }
          />
          <Route
            path="/users"
            element={
              <RoleRoute role="admin">
                <Users />
              </RoleRoute>
            }
          />
          <Route path="/me" element={<Me />} />
          {/* 业务单据与查询页面 */}
          <Route path="/inbound" element={<Inbound />} />
          <Route path="/outbound" element={<Outbound />} />
          <Route path="/returns" element={<Returns />} />
          <Route
            path="/stocktakes"
            element={<NoTeacher><Stocktakes /></NoTeacher>}
          />
          <Route
            path="/stocktakes/:id"
            element={<NoTeacher><StocktakeExec /></NoTeacher>}
          />
          <Route path="/inventory" element={<Inventory />} />
          <Route
            path="/movements"
            element={<NoTeacher><Movements /></NoTeacher>}
          />
          <Route
            path="/reports"
            element={<NoTeacher><Reports /></NoTeacher>}
          />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </Suspense>
  );
}
