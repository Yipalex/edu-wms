"""密码哈希（bcrypt）与 JWT 签发/校验。

- access token：2h，payload {sub, role, type:'access', jti, exp}
- refresh token：7d，payload {sub, role, type:'refresh', jti, exp}
- jti 用于 logout 时把 refresh 加入黑名单
"""
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def _create_token(user_id: int, role: str, token_type: str, expires_delta: timedelta) -> tuple[str, str]:
    """返回 (token, jti)。"""
    jti = uuid.uuid4().hex
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "role": role,
        "type": token_type,
        "jti": jti,
        "iat": now,
        "exp": now + expires_delta,
    }
    token = jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
    return token, jti


def create_access_token(user_id: int, role: str) -> str:
    token, _ = _create_token(
        user_id, role, "access",
        timedelta(minutes=settings.JWT_EXPIRE_MINUTES),
    )
    return token


def create_refresh_token(user_id: int, role: str) -> tuple[str, str, datetime]:
    """返回 (token, jti, 过期时间)。"""
    expires = timedelta(days=settings.JWT_REFRESH_EXPIRE_DAYS)
    token, jti = _create_token(user_id, role, "refresh", expires)
    return token, jti, datetime.now(timezone.utc) + expires


def decode_token(token: str) -> dict[str, Any] | None:
    """解码并校验；失败返回 None。"""
    try:
        return jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    except JWTError:
        return None
