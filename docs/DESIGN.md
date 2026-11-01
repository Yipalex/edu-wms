# 教培机构 · 仓储管理系统（WMS）设计契约 v1

> 本文件是**唯一契约**。后端 / 前端 / 部署 / 迁移四个工作流都以本文为准，不得各自臆造表名、字段名、路由。
> 需要变更时改本文并同步通知其他工作流。

## 0. 目标与边界

**替代**：腾讯文档智能表格「教培机构仓储管理」+ Python 脚本打印不干胶。

**范围内**：物品档案（含照片）、类目、条码生成/重分配/变更历史、标签打印、入库、出库（调拨）、退库、盘点、库存查询、报表导出、扫码录入（枪+摄像头）、登录与角色权限、易知鸟入库模板导出。

**范围外（明确不做）**：
- ❌ 售卖/销售订单。学员购买学杂仍走易知鸟 ERP，易知鸟「学员中心」自动扣库存。本系统只管仓储侧。
- ❌ 易知鸟双向 API 对接（易知鸟无开放 API）。仅提供**导出易知鸟库存导入模板 xlsx**（9 列）供人工导入。
- ❌ 财务/应收应付。

**组织**：总部仓库（前置仓，采购先到此）+ 5 校区（金城/社坛/海东/麻章/开发区）。货品流向：总部 → 校区（调拨出库）；校区 → 总部（退库）。

## 1. 技术选型

| 层 | 选型 | 理由 |
|---|---|---|
| 后端 | **Python 3.11 + FastAPI + SQLAlchemy 2.0 + Alembic** | 现有条码/标签渲染代码是 Python（python-barcode + Pillow），可直接移植，版式参数是踩坑换来的（300dpi、A4 像素尺寸、条码尺寸上限 507×202px、Hiragino W6 字体索引），不重写 |
| 数据库 | **PostgreSQL 16**（独立容器 + 独立数据卷） | 并发扫码写库存需要事务与行锁；用户 VPS 上已有其他业务数据库，必须物理隔离，不复用 |
| 前端 | **React 18 + TypeScript + Vite + Ant Design 5 + TanStack Query + zustand** | antd 表格/表单/移动端自适应成熟，中文生态好，内部系统开发效率高 |
| 条码预览 | 前端 **jsbarcode**（Code128 SVG，即时预览） | 无需请求后端 |
| 标签 PDF | 后端 **Pillow**（移植现有 layout 逻辑） | 打印精度与可扫性由后端保证，前端不管 |
| 摄像头扫码 | **html5-qrcode**（内含 zxing），BarcodeDetector 优先降级 | iOS Safari 不支持 BarcodeDetector，需降级 |
| 认证 | **JWT**（access 2h + refresh 7d），passlib[bcrypt] | 无第三方依赖，内部系统够用 |
| 部署 | **Docker Compose**（独立 bridge 网络 + 独立卷）+ 宿主机 nginx 反代 + Let's Encrypt | 与现有业务系统零冲突 |

## 2. 编码规则（必须 100% 兼容存量）

**8 位纯数字** = `"2"` + 地区码(2) + 分类位(1) + 流水(4)，如 `21010001`。

- 首位 `2`：国际店内码惯例，避开 EAN-13（国内 690-699 开头）
- 地区码：`10` = 湛江（可配置，当前唯一取值）
- 分类位：`1`教材 / `2`书籍 / `3`辅材 / `4`耗材 / `5`礼品 / `9`其他
- 流水：4 位，**按分类独立递增**，从 0001 起
- **一物一码，不含校区**（同物同码；校区只是库存维度）
- 约束来源：易知鸟「条形编码」字段**只接受纯数字**（字母和 `-` 被拒）→ 这是历史硬约束，编码规则配置界面必须校验「只允许数字前缀」

**外部码例外**：商品原装 EAN-13（如 `6950898000191` 北太墨汁）直接沿用，**不套本机构码**。判定规则：
- `is_internal(code)` = 长度 8 且以配置的 prefix(`2`) 开头且全数字
- 内部码：可解析地区/分类/流水，可按规则生成
- 外部码：只校验「纯数字 + 长度 8~14 + 全局唯一」，不解析、不参与流水分配

**当前各分类流水已用量**（种子值，迁移时按存量最大值初始化）：教材 1→0032、书籍 2→0000、辅材 3→0042、耗材 4→0055、礼品 5→0010、其他 9→0014。

## 3. 数据库设计（PostgreSQL DDL）

命名规范：表名复数下划线，主键 `id BIGSERIAL`，时间戳 `created_at/updated_at TIMESTAMPTZ DEFAULT now()`，软删除用 `status`/`deleted_at` 不用物理删除。

