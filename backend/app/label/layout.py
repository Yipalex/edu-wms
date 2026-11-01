"""A4 排版（纯函数）。数值全部照抄 DESIGN.md §8 与现有脚本，不得改动。

来源对照：
- DPI/A4_W/A4_H/PAGE_MARGIN/LABEL_GAP(4col=24px) ← generate_barcodes.py
- COLS/ROWS=3×6、GAP=mm(5)、BC_MAX_W/H=507×202 ← make_all_barcodes_pdf.py（3col 用户偏好版）
"""
from __future__ import annotations

from typing import Iterable, List, Sequence, Tuple

from PIL import Image

# ---------- A4 排版配置（300dpi）——照抄，勿改 ----------
DPI = 300
A4_W, A4_H = 2480, 3508          # A4 @300dpi，单位 px
PAGE_MARGIN = 118                # 页边距 ~10mm

# 条码尺寸上限 = 原「每物一枚」4列版式的实际尺寸（保持可扫等级不变），只缩不放
BC_MAX_W = 507
BC_MAX_H = 202

def mm(mm_val: float) -> int:
    """毫米 → 像素（照抄 generate_barcodes.mm）。"""
    return int(mm_val / 25.4 * DPI)


GAP_3COL = mm(5)   # 3col 间隙 ~5mm = 59px（照抄 make_all_barcodes_pdf.GAP）
GAP_4COL = 24      # 4col 间隙 ~2mm（照抄 generate_barcodes.LABEL_GAP）

_LAYOUTS = {
    # layout: (cols, rows, gap_px)
    "3col": (3, 6, GAP_3COL),   # 每页 18 枚（用户当前偏好）
    "4col": (4, 8, GAP_4COL),   # 每页 32 枚（密集版）
}


def get_layout(layout: str) -> Tuple[int, int, int]:
    """返回 (cols, rows, gap_px)；未知版式抛 ValueError。"""
    if layout not in _LAYOUTS:
        raise ValueError(f"未知版式: {layout}（支持 {'/'.join(_LAYOUTS)}）")
    return _LAYOUTS[layout]


def label_size(layout: str, paper: str = "a4") -> Tuple[int, int]:
    """单枚标签像素尺寸 (lw, lh)。"""
    _check_paper(paper)
    cols, rows, gap = get_layout(layout)
    lw = (A4_W - 2 * PAGE_MARGIN - (cols - 1) * gap) // cols
    lh = (A4_H - 2 * PAGE_MARGIN - (rows - 1) * gap) // rows
    return lw, lh


def per_page(layout: str) -> int:
    cols, rows, _ = get_layout(layout)
    return cols * rows


def _check_paper(paper: str) -> Tuple[int, int]:
    if paper != "a4":
        # TODO(热敏标签机): 将来支持如 40x30mm / 50x30mm 连续纸，
        # 需要引入卷筒纸无边距排版与不同 DPI；本次交付范围仅 A4。
        raise NotImplementedError(f"暂不支持纸张 {paper!r}，当前仅支持 'a4'")
    return A4_W, A4_H


def compose_pages(labels: Sequence[Image.Image], layout: str, paper: str = "a4") -> List[Image.Image]:
    """把已渲染的标签图按版式排进 A4 页（照抄 make_all_barcodes_pdf.main 的排版循环）。"""
    page_w, page_h = _check_paper(paper)
    cols, rows, gap = get_layout(layout)
    lw, lh = label_size(layout, paper)
    n = cols * rows
    pages: List[Image.Image] = []
    for i in range(0, len(labels), n):
        page = Image.new("RGB", (page_w, page_h), "white")
        for j, lbl in enumerate(labels[i:i + n]):
            r, c = divmod(j, cols)
            page.paste(lbl, (PAGE_MARGIN + c * (lw + gap),
                             PAGE_MARGIN + r * (lh + gap)))
        pages.append(page)
    return pages


def expand_copies(items: Iterable, copies: int, mode: str) -> List:
    """按打印模式展开份数：label=每物 copies 枚；scan_card=每物固定 1 枚（忽略 copies）。"""
    out = []
    for it in items:
        out.extend([it] * (1 if mode == "scan_card" else max(1, copies)))
    return out
