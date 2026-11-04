"""ORM 模型：严格按 DESIGN.md 第 3 节 DDL 1:1 实现全部表。

跨库兼容策略（SQLite 本地/测试，PostgreSQL 生产）：
- 主键 BIGSERIAL → BigInteger.with_variant(Integer, "sqlite")（SQLite 需 INTEGER 才有 rowid 自增）
- TIMESTAMPTZ → DateTime(timezone=True)（PG 渲染 TIMESTAMPTZ，SQLite 渲染 DATETIME）
- ENUM → SQLAlchemy Enum(create_constraint=True)：PG 生成原生 TYPE，SQLite 降级 VARCHAR+CHECK
- JSONB → JSON().with_variant(JSONB, "postgresql")
- 正则 CHECK（barcode/prefix/region 纯数字）→ column.regexp_match()：
  PG 渲染 `~`，SQLite 渲染 REGEXP（db.py 中为 SQLite 注册 regexp 函数）
- items.barcode 唯一但允许多 NULL → 部分唯一索引 uq_items_barcode（PG postgresql_where，SQLite sqlite_where）
- idx_items_name 契约中是 PG gin_trgm_ops 索引：模型层建普通 B-tree 索引保证两边可建表，
  gin_trgm 索引在 alembic migration 中仅对 PG 创建
- stocktake_items.variance 生成列 → Computed(persisted=True)，PG 与 SQLite(>=3.31) 均支持 STORED
"""
from datetime import date, datetime, timezone

from sqlalchemy import (
    CHAR,
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy import column as sa_column
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

# ---------- 跨库类型工具 ----------
BigIntPK = BigInteger().with_variant(Integer, "sqlite")
JSONType = JSON().with_variant(JSONB, "postgresql")
TZDateTime = DateTime(timezone=True)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _pk() -> Mapped[int]:
    return mapped_column(BigIntPK, primary_key=True, autoincrement=True)


# ---------- 枚举（PG 原生 TYPE / SQLite VARCHAR+CHECK） ----------
UserRoleEnum = Enum("admin", "superadmin", "operator", name="user_role", create_constraint=True)
ItemStatusEnum = Enum("active", "merged", "retired", name="item_status", create_constraint=True)
PrintModeEnum = Enum("label", "scan_card", name="print_mode", create_constraint=True)
DocTypeEnum = Enum(
    "inbound", "outbound", "return", "transfer", "stocktake", "adjust",
    name="doc_type", create_constraint=True,
)
BarcodeChangeEnum = Enum(
    "assign", "reassign", "merge_retire", "manual_fix", "import",
    name="barcode_change", create_constraint=True,
)
StocktakeStateEnum = Enum("draft", "counting", "done", name="stocktake_state", create_constraint=True)
ReturnStateEnum = Enum("pending", "accepted", "rejected", name="return_state", create_constraint=True)
DocStateEnum = Enum("draft", "posted", "voided", name="doc_state", create_constraint=True)

# 正则 CHECK 用（regexp_match 双方言编译：PG `~` / SQLite REGEXP）
_c_barcode = sa_column("barcode")
_c_prefix = sa_column("prefix")
_c_region = sa_column("region_code")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = _pk()
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(50), nullable=False)
    role: Mapped[str] = mapped_column(UserRoleEnum, nullable=False, default="operator", server_default=text("'operator'"))
    home_location_id: Mapped[int | None] = mapped_column(
        BigIntPK, ForeignKey("locations.id", name="fk_users_home_location"), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    last_login_at: Mapped[datetime | None] = mapped_column(TZDateTime, nullable=True)
    # 头像（2026-11-04）：base64 PNG，与工作台统一账号体系同步
    avatar_data: Mapped[str | None] = mapped_column(Text, nullable=True)
    avatar_updated_at: Mapped[datetime | None] = mapped_column(TZDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"), default=utcnow, onupdate=utcnow)

    home_location: Mapped["Location | None"] = relationship("Location", lazy="joined")


class Location(Base):
    __tablename__ = "locations"

    id: Mapped[int] = _pk()
    code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)   # HQ / JC / ST / HD / MZ / KFQ
    name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)   # 总校办仓库 / 金城校区 ...
    type: Mapped[str] = mapped_column(String(20), nullable=False, default="campus", server_default=text("'campus'"))  # warehouse | campus
    is_front_warehouse: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"), default=utcnow)


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = _pk()
    digit: Mapped[str] = mapped_column(String(1), unique=True, nullable=False)   # CHAR(1)：1/2/3/4/5/9，参与条码构成
    name: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)  # 教材/书籍/辅材/耗材/礼品/其他
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"), default=utcnow, onupdate=utcnow)


