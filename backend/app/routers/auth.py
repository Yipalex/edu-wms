"""认证路由（DESIGN §6）：login / refresh / logout / me / change-password。

logout 取舍：把 refresh token 的 jti 写入黑名单表（refresh_token_blacklist），
access token（2h 短时效）不即时失效、依赖前端丢弃——内部系统规模下够用，
无需引入 Redis。
"""
import base64
import logging
import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import Response
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
        # 头像（base64 PNG 存库，2026-11-04）：has_avatar 供前端判断是否显示首字兜底
        "has_avatar": bool(u.avatar_data),
        "avatar_url": (f"/api/auth/avatars/{u.id}?v={int(u.avatar_updated_at.timestamp() * 1000)}"
                       if u.avatar_data and u.avatar_updated_at else
                       (f"/api/auth/avatars/{u.id}" if u.avatar_data else None)),
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


# ---------- 个人资料：头像 / 姓名 / 手机号（2026-11-04） ----------
# 头像以 base64 PNG 存 users.avatar_data；与工作台统一账号体系同步（由 zexi-api 广播）。
# 手机号是本系统的登录标识（users.username），修改需校验原密码。

class ProfileUpdateBody(BaseModel):
    display_name: str | None = Field(default=None, max_length=50)
    username: str | None = Field(default=None, max_length=50)
    old_password: str | None = Field(default=None, max_length=200)


@router.post("/avatar")
def upload_avatar(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """上传头像（前端已裁剪为正方形 PNG）。"""
    data = file.file.read()
    if not data:
        raise BizError("图片内容为空", code="ERR_EMPTY_FILE")
    if len(data) > 3 * 1024 * 1024:
        raise BizError("图片太大，请选择 3MB 以内的图片", code="ERR_FILE_TOO_LARGE")
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise BizError("图片格式无法识别，请重新选择图片", code="ERR_BAD_IMAGE")
    user.avatar_data = data.decode("base64")
    user.avatar_updated_at = datetime.now(timezone.utc)
    db.commit()
    logger.info("用户 %s 更新了头像", user.username)
    return ok({"avatar_url": f"/api/auth/avatars/{user.id}?v={int(user.avatar_updated_at.timestamp() * 1000)}"})


@router.get("/avatars/{user_id}")
def get_avatar(user_id: int, db: Session = Depends(get_db)):
    """读取头像（公开，仅返回图片）。"""
    u = db.get(User, user_id)
    if u is None or not u.avatar_data:
        raise BizError("头像不存在", code="ERR_NOT_FOUND", status=404)
    return Response(
        content=base64.b64decode(u.avatar_data),
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=300"},
    )


@router.post("/profile")
def update_profile(
    body: ProfileUpdateBody,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """修改姓名 / 手机号（改手机号需校验原密码；跨系统联动由工作台统一账号体系处理）。"""
    if body.display_name is not None:
        name = body.display_name.strip()
        if not name:
            raise BizError("姓名不能为空", code="ERR_BAD_NAME")
        if len(name) > 30:
            raise BizError("姓名最多 30 个字", code="ERR_NAME_TOO_LONG")
        user.display_name = name
    if body.username is not None and body.username.strip() != user.username:
        new_username = body.username.strip()
        if not re.fullmatch(r"1\d{10}", new_username):
            raise BizError("请输入正确的 11 位手机号", code="ERR_BAD_PHONE")
        if not body.old_password or not verify_password(body.old_password, user.password_hash):
            raise BizError("原密码错误", code="ERR_BAD_OLD_PASSWORD")
        dup = db.scalar(select(User.id).where(User.username == new_username, User.id != user.id))
        if dup is not None:
            raise BizError("该手机号已被其他账号使用", code="ERR_PHONE_DUP", status=409)
        user.username = new_username
    db.commit()
    logger.info("用户 %s 更新了个人资料", user.id)
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
