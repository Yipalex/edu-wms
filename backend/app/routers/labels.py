"""标签打印 API（DESIGN §6：GET /labels/pdf、/labels/barcode/{code}.png）。

由 app/main.py 注册：`app.include_router(labels.router)`（前缀 /api 在 main 统一加）。
渲染逻辑全部来自 app.label 纯函数引擎（与 wms/tools/label_cli.py 同源，
保证 Web 打印与 CLI 打印结果完全一致）。

print_mode 自动分流策略（简单可预期方案）：
- 请求显式给了 mode → 全部按该 mode 排版；
- 未显式给 mode → 默认全部按 label 排版（保持单段 PDF），
  并在响应头 X-Scan-Card-Count 告知其中有多少种物品的 print_mode='scan_card'
  （前端可提示用户改用 mode=scan_card 单独打印合集卡）。
"""
from __future__ import annotations

import datetime
import os
import re
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user, require_role
from app.label import LabelItem, barcode_png_bytes, labels_to_pdf
from app.label import fonts as label_fonts
from app.label.pdf import sample_pdf
from app.models import Item, ItemAlias, User
from app.schemas.common import BizError, ok

router = APIRouter(prefix="/labels", tags=["标签打印"])

AdminUser = require_role("admin")

_CODE_RE = re.compile(r"^[0-9]{8,14}$")

# 把 config 的字体路径注入字体探测（环境变量已显式设置时不覆盖；文件不存在会被安全忽略）
try:
    from app.config import settings as _settings
    if not os.environ.get(label_fonts.ENV_REGULAR):
        label_fonts.configure(regular=_settings.LABEL_FONT_REGULAR, bold=_settings.LABEL_FONT_BOLD)
except Exception:  # noqa: BLE001 - config 未就绪时纯探测也能工作
    pass


def _query_items(db: Session, item_ids, category_id, status, need_label, print_mode, q):
    """按与 GET /items 一致的筛选查物品，返回 [Item]（无条码的跳过）。"""
    conds = []
    if item_ids:
        conds.append(Item.id.in_(item_ids))
    if category_id is not None:
        conds.append(Item.category_id == category_id)
    if status:
        conds.append(Item.status == status)
    if need_label is not None:
        conds.append(Item.need_label == need_label)
    if print_mode:
        conds.append(Item.print_mode == print_mode)
    if q:
        like = f"%{q.strip()}%"
        alias_item_ids = select(ItemAlias.item_id).where(ItemAlias.alias.like(like))
        conds.append(or_(
            Item.name.like(like),
            Item.barcode.like(like),
            Item.id.in_(alias_item_ids),
        ))
    conds.append(Item.barcode.is_not(None))
    stmt = select(Item)
    for c in conds:
        stmt = stmt.where(c)
    stmt = stmt.order_by(Item.id)
    return db.scalars(stmt).all()


def _to_label_items(items: List[Item]) -> List[LabelItem]:
    out = []
    for it in items:
        cat = it.category
        out.append(LabelItem(
            code=it.barcode or "",
            name=it.name,
            category_name=cat.name if cat else "",
            spec=(it.spec or "").strip(),
        ))
    return out


@router.get("/pdf")
def labels_pdf(
    item_ids: Optional[str] = Query(None, description="逗号分隔的物品 id，优先于筛选参数"),
    category_id: Optional[int] = Query(None),
    status: Optional[str] = Query(None, description="active/merged/retired"),
    need_label: Optional[bool] = Query(None),
    print_mode: Optional[str] = Query(None, description="label/scan_card"),
    q: Optional[str] = Query(None, description="名称/条码/别名模糊"),
    mode: Optional[str] = Query(None, pattern="^(label|scan_card)$"),
    layout: str = Query("3col", pattern="^(3col|4col)$"),
    copies: int = Query(1, ge=1, le=200),
    paper: str = Query("a4"),
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """生成标签 PDF（AO 权限）。"""
    if paper != "a4":
        raise BizError("暂不支持该纸张规格，当前仅支持 a4（热敏标签机版式待扩展）")
    ids: List[int] = []
    if item_ids:
        for part in item_ids.split(","):
            part = part.strip()
            if not part:
                continue
            if not part.isdigit():
                raise BizError(f"item_ids 含非法值: {part}")
            ids.append(int(part))
    items = _query_items(db, ids or None, category_id, status, need_label, print_mode, q)
    if not items:
        raise BizError("没有匹配的物品可打印")

    label_items = _to_label_items(items)
    eff_mode = mode or "label"
    scan_card_count = sum(1 for it in items if it.print_mode == "scan_card")
    pdf = labels_to_pdf(label_items, layout=layout, copies=copies, mode=eff_mode, paper=paper)
    headers = {
        "Content-Disposition": f'attachment; filename="labels-{datetime.date.today():%Y%m%d}.pdf"',
        "X-Scan-Card-Count": str(scan_card_count if not mode else 0),
        "X-Label-Count": str(len(label_items) * (copies if eff_mode == "label" else 1)),
    }
    return Response(content=pdf, media_type="application/pdf", headers=headers)


@router.get("/barcode/{code}.png")
def barcode_png(
    code: str,
    scale: int = Query(2, ge=1, le=8),
    _: User = Depends(get_current_user),
):
    """单条码 PNG（AO 权限），与 PDF 内条码同源同参数。"""
    if not _CODE_RE.match(code):
        raise BizError("条码格式非法（应为 8~14 位纯数字）")
    return Response(content=barcode_png_bytes(code, scale=scale), media_type="image/png")


@router.get("/font-check")
def font_check(_: User = Depends(AdminUser)):
    """字体探测结果（A 权限），排查容器内缺字体/豆腐块问题。"""
    info = label_fonts.font_info()
    info["self_check"] = label_fonts.self_check()
    return ok(info)


@router.get("/sample.pdf")
def sample(
    layout: str = Query("3col", pattern="^(3col|4col)$"),
    _: User = Depends(get_current_user),
):
    """样张 PDF（固定代表性物品，无需 DB 数据），部署后人工肉眼验收字体与版式。"""
    pdf = sample_pdf(layout=layout)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="labels-sample-{layout}.pdf"'},
    )