class BarcodeRule(Base):
    """编码规则单行配置（id 恒为 1）。"""
    __tablename__ = "barcode_rules"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_singleton"),
        CheckConstraint(_c_prefix.regexp_match(r"^[0-9]+$"), name="ck_prefix_numeric"),
        CheckConstraint(_c_region.regexp_match(r"^[0-9]+$"), name="ck_region_numeric"),
    )

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, default=1, server_default=text("1"))
    prefix: Mapped[str] = mapped_column(String(4), nullable=False, default="2", server_default=text("'2'"))
    region_code: Mapped[str] = mapped_column(String(4), nullable=False, default="10", server_default=text("'10'"))
    seq_width: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=4, server_default=text("4"))
    total_length: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=8, server_default=text("8"))
    allow_external: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    updated_by: Mapped[int | None] = mapped_column(BigIntPK, ForeignKey("users.id"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"), default=utcnow, onupdate=utcnow)


class BarcodeSequence(Base):
    """各分类当前流水。分配时 PG 用 SELECT ... FOR UPDATE，SQLite 靠事务+唯一索引兜底。"""
    __tablename__ = "barcode_sequences"

    category_id: Mapped[int] = mapped_column(
        BigIntPK, ForeignKey("categories.id"), primary_key=True
    )
    next_seq: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default=text("1"))
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"), default=utcnow, onupdate=utcnow)

    category: Mapped[Category] = relationship("Category", lazy="joined")


class Item(Base):
    __tablename__ = "items"
    __table_args__ = (
        # 条码格式：NULL（待编码）或 8~14 位纯数字
        CheckConstraint(
            _c_barcode.is_(None) | _c_barcode.regexp_match(r"^[0-9]{8,14}$"),
            name="ck_barcode_numeric",
        ),
        # status='merged' 当且仅当 merged_into_id 非空
        CheckConstraint(
            text("(status = 'merged') = (merged_into_id IS NOT NULL)"),
            name="ck_merged_consistency",
        ),
        # 全局唯一但允许多个 NULL（部分唯一索引；PG/SQLite 各自 where 语法）
        Index(
            "uq_items_barcode", "barcode", unique=True,
            postgresql_where=text("barcode IS NOT NULL"),
            sqlite_where=text("barcode IS NOT NULL"),
        ),
        # 契约中 PG 用 gin_trgm_ops 模糊搜索索引；此处建普通索引保证 SQLite 可建表，
        # gin_trgm 版本在 alembic migration 中对 PG 单独创建
        Index("idx_items_name", "name"),
        Index("idx_items_category", "category_id"),
        Index("idx_items_status", "status"),
    )

    id: Mapped[int] = _pk()
    barcode: Mapped[str | None] = mapped_column(String(20), unique=False, nullable=True)  # NULL=待编码
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    category_id: Mapped[int] = mapped_column(BigIntPK, ForeignKey("categories.id"), nullable=False)
    spec: Mapped[str | None] = mapped_column(String(100), default="", server_default=text("''"))
    suggest_price: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    unit: Mapped[str | None] = mapped_column(String(20), default="件", server_default=text("'件'"))
    need_label: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    print_mode: Mapped[str] = mapped_column(PrintModeEnum, nullable=False, default="label", server_default=text("'label'"))
    status: Mapped[str] = mapped_column(ItemStatusEnum, nullable=False, default="active", server_default=text("'active'"))
    merged_into_id: Mapped[int | None] = mapped_column(
        BigIntPK, ForeignKey("items.id", name="fk_items_merged_into", use_alter=True), nullable=True
    )
    barcode_origin: Mapped[str] = mapped_column(String(10), nullable=False, default="internal", server_default=text("'internal'"))
    remark: Mapped[str | None] = mapped_column(Text, default="", server_default=text("''"))
    created_by: Mapped[int | None] = mapped_column(BigIntPK, ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"), default=utcnow, onupdate=utcnow)

    category: Mapped[Category] = relationship("Category", lazy="joined")
    # 自引用多对一：merged_into 指向保留项。remote_side 用列对象列表形式
    # （SQLAlchemy 2.x 官方文档自引用写法），比字符串 "Item.id" 更稳妥，
    # 避免 mapper 配置期解析失败导致全 app 首次查询即崩。
    merged_into: Mapped["Item | None"] = relationship("Item", remote_side=[id], lazy="select")
    photos: Mapped[list["ItemPhoto"]] = relationship(
        "ItemPhoto", back_populates="item", cascade="all, delete-orphan",
        order_by="ItemPhoto.sort_order", lazy="select",
    )
    aliases: Mapped[list["ItemAlias"]] = relationship("ItemAlias", back_populates="item", cascade="all, delete-orphan", lazy="select")


class ItemPhoto(Base):
    __tablename__ = "item_photos"
    __table_args__ = (Index("idx_photos_item", "item_id"),)

    id: Mapped[int] = _pk()
    item_id: Mapped[int] = mapped_column(BigIntPK, ForeignKey("items.id", ondelete="CASCADE"), nullable=False)
    file_path: Mapped[str] = mapped_column(String(300), nullable=False)   # 相对 uploads/ 的路径
    file_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="upload", server_default=text("'upload'"))  # upload | camera | migrated
    uploaded_by: Mapped[int | None] = mapped_column(BigIntPK, ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"), default=utcnow)

    item: Mapped[Item] = relationship("Item", back_populates="photos")


class ItemAlias(Base):
    """物品别名（DESIGN §5.1）：保留历史叫法，扫码/搜索可命中。DDL 未列出，按任务契约补全。"""
    __tablename__ = "item_aliases"
    __table_args__ = (Index("idx_aliases_item", "item_id"), Index("idx_aliases_alias", "alias"))

    id: Mapped[int] = _pk()
    item_id: Mapped[int] = mapped_column(BigIntPK, ForeignKey("items.id", ondelete="CASCADE"), nullable=False)
    alias: Mapped[str] = mapped_column(String(200), nullable=False)
    source: Mapped[str] = mapped_column(String(30), nullable=False, default="manual", server_default=text("'manual'"))
    created_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"), default=utcnow)

    item: Mapped[Item] = relationship("Item", back_populates="aliases")


class BarcodeHistory(Base):
    __tablename__ = "barcode_history"
    __table_args__ = (
        Index("idx_bchist_item", "item_id"),
        Index("idx_bchist_oldcode", "old_barcode"),           # 扫旧码溯源用
        Index("idx_bchist_created", "created_at"),             # 查询按 created_at DESC 排序
    )

    id: Mapped[int] = _pk()
    item_id: Mapped[int] = mapped_column(BigIntPK, ForeignKey("items.id"), nullable=False)
    old_barcode: Mapped[str | None] = mapped_column(String(20), nullable=True)
    new_barcode: Mapped[str | None] = mapped_column(String(20), nullable=True)
    change_type: Mapped[str] = mapped_column(BarcodeChangeEnum, nullable=False)
    reason: Mapped[str | None] = mapped_column(String(300), default="", server_default=text("''"))
    operator_id: Mapped[int | None] = mapped_column(BigIntPK, ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"), default=utcnow)

    item: Mapped[Item] = relationship("Item", lazy="joined")
    operator: Mapped["User | None"] = relationship("User", lazy="joined")


class Inventory(Base):
    """库存（一物 × 一库位 一行）。"""
    __tablename__ = "inventory"
    __table_args__ = (
        UniqueConstraint("item_id", "location_id", name="uq_inventory_item_location"),
        CheckConstraint("qty_on_hand >= 0", name="ck_qty_non_negative"),
        CheckConstraint("qty_reserved >= 0", name="ck_reserved_non_negative"),
        Index("idx_inventory_location", "location_id"),
    )

    id: Mapped[int] = _pk()
    item_id: Mapped[int] = mapped_column(BigIntPK, ForeignKey("items.id"), nullable=False)
    location_id: Mapped[int] = mapped_column(BigIntPK, ForeignKey("locations.id"), nullable=False)
    qty_on_hand: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    qty_reserved: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    safety_stock: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"), default=utcnow, onupdate=utcnow)

    item: Mapped[Item] = relationship("Item", lazy="joined")
    location: Mapped[Location] = relationship("Location", lazy="joined")


class StockMovement(Base):
    """统一库存流水（审计 + 报表真源）。change_qty 正=入，负=出。"""
    __tablename__ = "stock_movements"
    __table_args__ = (
        Index("idx_sm_item_loc_time", "item_id", "location_id", "created_at"),
        Index("idx_sm_doc", "doc_type", "doc_id"),
        Index("idx_sm_created", "created_at"),
    )

    id: Mapped[int] = _pk()
    item_id: Mapped[int] = mapped_column(BigIntPK, ForeignKey("items.id"), nullable=False)
    location_id: Mapped[int] = mapped_column(BigIntPK, ForeignKey("locations.id"), nullable=False)
    change_qty: Mapped[int] = mapped_column(Integer, nullable=False)
    qty_before: Mapped[int] = mapped_column(Integer, nullable=False)
    qty_after: Mapped[int] = mapped_column(Integer, nullable=False)
    doc_type: Mapped[str] = mapped_column(DocTypeEnum, nullable=False)
    doc_id: Mapped[int | None] = mapped_column(BigIntPK, nullable=True)      # 多态指向单据 id
    doc_no: Mapped[str | None] = mapped_column(String(30), nullable=True)    # 冗余单据号
    operator_id: Mapped[int | None] = mapped_column(BigIntPK, ForeignKey("users.id"), nullable=True)
    note: Mapped[str | None] = mapped_column(String(300), default="", server_default=text("''"))
    created_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"), default=utcnow)

    item: Mapped[Item] = relationship("Item", lazy="joined")
    location: Mapped[Location] = relationship("Location", lazy="joined")
    operator: Mapped["User | None"] = relationship("User", lazy="joined")


class InboundOrder(Base):
    """入库单（采购到总校办前置仓）。doc_no: IN-YYYYMMDD-NNN"""
    __tablename__ = "inbound_orders"

    id: Mapped[int] = _pk()
    doc_no: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    supplier: Mapped[str | None] = mapped_column(String(100), default="", server_default=text("''"))
    location_id: Mapped[int] = mapped_column(BigIntPK, ForeignKey("locations.id"), nullable=False)
    is_for_sale: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    state: Mapped[str] = mapped_column(DocStateEnum, nullable=False, default="draft", server_default=text("'draft'"))
    order_date: Mapped[date] = mapped_column(Date, nullable=False, server_default=text("CURRENT_DATE"))
    total_amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0, server_default=text("0"))
    remark: Mapped[str | None] = mapped_column(Text, default="", server_default=text("''"))
    operator_id: Mapped[int | None] = mapped_column(BigIntPK, ForeignKey("users.id"), nullable=True)
    posted_at: Mapped[datetime | None] = mapped_column(TZDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"), default=utcnow, onupdate=utcnow)

    location: Mapped[Location] = relationship("Location", lazy="joined")
    items: Mapped[list["InboundItem"]] = relationship(
        "InboundItem", back_populates="order", cascade="all, delete-orphan",
        order_by="InboundItem.sort_order", lazy="select",
    )


class InboundItem(Base):
    __tablename__ = "inbound_items"
    __table_args__ = (
        CheckConstraint("qty > 0", name="ck_inb_qty_positive"),
        Index("idx_inb_items_order", "order_id"),
    )

    id: Mapped[int] = _pk()
    order_id: Mapped[int] = mapped_column(BigIntPK, ForeignKey("inbound_orders.id", ondelete="CASCADE"), nullable=False)
    item_id: Mapped[int] = mapped_column(BigIntPK, ForeignKey("items.id"), nullable=False)
    barcode_snapshot: Mapped[str | None] = mapped_column(String(20), nullable=True)
    name_snapshot: Mapped[str | None] = mapped_column(String(200), nullable=True)
    spec_snapshot: Mapped[str | None] = mapped_column(String(100), nullable=True)
    qty: Mapped[int] = mapped_column(Integer, nullable=False)
    purchase_price: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    sale_price: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))

    order: Mapped[InboundOrder] = relationship("InboundOrder", back_populates="items")
    item: Mapped[Item] = relationship("Item", lazy="joined")


class OutboundOrder(Base):
    """出库单/调拨单（总校办 → 校区）。doc_no: OUT-YYYYMMDD-NNN"""
    __tablename__ = "outbound_orders"

    id: Mapped[int] = _pk()
    doc_no: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="transfer", server_default=text("'transfer'"))  # transfer | issue
    from_location_id: Mapped[int] = mapped_column(BigIntPK, ForeignKey("locations.id"), nullable=False)
    to_location_id: Mapped[int | None] = mapped_column(BigIntPK, ForeignKey("locations.id"), nullable=True)
    state: Mapped[str] = mapped_column(DocStateEnum, nullable=False, default="draft", server_default=text("'draft'"))
    order_date: Mapped[date] = mapped_column(Date, nullable=False, server_default=text("CURRENT_DATE"))
    remark: Mapped[str | None] = mapped_column(Text, default="", server_default=text("''"))
    operator_id: Mapped[int | None] = mapped_column(BigIntPK, ForeignKey("users.id"), nullable=True)
    posted_at: Mapped[datetime | None] = mapped_column(TZDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"), default=utcnow, onupdate=utcnow)

    from_location: Mapped[Location] = relationship("Location", foreign_keys=[from_location_id], lazy="joined")
    to_location: Mapped["Location | None"] = relationship("Location", foreign_keys=[to_location_id], lazy="joined")
    items: Mapped[list["OutboundItem"]] = relationship(
        "OutboundItem", back_populates="order", cascade="all, delete-orphan",
        order_by="OutboundItem.sort_order", lazy="select",
    )


class OutboundItem(Base):
    __tablename__ = "outbound_items"
    __table_args__ = (
        CheckConstraint("qty > 0", name="ck_outb_qty_positive"),
        Index("idx_outb_items_order", "order_id"),
    )

    id: Mapped[int] = _pk()
    order_id: Mapped[int] = mapped_column(BigIntPK, ForeignKey("outbound_orders.id", ondelete="CASCADE"), nullable=False)
    item_id: Mapped[int] = mapped_column(BigIntPK, ForeignKey("items.id"), nullable=False)
    barcode_snapshot: Mapped[str | None] = mapped_column(String(20), nullable=True)
    name_snapshot: Mapped[str | None] = mapped_column(String(200), nullable=True)
    qty: Mapped[int] = mapped_column(Integer, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))

    order: Mapped[OutboundOrder] = relationship("OutboundOrder", back_populates="items")
    item: Mapped[Item] = relationship("Item", lazy="joined")