```sql
-- ========== 枚举类型 ==========
CREATE TYPE user_role      AS ENUM ('admin', 'operator');
CREATE TYPE item_status    AS ENUM ('active', 'merged', 'retired');
CREATE TYPE print_mode     AS ENUM ('label', 'scan_card');   -- 贴标 / 扫码卡
CREATE TYPE doc_type       AS ENUM ('inbound','outbound','return','transfer','stocktake','adjust');
CREATE TYPE barcode_change AS ENUM ('assign','reassign','merge_retire','manual_fix','import');
CREATE TYPE stocktake_state AS ENUM ('draft','counting','done');
CREATE TYPE return_state   AS ENUM ('pending','accepted','rejected');
CREATE TYPE doc_state      AS ENUM ('draft','posted','voided');   -- posted=已过账影响库存

-- ========== 用户与权限 ==========
CREATE TABLE users (
  id            BIGSERIAL PRIMARY KEY,
  username      VARCHAR(50)  NOT NULL UNIQUE,
  password_hash VARCHAR(255) NOT NULL,
  display_name  VARCHAR(50)  NOT NULL,
  role          user_role    NOT NULL DEFAULT 'operator',
  home_location_id BIGINT,                 -- 操作员默认库位（仅用于前端默认筛选，不做数据隔离）
  is_active     BOOLEAN      NOT NULL DEFAULT true,
  last_login_at TIMESTAMPTZ,
  created_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at    TIMESTAMPTZ  NOT NULL DEFAULT now()
);

-- ========== 库位（仓库/校区） ==========
CREATE TABLE locations (
  id         BIGSERIAL PRIMARY KEY,
  code       VARCHAR(20) NOT NULL UNIQUE,   -- HQ / JC / ST / HD / MZ / KFQ
  name       VARCHAR(50) NOT NULL UNIQUE,   -- 总部仓库 / 城东校区 ...
  type       VARCHAR(20) NOT NULL DEFAULT 'campus',  -- warehouse | campus
  is_front_warehouse BOOLEAN NOT NULL DEFAULT false,  -- 总部=前置仓
  sort_order INT NOT NULL DEFAULT 0,
  is_active  BOOLEAN NOT NULL DEFAULT true,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE users ADD CONSTRAINT fk_users_home_location
  FOREIGN KEY (home_location_id) REFERENCES locations(id);

-- ========== 类目（6 大分类，可配置） ==========
CREATE TABLE categories (
  id          BIGSERIAL PRIMARY KEY,
  digit       CHAR(1)     NOT NULL UNIQUE,  -- 1/2/3/4/5/9  ← 参与条码构成，改它会影响新码
  name        VARCHAR(30) NOT NULL UNIQUE,  -- 教材/书籍/辅材/耗材/礼品/其他
  sort_order  INT NOT NULL DEFAULT 0,
  is_active   BOOLEAN NOT NULL DEFAULT true,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ========== 编码规则配置 ==========
CREATE TABLE barcode_rules (
  id             SMALLINT PRIMARY KEY DEFAULT 1,
  prefix         VARCHAR(4)  NOT NULL DEFAULT '2',   -- 必须纯数字
  region_code    VARCHAR(4)  NOT NULL DEFAULT '10',  -- 湛江
  seq_width      SMALLINT    NOT NULL DEFAULT 4,
  total_length   SMALLINT    NOT NULL DEFAULT 8,
  allow_external BOOLEAN     NOT NULL DEFAULT true,  -- 是否允许录入商品原装码
  updated_by     BIGINT REFERENCES users(id),
  updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT ck_singleton CHECK (id = 1),
  CONSTRAINT ck_prefix_numeric CHECK (prefix ~ '^[0-9]+$'),
  CONSTRAINT ck_region_numeric CHECK (region_code ~ '^[0-9]+$')
);

-- 各分类当前流水（分配时 SELECT ... FOR UPDATE 保证并发安全）
CREATE TABLE barcode_sequences (
  category_id BIGINT PRIMARY KEY REFERENCES categories(id),
  next_seq    INT NOT NULL DEFAULT 1,
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ========== 物品档案（一物一行，主数据） ==========
CREATE TABLE items (
  id             BIGSERIAL PRIMARY KEY,
  barcode        VARCHAR(20) UNIQUE,        -- NULL = 待编码（现场只填名称+拍照）
  name           VARCHAR(200) NOT NULL,
  category_id    BIGINT NOT NULL REFERENCES categories(id),
  spec           VARCHAR(100) DEFAULT '',   -- 规格
  suggest_price  NUMERIC(10,2),             -- 建议售价
  unit           VARCHAR(20) DEFAULT '件',
  need_label     BOOLEAN NOT NULL DEFAULT true,   -- 是否贴码（费用类=false）
  print_mode     print_mode NOT NULL DEFAULT 'label',
  status         item_status NOT NULL DEFAULT 'active',
  merged_into_id BIGINT REFERENCES items(id),     -- status=merged 时指向保留项
  barcode_origin VARCHAR(10) NOT NULL DEFAULT 'internal',  -- internal | external
  remark         TEXT DEFAULT '',
  created_by     BIGINT REFERENCES users(id),
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT ck_barcode_numeric CHECK (barcode IS NULL OR barcode ~ '^[0-9]{8,14}$'),
  CONSTRAINT ck_merged_consistency CHECK (
    (status = 'merged') = (merged_into_id IS NOT NULL))
);
CREATE INDEX idx_items_name       ON items USING gin (name gin_trgm_ops);  -- 模糊搜索
CREATE INDEX idx_items_category   ON items(category_id);
CREATE INDEX idx_items_status     ON items(status);

-- 物品照片（一物多图；名录是照片唯一存放点）
CREATE TABLE item_photos (
  id         BIGSERIAL PRIMARY KEY,
  item_id    BIGINT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
  file_path  VARCHAR(300) NOT NULL,   -- 相对 uploads/ 的路径
  file_size  INT,
  sort_order INT NOT NULL DEFAULT 0,
  is_primary BOOLEAN NOT NULL DEFAULT false,
  source     VARCHAR(20) NOT NULL DEFAULT 'upload',  -- upload | camera | migrated
  uploaded_by BIGINT REFERENCES users(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_photos_item ON item_photos(item_id);

-- ========== 条码变更历史（用户明确要求） ==========
CREATE TABLE barcode_history (
  id           BIGSERIAL PRIMARY KEY,
  item_id      BIGINT NOT NULL REFERENCES items(id),
  old_barcode  VARCHAR(20),
  new_barcode  VARCHAR(20),
  change_type  barcode_change NOT NULL,
  reason       VARCHAR(300) DEFAULT '',
  operator_id  BIGINT REFERENCES users(id),
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_bchist_item    ON barcode_history(item_id);
CREATE INDEX idx_bchist_oldcode ON barcode_history(old_barcode);  -- 扫旧码溯源用
CREATE INDEX idx_bchist_created ON barcode_history(created_at DESC);

-- ========== 库存（一物 × 一库位 一行） ==========
CREATE TABLE inventory (
  id            BIGSERIAL PRIMARY KEY,
  item_id       BIGINT NOT NULL REFERENCES items(id),
  location_id   BIGINT NOT NULL REFERENCES locations(id),
  qty_on_hand   INT NOT NULL DEFAULT 0,   -- 当前库存
  qty_reserved  INT NOT NULL DEFAULT 0,   -- 待领取数量（已批未提）
  safety_stock  INT NOT NULL DEFAULT 0,   -- 安全库存
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT uq_inventory_item_location UNIQUE (item_id, location_id),
  CONSTRAINT ck_qty_non_negative CHECK (qty_on_hand >= 0),
  CONSTRAINT ck_reserved_non_negative CHECK (qty_reserved >= 0)
);
CREATE INDEX idx_inventory_location ON inventory(location_id);
-- 库存金额视图（建议售价 × 当前库存）
CREATE VIEW v_inventory_value AS
SELECT i.id AS inventory_id, i.item_id, i.location_id, i.qty_on_hand,
       it.suggest_price, COALESCE(it.suggest_price,0) * i.qty_on_hand AS stock_value
FROM inventory i JOIN items it ON it.id = i.item_id;

-- ========== 统一库存流水（审计 + 报表真源） ==========
CREATE TABLE stock_movements (
  id            BIGSERIAL PRIMARY KEY,
  item_id       BIGINT NOT NULL REFERENCES items(id),
  location_id   BIGINT NOT NULL REFERENCES locations(id),
  change_qty    INT NOT NULL,             -- 正=入，负=出
  qty_before    INT NOT NULL,
  qty_after     INT NOT NULL,
  doc_type      doc_type NOT NULL,
  doc_id        BIGINT,                   -- 对应单据 id（多态）
  doc_no        VARCHAR(30),              -- 冗余单据号，便于查询
  operator_id   BIGINT REFERENCES users(id),
  note          VARCHAR(300) DEFAULT '',
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_sm_item_loc_time ON stock_movements(item_id, location_id, created_at DESC);
CREATE INDEX idx_sm_doc           ON stock_movements(doc_type, doc_id);
CREATE INDEX idx_sm_created       ON stock_movements(created_at DESC);

-- ========== 单据 ==========
-- 入库单（采购到总部前置仓）
CREATE TABLE inbound_orders (
  id            BIGSERIAL PRIMARY KEY,
  doc_no        VARCHAR(30) NOT NULL UNIQUE,   -- IN-YYYYMMDD-NNN
  supplier      VARCHAR(100) DEFAULT '',
  location_id   BIGINT NOT NULL REFERENCES locations(id),  -- 入到哪个库位
  is_for_sale   BOOLEAN NOT NULL DEFAULT true, -- 易知鸟「是否售卖」
  state         doc_state NOT NULL DEFAULT 'draft',
  order_date    DATE NOT NULL DEFAULT CURRENT_DATE,
  total_amount  NUMERIC(12,2) NOT NULL DEFAULT 0,
  remark        TEXT DEFAULT '',
  operator_id   BIGINT REFERENCES users(id),
  posted_at     TIMESTAMPTZ,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE inbound_items (
  id           BIGSERIAL PRIMARY KEY,
  order_id     BIGINT NOT NULL REFERENCES inbound_orders(id) ON DELETE CASCADE,
  item_id      BIGINT NOT NULL REFERENCES items(id),
  barcode_snapshot VARCHAR(20),   -- 下单时的条码（防重分配后历史失真）
  name_snapshot    VARCHAR(200),
  spec_snapshot    VARCHAR(100),
  qty          INT NOT NULL CHECK (qty > 0),
  purchase_price NUMERIC(10,2),   -- 采购单价
  sale_price     NUMERIC(10,2),   -- 售卖价格（易知鸟模板要）
  sort_order   INT NOT NULL DEFAULT 0
);
CREATE INDEX idx_inb_items_order ON inbound_items(order_id);

-- 出库单 / 调拨单（总部 → 校区）
CREATE TABLE outbound_orders (
  id            BIGSERIAL PRIMARY KEY,
  doc_no        VARCHAR(30) NOT NULL UNIQUE,   -- OUT-YYYYMMDD-NNN
  kind          VARCHAR(20) NOT NULL DEFAULT 'transfer',  -- transfer=调拨给校区 | issue=领用消耗
  from_location_id BIGINT NOT NULL REFERENCES locations(id),
  to_location_id   BIGINT REFERENCES locations(id),       -- 调拨目标（领取校区）
  state         doc_state NOT NULL DEFAULT 'draft',
  order_date    DATE NOT NULL DEFAULT CURRENT_DATE,
  remark        TEXT DEFAULT '',
  operator_id   BIGINT REFERENCES users(id),
  posted_at     TIMESTAMPTZ,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE outbound_items (
  id          BIGSERIAL PRIMARY KEY,
  order_id    BIGINT NOT NULL REFERENCES outbound_orders(id) ON DELETE CASCADE,
  item_id     BIGINT NOT NULL REFERENCES items(id),
  barcode_snapshot VARCHAR(20),
  name_snapshot    VARCHAR(200),
  qty         INT NOT NULL CHECK (qty > 0),
  sort_order  INT NOT NULL DEFAULT 0
);
CREATE INDEX idx_outb_items_order ON outbound_items(order_id);

-- 退库单（校区 → 总部；依据《仓库管理制度》第十五条：未拆封未使用才可退）
CREATE TABLE return_orders (
  id            BIGSERIAL PRIMARY KEY,
  doc_no        VARCHAR(30) NOT NULL UNIQUE,   -- RET-YYYYMMDD-NNN
  from_location_id BIGINT NOT NULL REFERENCES locations(id),  -- 退回校区
  to_location_id   BIGINT NOT NULL REFERENCES locations(id),  -- 退回总部仓库
  item_condition VARCHAR(20) NOT NULL DEFAULT 'sealed',  -- sealed=未拆封可再发放 | opened=已拆封或已使用
  state         return_state NOT NULL DEFAULT 'pending',  -- pending/accepted/rejected
  accept_state  doc_state NOT NULL DEFAULT 'draft',       -- accepted 后过账才影响库存
  order_date    DATE NOT NULL DEFAULT CURRENT_DATE,
  remark        TEXT DEFAULT '',
  operator_id   BIGINT REFERENCES users(id),
  accepted_by   BIGINT REFERENCES users(id),   -- 验收人
  posted_at     TIMESTAMPTZ,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT ck_return_condition CHECK (item_condition IN ('sealed','opened'))
);
CREATE TABLE return_items (
  id          BIGSERIAL PRIMARY KEY,
  order_id    BIGINT NOT NULL REFERENCES return_orders(id) ON DELETE CASCADE,
  item_id     BIGINT NOT NULL REFERENCES items(id),
  barcode_snapshot VARCHAR(20),
  name_snapshot    VARCHAR(200),
  qty         INT NOT NULL CHECK (qty > 0),
  sort_order  INT NOT NULL DEFAULT 0
);
CREATE INDEX idx_ret_items_order ON return_items(order_id);

-- 盘点单（按分类或全仓盘点，一单多行）
CREATE TABLE stocktakes (
  id            BIGSERIAL PRIMARY KEY,
  doc_no        VARCHAR(30) NOT NULL UNIQUE,   -- STK-YYYYMMDD-NNN
  location_id   BIGINT NOT NULL REFERENCES locations(id),
  category_id   BIGINT REFERENCES categories(id),   -- NULL=全类目
  state         stocktake_state NOT NULL DEFAULT 'draft',
  stocktake_date DATE NOT NULL DEFAULT CURRENT_DATE,
  remark        TEXT DEFAULT '',
  operator_id   BIGINT REFERENCES users(id),
  posted_at     TIMESTAMPTZ,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE stocktake_items (
  id            BIGSERIAL PRIMARY KEY,
  stocktake_id  BIGINT NOT NULL REFERENCES stocktakes(id) ON DELETE CASCADE,
  item_id       BIGINT NOT NULL REFERENCES items(id),
  barcode_snapshot VARCHAR(20),
  name_snapshot    VARCHAR(200),
  qty_book      INT NOT NULL DEFAULT 0,   -- 账面数量（开单时快照）
  qty_counted   INT,                       -- 实盘数量（NULL=未盘）
  variance      INT GENERATED ALWAYS AS (qty_counted - qty_book) STORED,  -- 差异
  diff_state    VARCHAR(20) DEFAULT '',    -- 盘盈/盘亏/相符（应用层写，便于筛选）
  handle_result VARCHAR(100) DEFAULT '',   -- 处理结果
  remark        VARCHAR(300) DEFAULT '',
  sort_order    INT NOT NULL DEFAULT 0,
  CONSTRAINT uq_stk_item UNIQUE (stocktake_id, item_id)
);
CREATE INDEX idx_stk_items_doc ON stocktake_items(stocktake_id);

-- ========== 物品合并日志（去重合并，可回滚） ==========
CREATE TABLE item_merge_log (
  id            BIGSERIAL PRIMARY KEY,
  keeper_id     BIGINT NOT NULL REFERENCES items(id),
  merged_id     BIGINT NOT NULL REFERENCES items(id),
  merged_barcode VARCHAR(20),
  merged_name    VARCHAR(200),
  impact_snapshot JSONB NOT NULL,   -- 合并前快照：库存/单据行数/照片，用于回滚
  reason        VARCHAR(300) DEFAULT '',
  operator_id   BIGINT REFERENCES users(id),
  rolled_back_at TIMESTAMPTZ,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_merge_keeper ON item_merge_log(keeper_id);
CREATE INDEX idx_merge_merged ON item_merge_log(merged_id);

-- ========== 通用审计 ==========
CREATE TABLE audit_log (
  id          BIGSERIAL PRIMARY KEY,
  user_id     BIGINT REFERENCES users(id),
  action      VARCHAR(50) NOT NULL,   -- create/update/delete/merge/reassign/post...
  entity      VARCHAR(30) NOT NULL,   -- item/category/inbound_order...
  entity_id   BIGINT,
  detail      JSONB,
  ip          VARCHAR(50),
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_audit_entity ON audit_log(entity, entity_id);
CREATE INDEX idx_audit_time   ON audit_log(created_at DESC);

-- ========== 序列号生成器（单据号） ==========
CREATE TABLE doc_counters (
  prefix    VARCHAR(20) NOT NULL,   -- IN / OUT / RET / STK
  ymd       CHAR(8)     NOT NULL,   -- 20261019
  seq       INT         NOT NULL DEFAULT 0,
  PRIMARY KEY (prefix, ymd)
);
```

