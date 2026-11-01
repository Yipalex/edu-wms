"""标签渲染引擎入口。

对外导出纯函数 API（与 wms/tools/label_cli.py 及 app/routers/labels.py 同源）：
- LabelItem            标签内容数据类（render.py）
- render_barcode_pil   单条码 PIL 图（render.py）
- render_label         单枚标签渲染（render.py）
- labels_to_pdf        批量标签 → PDF 字节流（pdf.py）
- compose_page_images  批量标签 → 页图列表（pdf.py）
- barcode_png_bytes    单条码 PNG 字节流（pdf.py）
- sample_items/sample_pdf 部署验收样张（pdf.py）
- fonts                字体探测子模块（容器 Noto CJK / 本机 Hiragino）

版式参数（DPI/A4/间隙/条码上限）见 layout.py，数值照抄 DESIGN §8 不得改动。
"""
from .fonts import configure, font_bold, font_info, font_regular, resolve_fonts, self_check
from .layout import A4_H, A4_W, BC_MAX_H, BC_MAX_W, DPI, PAGE_MARGIN, get_layout, label_size, mm
from .pdf import (
    barcode_png_bytes,
    compose_page_images,
    labels_to_pdf,
    sample_items,
    sample_pdf,
    sanitize_filename,
)
from .render import (
    LabelItem,
    render_barcode_pil,
    render_label,
    render_label_3col,
    render_label_4col,
)

__all__ = [
    "LabelItem",
    "render_barcode_pil",
    "render_label",
    "render_label_3col",
    "render_label_4col",
    "labels_to_pdf",
    "compose_page_images",
    "barcode_png_bytes",
    "sample_items",
    "sample_pdf",
    "sanitize_filename",
    "configure",
    "font_bold",
    "font_info",
    "font_regular",
    "resolve_fonts",
    "self_check",
    "A4_H",
    "A4_W",
    "BC_MAX_H",
    "BC_MAX_W",
    "DPI",
    "PAGE_MARGIN",
    "get_layout",
    "label_size",
    "mm",
]
