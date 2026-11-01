"""审计日志 helper：写 audit_log 表。

在增删改与关键动作（分配码/重分配/改类目/改编码规则等）处调用。
不单独 commit——与调用方的业务事务同一 Session 提交。
"""
from typing import Any

from fastapi import Request
from sqlalchemy.orm import Session

from app.models import AuditLog, User


def client_ip(request: Request | None) -> str | None:
    if request is None:
        return None
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()[:50]
    return request.client.host[:50] if request.client else None


def write_audit(
    db: Session,
    *,
    action: str,
    entity: str,
    entity_id: int | None = None,
    user: User | None = None,
    detail: dict[str, Any] | None = None,
    request: Request | None = None,
) -> AuditLog:
    log = AuditLog(
        user_id=user.id if user else None,
        action=action,
        entity=entity,
        entity_id=entity_id,
        detail=detail,
        ip=client_ip(request),
    )
    db.add(log)
    return log