### 关键约束与并发

1. **条码全局唯一**：`items.barcode UNIQUE`（部分索引，允许多个 NULL 待编码）→ 实际用 `CREATE UNIQUE INDEX uq_items_barcode ON items(barcode) WHERE barcode IS NOT NULL;`
2. **库存不超卖**：出库过账时 `UPDATE inventory SET qty_on_hand = qty_on_hand - :q WHERE item_id=:i AND location_id=:l AND qty_on_hand >= :q`，`rowcount=0` → 抛 409「库存不足」。配合单据级 `SELECT ... FOR UPDATE` 锁 inventory 行。
3. **流水分配并发**：`SELECT next_seq FROM barcode_sequences WHERE category_id=:c FOR UPDATE` → +1 → 回写。事务内完成。
4. **单据过账幂等**：`state` 从 draft→posted 用条件更新 `WHERE state='draft'`，防重复提交。
5. **库存变动一律写 stock_movements**，且必须在同一事务内。报表只查 movements，不查 inventory 快照。
6. **条码重分配**：旧码写入 `barcode_history`（type=reassign），items.barcode 改为新码。旧码**不释放复用**——扫码解析时能查到「该码已停用，现码为 XXX」。

## 4. 扫码解析（核心交互）

**统一入口**：`GET /api/scan/resolve?code={code}`

