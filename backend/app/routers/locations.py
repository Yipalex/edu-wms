"""库位路由（DESIGN §6）：GET（AO）/ POST（A）/ PATCH（A）。"""
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user, require_role
from app.models import Location, User
from app.schemas.common import BizError, ok
from app.services.audit import write_audit

router = APIRouter(prefix="/locations", tags=["库位"])

AdminUser = require_role("admin")


class LocationCreate(BaseModel):
    code: str = Field(min_length=1, max_length=20, pattern=r"^[A-Za-z0-9_\-]+$")
    name: str = Field(min_length=1, max_length=50)
    type: str = Field(default="campus", pattern=r"^(warehouse|campus)$")
    is_front_warehouse: bool = False
    sort_order: int = 0


class LocationPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=50)
    type: str | None = Field(default=None, pattern=r"^(warehouse|campus)$")
    is_front_warehouse: bool | None = None
    sort_order: int | None = None
    is_active: bool | None = None


def loc_row(l: Location) -> dict:
    return {
        "id": l.id, "code": l.code, "name": l.name, "type": l.type,
        "is_front_warehouse": l.is_front_warehouse, "sort_order": l.sort_order,
        "is_active": l.is_active,
    }


@router.get("")
def list_locations(_: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(Location).order_by(Location.sort_order, Location.id)).all()
    return ok([loc_row(l) for l in rows])


@router.post("")
def create_location(body: LocationCreate, request: Request, admin: User = Depends(AdminUser), db: Session = Depends(get_db)):
    if db.scalar(select(Location).where(Location.code == body.code)) is not None:
        raise BizError(f"库位编码 {body.code} 已存在", code="ERR_CODE_DUP", status=409)
    if db.scalar(select(Location).where(Location.name == body.name)) is not None:
        raise BizError(f"库位名称 {body.name} 已存在", code="ERR_NAME_DUP", status=409)
    l = Location(**body.model_dump())
    db.add(l)
    db.flush()
    write_audit(db, action="create", entity="location", entity_id=l.id, user=admin,
                detail={"code": l.code, "name": l.name}, request=request)
    db.commit()
    return ok(loc_row(l))


@router.patch("/{location_id}")
def patch_location(location_id: int, body: LocationPatch, request: Request, admin: User = Depends(AdminUser), db: Session = Depends(get_db)):
    l = db.get(Location, location_id)
    if l is None:
        raise BizError("库位不存在", code="ERR_NOT_FOUND", status=404)
    data = body.model_dump(exclude_unset=True)
    if "name" in data and data["name"] != l.name:
        dup = db.scalar(select(Location).where(Location.name == data["name"], Location.id != l.id))
        if dup is not None:
            raise BizError(f"库位名称 {data['name']} 已存在", code="ERR_NAME_DUP", status=409)
    write_audit(db, action="update", entity="location", entity_id=l.id, user=admin,
                detail=data, request=request)
    for k, v in data.items():
        setattr(l, k, v)
    db.commit()
    db.refresh(l)
    return ok(loc_row(l))
