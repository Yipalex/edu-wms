"""统一响应包装与业务异常（DESIGN §6）。

成功：{"data": ..., "meta": {"page":..,"page_size":..,"total":..}}（meta 可选）
失败：{"detail": "中文错误信息", "code": "ERR_XXX"}

用法（全部路由都用它）：
    from app.schemas.common import ok, ok_page, BizError
    return ok(item_dict)
    return ok_page(rows, page=1, page_size=20, total=100)
    raise BizError("该物品仍有库存/流水，不能删除", code="ERR_ITEM_HAS_STOCK", status=409)
"""
from typing import Any, Generic, TypeVar

from fastapi import HTTPException
from pydantic import BaseModel

T = TypeVar("T")


class Meta(BaseModel):
    page: int
    page_size: int
    total: int


class Page(BaseModel, Generic[T]):
    data: list[T]
    meta: Meta


class Wrapped(BaseModel, Generic[T]):
    data: T
    meta: Meta | None = None


def ok(data: Any = None, meta: dict | None = None) -> dict:
    """成功响应：{"data":..., "meta":{...}?}"""
    body: dict = {"data": data}
    if meta is not None:
        body["meta"] = meta
    return body


def ok_page(rows: list, *, page: int, page_size: int, total: int) -> dict:
    """分页成功响应。"""
    return ok(rows, meta={"page": page, "page_size": page_size, "total": total})


class BizError(HTTPException):
    """业务异常：中文 detail + 稳定错误码 code。main.py 的异常处理器会转成统一失败格式。"""

    def __init__(self, detail: str, *, code: str = "ERR_BIZ", status: int = 400):
        super().__init__(status_code=status, detail=detail)
        self.code = code


def not_found(detail: str = "记录不存在") -> BizError:
    return BizError(detail, code="ERR_NOT_FOUND", status=404)


def conflict(detail: str) -> BizError:
    return BizError(detail, code="ERR_CONFLICT", status=409)