class ReturnOrder(Base):
    """退库单（校区 → 总校办）。doc_no: RET-YYYYMMDD-NNN"""
    __tablename__ = "return_orders"
    __table_args__ = (
        CheckConstraint("item_condition IN ('sealed','opened')", name="ck_return_condition"),
    )

    id: Mapped[int] = _pk()
    doc_no: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    from_location_id: Mapped[int] = mapped_column(BigIntPK, ForeignKey("locations.id"), nullable=False)
    to_location_id: Mapped[int] = mapped_column(BigIntPK, ForeignKey("locations.id"), nullable=False)
    item_condition: Mapped[str] = mapped_column(String(20), nullable=False, default="sealed", server_default=text("'sealed'"))
    state: Mapped[str] = mapped_column(ReturnStateEnum, nullable=False, default="pending", server_default=text("'pending'"))
    accept_state: Mapped[str] = mapped_column(DocStateEnum, nullable=False, default="draft", server_default=text("'draft'"))
    order_date: Mapped[date] = mapped_column(Date, nullable=False, server_default=text("CURRENT_DATE"))
    remark: Mapped[str | None] = mapped_column(Text, default="", server_default=text("''"))
    operator_id: Mapped[int | None] = mapped_column(BigIntPK, ForeignKey("users.id"), nullable=True)
    accepted_by: Mapped[int | None] = mapped_column(BigIntPK, ForeignKey("users.id"), nullable=True)
    posted_at: Mapped[datetime | None] = mapped_column(TZDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"), default=utcnow, onupdate=utcnow)

    from_location: Mapped[Location] = relationship("Location", foreign_keys=[from_location_id], lazy="joined")
    to_location: Mapped[Location] = relationship("Location", foreign_keys=[to_location_id], lazy="joined")
    items: Mapped[list["ReturnItem"]] = relationship(
        "ReturnItem", back_populates="order", cascade="all, delete-orphan",
        order_by="ReturnItem.sort_order", lazy="select",
    )


class ReturnItem(Base):
    __tablename__ = "return_items"
    __table_args__ = (
        CheckConstraint("qty > 0", name="ck_ret_qty_positive"),
        Index("idx_ret_items_order", "order_id"),
    )

    id: Mapped[int] = _pk()
    order_id: Mapped[int] = mapped_column(BigIntPK, ForeignKey("return_orders.id", ondelete="CASCADE"), nullable=False)
    item_id: Mapped[int] = mapped_column(BigIntPK, ForeignKey("items.id"), nullable=False)
    barcode_snapshot: Mapped[str | None] = mapped_column(String(20), nullable=True)
    name_snapshot: Mapped[str | None] = mapped_column(String(200), nullable=True)
    qty: Mapped[int] = mapped_column(Integer, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))

    order: Mapped[ReturnOrder] = relationship("ReturnOrder", back_populates="items")
    item: Mapped[Item] = relationship("Item", lazy="joined")


