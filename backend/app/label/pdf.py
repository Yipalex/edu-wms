"""PDF / PNG 输出组装（纯函数）。"""
from __future__ import annotations

import io
from typing import List, Sequence, Union

from PIL import Image

from .layout import DPI, compose_pages, expand_copies, label_size
from .render import LabelItem, render_barcode_pil, render_label


def sanitize_filename(name: str) -> str:
    """移植 generate_barcodes.sanitize()：替换非法字符并截断 60 字符。"""
    for ch in '/\\:*?"<>|':
        name = name.replace(ch, "_")
    return name[:60]


def labels_to_pdf(
    labels: Sequence[Union[LabelItem, dict]],
    layout: str = "3col",
    copies: int = 1,
    mode: str = "label",
    paper: str = "a4",
) -> bytes:
    """渲染并排版标签，返回 PDF 字节流（Pillow save_all，300dpi）。

    - mode='label'     ：每物 repeats `copies` 枚（贴标，可多份）
    - mode='scan_card' ：每物**固定 1 枚**（copies 忽略；小物品合集扫码卡）
    """
    if mode not in ("label", "scan_card"):
        raise ValueError(f"未知打印模式: {mode}（支持 label/scan_card）")
    items = [it if isinstance(it, LabelItem) else LabelItem.from_dict(it) for it in labels]
    if not items:
        raise ValueError("没有可打印的物品")
    expanded = expand_copies(items, copies, mode)
    lw, lh = label_size(layout, paper)
    rendered = [render_label(it, lw, lh, layout) for it in expanded]
    pages = compose_pages(rendered, layout, paper)
    buf = io.BytesIO()
    pages[0].save(buf, format="PDF", save_all=True, append_images=pages[1:], resolution=DPI)
    return buf.getvalue()


def compose_page_images(
    labels: Sequence[Union[LabelItem, dict]],
    layout: str = "3col",
    copies: int = 1,
    mode: str = "label",
    paper: str = "a4",
) -> List[Image.Image]:
    """同 labels_to_pdf，但返回页图列表（供对比测试/预览用）。"""
    items = [it if isinstance(it, LabelItem) else LabelItem.from_dict(it) for it in labels]
    if not items:
        raise ValueError("没有可打印的物品")
    expanded = expand_copies(items, copies, mode)
    lw, lh = label_size(layout, paper)
    rendered = [render_label(it, lw, lh, layout) for it in expanded]
    return compose_pages(rendered, layout, paper)


def barcode_png_bytes(code: str, scale: int = 1) -> bytes:
    """单条码 PNG 字节流（供前端预览/下载），与 PDF 内条码同源同参数。"""
    img = render_barcode_pil(code)
    if scale and scale > 1:
        img = img.resize((img.width * scale, img.height * scale), Image.NEAREST)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def sample_items() -> List[LabelItem]:
    """样张代表性物品（部署后人工肉眼验收字体与版式，无需 DB 数据）。
    取自真实数据 items_all_v2.csv 的代表行 + 一个外部码示例。"""
    return [
        LabelItem(code="21040008", name="毛笔", category_name="耗材", spec="耗材"),
        LabelItem(code="21030015",
                  name="正品红星墨汁500ml书法专用毛笔墨水国画练习初学者学生书画墨汁",
                  category_name="辅材", spec="100g书画墨汁"),
        LabelItem(code="21010003",
                  name="偏旁部首下",
                  category_name="教材",
                  spec="整套"),
        LabelItem(code="21010004",
                  name="偏旁部首下教材",
                  category_name="教材",
                  spec="偏旁部首下套装·单卖"),
        LabelItem(code="6950898000191", name="北太墨汁", category_name="耗材", spec="外部码"),
    ]


def sample_pdf(layout: str = "3col") -> bytes:
    """样张 PDF 字节流。"""
    return labels_to_pdf(sample_items(), layout=layout, copies=1, mode="label")
