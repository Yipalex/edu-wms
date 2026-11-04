"""FastAPI 依赖：当前用户解析与角色鉴权。

- 401 ERR_UNAUTHORIZED：未登录 / token 无效 / token 过期 / 账号被停用
- 403 ERR_FORBIDDEN：权限不足（角色不匹配）
错误信息全部中文。
"""
from typing import Callable, Sequence

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import RefreshTokenBlacklist, User
from app.schemas.common import BizError
from app.security import decode_token

# auto_error=False：由我们自己返回中文 401，而不是 FastAPI 默认的英文 403
bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None or not credentials.credentials:
        raise BizError("未登录或登录已过期，请重新登录", code="ERR_UNAUTHORIZED", status=401)
    payload = decode_token(credentials.credentials)
    if payload is None:
        raise BizError("登录凭证无效或已过期，请重新登录", code="ERR_UNAUTHORIZED", status=401)
    if payload.get("type") != "access":
        raise BizError("凭证类型错误，请使用 access token", code="ERR_UNAUTHORIZED", status=401)
    user = db.get(User, int(payload["sub"]))
    if user is None:
        raise BizError("用户不存在", code="ERR_UNAUTHORIZED", status=401)
    if not user.is_active:
        raise BizError("账号已停用，请联系管理员", code="ERR_FORBIDDEN", status=403)
    return user


def require_role(*roles: str) -> Callable[..., User]:
    """生成一个依赖：当前用户必须拥有指定角色之一。

    superadmin 是全部角色的超集：任何 require_role(...) 都放行 superadmin
    （与前端 RoleRoute 的约定一致，否则超管连新建物品等基础操作都会被拒）。
    """

    def _dep(user: User = Depends(get_current_user)) -> User:
        if user.role != "superadmin" and user.role not in roles:
            raise BizError("权限不足：本操作仅限管理员", code="ERR_FORBIDDEN", status=403)
        return user

    return _dep


def require_any_role(roles: Sequence[str]) -> Callable[..., User]:
    return require_role(*roles)


def require_super_admin() -> Callable[..., User]:
    """超级管理员：仅 superadmin 角色。

    与 admin 的区别：admin 能管物品档案/用户/单据；superadmin 额外拥有
    「彻底删除物品档案」「查看与恢复已删除档案」等不可逆或高风险操作。
    """

    def _dep(user: User = Depends(get_current_user)) -> User:
        if user.role != "superadmin":
            raise BizError("权限不足：本操作仅限超级管理员", code="ERR_FORBIDDEN", status=403)
        return user

    return _dep


def require_refresh_not_blacklisted(jti: str, db: Session) -> None:
    """校验 refresh token 的 jti 不在黑名单中。"""
    if db.scalar(select(RefreshTokenBlacklist).where(RefreshTokenBlacklist.jti == jti)) is not None:
        raise BizError("该登录凭证已失效，请重新登录", code="ERR_UNAUTHORIZED", status=401)
