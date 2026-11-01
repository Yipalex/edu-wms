"""认证路由（DESIGN §6）：login / refresh / logout / me / change-password。

logout 取舍：把 refresh token 的 jti 写入黑名单表（refresh_token_blacklist），
access token（2h 短时效）不即时失效、依赖前端丢弃——内部系统规模下够用，
无需引入 Redis。
"""
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.deps import get_current_user, require_refresh_not_blacklisted
from app.models import RefreshTokenBlacklist, User
from app.schemas.common import BizError, ok
from app.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["认证"])


class LoginBody(BaseModel):
    username: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=1, max_length=200)


class ChangePasswordBody(BaseModel):
    old_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=8, max_length=200, description="新密码至少 8 位")


class RefreshBody(BaseModel):
    refresh_token: str


def user_dict(u: User) -> dict:
    return {
        "id": u.id,
        "username": u.username,
        "display_name": u.display_name,
        "role": u.role,
        "home_location_id": u.home_location_id,
        "home_location_name": u.home_location.name if u.home_location else None,
        "is_active": u.is_active,
        "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
    }


def _issue_tokens(db: Session, user: User) -> dict:
    access = create_access_token(user.id, user.role)
    refresh, _jti, exp = create_refresh_token(user.id, user.role)
    return {
        "access_token": access,
        "refresh_token": refresh,
        "token_type": "bearer",
        "expires_in": settings.JWT_EXPIRE_MINUTES * 60,
        "refresh_expires_at": exp,
    }


@router.post("/login")
def login(body: LoginBody, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.username == body.username))
    # 用户不存在与密码错误返回同一提示，避免枚举用户名
    if user is None or not verify_password(body.password, user.password_hash):
        raise BizError("用户名或密码错误", code="ERR_BAD_CREDENTIALS", status=401)
    if not user.is_active:
        raise BizError("账号已停用，请联系管理员", code="ERR_FORBIDDEN", status=403)
    user.last_login_at = datetime.now(timezone.utc)
    tokens = _issue_tokens(db, user)
    db.commit()
    logger.info("用户 %s 登录成功", user.username)
    return ok({**tokens, "user": user_dict(user)})


@router.post("/refresh")
def refresh(body: RefreshBody, db: Session = Depends(get_db)):
    payload = decode_token(body.refresh_token)
    if payload is None or payload.get("type") != "refresh":
        raise BizError("刷新凭证无效或已过期，请重新登录", code="ERR_UNAUTHORIZED", status=401)
    require_refresh_not_blacklisted(payload["jti"], db)
    user = db.get(User, int(payload["sub"]))
    if user is None or not user.is_active:
        raise BizError("账号不存在或已停用", code="ERR_UNAUTHORIZED", status=401)
    # 旧 refresh 旋转失效：进黑名单，发新的一对
    jti = payload["jti"]
    db.add(RefreshTokenBlacklist(
        jti=jti, user_id=user.id,
        expires_at=datetime.fromtimestamp(payload["exp"], tz=timezone.utc),
    ))
    tokens = _issue_tokens(db, user)
    db.commit()
    return ok({**tokens, "user": user_dict(user)})


@router.post("/logout")
def logout(body: RefreshBody | None = None, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """登出：把 refresh token 加入黑名单（若前端提供了它）。access 靠短时效+前端丢弃。"""
    if body and body.refresh_token:
        payload = decode_token(body.refresh_token)
        if payload is not None and payload.get("type") == "refresh":
            exists = db.scalar(select(RefreshTokenBlacklist).where(RefreshTokenBlacklist.jti == payload["jti"]))
            if exists is None:
                db.add(RefreshTokenBlacklist(
                    jti=payload["jti"], user_id=user.id,
                    expires_at=datetime.fromtimestamp(payload["exp"], tz=timezone.utc),
                ))
    db.commit()
    # 顺手清理已过期的黑名单行，避免表膨胀
    db.execute(delete(RefreshTokenBlacklist).where(RefreshTokenBlacklist.expires_at < datetime.now(timezone.utc)))
    db.commit()
    return ok({"logged_out": True})


@router.get("/me")
def me(user: User = Depends(get_current_user)):
    return ok(user_dict(user))


@router.post("/change-password")
def change_password(body: ChangePasswordBody, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not verify_password(body.old_password, user.password_hash):
        raise BizError("原密码错误", code="ERR_BAD_OLD_PASSWORD")
    if body.old_password == body.new_password:
        raise BizError("新密码不能与原密码相同", code="ERR_SAME_PASSWORD")
    user.password_hash = hash_password(body.new_password)
    db.commit()
    logger.info("用户 %s 修改了密码", user.username)
    return ok({"changed": True})
