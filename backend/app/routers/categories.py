"""类目路由（DESIGN §6）：GET（AO）/ POST（A）/ PATCH（A）。

PATCH 改 digit 必须带 ?confirm_digit=true，否则 400 中文警告——
分类位参与条码构成，改动会影响后续新码（DESIGN §3 categories.digit 注释）。
"""
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user, require_role
from app.models import BarcodeSequence, Category, User
from app.schemas.common import BizError, ok
from app.services.audit import write_audit

router = APIRouter(prefix="/categories", tags=["类目"])

AdminUser = require_role("admin")

DIGIT_WARNING = "修改分类位会影响后续新条码构成，请确认后重试"


class CategoryCreate(BaseModel):
    digit: str = Field(min_length=1, max_length=1, pattern=r"^[0-9]$")
    name: str = Field(min_length=1, max_length=30)
    sort_order: int = 0
    next_seq: int = Field(default=1, ge=1, description="流水种子；新建类目默认从 1 起")


class CategoryPatch(BaseModel):
    digit: str | None = Field(default=None, min_length=1, max_length=1, pattern=r"^[0-9]$")
    name: str | None = Field(default=None, min_length=1, max_length=30)
    sort_order: int | None = None
    is_active: bool | None = None


def cat_row(c: Category, next_seq: int | None = None) -> dict:
    d = {
        "id": c.id, "digit": c.digit, "name": c.name,
        "sort_order": c.sort_order, "is_active": c.is_active,
    }
    if next_seq is not None:
        d["next_seq"] = next_seq
    return d


@router.get("")
def list_categories(_: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(Category).order_by(Category.sort_order, Category.id)).all()
    out = []
    for c in rows:
        seq = db.scalar(select(BarcodeSequence).where(BarcodeSequence.category_id == c.id))
        out.append(cat_row(c, seq.next_seq if seq else None))
    return ok(out)


@router.post("")
def create_category(body: CategoryCreate, request: Request, admin: User = Depends(AdminUser), db: Session = Depends(get_db)):
    if db.scalar(select(Category).where(Category.digit == body.digit)) is not None:
        raise BizError(f"分类位 {body.digit} 已被占用", code="ERR_DIGIT_DUP", status=409)
    if db.scalar(select(Category).where(Category.name == body.name)) is not None:
        raise BizError(f"类目名称 {body.name} 已存在", code="ERR_NAME_DUP", status=409)
    c = Category(digit=body.digit, name=body.name, sort_order=body.sort_order)
    db.add(c)
    db.flush()
    db.add(BarcodeSequence(category_id=c.id, next_seq=body.next_seq))
    write_audit(db, action="create", entity="category", entity_id=c.id, user=admin,
                detail={"digit": c.digit, "name": c.name, "next_seq": body.next_seq}, request=request)
    db.commit()
    return ok(cat_row(c, body.next_seq))


@router.patch("/{category_id}")
def patch_category(
    category_id: int, body: CategoryPatch, request: Request,
    confirm_digit: bool = False,
    admin: User = Depends(AdminUser), db: Session = Depends(get_db),
):
    c = db.get(Category, category_id)
    if c is None:
        raise BizError("类目不存在", code="ERR_NOT_FOUND", status=404)
    data = body.model_dump(exclude_unset=True)

    if "digit" in data and data["digit"] != c.digit:
        if not confirm_digit:
            # 契约要求：改分类位需显式确认
            raise BizError(DIGIT_WARNING, code="ERR_DIGIT_CONFIRM_REQUIRED")
        if db.scalar(select(Category).where(Category.digit == data["digit"], Category.id != c.id)) is not None:
            raise BizError(f"分类位 {data['digit']} 已被其他类目占用", code="ERR_DIGIT_DUP", status=409)

    if "name" in data and data["name"] != c.name:
        if db.scalar(select(Category).where(Category.name == data["name"], Category.id != c.id)) is not None:
            raise BizError(f"类目名称 {data['name']} 已存在", code="ERR_NAME_DUP", status=409)

    if data:
        write_audit(db, action="update", entity="category", entity_id=c.id, user=admin,
                    detail=data, request=request)
    for k, v in data.items():
        setattr(c, k, v)
    db.commit()
    db.refresh(c)
    seq = db.scalar(select(BarcodeSequence).where(BarcodeSequence.category_id == c.id))
    return ok(cat_row(c, seq.next_seq if seq else None))
