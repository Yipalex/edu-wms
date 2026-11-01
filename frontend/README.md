# 教培机构 · 仓储管理系统（前端）

React 18 + TypeScript(strict) + Vite + Ant Design 5 + TanStack Query v5 + zustand + react-router v6。
界面全中文，移动优先（仓库现场站着用手机操作）。

## 启动

```bash
npm install

# 正常开发（后端在 localhost:8080，Vite proxy /api 与 /uploads）
npm run dev

# Mock 模式（无需后端，用真实名录数据演示全部页面）
npm run dev:mock
# 或：npm run dev 后浏览器访问 http://127.0.0.1:5173/?mock=1
# 关闭 mock：URL 加 ?mock=0

npm run build   # tsc -b + vite build
npm run lint    # eslint（零 error）
```

Mock 演示账号：`admin / 123456`（管理员）、`zhangsan / 123456`（仓库操作员）。

## Mock 模式说明

- 开关：环境变量 `VITE_USE_MOCK=true`，或 URL `?mock=1`（记忆到 localStorage，刷新保持；`?mock=0` 关闭）
- 实现：`src/api/client.ts` 的 `request()` 统一出口在 mock 模式下走 `src/mocks/handlers.ts`，不发真实 HTTP
- 数据：`src/mocks/data.ts`，物品取自真实名录 `barcode-tool/output/final/items_from_minglu.csv`（40+ 条真实名称与条码，含外部码 6950898000191 北太墨汁、2 条待编码物品）；库位为真实 6 个（总部仓库 + 金城/社坛/海东/麻章/开发区）；类目为真实 6 类（教材/书籍/辅材/耗材/礼品/其他）；照片为内联 SVG 占位图
- 覆盖接口：auth（login/me/logout/refresh/change-password 走真实路径）、users CRUD、locations、categories（含改数字位二次确认）、barcode-rules、barcode/preview、barcode/allocate、barcode/history、items 列表/详情/新建/编辑/照片、scan/resolve（**四分支全演示**：命中 21010013 / 已合并 21010002 / 旧码停用 21040024 / 未登记任意其他码）、inventory、movements、reports/dashboard、labels/pdf（mock 返回 HTML 预览页代替 PDF）

## 目录结构

```
src/
├── main.tsx / App.tsx        # 入口 + 路由表（React.lazy 分包）
├── api/                      # axios client + 各模块 API + 契约类型
├── stores/                   # zustand：authStore（token/user）、scanStore（扫码上下文）
├── hooks/                    # useAuth、useScanGun（扫码枪）、useCameraScan（摄像头）、usePagination、useIsMobile
├── components/               # PageContainer、BarcodePreview、ItemPhotoWall、ScanInput、StockTable、PermissionGate…
│   └── layout/               # AppLayout（桌面侧边栏 + 移动底部 Tab）、RequireAuth、RoleRoute
├── pages/                    # Login、Dashboard、Scan、Items、ItemDetail、PendingCode、Categories、BarcodeHistory、Labels、Users、Me、Placeholder
├── mocks/                    # Mock 数据与处理器
└── utils/                    # format（金额/日期/千分位）、barcode（码解析/提取）、download
```

## 关键交互（契约第 7 节）

- **扫码枪**（`useScanGun`）：document 级 keydown 累积字符，Enter 或 30ms 静默判定结束；只提取 `[0-9]{8,14}` 连续数字段（防前缀后缀污染与 Mac Dvorak 乱码）；同码 500ms 去重；事件目标为 input/textarea/contenteditable 时不抢焦点
- **摄像头**（`useCameraScan`）：`window.BarcodeDetector` 优先，降级 `html5-qrcode`；非 HTTPS/localhost 显示中文提示引导用扫码枪；必须用户手势点击「打开摄像头」（iOS Safari getUserMedia 限制）；支持前后摄切换；扫到震动
- **移动端**（<768px）：底部 TabBar（扫码/物品/单据/库存/我的，扫码第一入口）；物品档案窄屏转卡片列表；扫码页底部固定四个大操作按钮
- **权限**：管理员专属页（类目/条码历史/用户/去重）对 operator 隐藏菜单入口，直接访问显示「无权限」页

## 图表选型

仪表盘「各库位库存金额」用**纯 div 条形图**（CSS 渐变条 + 网格布局），不引入 @ant-design/plots 等重型图表库——数据只有 6 个库位，div 足够且包体最小。

## 部署约定

- `base: '/'`（新子域名根路径部署），BrowserRouter 无 basename
- API base 为相对路径 `/api`；生产由容器内 nginx 反代到后端（同域，无 CORS）；开发由 Vite proxy 到 `http://localhost:8080`
- `frontend/Dockerfile` 与 `nginx.conf` 由 deploy 工作流维护，不在本目录职责内
