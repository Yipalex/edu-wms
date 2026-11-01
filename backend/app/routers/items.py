"""物品档案路由（DESIGN §6）。

- GET    /items           分页 + q（名称/条码/别名模糊）+ 多条件筛选 + 排序
- POST   /items           新建（barcode 可空=待编码；填了则校验格式+唯一+分类位一致）
- GET    /items/{id}      详情（照片/各库位库存/最近流水/别名/条码历史）
- PATCH  /items/{id}      改档案
- DELETE /items/{id}      软删 status=retired（有库存/流水则 409）
- POST   /items/batch     CSV/xlsx 批量导入（openpyxl；列名兼容中文表头）
- POST   /items/{id}/photos / DELETE .../photos/{photo_id}   照片上传/删除
- GET/POST /items/{id}/aliases                               别名
"""
import csv
import io
import logging
import re
import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from fastapi import APIRouter, Depends, File, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.config import settings
from app.db import get_db
from app.deps import get_current_user, require_role
from app.models import (
    BarcodeHistory, Category, Inventory, Item, ItemAlias, ItemMergeLog, ItemPhoto,
    StockMovement, User,
)
from app.schemas.common import BizError, ok, ok_page
from app.services import barcode as bc
from app.services import merge as merge_svc
from app.services.audit import write_audit

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/items", tags=["物品档案"])

AdminUser = require_role("admin")

ALLOWED_IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
ALLOWED_IMAGE_MIME = {"image/jpeg", "image/png", "image/webp", "image/gif"}
PRINT_MODE_MAP = {"label": "label", "scan_card": "scan_card", "贴标": "label", "扫码卡": "scan_card"}


# ---------- Pydantic ----------

class ItemCreate(BaseModel):
    barcode: str | None = Field(default=None, max_length=20, description="留空=待编码")
    name: str = Field(min_length=1, max_length=200)
    category_id: int
    spec: str = Field(default="", max_length=100)
    suggest_price: Decimal | None = Field(default=None, ge=0, decimal_places=2)
    unit: str = Field(default="件", max_length=20)
    need_label: bool = True
    print_mode: str = Field(default="label", pattern=r"^(label|scan_card)$")
    remark: str = Field(default="", max_length=2000)


class ItemPatch(BaseModel):
    barcode: str | None = Field(default=None, max_length=20)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    category_id: int | None = None
    spec: str | None = Field(default=None, max_length=100)
    suggest_price: Decimal | None = Field(default=None, ge=0, decimal_places=2)
    unit: str | None = Field(default=None, max_length=20)
    need_label: bool | None = None
    print_mode: str | None = Field(default=None, pattern=r"^(label|scan_card)$")
    remark: str | None = Field(default=None, max_length=2000)


class AliasCreate(BaseModel):
    alias: str = Field(min_length=1, max_length=200)
    source: str = Field(default="manual", max_length=30)


# ---------- 序列化 ----------

def photo_url(p: ItemPhoto) -> str:
    return f"/api/uploads/{p.file_path}"


def item_row(i: Item, *, with_stock: bool = False, db: Session | None = None) -> dict:
    d = {
        "id": i.id,
        "barcode": i.barcode,
        "name": i.name,
        "category_id": i.category_id,
        "category_name": i.category.name if i.category else None,
        "category_digit": i.category.digit if i.category else None,
        "spec": i.spec or "",
        "suggest_price": float(i.suggest_price) if i.suggest_price is not None else None,
        "unit": i.unit,
        "need_label": i.need_label,
        "print_mode": i.print_mode,
        "status": i.status,
        "barcode_origin": i.barcode_origin,
        "remark": i.remark or "",
        "photo_url": None,
        "photo_count": 0,
        "created_at": i.created_at.isoformat() if i.created_at else None,
        "updated_at": i.updated_at.isoformat() if i.updated_at else None,
    }
    photos = i.photos or []
    d["photo_count"] = len(photos)
    primary = next((p for p in photos if p.is_primary), photos[0] if photos else None)
    if primary:
        d["photo_url"] = photo_url(primary)
    if with_stock and db is not None:
        d["total_qty"] = db.scalar(
            select(func.coalesce(func.sum(Inventory.qty_on_hand), 0))
            .where(Inventory.item_id == i.id)
        ) or 0
    return d