class Stocktake(Base):
    """盘点单。doc_no: STK-YYYYMMDD-NNN"""
    __tablename__ = "stocktakes"

    id: Mapped[int] = _pk()
    doc_no: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    location_id: Mapped[int] = mapped_column(BigIntPK, ForeignKey("locations.id"), nullable=False)
    category_id: Mapped[int | None] = mapped_column(BigIntPK, ForeignKey("categories.id"), nullable=True)  # NULL=全类目
    state: Mapped[str] = mapped_column(StocktakeStateEnum, nullable=False, default="draft", server_default=text("'draft'"))
    stocktake_date: Mapped[date] = mapped_column(Date, nullable=False, server_default=text("CURRENT_DATE"))
    remark: Mapped[str | None] = mapped_column(Text, default="", server_default=text("''"))
    operator_id: Mapped[int | None] = mapped_column(BigIntPK, ForeignKey("users.id"), nullable=True)
    posted_at: Mapped[datetime | None] = mapped_column(TZDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"), default=utcnow, onupdate=utcnow)

    location: Mapped[Location] = relationship("Location", lazy="joined")
    items: Mapped[list["StocktakeItem"]] = relationship(
        "StocktakeItem", back_populates="stocktake", cascade="all, delete-orphan",
        order_by="StocktakeItem.sort_order", lazy="select",
    )


class StocktakeItem(Base):
    """盘点行。variance 为存储生成列（PG GENERATED STORED / SQLite 3.31+ 均支持）。"""
    __tablename__ = "stocktake_items"
    __table_args__ = (
        UniqueConstraint("stocktake_id", "item_id", name="uq_stk_item"),
        Index("idx_stk_items_doc", "stocktake_id"),
    )

    id: Mapped[int] = _pk()
    stocktake_id: Mapped[int] = mapped_column(BigIntPK, ForeignKey("stocktakes.id", ondelete="CASCADE"), nullable=False)
    item_id: Mapped[int] = mapped_column(BigIntPK, ForeignKey("items.id"), nullable=False)
    barcode_snapshot: Mapped[str | None] = mapped_column(String(20), nullable=True)
    name_snapshot: Mapped[str | None] = mapped_column(String(200), nullable=True)
    qty_book: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    qty_counted: Mapped[int | None] = mapped_column(Integer, nullable=True)   # NULL=未盘
    variance: Mapped[int | None] = mapped_column(
        Integer,
        Computed("qty_counted - qty_book", persisted=True),
        nullable=True,
    )
    diff_state: Mapped[str | None] = mapped_column(String(20), default="", server_default=text("''"))     # 盘盈/盘亏/相符
    handle_result: Mapped[str | None] = mapped_column(String(100), default="", server_default=text("''"))
    remark: Mapped[str | None] = mapped_column(String(300), default="", server_default=text("''"))
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))

    stocktake: Mapped[Stocktake] = relationship("Stocktake", back_populates="items")
    item: Mapped[Item] = relationship("Item", lazy="joined")


