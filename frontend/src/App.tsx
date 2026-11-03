import React, { Suspense } from 'react';
import { Navigate, Route, Routes } from 'react-router-dom';
import { Spin } from 'antd';
import AppLayout from '@/components/layout/AppLayout';
import RequireAuth from '@/components/layout/RequireAuth';
import RoleRoute from '@/components/layout/RoleRoute';

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
          <Route path="/" element={<Dashboard />} />
          <Route path="/scan" element={<Scan />} />
          <Route path="/items" element={<Items />} />
          <Route path="/items/new" element={<ItemDetail />} />
          <Route path="/items/pending-code" element={<PendingCode />} />
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
          <Route path="/items/:id" element={<ItemDetail />} />
          <Route path="/labels" element={<Labels />} />
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
          <Route path="/stocktakes" element={<Stocktakes />} />
          <Route path="/stocktakes/:id" element={<StocktakeExec />} />
          <Route path="/inventory" element={<Inventory />} />
          <Route path="/movements" element={<Movements />} />
          <Route path="/reports" element={<Reports />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </Suspense>
  );
}
