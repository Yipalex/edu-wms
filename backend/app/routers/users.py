"""用户管理路由（DESIGN §6，仅 admin）。DELETE=停用（is_active=false），不物理删。"""
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import require_role
from app.models import Location, User
from app.schemas.common import BizError, ok, ok_page
from app.security import hash_password
from app.services.audit import write_audit

router = APIRouter(prefix="/users", tags=["用户管理"])

AdminUser = require_role("admin")


class UserCreate(BaseModel):
    username: str = Field(min_length=2, max_length=50, pattern=r"^[a-zA-Z0-9_\-]+$")
    password: str = Field(min_length=8, max_length=200)
    display_name: str = Field(min_length=1, max_length=50)
    role: str = Field(pattern=r"^(admin|superadmin|operator)$")
    home_location_id: int | None = None


class UserPatch(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=50)
    role: str | None = Field(default=None, pattern=r"^(admin|superadmin|operator)$")
    home_location_id: int | None = None
    password: str | None = Field(default=None, min_length=8, max_length=200)
    is_active: bool | None = None


def user_row(u: User) -> dict:
    return {
        "id": u.id,
        "username": u.username,
        "display_name": u.display_name,
        "role": u.role,
        "home_location_id": u.home_location_id,
        "home_location_name": u.home_location.name if u.home_location else None,
        "is_active": u.is_active,
        "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
        "created_at": u.created_at.isoformat() if u.created_at else None,
    }


def _check_location(db: Session, loc_id: int | None) -> None:
    if loc_id is not None and db.get(Location, loc_id) is None:
        raise BizError("所选默认库位不存在", code="ERR_NOT_FOUND", status=404)


@router.get("")
def list_users(
    page: int = 1, page_size: int = 20,
    _: User = Depends(AdminUser), db: Session = Depends(get_db),
):
    page = max(1, page)
    page_size = min(100, max(1, page_size))
    q = select(User).order_by(User.id)
    total = len(db.scalars(select(User.id)).all())
    rows = db.scalars(q.offset((page - 1) * page_size).limit(page_size)).all()
    return ok_page([user_row(u) for u in rows], page=page, page_size=page_size, total=total)


@router.post("")
def create_user(body: UserCreate, request: Request, admin: User = Depends(AdminUser), db: Session = Depends(get_db)):
    if db.scalar(select(User).where(User.username == body.username)) is not None:
        raise BizError(f"用户名 {body.username} 已存在", code="ERR_USERNAME_DUP", status=409)
    _check_location(db, body.home_location_id)
    u = User(
        username=body.username,
        password_hash=hash_password(body.password),
        display_name=body.display_name,
        role=body.role,
        home_location_id=body.home_location_id,
    )
    db.add(u)
    db.flush()
    write_audit(db, action="create", entity="user", entity_id=u.id, user=admin,
                detail={"username": u.username, "role": u.role}, request=request)
    db.commit()
    return ok(user_row(u))


def _get_user_or_404(db: Session, user_id: int) -> User:
    u = db.get(User, user_id)
    if u is None:
        raise BizError("用户不存在", code="ERR_NOT_FOUND", status=404)
    return u


@router.patch("/{user_id}")
def patch_user(user_id: int, body: UserPatch, request: Request, admin: User = Depends(AdminUser), db: Session = Depends(get_db)):
    u = _get_user_or_404(db, user_id)
    changed: dict = {}
    if body.display_name is not None:
        changed["display_name"] = (u.display_name, body.display_name)
        u.display_name = body.display_name
    if body.role is not None and body.role != u.role:
        if u.id == admin.id and body.role != "admin":
            raise BizError("不能把自己降级为非管理员", code="ERR_SELF_DEMOTE")
        changed["role"] = (u.role, body.role)
        u.role = body.role
    if body.home_location_id is not None:
        _check_location(db, body.home_location_id)
        changed["home_location_id"] = (u.home_location_id, body.home_location_id)
        u.home_location_id = body.home_location_id
    if body.password is not None:
        u.password_hash = hash_password(body.password)
        changed["password"] = ("***", "已重置")
    if body.is_active is not None:
        changed["is_active"] = (u.is_active, body.is_active)
        u.is_active = body.is_active
    if changed:
        write_audit(db, action="update", entity="user", entity_id=u.id, user=admin,
                    detail={k: {"old": v[0], "new": v[1]} for k, v in changed.items()}, request=request)
    db.commit()
    db.refresh(u)
    return ok(user_row(u))


@router.delete("/{user_id}")
def deactivate_user(user_id: int, request: Request, admin: User = Depends(AdminUser), db: Session = Depends(get_db)):
    u = _get_user_or_404(db, user_id)
    if u.id == admin.id:
        raise BizError("不能停用自己的账号", code="ERR_SELF_DEACTIVATE")
    if u.username == "admin":
        raise BizError("内置 admin 账号不允许停用", code="ERR_PROTECTED_ADMIN")
    u.is_active = False
    write_audit(db, action="delete", entity="user", entity_id=u.id, user=admin,
                detail={"username": u.username, "note": "软删=停用"}, request=request)
    db.commit()
    return ok(user_row(u))