解析顺序：
1. `items.barcode = code AND status='active'` → 命中，返回物品+全库位库存
2. `items.barcode = code AND status='merged'` → 返回 `resolved=false, hint='该物品已合并至「{keeper.name}」', redirect_barcode`
3. `barcode_history.old_barcode = code`（最新一条）→ 返回 `resolved=false, hint='该条码已停用（{change_type}），现用码 {new_barcode}'`
4. 都未命中 → `resolved=false, hint='未登记的条码'`，并**允许前端引导「登记新物品」**（现场发现新物品：填名称+拍照，条码留空或直接用扫到的外部码）

返回体：
```json
{
  "resolved": true,
  "code": "21010013",
  "code_type": "internal",
  "item": {"id":123,"barcode":"21010013","name":"实用性书写教材下","category":"教材",
           "spec":"","suggest_price":5.7,"need_label":true,"photo_url":"/api/uploads/xxx.jpg"},
  "inventory": [{"location_id":1,"location_name":"总部仓库","qty_on_hand":708,
                 "qty_reserved":0,"safety_stock":0}],
  "total_qty": 708,
  "hint": null
}
```

## 5. 物品去重合并（最大痛点）

### 5.1 相似检测算法（移植 prepare_items.py 已验证逻辑）

```
normalize(name): 去空格与标点 " 　-_—()（）【】[]·,，.。/"
ptype(name):     含「配套练习本/专练本/练习本/练字本」→练习本；含「材料包」→材料包；
                 含「教材」→教材；含「考级/赛事/研学/特权包/新权包/费用」→费用；else 其他
volume(name):    正则 (上|下)(册|教材|配套|（|\(|$) → '上'/'下'/''
digits(name):    抽出所有数字串

分桶键 = (ptype, volume, digits)   ← 跨桶必是不同物品，绝不比较
桶内两两 difflib.SequenceMatcher(None, norm(a), norm(b)).ratio() >= 0.70 → 同组
组内推荐统一名 = 出现次数最多者；并列取最短（pick_unified）
```