class ItemMergeLog(Base):
    """物品合并日志（可回滚）。impact_snapshot 存合并前快照。"""
    __tablename__ = "item_merge_log"
    __table_args__ = (
        Index("idx_merge_keeper", "keeper_id"),
        Index("idx_merge_merged", "merged_id"),
    )

    id: Mapped[int] = _pk()
    keeper_id: Mapped[int] = mapped_column(BigIntPK, ForeignKey("items.id"), nullable=False)
    merged_id: Mapped[int] = mapped_column(BigIntPK, ForeignKey("items.id"), nullable=False)
    merged_barcode: Mapped[str | None] = mapped_column(String(20), nullable=True)
    merged_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    impact_snapshot: Mapped[dict] = mapped_column(JSONType, nullable=False)
    reason: Mapped[str | None] = mapped_column(String(300), default="", server_default=text("''"))
    operator_id: Mapped[int | None] = mapped_column(BigIntPK, ForeignKey("users.id"), nullable=True)
    rolled_back_at: Mapped[datetime | None] = mapped_column(TZDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"), default=utcnow)

    keeper: Mapped[Item] = relationship("Item", foreign_keys=[keeper_id], lazy="joined")
    merged: Mapped[Item] = relationship("Item", foreign_keys=[merged_id], lazy="joined")
    operator: Mapped["User | None"] = relationship("User", lazy="joined")


class DeletedItem(Base):
    """已彻底删除的物品档案（归档，2026-11-04 引入）。

    背景：仓库早期录入了不少库存数值胡乱填写的物品，普通「删除」（软删=retired）
    因有库存/流水而被拦。超级管理员需要能「彻底删除」——物品档案从名录消失、
    条码释放可再分配，但历史业务凭证（入库/出库/盘点单据）必须完整保留。

    做法：物品行真正从 items 表移除；所有引用它的行按下列策略处理——
      · inventory（库存行）        → 行保留，qty_on_hand/qty_reserved 归零
      · stock_movements（流水）     → 行保留（审计真源，不可删）
      · inbound/outbound/return/stocktake 明细行 → 行保留，item_id 改指向
        「已删除物品」占位档案（快照字段 name_snapshot/barcode_snapshot 已存原值，
        历史单据展示不受影响）
      · item_photos / item_aliases  → 行保留，关联占位档案
      · barcode_history             → 行保留，关联占位档案
      · item_merge_log              → 行保留，关联占位档案
    本表存被删物品的原始快照 + 处理摘要，供「查看已删除档案」与「恢复」使用。
    """

    __tablename__ = "deleted_items"
    __table_args__ = (
        Index("idx_deleted_items_barcode", "barcode"),
        Index("idx_deleted_items_time", "deleted_at"),
    )

    id: Mapped[int] = _pk()
    origin_item_id: Mapped[int] = mapped_column(BigIntPK, nullable=False)  # 原 items.id
    barcode: Mapped[str | None] = mapped_column(String(20), nullable=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    category_id: Mapped[int | None] = mapped_column(BigIntPK, nullable=True)
    category_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    spec: Mapped[str | None] = mapped_column(String(100), nullable=True)
    unit: Mapped[str | None] = mapped_column(String(20), nullable=True)
    suggest_price: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    remark: Mapped[str | None] = mapped_column(Text, default="", server_default=text("''"))
    # 处理摘要（JSON）：{"stock_rows":12,"movements":34,"doc_lines":8,"photos":3,...}
    # server_default 用 '{}'（不带 ::jsonb）：PG 会隐式转成 jsonb，SQLite 也能解析
    impact: Mapped[dict] = mapped_column(JSONType, nullable=False, default=dict, server_default=text("'{}'"))
    reason: Mapped[str | None] = mapped_column(String(300), default="", server_default=text("''"))
    operator_id: Mapped[int | None] = mapped_column(BigIntPK, ForeignKey("users.id"), nullable=True)
    operator_name: Mapped[str | None] = mapped_column(String(50), nullable=True)
    deleted_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"), default=utcnow)
    # 恢复痕迹：恢复后标记时间与操作人（保留记录不物理删，便于追溯）
    restored_at: Mapped[datetime | None] = mapped_column(TZDateTime, nullable=True)
    restored_by: Mapped[str | None] = mapped_column(String(50), nullable=True)

    operator: Mapped["User | None"] = relationship("User", lazy="joined")


class AuditLog(Base):
    __tablename__ = "audit_log"
    __table_args__ = (
        Index("idx_audit_entity", "entity", "entity_id"),
        Index("idx_audit_time", "created_at"),
    )

    id: Mapped[int] = _pk()
    user_id: Mapped[int | None] = mapped_column(BigIntPK, ForeignKey("users.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(50), nullable=False)   # create/update/delete/merge/reassign/post...
    entity: Mapped[str] = mapped_column(String(30), nullable=False)   # item/category/inbound_order...
    entity_id: Mapped[int | None] = mapped_column(BigIntPK, nullable=True)
    detail: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    ip: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"), default=utcnow)

    user: Mapped["User | None"] = relationship("User", lazy="joined")


class DocCounter(Base):
    """单据号计数器：prefix + ymd 复合主键。"""
    __tablename__ = "doc_counters"

    prefix: Mapped[str] = mapped_column(String(20), primary_key=True)   # IN / OUT / RET / STK
    ymd: Mapped[str] = mapped_column(CHAR(8), primary_key=True)         # CHAR(8): 20261019
    seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))


class RefreshTokenBlacklist(Base):
    """logout 失效的 refresh token 黑名单（存 jti）。

    取舍说明：不引入 Redis，内部系统几十用户规模用表即可；
    access token（2h）无法即时失效，logout 只失效 refresh 并依赖前端丢弃 access。
    """
    __tablename__ = "refresh_token_blacklist"

    jti: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int | None] = mapped_column(BigIntPK, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"), default=utcnow)