def _get_item_or_404(db: Session, item_id: int) -> Item:
    item = db.get(Item, item_id)
    if item is None:
        raise BizError("物品不存在", code="ERR_NOT_FOUND", status=404)
    return item


def _apply_barcode(db: Session, item: Item, barcode: str | None, category_id: int) -> None:
    """校验并设置条码；barcode 为 None/空串表示待编码。"""
    if barcode in (None, ""):
        item.barcode = None
        return
    code = barcode.strip()
    origin = bc.check_barcode_for_item(db, code, category_id, exclude_item_id=item.id)
    item.barcode = code
    item.barcode_origin = origin


# ---------- 列表 ----------

SORTABLE = {
    "id": Item.id, "barcode": Item.barcode, "name": Item.name,
    "category_id": Item.category_id, "suggest_price": Item.suggest_price,
    "created_at": Item.created_at, "updated_at": Item.updated_at,
}


@router.get("")
def list_items(
    page: int = 1, page_size: int = 20,
    q: str | None = None,
    category_id: int | None = None,
    status: str | None = None,
    need_label: bool | None = None,
    print_mode: str | None = None,
    has_photo: bool | None = None,
    pending_code: bool | None = None,
    sort_by: str = "id", sort_dir: str = "asc",
    _: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    page = max(1, page)
    page_size = min(200, max(1, page_size))
    conds = []
    if q:
        like = f"%{q.strip()}%"
        alias_item_ids = select(ItemAlias.item_id).where(ItemAlias.alias.like(like))
        conds.append(or_(
            Item.name.like(like),
            Item.barcode.like(like),
            Item.id.in_(alias_item_ids),
        ))
    if category_id is not None:
        conds.append(Item.category_id == category_id)
    if status:
        conds.append(Item.status == status)
    if need_label is not None:
        conds.append(Item.need_label == need_label)
    if print_mode:
        conds.append(Item.print_mode == print_mode)
    if has_photo is not None:
        sub = select(ItemPhoto.item_id).distinct()
        conds.append(Item.id.in_(sub) if has_photo else ~Item.id.in_(sub))
    if pending_code is True:
        # 待编码物品：barcode 为空（现场只填名称+拍照、盘点后统一编码的流程）
        conds.append(Item.barcode.is_(None))

    col = SORTABLE.get(sort_by, Item.id)
    order = col.desc() if sort_dir == "desc" else col.asc()

    cq = select(func.count(Item.id))
    for c in conds:
        cq = cq.where(c)
    total = db.scalar(cq) or 0

    q_stmt = (
        select(Item).options(selectinload(Item.photos), selectinload(Item.category))
        .order_by(order, Item.id)
        .offset((page - 1) * page_size).limit(page_size)
    )
    for c in conds:
        q_stmt = q_stmt.where(c)
    rows = db.scalars(q_stmt).all()
    return ok_page([item_row(i, with_stock=True, db=db) for i in rows],
                   page=page, page_size=page_size, total=total)


# ---------- 去重合并（DESIGN §5；注意：必须注册在 GET /{item_id} 之前） ----------

@router.get("/duplicates")
def list_duplicates(
    threshold: float = 0.7,
    admin: User = Depends(AdminUser), db: Session = Depends(get_db),
):
    """相似分组（status='active' 全部物品）。算法见契约 §5.1 / services/merge.py。"""
    threshold = min(1.0, max(0.5, threshold))
    items = db.scalars(
        select(Item).options(selectinload(Item.photos))
        .where(Item.status == "active")
    ).all()
    if not items:
        return ok([])

    ids = [i.id for i in items]
    # 全库位库存合计 / 主图 / 别名数，一次性聚合
    qty_map = {
        r[0]: (r[1] or 0)
        for r in db.execute(
            select(Inventory.item_id, func.sum(Inventory.qty_on_hand))
            .where(Inventory.item_id.in_(ids)).group_by(Inventory.item_id)
        )
    }
    alias_map = {
        r[0]: r[1]
        for r in db.execute(
            select(ItemAlias.item_id, func.count(ItemAlias.id))
            .where(ItemAlias.item_id.in_(ids)).group_by(ItemAlias.item_id)
        )
    }
    member_map = {
        i.id: {
            "id": i.id, "barcode": i.barcode, "name": i.name, "spec": i.spec or "",
            "category_name": i.category.name if i.category else None,
            "suggest_price": float(i.suggest_price) if i.suggest_price is not None else None,
            "total_qty": qty_map.get(i.id, 0),
            "photo_url": None,
            "alias_count": alias_map.get(i.id, 0),
        }
        for i in items
    }
    for i in items:
        photos = i.photos or []
        primary = next((p for p in photos if p.is_primary), photos[0] if photos else None)
        if primary:
            member_map[i.id]["photo_url"] = photo_url(primary)

    groups = merge_svc.find_duplicate_groups(
        [{"id": i.id, "name": i.name} for i in items], threshold=threshold,
    )
    out = []
    for g in groups:
        out.append({
            "group_key": g["group_key"],
            "match_type": g["match_type"],
            "confidence": g["confidence"],
            "suggested_name": g["suggested_name"],
            "members": [member_map[mid] for mid in g["member_ids"]],
        })
    return ok(out)


@router.get("/merges")
def list_merges(
    page: int = 1, page_size: int = 20,
    admin: User = Depends(AdminUser), db: Session = Depends(get_db),
):
    """合并记录（item_merge_log 倒序）。"""
    page = max(1, page)
    page_size = min(200, max(1, page_size))
    total = db.scalar(select(func.count(ItemMergeLog.id))) or 0
    rows = db.scalars(
        select(ItemMergeLog)
        .order_by(ItemMergeLog.id.desc())
        .offset((page - 1) * page_size).limit(page_size)
    ).all()
    return ok_page([
        {
            "id": m.id,
            "keeper_id": m.keeper_id,
            "keeper_name": m.keeper.name if m.keeper else None,
            "merged_id": m.merged_id,
            "merged_barcode": m.merged_barcode,
            "merged_name": m.merged_name,
            "reason": m.reason or "",
            "operator_id": m.operator_id,
            "operator_name": m.operator.display_name if m.operator else None,
            "rolled_back_at": m.rolled_back_at.isoformat() if m.rolled_back_at else None,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        }
        for m in rows
    ], page=page, page_size=page_size, total=total)


# ---------- 新建 / 详情 / 修改 / 删除 ----------

@router.post("")
def create_item(body: ItemCreate, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    cat = db.get(Category, body.category_id)
    if cat is None:
        raise BizError("类目不存在", code="ERR_NOT_FOUND", status=404)
    item = Item(
        name=body.name.strip(),
        category_id=body.category_id,
        spec=body.spec,
        suggest_price=body.suggest_price,
        unit=body.unit,
        need_label=body.need_label,
        print_mode=body.print_mode,
        remark=body.remark,
        status="active",
        created_by=user.id,
    )
    _apply_barcode(db, item, body.barcode, body.category_id)
    code_snapshot = item.barcode
    db.add(item)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise BizError(f"条码 {code_snapshot} 已被其他物品占用，一物一码不能重复", code="ERR_BARCODE_DUP", status=409)
    if item.barcode:
        db.add(BarcodeHistory(
            item_id=item.id, old_barcode=None, new_barcode=item.barcode,
            change_type="assign", reason="新建物品", operator_id=user.id,
        ))
    write_audit(db, action="create", entity="item", entity_id=item.id, user=user,
                detail={"name": item.name, "barcode": item.barcode}, request=request)
    db.commit()
    db.refresh(item)
    return ok(item_row(item))


@router.get("/{item_id}")
def get_item(item_id: int, _: User = Depends(get_current_user), db: Session = Depends(get_db)):
    item = db.get(Item, item_id)
    if item is None:
        raise BizError("物品不存在", code="ERR_NOT_FOUND", status=404)
    d = item_row(item, with_stock=True, db=db)
    d["photos"] = [
        {"id": p.id, "url": photo_url(p), "file_size": p.file_size,
         "is_primary": p.is_primary, "source": p.source, "sort_order": p.sort_order,
         "created_at": p.created_at.isoformat() if p.created_at else None}
        for p in (item.photos or [])
    ]
    d["aliases"] = [
        {"id": a.id, "alias": a.alias, "source": a.source}
        for a in (item.aliases or [])
    ]
    invs = db.scalars(
        select(Inventory).where(Inventory.item_id == item_id)
    ).all()
    d["inventory"] = [
        {"id": inv.id, "location_id": inv.location_id,
         "location_name": inv.location.name if inv.location else None,
         "qty_on_hand": inv.qty_on_hand, "qty_reserved": inv.qty_reserved,
         "safety_stock": inv.safety_stock}
        for inv in invs
    ]
    movs = db.scalars(
        select(StockMovement).where(StockMovement.item_id == item_id)
        .order_by(StockMovement.created_at.desc(), StockMovement.id.desc()).limit(20)
    ).all()
    d["recent_movements"] = [
        {"id": m.id, "location_id": m.location_id,
         "location_name": m.location.name if m.location else None,
         "change_qty": m.change_qty, "qty_after": m.qty_after,
         "doc_type": m.doc_type, "doc_no": m.doc_no, "note": m.note,
         "created_at": m.created_at.isoformat() if m.created_at else None}
        for m in movs
    ]
    hist = db.scalars(
        select(BarcodeHistory).where(BarcodeHistory.item_id == item_id)
        .order_by(BarcodeHistory.created_at.desc(), BarcodeHistory.id.desc())
    ).all()
    d["barcode_history"] = [
        {"id": h.id, "old_barcode": h.old_barcode, "new_barcode": h.new_barcode,
         "change_type": h.change_type, "reason": h.reason,
         "operator_name": h.operator.display_name if h.operator else None,
         "created_at": h.created_at.isoformat() if h.created_at else None}
        for h in hist
    ]
    return ok(d)


@router.patch("/{item_id}")
def patch_item(item_id: int, body: ItemPatch, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    item = _get_item_or_404(db, item_id)
    if item.status == "merged":
        raise BizError("已合并的物品不能修改，请到保留项上操作", code="ERR_ITEM_MERGED", status=409)
    data = body.model_dump(exclude_unset=True)
    detail: dict = {}

    old_cat_id = item.category_id
    new_cat_id = data.get("category_id", old_cat_id)
    if "category_id" in data:
        if db.get(Category, new_cat_id) is None:
            raise BizError("类目不存在", code="ERR_NOT_FOUND", status=404)
        detail["category_id"] = (old_cat_id, new_cat_id)
        item.category_id = new_cat_id

    if "barcode" in data:
        new_code = data["barcode"]
        if (new_code or None) != item.barcode:
            old = item.barcode
            _apply_barcode(db, item, new_code, new_cat_id)
            detail["barcode"] = (old, item.barcode)
            db.add(BarcodeHistory(
                item_id=item.id, old_barcode=old, new_barcode=item.barcode,
                change_type="manual_fix", reason="档案修改", operator_id=user.id,
            ))
        elif new_cat_id != old_cat_id and item.barcode:
            # 类目变了但条码没变：内部码分类位必须与新类目重新校验一致
            bc.check_barcode_for_item(db, item.barcode, new_cat_id, exclude_item_id=item.id)

    for k in ("name", "spec", "suggest_price", "unit", "need_label", "print_mode", "remark"):
        if k in data:
            v = data[k]
            if k == "name" and isinstance(v, str):
                v = v.strip()
            if getattr(item, k) != v:
                detail[k] = (getattr(item, k), v)
                setattr(item, k, v)

    if detail:
        write_audit(db, action="update", entity="item", entity_id=item.id, user=user,
                    detail={k: {"old": str(x), "new": str(y)} for k, (x, y) in detail.items()},
                    request=request)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise BizError("条码已被其他物品占用，一物一码不能重复", code="ERR_BARCODE_DUP", status=409)
    db.refresh(item)
    return ok(item_row(item))


@router.delete("/{item_id}")
def delete_item(item_id: int, request: Request, admin: User = Depends(AdminUser), db: Session = Depends(get_db)):
    """软删：status=retired。有库存（qty_on_hand>0）或有流水则 409。"""
    item = _get_item_or_404(db, item_id)
    if item.status == "merged":
        raise BizError("已合并的物品不能删除", code="ERR_ITEM_MERGED", status=409)
    if item.status == "retired":
        raise BizError("该物品已是停用状态", code="ERR_ITEM_RETIRED", status=409)
    stock = db.scalar(
        select(func.coalesce(func.sum(Inventory.qty_on_hand), 0)).where(Inventory.item_id == item_id)
    ) or 0
    if stock > 0:
        raise BizError("该物品仍有库存/流水，不能删除；请先清零库存后再操作", code="ERR_ITEM_HAS_STOCK", status=409)
    has_mov = db.scalar(select(StockMovement.id).where(StockMovement.item_id == item_id).limit(1))
    if has_mov is not None:
        raise BizError("该物品仍有库存/流水，不能删除；请先清零库存后再操作", code="ERR_ITEM_HAS_STOCK", status=409)

    item.status = "retired"
    db.add(BarcodeHistory(
        item_id=item.id, old_barcode=item.barcode, new_barcode=None,
        change_type="merge_retire", reason="物品停用（软删）", operator_id=admin.id,
    ))
    write_audit(db, action="delete", entity="item", entity_id=item.id, user=admin,
                detail={"name": item.name, "barcode": item.barcode, "note": "软删=retired"}, request=request)
    db.commit()
    return ok(item_row(item))


# ---------- 别名 ----------

@router.get("/{item_id}/aliases")
def list_aliases(item_id: int, _: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _get_item_or_404(db, item_id)
    rows = db.scalars(select(ItemAlias).where(ItemAlias.item_id == item_id).order_by(ItemAlias.id)).all()
    return ok([{"id": a.id, "alias": a.alias, "source": a.source,
                "created_at": a.created_at.isoformat() if a.created_at else None} for a in rows])


@router.post("/{item_id}/aliases")
def add_alias(item_id: int, body: AliasCreate, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _get_item_or_404(db, item_id)
    alias = body.alias.strip()
    dup = db.scalar(select(ItemAlias).where(
        ItemAlias.item_id == item_id, ItemAlias.alias == alias))
    if dup is not None:
        raise BizError("该别名已存在", code="ERR_ALIAS_DUP", status=409)
    a = ItemAlias(item_id=item_id, alias=alias, source=body.source)
    db.add(a)
    write_audit(db, action="create", entity="item_alias", entity_id=item_id, user=user,
                detail={"alias": alias, "source": body.source}, request=request)
    db.commit()
    return ok({"id": a.id, "alias": alias, "source": a.source})


# ---------- 照片 ----------

def _save_upload(item_id: int, file: UploadFile) -> tuple[str, int]:
    """校验并保存上传文件到 UPLOAD_DIR/items/{item_id}/，返回 (相对路径, 大小)。"""
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_IMAGE_EXT:
        raise BizError("只支持 jpg/png/webp/gif 图片格式", code="ERR_BAD_FILE_TYPE")
    if file.content_type and file.content_type not in ALLOWED_IMAGE_MIME:
        raise BizError("只支持 jpg/png/webp/gif 图片格式", code="ERR_BAD_FILE_TYPE")
    content = file.file.read()
    if len(content) > settings.UPLOAD_MAX_SIZE:
        raise BizError("图片大小不能超过 10MB，请压缩后再上传", code="ERR_FILE_TOO_LARGE", status=413)
    if len(content) == 0:
        raise BizError("上传的文件是空的", code="ERR_EMPTY_FILE")
    rel_dir = Path("items") / str(item_id)
    abs_dir = Path(settings.UPLOAD_DIR) / rel_dir
    abs_dir.mkdir(parents=True, exist_ok=True)
    fname = f"{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}{ext}"
    (abs_dir / fname).write_bytes(content)
    return f"{rel_dir.as_posix()}/{fname}", len(content)


@router.post("/{item_id}/photos")
def upload_photo(item_id: int, request: Request, file: UploadFile = File(...),
                 source: str = "upload",
                 user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    item = _get_item_or_404(db, item_id)
    if source not in ("upload", "camera"):
        source = "upload"
    rel_path, size = _save_upload(item.id, file)
    has_primary = db.scalar(select(func.count(ItemPhoto.id)).where(
        ItemPhoto.item_id == item.id, ItemPhoto.is_primary.is_(True))) or 0
    p = ItemPhoto(
        item_id=item.id, file_path=rel_path, file_size=size,
        is_primary=(has_primary == 0), source=source, uploaded_by=user.id,
    )
    db.add(p)
    write_audit(db, action="upload_photo", entity="item", entity_id=item.id, user=user,
                detail={"file_path": rel_path, "size": size}, request=request)
    db.commit()
    db.refresh(p)
    return ok({"id": p.id, "url": photo_url(p), "is_primary": p.is_primary, "file_size": p.file_size})


@router.delete("/{item_id}/photos/{photo_id}")
def delete_photo(item_id: int, photo_id: int, request: Request,
                 user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _get_item_or_404(db, item_id)
    p = db.get(ItemPhoto, photo_id)
    if p is None or p.item_id != item_id:
        raise BizError("照片不存在", code="ERR_NOT_FOUND", status=404)
    was_primary = p.is_primary
    file_path = p.file_path
    db.delete(p)
    db.flush()
    if was_primary:
        # 主图被删：把剩余最早一张设为主图
        nxt = db.scalar(select(ItemPhoto).where(ItemPhoto.item_id == item_id)
                        .order_by(ItemPhoto.sort_order, ItemPhoto.id).limit(1))
        if nxt:
            nxt.is_primary = True
    # 磁盘文件删除（失败不影响业务，只记日志）
    try:
        abs_path = Path(settings.UPLOAD_DIR) / file_path
        if abs_path.is_file():
            abs_path.unlink()
    except OSError as e:  # pragma: no cover
        logger.warning("删除照片文件失败 %s: %s", file_path, e)
    write_audit(db, action="delete_photo", entity="item", entity_id=item_id, user=user,
                detail={"photo_id": photo_id, "file_path": file_path}, request=request)
    db.commit()
    return ok({"deleted": photo_id})


class PhotoPatch(BaseModel):
    is_primary: bool | None = None
    sort_order: int | None = None


@router.patch("/{item_id}/photos/{photo_id}")
def patch_photo(item_id: int, photo_id: int, body: PhotoPatch, request: Request,
                user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """设主图 / 调排序。设主图时把该物品其余照片 is_primary 置 False（一物一主图）。"""
    _get_item_or_404(db, item_id)
    p = db.get(ItemPhoto, photo_id)
    if p is None or p.item_id != item_id:
        raise BizError("照片不存在", code="ERR_NOT_FOUND", status=404)
    if body.is_primary is True:
        db.execute(
            update(ItemPhoto)
            .where(ItemPhoto.item_id == item_id, ItemPhoto.id != photo_id)
            .values(is_primary=False)
        )
        p.is_primary = True
    if body.sort_order is not None:
        p.sort_order = body.sort_order
    write_audit(db, action="update_photo", entity="item", entity_id=item_id, user=user,
                detail={"photo_id": photo_id, "is_primary": p.is_primary,
                        "sort_order": p.sort_order}, request=request)
    db.commit()
    db.refresh(p)
    return ok({"id": p.id, "url": photo_url(p), "is_primary": p.is_primary,
               "sort_order": p.sort_order, "file_size": p.file_size})


# ---------- 批量导入 ----------

COL_ALIASES = {
    "条码号": "barcode", "条码": "barcode", "条形编码": "barcode", "barcode": "barcode",
    "物品名称": "name", "名称": "name", "name": "name",
    "分类": "category", "类目": "category", "category": "category",
    "规格": "spec", "spec": "spec",
    "建议售价": "suggest_price", "售价": "suggest_price", "price": "suggest_price",
    "印刷方式": "print_mode", "print_mode": "print_mode",
    "单位": "unit", "unit": "unit",
    "是否贴码": "need_label", "备注": "remark",
}


def _normalize_header(h: str) -> str | None:
    h = (h or "").strip().replace("\ufeff", "")
    return COL_ALIASES.get(h, COL_ALIASES.get(h.lower()))


def _parse_rows(header: list[str], records: list[list]) -> list[dict]:
    field_map: dict[int, str] = {}
    for idx, h in enumerate(header):
        f = _normalize_header(h)
        if f:
            field_map[idx] = f
    if "name" not in field_map.values():
        raise BizError("导入文件缺少「物品名称」列", code="ERR_IMPORT_NO_NAME")
    rows: list[dict] = []
    for rec in records:
        row: dict = {}
        empty = True
        for idx, field in field_map.items():
            v = rec[idx] if idx < len(rec) else None
            if v is None:
                continue
            v = str(v).strip()
            if v:
                empty = False
                row[field] = v
        if not empty and row.get("name"):
            rows.append(row)
    return rows


def _read_xlsx(content: bytes) -> tuple[list[str], list[list]]:
    from openpyxl import load_workbook
    wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    wb.close()
    if not rows:
        raise BizError("导入文件是空的", code="ERR_IMPORT_EMPTY")
    header = [str(c) if c is not None else "" for c in rows[0]]
    records = [list(r) for r in rows[1:] if any(c is not None and str(c).strip() for c in r)]
    return header, records


def _read_csv(content: bytes) -> tuple[list[str], list[list]]:
    text_content = None
    for enc in ("utf-8-sig", "gbk", "gb18030"):
        try:
            text_content = content.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text_content is None:
        raise BizError("CSV 文件编码无法识别，请另存为 UTF-8 后重试", code="ERR_IMPORT_ENCODING")
    reader = csv.reader(io.StringIO(text_content))
    all_rows = [r for r in reader if any(str(c).strip() for c in r)]
    if not all_rows:
        raise BizError("导入文件是空的", code="ERR_IMPORT_EMPTY")
    return all_rows[0], all_rows[1:]


def _resolve_category(db: Session, raw: str) -> Category:
    """分类支持中文名或数字位。"""
    raw = raw.strip()
    cat = db.scalar(select(Category).where(Category.name == raw))
    if cat is None and re.match(r"^[0-9]$", raw):
        cat = db.scalar(select(Category).where(Category.digit == raw))
    if cat is None:
        raise BizError(f"无法识别的分类「{raw}」，请使用类目名称（如：教材）或分类位数字（如：1）",
                       code="ERR_IMPORT_CATEGORY")
    return cat


def _resolve_print_mode(raw: str | None) -> str:
    if not raw:
        return "label"
    v = PRINT_MODE_MAP.get(raw.strip())
    if v is None:
        raise BizError(f"无法识别的印刷方式「{raw}」，请使用：贴标 / 扫码卡", code="ERR_IMPORT_PRINT_MODE")
    return v


def _resolve_need_label(raw: str | None) -> bool:
    if not raw:
        return True
    v = raw.strip()
    if v in ("是", "true", "True", "1", "y", "Y"):
        return True
    if v in ("否", "false", "False", "0", "n", "N"):
        return False
    raise BizError(f"无法识别的「是否贴码」值「{raw}」，请使用：是 / 否", code="ERR_IMPORT_NEED_LABEL")


@router.post("/batch")
def batch_import(request: Request, file: UploadFile = File(...),
                 dry_run: bool = False,
                 admin: User = Depends(AdminUser), db: Session = Depends(get_db)):
    """CSV/xlsx 批量导入。dry_run=true 只校验不落库。返回成功/跳过/错误明细。"""
    content = file.file.read()
    fname = (file.filename or "").lower()
    if fname.endswith((".xlsx", ".xlsm")):
        header, records = _read_xlsx(content)
    else:
        header, records = _read_csv(content)
    rows = _parse_rows(header, records)
    if not rows:
        raise BizError("没有解析到有效数据行（至少需要「物品名称」列有值）", code="ERR_IMPORT_EMPTY")

    created, skipped, errors = [], [], []
    for line_no, row in enumerate(rows, start=2):
        # 每行一个 SAVEPOINT：单行失败只回滚该行，不影响批次内其他行
        try:
            with db.begin_nested():
                name = row["name"].strip()
                cat = _resolve_category(db, row.get("category") or "其他")
                barcode = (row.get("barcode") or "").strip() or None
                # 已存在同码 → 跳过（幂等）
                if barcode:
                    exists = db.scalar(select(Item).where(Item.barcode == barcode))
                    if exists is not None:
                        skipped.append({"line": line_no, "barcode": barcode,
                                        "reason": f"条码已存在（物品：{exists.name}）"})
                        continue
                price = None
                if row.get("suggest_price"):
                    try:
                        price = Decimal(row["suggest_price"])
                        if price < 0:
                            raise ValueError
                    except (InvalidOperation, ValueError):
                        raise BizError(f"建议售价「{row['suggest_price']}」不是合法的非负数字",
                                       code="ERR_IMPORT_PRICE")
                item = Item(
                    name=name, category_id=cat.id, barcode=None,
                    spec=row.get("spec", ""), suggest_price=price,
                    unit=row.get("unit", "件"),
                    need_label=_resolve_need_label(row.get("need_label")),
                    print_mode=_resolve_print_mode(row.get("print_mode")),
                    remark=row.get("remark", ""), status="active", created_by=admin.id,
                )
                if barcode:
                    origin = bc.check_barcode_for_item(db, barcode, cat.id)
                    item.barcode = barcode
                    item.barcode_origin = origin
                db.add(item)
                db.flush()
                if item.barcode:
                    db.add(BarcodeHistory(
                        item_id=item.id, old_barcode=None, new_barcode=item.barcode,
                        change_type="import", reason="批量导入", operator_id=admin.id,
                    ))
                db.flush()
                created.append({"line": line_no, "id": item.id, "name": name, "barcode": item.barcode})
        except BizError as e:
            errors.append({"line": line_no, "name": row.get("name", ""), "error": e.detail})
        except IntegrityError:
            errors.append({"line": line_no, "name": row.get("name", ""), "error": "条码重复或数据冲突"})

    if dry_run:
        db.rollback()
    else:
        write_audit(db, action="import", entity="item", user=admin,
                    detail={"file": file.filename, "created": len(created),
                            "skipped": len(skipped), "errors": len(errors)}, request=request)
        db.commit()
    return ok({
        "created": created, "skipped": skipped, "errors": errors,
        "created_count": len(created), "skipped_count": len(skipped),
        "error_count": len(errors), "dry_run": dry_run,
    })


# ---------- 合并执行 / 回滚（DESIGN §5.2，仅 admin） ----------

class MergeBody(BaseModel):
    merged_ids: list[int] = Field(min_length=1)
    reason: str = Field(default="", max_length=300)


@router.post("/{keeper_id}/merge")
def merge_items(
    keeper_id: int, body: MergeBody, request: Request,
    admin: User = Depends(AdminUser), db: Session = Depends(get_db),
):
    """十步合并（契约 §5.2）：多 merged 逐个循环，全部一个事务 commit 一次。"""
    try:
        keeper, log_ids = merge_svc.perform_merge(
            db, keeper_id, body.merged_ids, body.reason, admin.id,
        )
        write_audit(db, action="merge", entity="item", entity_id=keeper.id, user=admin,
                    detail={"keeper_id": keeper.id, "keeper_name": keeper.name,
                            "merged_ids": body.merged_ids,
                            "log_ids": log_ids, "reason": body.reason}, request=request)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return ok({
        "keeper_id": keeper.id,
        "merged_ids": body.merged_ids,
        "log_ids": log_ids,
        "message": f"已将 {len(body.merged_ids)} 个物品合并到「{keeper.name}」",
    })


@router.post("/merges/{log_id}/rollback")
def rollback_merge(
    log_id: int, request: Request,
    admin: User = Depends(AdminUser), db: Session = Depends(get_db),
):
    """按 impact_snapshot 逆向恢复合并。守卫：已回滚 409；keeper 非 active 409。"""
    log = db.get(ItemMergeLog, log_id)
    if log is None:
        raise BizError("合并记录不存在", code="ERR_NOT_FOUND", status=404)
    if log.rolled_back_at is not None:
        raise BizError("该合并记录已回滚，请勿重复操作", code="ERR_ALREADY_ROLLED_BACK", status=409)
    keeper = db.get(Item, log.keeper_id)
    if keeper is None or keeper.status != "active":
        raise BizError(
            f"保留项「{log.keeper.name if log.keeper else log.keeper_id}」当前不是正常状态"
            "（可能已被合并或停用），无法回滚",
            code="ERR_KEEPER_NOT_ACTIVE", status=409,
        )
    try:
        merged = merge_svc.rollback_merge(db, log, admin.id)
        write_audit(db, action="merge_rollback", entity="item", entity_id=merged.id, user=admin,
                    detail={"log_id": log.id, "keeper_id": log.keeper_id,
                            "merged_id": log.merged_id}, request=request)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return ok({
        "log_id": log.id,
        "merged_id": merged.id,
        "message": f"已回滚合并，「{merged.name}」恢复为独立物品",
    })