**新增**（针对真实脏数据）：
- **空格归一化命中**：`墨 水` vs `墨水`、`橡 皮` vs `橡皮` → norm 后完全相等，标记 `match_type='space_variant'`（最高置信，优先展示）
- **完全同名不同码** → `match_type='same_name'`（必须合并或改名）
- **同码不同名**（跨数据源冲突，如 21030019 名录=积分存折 / Excel=考级证）→ `match_type='code_conflict'`，**不允许自动合并**，必须人工裁决保留哪个名称（另一个转 alias）
- **别名机制**：`item_aliases(item_id, alias, source)` 保留历史叫法，扫码/搜索时别名也能命中，避免"合并后搜不到"

`GET /api/items/duplicates?threshold=0.7` 返回分组结果，按置信度降序（space_variant > same_name > fuzzy 90% > fuzzy 70%），低置信排后但**默认展示全部待人工复核**。

### 5.2 合并语义（`POST /api/items/{keeper_id}/merge`）

body: `{"merged_ids":[...], "reason":"..."}`，**仅 admin**。

事务内依次执行：
1. 校验：keeper 与 merged 均 `status='active'`，不允许自合并，不允许合并到已合并项
2. **快照** impact_snapshot（JSONB）：每个 merged 的 barcode/name/photos/各库位 inventory/关联单据行 id 列表 → 用于回滚
3. **库存**：`inventory` 按 location 相加到 keeper（`ON CONFLICT (item_id,location_id) DO UPDATE SET qty_on_hand = inventory.qty_on_hand + EXCLUDED.qty_on_hand`），qty_reserved/safety_stock 同法（safety 取 max 不求和）；写 stock_movements（doc_type='adjust'，note='合并自 {barcode}'）
4. **单据明细**：`inbound_items/outbound_items/return_items/stocktake_items` 的 `item_id` 全部改指 keeper，并把 merged 的 barcode/name 写入该行的 `*_snapshot` 字段（历史不失真）
5. **stock_movements.item_id** 改指 keeper（保留原 doc_no）
6. **照片**：merged 的 item_photos 改挂 keeper，按文件 hash 去重，keeper 无主图时把 merged 主图设为主图
7. **别名**：merged.name 与 merged.barcode 写入 item_aliases
8. **条码退役**：merged.barcode 写入 barcode_history（change_type='merge_retire'，reason）；该码**不释放复用**
9. **软删**：merged.status='merged'，merged_into_id=keeper，barcode 置 NULL（唯一索引让位），name 加前缀 `[已合并] `
10. 写 item_merge_log + audit_log

**回滚** `POST /api/items/merges/{log_id}/rollback`（仅 admin，且 keeper 未被再次合并）：按 impact_snapshot 逆向恢复（库存相减、单据 item_id 改回、条码还原、status 改回 active、删别名与照片挂靠）。

### 5.3 孤儿数据处理

主表有条码但名录无档案（真实存在：21030022 / 21030023 / 21040003）→ 迁移时**自动补建 items 档案**（name 取主表/Excel 可得名称，拿不到则标 `[待确认名称]`，status='active'，remark 写明「迁移自物品主表孤儿行」），并列入迁移报告的「待人工确认」清单。不静默丢弃。

## 6. 后端 API（REST，前缀 `/api`）

