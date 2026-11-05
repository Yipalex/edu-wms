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


# ---------- 教师角色（2026-11-05） ----------
# 教师：扫码出入库/退库 + 看本校区库存数量与建议售价；看不到采购价/内部销售价，
# 不能改物品档案、不能做调拨、不能看全校数据。所属校区 = users.home_location_id。

def deny_teacher(user: User, what: str = "此操作") -> None:
    """教师角色的写操作白名单（出库/入库/退库）之外的统一拦截。"""
    if user.role == "teacher":
        raise BizError(
            f"教师角色只能进行出库、入库、退库操作，{what}请联系管理员",
            code="ERR_FORBIDDEN", status=403,
        )


def can_see_cost_prices(user: User) -> bool:
    """采购价/内部销售价仅管理员与仓库操作员可见；教师不可见。"""
    return user.role in ("admin", "superadmin", "operator")


def no_teacher(what: str = "此操作") -> Callable[..., User]:
    """路由级依赖：整个模块对教师不可用（如盘点/报表/仪表盘）。"""

    def _dep(user: User = Depends(get_current_user)) -> User:
        deny_teacher(user, what)
        return user

    return _dep


def teacher_home_location(user: User) -> int:
    """教师必须绑定所属校区，返回校区 location_id。"""
    if user.home_location_id is None:
        raise BizError(
            "该教师账号未绑定所属校区，请让超级管理员在泽曦工作台的「系统权限」里为其选择校区",
            code="ERR_NO_CAMPUS", status=403,
        )
    return user.home_location_id


def require_refresh_not_blacklisted(jti: str, db: Session) -> None:
    """校验 refresh token 的 jti 不在黑名单中。"""
    if db.scalar(select(RefreshTokenBlacklist).where(RefreshTokenBlacklist.jti == jti)) is not None:
        raise BizError("该登录凭证已失效，请重新登录", code="ERR_UNAUTHORIZED", status=401)
