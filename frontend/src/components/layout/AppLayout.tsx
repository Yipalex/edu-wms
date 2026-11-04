import { useEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { Grid } from 'antd';
import {
  AppstoreOutlined,
  BellOutlined,
  DashboardOutlined,
  DownOutlined,
  FileTextOutlined,
  HistoryOutlined,
  InboxOutlined,
  PrinterOutlined,
  ScanOutlined,
  SettingOutlined,
  TagsOutlined,
  TeamOutlined,
  UserOutlined,
  LogoutOutlined,
  MergeCellsOutlined,
  DatabaseOutlined,
  SwapOutlined,
  BarChartOutlined,
  DeleteOutlined,
} from '@ant-design/icons';
import { Outlet, useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from '@/hooks/useAuth';
import { getMe } from '@/api/auth';
import { ROLE_LABELS, useAuthStore } from '@/stores/authStore';

const { useBreakpoint } = Grid;

/** 系统切换器（全系统统一配置） */
const ZX_SYSTEMS = [
  { id: 'yj', name: '业绩登记系统', domain: 'yj.zexishuhua.com', color: 'var(--zx-sys-yj)', url: 'https://yj.zexishuhua.com/' },
  { id: 'quan', name: '券类管理系统', domain: 'quan.zexishuhua.com', color: 'var(--zx-sys-quan)', url: 'https://quan.zexishuhua.com/' },
  { id: 'jz', name: '教资报名系统', domain: 'jz.zexishuhua.com', color: 'var(--zx-sys-jz)', url: 'https://jz.zexishuhua.com/' },
  { id: 'sf', name: '评测报告系统', domain: 'sf.zexishuhua.com', color: 'var(--zx-sys-sf)', url: 'https://sf.zexishuhua.com/' },
  { id: 'wms', name: '仓库管理系统', domain: 'wms.zexishuhua.com', color: 'var(--zx-sys-wms)', url: 'https://wms.zexishuhua.com/' },
  { id: 'zc', name: '固定资产管理', domain: 'zc.zexishuhua.com', color: 'var(--zx-sys-zc)', url: 'https://zc.zexishuhua.com/' },
];
const CURRENT_SYSTEM = ZX_SYSTEMS.find((s) => s.id === 'wms')!;

/** 全部菜单（按角色过滤在下方处理） */
const ALL_MENUS: { key: string; label: string; group?: string; adminOnly?: boolean; superOnly?: boolean }[] = [
  { key: '/', label: '仪表盘', group: '工作台' },
  { key: '/scan', label: '扫码工作台', group: '工作台' },
  { key: '/items', label: '物品档案', group: '物品与条码' },
  { key: '/items/pending-code', label: '待编码物品', group: '物品与条码' },
  { key: '/items/duplicates', label: '去重合并', group: '物品与条码', adminOnly: true },
  { key: '/items/deleted', label: '已删除档案', group: '物品与条码', superOnly: true },
  { key: '/labels', label: '标签打印', group: '物品与条码' },
  { key: '/inbound', label: '入库单', group: '出入库' },
  { key: '/outbound', label: '出库/调拨', group: '出入库' },
  { key: '/returns', label: '退库单', group: '出入库' },
  { key: '/stocktakes', label: '盘点', group: '出入库' },
  { key: '/inventory', label: '库存查询', group: '库存与报表' },
  { key: '/movements', label: '库存流水', group: '库存与报表' },
  { key: '/reports', label: '报表', group: '库存与报表' },
  { key: '/categories', label: '类目与编码规则', group: '系统设置', adminOnly: true },
  { key: '/barcode/history', label: '条码变更历史', group: '系统设置', adminOnly: true },
  { key: '/users', label: '用户与权限', group: '系统设置', adminOnly: true },
];

const PATH_ICONS: Record<string, ReactNode> = {
  '/': <DashboardOutlined />,
  '/scan': <ScanOutlined />,
  '/items': <AppstoreOutlined />,
  '/items/pending-code': <TagsOutlined />,
  '/items/duplicates': <MergeCellsOutlined />,
  '/items/deleted': <DeleteOutlined />,
  '/labels': <PrinterOutlined />,
  '/inbound': <InboxOutlined />,
  '/outbound': <SwapOutlined />,
  '/returns': <FileTextOutlined />,
  '/stocktakes': <FileTextOutlined />,
  '/inventory': <DatabaseOutlined />,
  '/movements': <HistoryOutlined />,
  '/reports': <BarChartOutlined />,
  '/categories': <SettingOutlined />,
  '/barcode/history': <HistoryOutlined />,
  '/users': <TeamOutlined />,
};

/** 移动端底部 Tab（扫码第一入口） */
const MOBILE_TABS: { key: string; label: string; icon: ReactNode }[] = [
  { key: '/scan', label: '扫码', icon: <ScanOutlined /> },
  { key: '/items', label: '物品', icon: <AppstoreOutlined /> },
  { key: '/inbound', label: '单据', icon: <FileTextOutlined /> },
  { key: '/inventory', label: '库存', icon: <DatabaseOutlined /> },
  { key: '/me', label: '我的', icon: <UserOutlined /> },
];

export default function AppLayout() {
  const navigate = useNavigate();
  const location = useLocation();
  const { user, logout, isAdmin, isSuperAdmin, roleLabel } = useAuth();
  const screens = useBreakpoint();
  const isMobile = !screens.md; // <768px
  const [sysOpen, setSysOpen] = useState(false);
  const sysRef = useRef<HTMLDivElement>(null);

  // 启动时从服务端刷新当前用户（角色提升/头像修改后无需重新登录即可生效）
  const setUser = useAuthStore((s) => s.setUser);
  useEffect(() => {
    getMe()
      .then((me) => setUser({ ...useAuthStore.getState().user, ...me }))
      .catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 点击外部关闭系统切换菜单
  useEffect(() => {
    if (!sysOpen) return;
    const onDocClick = (e: MouseEvent) => {
      if (sysRef.current && !sysRef.current.contains(e.target as Node)) {
        setSysOpen(false);
      }
    };
    document.addEventListener('mousedown', onDocClick);
    return () => document.removeEventListener('mousedown', onDocClick);
  }, [sysOpen]);

  const visibleMenus = useMemo(
    () => ALL_MENUS.filter((m) => {
      if (m.superOnly) return isSuperAdmin;
      if (m.adminOnly) return isAdmin;
      return true;
    }),
    [isAdmin, isSuperAdmin],
  );

  const navGroups = useMemo(() => {
    const groups = Array.from(new Set(visibleMenus.map((m) => m.group!)));
    return groups.map((g) => ({
      label: g,
      items: visibleMenus.filter((m) => m.group === g),
    }));
  }, [visibleMenus]);

  const selectedKey = useMemo(() => {
    const { pathname } = location;
    if (pathname === '/') return '/';
    // 最长前缀匹配（/items/123 → /items）
    const matched = ALL_MENUS.map((m) => m.key)
      .filter((k) => k !== '/' && pathname.startsWith(k))
      .sort((a, b) => b.length - a.length)[0];
    return matched ?? pathname;
  }, [location]);

  const displayName = user?.display_name ?? user?.username ?? '';
  const avatarChar = displayName.slice(0, 1) || '泽';
  // 圆形头像：有头像图则显示图片（失败自动回退到名字首字）
  const avatarImg = user?.avatar_url || (user?.has_avatar ? `/api/auth/avatars/${user.id}` : '');

  return (
    <>
      {/* ============ 全局顶栏 ============ */}
      <header className="zx-topbar">
        <a className="zx-topbar__brand" href="/" onClick={(e) => { e.preventDefault(); navigate('/'); }}>
          <img src="/img/zexi-logo.png?v=20261104d" alt="" className="zx-topbar__logo" />
          泽曦书画
        </a>
        <div className="zx-topbar__spacer" />
        <div className={`zx-sys-switch${sysOpen ? ' zx-sys-switch--open' : ''}`} ref={sysRef}>
          <button
            type="button"
            className="zx-sys-switch__btn"
            onClick={() => setSysOpen((v) => !v)}
            aria-haspopup="menu"
            aria-expanded={sysOpen}
          >
            <span className="zx-sys-dot" style={{ background: CURRENT_SYSTEM.color }} />
            {CURRENT_SYSTEM.name}
            <span className="zx-sys-switch__domain zx-topbar__sys-domain" style={{ color: 'var(--zx-dark-text-2)', fontSize: 11 }}>
              {CURRENT_SYSTEM.domain}
            </span>
            <DownOutlined className="zx-sys-switch__caret" />
          </button>
          {sysOpen && (
            <div className="zx-sys-switch__menu" role="menu">
              {ZX_SYSTEMS.map((s) => (
                <a
                  key={s.id}
                  className={`zx-sys-switch__item${s.id === CURRENT_SYSTEM.id ? ' is-current' : ''}`}
                  href={s.url}
                  onClick={(e) => {
                    if (s.id === CURRENT_SYSTEM.id) {
                      e.preventDefault();
                      setSysOpen(false);
                    }
                  }}
                >
                  <span className="zx-sys-dot" style={{ background: s.color }} />
                  {s.name}
                  <small>{s.domain}</small>
                </a>
              ))}
            </div>
          )}
        </div>
        <button type="button" className="zx-icon-btn" aria-label="通知">
          <BellOutlined />
        </button>
        <div className="zx-user">
          <span className="zx-user__avatar">
            {avatarImg ? (
              <img src={avatarImg} alt="" onError={(e) => { (e.target as HTMLImageElement).style.display = 'none'; }} />
            ) : null}
            <span className="zx-user__avatar-txt">{avatarChar}</span>
          </span>
          <span className="zx-user__name">{displayName}</span>
          <span className="zx-user__role">{roleLabel || ROLE_LABELS[user?.role ?? 'operator']}</span>
        </div>
      </header>

      {/* ============ 左侧导航（桌面） ============ */}
      {!isMobile && (
        <aside className="zx-sidebar">
          {navGroups.map((g) => (
            <div className="zx-nav-group" key={g.label}>
              <div className="zx-nav-group__label">{g.label}</div>
              {g.items.map((m) => (
                <a
                  key={m.key}
                  className={`zx-nav-item${selectedKey === m.key ? ' is-active' : ''}`}
                  href={m.key}
                  onClick={(e) => {
                    e.preventDefault();
                    navigate(m.key);
                  }}
                >
                  <span className="zx-nav-item__icon">{PATH_ICONS[m.key]}</span>
                  {m.label}
                </a>
              ))}
            </div>
          ))}
          <div className="zx-sidebar__user">
            <span className="zx-user__avatar">
            {avatarImg ? (
              <img src={avatarImg} alt="" onError={(e) => { (e.target as HTMLImageElement).style.display = 'none'; }} />
            ) : null}
            <span className="zx-user__avatar-txt">{avatarChar}</span>
          </span>
            <span>
              <div className="zx-sidebar__user-name">{displayName}</div>
              <div className="zx-sidebar__user-role">
                {roleLabel || ROLE_LABELS[user?.role ?? 'operator']}
              </div>
            </span>
            <button
              type="button"
              className="zx-sidebar__logout"
              aria-label="退出登录"
              onClick={() => void logout()}
            >
              <LogoutOutlined />
            </button>
          </div>
        </aside>
      )}

      {/* ============ 内容区 ============ */}
      <main className="zx-main">
        <div className="zx-content">
          <Outlet />
        </div>
      </main>

      {/* ============ 移动端底部标签栏 ============ */}
      {isMobile && (
        <nav className="zx-tabbar" aria-label="底部导航">
          {MOBILE_TABS.map((t) => {
            const active =
              t.key === '/me'
                ? location.pathname === '/me'
                : location.pathname === t.key || location.pathname.startsWith(t.key + '/');
            return (
              <button
                key={t.key}
                type="button"
                className={`zx-tabbar__item${active ? ' is-active' : ''}`}
                onClick={() => navigate(t.key)}
                aria-label={t.label}
              >
                <span className="zx-tabbar__icon">{t.icon}</span>
                <span>{t.label}</span>
              </button>
            );
          })}
        </nav>
      )}
    </>
  );
}