认证：`Authorization: Bearer <access_token>`。权限：`admin` / `operator`（下表 A=仅管理员，AO=两者，AO(own)=操作员只能改自己创建的草稿单）。

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| POST | `/auth/login` | 公开 | → `{access_token, refresh_token, user}` |
| POST | `/auth/refresh` | 公开 | 刷新 access |
| POST | `/auth/logout` | AO | 失效 refresh |
| GET | `/auth/me` | AO | 当前用户 |
| POST | `/auth/change-password` | AO | |
| GET/POST | `/users` | A | 用户列表 / 新建 |
| PATCH/DELETE | `/users/{id}` | A | 改角色/库位、停用 |
| GET/POST | `/locations` | A(写) | 库位（校区+总部） |
| PATCH | `/locations/{id}` | A | |
| GET/POST | `/categories` | A(写) | 类目列表/新建 |
| PATCH | `/categories/{id}` | A | 改名（digit 改动需 `?confirm_digit=true`，警告影响新码） |
| GET | `/barcode-rules` | AO | 编码规则 |
| PUT | `/barcode-rules` | A | 改前缀/地区码/流水位（校验纯数字） |
| POST | `/barcode/preview` | AO | 试算下一个可用码（不占用） |
| POST | `/barcode/allocate` | AO | 给指定物品分配码（body: item_id 或 category_id+count） |
| POST | `/items/{id}/reassign-barcode` | A | 重分配：body `{new_barcode?:自动, reason}` → 写 barcode_history |
| GET | `/items/{id}/barcode-history` | AO | 条码变更历史 |
| GET | `/barcode/history` | A | 全局变更历史（筛选 type/时间段/操作人） |
| GET | `/items` | AO | 列表：分页 + `q`(名称/条码/别名模糊) + category_id + status + need_label + print_mode + has_photo + 排序 |
| POST | `/items` | AO | 新建（barcode 可空=待编码；填了则校验唯一+格式） |
| GET | `/items/{id}` | AO | 详情（含照片、各库位库存、最近流水、别名、条码历史） |
| PATCH | `/items/{id}` | AO | 改档案 |
| DELETE | `/items/{id}` | A | 软删（status=retired；有库存或流水则拒绝，提示先清零） |
| POST | `/items/batch` | A | 批量新建/导入（CSV/xlsx） |
| GET | `/items/duplicates` | A | 相似分组（`?threshold=0.7`） |
| POST | `/items/{keeper_id}/merge` | A | 合并（见 5.2） |
| GET | `/items/merges` | A | 合并记录 |
| POST | `/items/merges/{log_id}/rollback` | A | 回滚合并 |
| POST | `/items/{id}/photos` | AO | 上传照片（multipart；手机拍照直传） |
| DELETE | `/items/{id}/photos/{photo_id}` | AO | |
| GET | `/uploads/{path}` | 公开(签名可选) | 照片静态访问 |
| GET | `/scan/resolve` | AO | **扫码解析**（见第 4 节） |
| GET | `/inventory` | AO | 多维库存：`item_id/category_id/location_id/q/below_safety` + 分页 |
| GET | `/inventory/summary` | AO | 按库位/类目汇总（件数、金额、SKU 数） |
| PATCH | `/inventory/{id}` | A | 改安全库存/待领取数量 |
| GET/POST | `/inbound-orders` | AO | 入库单列表/新建（草稿） |
| GET | `/inbound-orders/{id}` | AO | 详情 |
| PATCH | `/inbound-orders/{id}` | AO(own) | 改草稿 |
| POST | `/inbound-orders/{id}/post` | AO | **过账**：增库存 + 写流水（幂等） |
| POST | `/inbound-orders/{id}/void` | A | 作废（冲销库存） |
| GET | `/inbound-orders/{id}/yizhiniao-export` | AO | **导出易知鸟 9 列模板 xlsx** |
| GET/POST | `/outbound-orders` | AO | 出库/调拨单 |
| PATCH | `/outbound-orders/{id}` | AO(own) | |
| POST | `/outbound-orders/{id}/post` | AO | 过账：from 减 / to 增（同事务，防超卖） |
| POST | `/outbound-orders/{id}/void` | A | |
| GET/POST | `/return-orders` | AO | 退库单 |
| POST | `/return-orders/{id}/accept` | A | 验收通过 → 过账增库存 |
| POST | `/return-orders/{id}/reject` | A | 拒收（不动库存） |
| GET/POST | `/stocktakes` | AO | 盘点单 |
| POST | `/stocktakes` | AO | 新建：按 location_id + category_id 生成待盘行（快照 qty_book） |
| POST | `/stocktakes/{id}/scan` | AO | **扫码录入实盘数**：body `{barcode, qty_counted}`，不存在则自动加行 |
| PATCH | `/stocktakes/{id}/items/{row_id}` | AO | 改实盘数/处理结果/备注 |
| POST | `/stocktakes/{id}/post` | AO | 过账：按差异写 adjust 流水校正库存 |
| GET | `/movements` | AO | 库存流水明细（多维筛选 + 分页） |
| GET | `/reports/stock` | AO | 库存报表（按商品/类目/仓库） |
| GET | `/reports/movements` | AO | 出入库流水统计汇总 |
| GET | `/reports/dashboard` | AO | 仪表盘：物品种数/库存总件数/待领取总数/盘点次数/各库位库存金额 |
| GET | `/exports/{kind}` | AO | 导出 CSV/xlsx（kind=items/inventory/movements/...） |
| GET | `/labels/pdf` | AO | **标签 PDF**：`?item_ids=&mode=label\|scan_card&layout=3col\|4col&copies=1&paper=a4` |
| GET | `/labels/barcode/{code}.png` | AO | 单条码 PNG（后端出图，与 PDF 同源） |
| GET | `/healthz` | 公开 | 健康检查（含 DB 连通） |

**统一响应**：成功 `{ "data": ..., "meta": {"page":1,"page_size":20,"total":100} }`；失败 `{"detail":"中文错误信息","code":"ERR_XXX"}`。
**校验**：Pydantic v2；条码格式 `^[0-9]{8,14}$`；数量 > 0；日期 ISO；金额 ≥ 0。

## 7. 前端页面

| 路由 | 页面 | 核心内容 | 权限 |
|---|---|---|---|
| `/login` | 登录 | 用户名+密码 | 公开 |
| `/` | 仪表盘 | 4 张统计卡（物品种数/库存总件数/待领取/盘点次数）+ 各库位库存金额柱状图 + 低库存预警列表 + 最近流水 | AO |
| `/scan` | **扫码工作台**（移动端首页） | 大扫码框（摄像头）+ 输入框（枪）；解析后显示物品卡（照片/名称/各库位库存）；一键跳「入库/出库/退库/盘点」登记 | AO |
| `/items` | 物品档案 | 表格：条码(可点开看条码图)/照片缩略/名称/类目/规格/售价/是否贴码/总库存/状态；筛选+搜索；行内快捷编辑 | AO |
| `/items/new` `/items/:id` | 物品详情/新建 | 档案表单 + 照片墙（拍照直传）+ 各库位库存 + 条码历史 + 关联单据 + 别名 | AO |
| `/items/pending-code` | 待编码物品 | 条码为空的新物品；批量选中→分配条码→打印 | AO |
| `/items/duplicates` | **去重合并** | 相似分组卡片；每组勾选保留项；预览影响面（库存/单据/照片）→确认合并；合并历史+回滚 | A |
| `/categories` | 类目与编码规则 | 6 大类目（改名/排序）+ 编码规则配置（前缀/地区码/流水位）+ 各类目下一个可用码 | A |
| `/barcode/history` | 条码变更历史 | 全局时间线：物品/旧码/新码/类型/原因/操作人 | A |
| `/labels` | 标签打印 | 选物品（多选/按筛选/按类目）→ 选版式（每行3枚/4枚、贴标/扫码卡、份数）→ 在线预览 → 下载 PDF | AO |
| `/inbound` `/outbound` `/returns` | 三类单据 | 列表（状态/单号/日期筛选）+ 新建（扫码加行）+ 详情 + 过账/作废/验收 + 易知鸟导出 | AO |
| `/stocktakes` | 盘点 | 列表 + 新建（选库位+类目）+ 盘点执行页（连续扫码录数，大按钮，移动端优先）+ 差异确认过账 | AO |
| `/inventory` | 库存查询 | 多维：按商品/类目/仓库切换；低库存高亮；导出 | AO |
| `/movements` | 库存流水 | 明细+筛选+导出 | AO |
| `/reports` | 报表 | 出入库统计汇总（按日/月、按库位、按类目）+ 导出 | AO |
| `/users` | 用户与权限 | 用户 CRUD、角色、绑定默认库位 | A |

**移动端要点**：`/scan` 与盘点执行页为**移动优先**（大按钮、单手操作、固定底部操作栏）；其余页面用 antd 响应式（`<Grid>` + 表格在窄屏转卡片列表）。

**扫码枪交互**（关键，踩过 Mac Dvorak 乱码坑）：
- 页面有一个**常驻隐藏输入框**保持焦点（点击页面任意处重新聚焦）
- 监听 keydown，累积字符；遇 `Enter` 或 **30ms 内无新字符**视为一次扫码完成
- 防重复：同码 500ms 内忽略；防前缀后缀污染：只取 `^[0-9]{8,14}$` 的连续数字段
- 扫到即调 `/api/scan/resolve`，命中后按当前页上下文动作（盘点页→加行+聚焦数量；出库页→加行）
- 未命中→弹「登记新物品」抽屉（名称+拍照，条码留空或沿用外部码）

**摄像头扫码**：`BarcodeDetector` 存在则用（性能好），否则 `html5-qrcode`；必须 HTTPS（localhost 除外）；iOS Safari 需用户手势触发 `getUserMedia`；提供「扫码失败？手动输入」兜底。

## 8. 标签打印版式（移植现有参数，不得改动数值）

```
DPI = 300
A4  = 2480 × 3508 px
每页：3 列 × 6 行 = 18 枚（layout=3col，用户当前偏好）
      4 列 × 8 行 = 32 枚（layout=4col，密集版）
页边距 = 118px (~10mm)
3col 间隙 = 5mm；4col 间隙 = 24px (~2mm)
条码尺寸上限 = 507 × 202 px @300dpi（≈43×17mm），**只缩不放**（保证可扫等级不变）
Code128 writer_options = {module_height:12.0, font_size:0, text_distance:1.0,
                          quiet_zone:2.0, write_text:False, dpi:300}
字体 = Noto Sans CJK（容器内，替代 macOS 的 Hiragino Sans GB）
       bold 用于编码与名称（3col: 4.5mm；4col: 3.2mm/3.0mm）
       regular 用于底部「分类 · 规格」小字（3col: 3.4mm）
长名称处理 = 字号从 4.5mm 递减到 3.6mm（步长 0.3mm），仍超宽则中点附近拆两行，**不截断**
裁切参考线 = #CCCCCC 2px 边框
标签内容 = 条码 + 编码 + 物品名称（+规格）+ 分类，**不含校区**（前置仓原则）
```
⚠️ 容器内**没有** macOS 字体。必须在镜像里装 `fonts-noto-cjk`，并把字体路径做成可配置（`LABEL_FONT_REGULAR` / `LABEL_FONT_BOLD` 环境变量），默认 `/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc` 与 `-Bold.ttc`。生成后必须用真实中文名校验不出现豆腐块。

## 9. 部署（Docker + 宿主机 nginx 反代，与现有业务零冲突）

### 隔离原则
- 独立 compose 项目名 `edu-wms`，独立网络 `edu_wms_net`（**不加入**任何现有网络）
- 独立命名卷 `edu_wms_pgdata` / `edu_wms_uploads` / `edu_wms_backups`（**不挂载**现有目录）
- 独立 PostgreSQL 16 容器（**不复用**现有数据库实例；新库名 `edu_wms`，独立超级用户）
- **只监听 127.0.0.1**，不对外暴露端口（`127.0.0.1:8080:8080`），公网流量只能经 nginx
- 容器加资源上限（`mem_limit` / `cpus`），避免影响现有业务
- 不改现有 nginx 的任何 server 块，只**新增一个独立 conf 文件**；用 `nginx -t` 校验后 `reload`（不是 restart）

### 组件
```
edu-wms/
├── docker-compose.yml        # api + web(nginx) + db + backup
├── .env.example              # 全部可配项，含端口/域名/密码/JWT密钥
├── backend/Dockerfile        # python:3.11-slim + fonts-noto-cjk + uvicorn
├── frontend/Dockerfile       # node:20 build → nginx:alpine 托管静态 + /api 反代到 api:8080
├── deploy/nginx/<subdomain>.conf   # 宿主机 nginx server 块（新增文件，不改现有）
└── deploy/scripts/{deploy.sh,backup.sh,restore.sh,probe-vps.sh}
```

### 端口
`WMS_HOST_PORT` 默认 `8080`，部署前先 `ss -tlnp` 探测占用，冲突则自动顺延（8081/8082…）并写入 `.env`。

### HTTPS
Let's Encrypt certbot（`--nginx` 或 webroot）。若宿主机已有 certbot/证书则复用其签发流程。**摄像头扫码硬依赖 HTTPS**，无证书则摄像头功能降级为扫码枪+手动输入（需在 UI 明示）。

### 上线步骤（拿到 VPS 信息后）
1. `probe-vps.sh`：探测 OS/内存/磁盘/Docker 是否装/现有容器/现有 nginx（宿主机 or 容器）/端口占用/现有域名与证书/防火墙与阿里云安全组
2. 依据探测结果确定：反代形态（宿主机 nginx 加 server 块 / 现有反代容器加路由 / 我们自带 nginx 容器）、端口、证书签发方式
3. 用户加 DNS：`<子域名> A 记录 → VPS 公网 IP`；阿里云安全组放行 80/443
4. 上传代码 → `docker compose build` → 初始化 DB（alembic upgrade head + 种子：6 类目/6 库位/编码规则/admin 账号）
5. 数据迁移（见第 10 节）
6. 配 nginx + 签证书 + reload
7. 真实验证：登录/权限隔离/扫码（枪+手机摄像头）/建单过账/库存增减/打印 PDF 中文与可扫性/导出
8. 备份定时任务（pg_dump + uploads，保留 14 天）

### 需要用户提供
VPS：IP、SSH 用户与密钥/密码、sudo 权限；域名：可用子域名、DNS 是否可改、现有证书情况；现有系统：nginx 形态、已占用端口（避免冲突）。

## 10. 数据迁移（全量）

### 前置
企业微信机器人「文档」授权恢复（当前 errcode 850003 已过期）。授权后用 `wecom-cli smartsheet records query --docid s3_AAcAGng7AKoCN7ptXnoYaSrOcsQhc_a --sql 'SELECT ...'` **只读**采集。

### 步骤
1. **采集**（分页拉全量，注意公式字段返回数组要 flatten）：
   物品名录（条码号/物品名称/物品图片/编码查重）→ 物品主表（411 行，条码号/分类/规格/建议售价/所在校区/仓库/安全库存/当前库存/待领取数量/是否贴码）→ 入库单/出库单/退库单/盘点记录（全部历史）→ 仪表盘配置（仅参考）
2. **照片下载**：企业微信 CDN URL（`https://wdcdn.qpic.cn/...`）**可能过期或需鉴权，必须第一时间批量下载**到本地，再转存到 uploads 卷；记录下载失败清单，失败的物品在迁移报告标红（可后续用手机重拍）
3. **清洗**（生成「迁移前对照表」xlsx 给用户确认后再入库）：
   - 名称去多余空格（`墨 水`→`墨水`、`橡 皮`→`橡皮`、`纸 杯`→`纸杯`、`铅 笔`→`铅笔`），原名存入 item_aliases
   - 同物多名归并（毛毡白色/白色毛毡、一次性纸杯/纸杯、双肩包/教培定制书包、书法课程袋/黑色书法袋、正姿教材下/正姿.教材）→ 走第 5 节合并流程，但**迁移期先只出建议清单，不自动执行**
   - 同码不同名冲突（21030019 积分存折 vs 考级证；21040034 幼小套盒 vs 幼小套盒（上））→ 列入人工裁决清单
   - 孤儿行（21030022/21030023/21040003 主表有码名录无档案）→ 自动补建档案 + 列入待确认
   - 外部码（6950898000191 北太墨汁）→ barcode_origin='external'，不参与流水分配
   - 各分类流水种子 = 存量该分类最大流水 + 1
4. **入库**：迁移脚本幂等（按 barcode 幂等 upsert；重复执行不产生脏数据），单事务分批（每批 200 行），失败整批回滚
5. **对账校验**（迁移后必须全绿才算成功）：
   - 物品数 = 名录有码行数（+ 补建孤儿数）
   - inventory 行数 = 主表行数（去掉已合并）
   - `SUM(qty_on_hand)` 按库位逐一与主表「当前库存」合计相等
   - 各单据行数与源表条数一致；条码唯一性无冲突；照片数 = 下载成功数
6. **回滚**：迁移前 `pg_dump` 空库快照；迁移失败可 `docker compose down -v` 重来（数据源始终在智能表格，未破坏）

### 冻结期
迁移执行期间，智能表格**停止录入**（用户口头通知各校区）；迁移完成并验收后，智能表格转为只读归档，日常操作切到新系统。若迁移后仍需补录，在新系统操作，不回写智能表格。

### 本地兜底
若授权短期无法恢复，可先用本地 `barcode-tool/output/final/items_from_minglu.csv`（127 行名录快照）+ `items_all_v2.csv`（含规格/售价/印刷方式）+ `items_from_xlsx.csv`（33 种最新改名）做**档案与库存的近似迁移**，单据历史与照片待授权后补。三个文件间的冲突按第 5 节 code_conflict 流程人工裁决。

## 11. 实施阶段

| 阶段 | 交付 | 验收 |
|---|---|---|
| **P0 地基** | Docker 骨架、DB schema + Alembic、种子数据、JWT 认证与角色、健康检查 | 容器起得来，能登录，权限拦截生效 |
| **P1 档案与条码** | 类目/编码规则、物品 CRUD、条码分配与校验、照片上传、条码变更历史 | 建物品→自动分码→改码留痕；条码唯一性拦截 |
| **P2 打印** | 标签 PDF（3col/4col、贴标/扫码卡、份数、批量）、前端条码预览 | 打印出的 PDF 中文名正常、真实扫码枪能扫 |
| **P3 库存与单据** | inventory、入库/出库调拨/退库/盘点、stock_movements、过账与作废、易知鸟导出 | 全流程库存增减正确、并发不超卖、单据号连续 |
| **P4 扫码与查询** | `/scan` 工作台、扫码枪适配、摄像头扫码、库存多维查询、流水、报表、仪表盘、导出 | 手机摄像头与扫码枪都能连续作业 |
| **P5 去重合并** | 相似检测、合并预览与执行、回滚、别名、孤儿处理 | 用真实脏数据跑通合并+回滚，历史单据不失真 |
| **P6 迁移与上线** | 采集/清洗/入库/对账脚本、VPS 部署、nginx+TLS、备份 | 线上真实数据可用，对账全绿，HTTPS 扫码正常 |

**依赖**：P0→P1→P2/P3 可并行→P4 依赖 P3→P5 依赖 P1+P3→P6 依赖全部。
**最小可用**（先跑起来）：P0+P1+P2+P3。P4/P5 紧随。P6 需 VPS 信息与企业微信授权。

## 12. 风险与开放问题

1. **企业微信授权**（阻塞 P6 全量迁移）：需机器人在企业微信重新授权「文档」权限。授权前只能走本地 CSV 兜底迁移。
2. **照片 CDN 时效**：`wdcdn.qpic.cn` 链接可能过期 → 授权恢复后**立即下载**，不要延后。
3. **VPS 现状未知**：现有 nginx 形态、端口占用、内存余量、是否已有 certbot、阿里云安全组是否放行 443 —— 探测后才能定部署细节。内存 < 2GB 时需限制 PG 共享缓冲与容器内存。
4. **旧标签物理存在**：条码重分配/合并后，物品上贴的旧标签仍可被扫到 → 靠 `/scan/resolve` 的 retired/merged 提示引导，不做物理回收。需向校区说明。
5. **易知鸟同步是人工的**：本系统改码/合并后，易知鸟侧需人工按导出对照表改名+填码。系统应在重分配与合并后**自动生成易知鸟改名对照表**（xlsx：校区/原名/新统一名/新条码/售价），减少人工出错。
6. **并发规模**：几十用户、每天几百次扫码 → PG + 单 API 实例足够，无需缓存层/消息队列，避免过度设计。
7. **待用户确认**：子域名具体名称；admin 初始账号名与首密（建议部署时随机生成并只告知用户）；是否需要盘点审批流（当前设计为「盘点过账即校正库存」，无二级审批）；退库是否必须验收后才增库存（当前设计=是，符合制度第十五条）。
