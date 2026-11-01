"""单枚标签渲染（纯函数，零 app 依赖）。

版式来源（数值照抄，不得改动）：
- render_barcode_pil ← generate_barcodes.render_barcode_png（Code128 writer_options 逐项一致）
- 3col 单枚 ← make_selected_barcodes_pdf.render_label_wrap（用户认可的最终版：
  长名称字号 4.5mm→3.6mm 递减、仍超宽则中点附近拆两行、**不截断**）
- 4col 单枚 ← generate_barcodes.render_label（编码 bold 3.2mm、名称 bold 3.0mm、
  分类 regular 3.0mm #444444、名称超宽截断加 …）

字体统一走 fonts.py 探测（容器 Noto CJK / 本机 Hiragino），不再硬编码 macOS 路径。
"""
from __future__ import annotations

import io
from dataclasses import dataclass

import barcode
from barcode.writer import ImageWriter
from PIL import Image, ImageDraw

from .fonts import font_bold, font_regular
from .layout import BC_MAX_H, BC_MAX_W, DPI, mm


@dataclass
class LabelItem:
    """标签内容 = 条码 + 编码 + 物品名称（+规格）+ 分类，不含校区（前置仓原则）。"""
    code: str
    name: str
    category_name: str = ""
    spec: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "LabelItem":
        return cls(
            code=str(d.get("code") or d.get("barcode") or "").strip(),
            name=str(d.get("name") or "").strip(),
            category_name=str(d.get("category_name") or d.get("category") or "").strip(),
            spec=str(d.get("spec") or "").strip(),
        )


# Code128 生成参数——照抄 generate_barcodes.render_barcode_png，勿改
_WRITER_OPTIONS = {
    "module_height": 12.0,
    "font_size": 0,
    "text_distance": 1.0,
    "quiet_zone": 2.0,
    "write_text": False,
    "dpi": DPI,
}


def render_barcode_pil(code: str) -> Image.Image:
    """生成 Code 128 条码（返回 PIL Image，RGB）。"""
    buf = io.BytesIO()
    barcode.generate("code128", code, writer=ImageWriter(),
                     output=buf, writer_options=_WRITER_OPTIONS)
    buf.seek(0)
    return Image.open(buf).convert("RGB")


def _fit_barcode_3col(code: str) -> Image.Image:
    """3col：按原版尺寸上限缩放，只缩不放（照抄 make_all_barcodes_pdf）。"""
    bc = render_barcode_pil(code)
    ratio = min(BC_MAX_W / bc.width, BC_MAX_H / bc.height, 1.0)
    return bc.resize((int(bc.width * ratio), int(bc.height * ratio)))


def render_label_3col(item: LabelItem, lw: int, lh: int) -> Image.Image:
    """3col 单枚标签：照抄 make_selected_barcodes_pdf.render_label_wrap（长名称两行不截断）。"""
    img = Image.new("RGB", (lw, lh), "white")
    d = ImageDraw.Draw(img)
    pad = mm(2.5)

    bc = _fit_barcode_3col(item.code)

    f_code = font_bold(mm(4.5))    # 编码：粗体 ~4.5mm 高
    f_name = font_bold(mm(4.5))    # 名称：粗体 ~4.5mm 高
    f_foot = font_regular(mm(3.4))  # 分类/规格：小字

    # 名称：先尝试单行（逐步缩小字号 4.5mm→3.6mm 步长 0.3mm），再不行拆两行
    name = item.name
    size = mm(4.5)
    lines = [name]
    max_w = lw - 2 * pad
    while size >= mm(3.6) and d.textlength(name, font=f_name) > max_w:
        size -= mm(0.3)
        f_name = font_bold(size)
    if d.textlength(name, font=f_name) > max_w:
        # 拆两行：尽量在中间附近断开（照抄原逻辑）
        mid = len(name) // 2
        best = mid
        for i in range(len(name)):
            if d.textlength(name[:i + 1], font=f_name) > max_w:
                best = max(mid, i - 1) if i >= mid else min(mid, i)
                break
        else:
            best = len(name) - 1
        lines = [name[:best].strip(), name[best:].strip()]
    name_h = mm(5.5) * len(lines)

    foot = item.category_name
    if item.spec:
        foot += f" · {item.spec}"

    # 垂直内容块（含间距）——照抄
    blk = [bc.height, mm(5.5), name_h, mm(4.5)]
    content_h = pad + sum(blk) + mm(1)
    y0 = max(pad, (lh - content_h) // 2)   # 垂直居中

    img.paste(bc, ((lw - bc.width) // 2, y0))
    y = y0 + bc.height + mm(1)
    d.text(((lw - d.textlength(item.code, font=f_code)) / 2, y),
           item.code, fill="black", font=f_code)
    y += mm(5.5)
    for ln in lines:
        d.text(((lw - d.textlength(ln, font=f_name)) / 2, y),
               ln, fill="black", font=f_name)
        y += mm(5.5)
    d.text(((lw - d.textlength(foot, font=f_foot)) / 2, y),
           foot, fill="#555555", font=f_foot)

    # 浅灰裁切参考线
    d.rectangle([0, 0, lw - 1, lh - 1], outline="#CCCCCC", width=2)
    return img


def render_label_4col(item: LabelItem, lw: int, lh: int) -> Image.Image:
    """4col 单枚标签：照抄 generate_barcodes.render_label（密集版，名称超宽截断）。"""
    img = Image.new("RGB", (lw, lh), "white")
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, lw - 1, lh - 1], outline="#CCCCCC", width=2)
    pad = mm(1.5)
    f_code = font_bold(mm(3.2))
    f_name = font_bold(mm(3.0))
    f_foot = font_regular(mm(3.0))
    # 条码区（上部 ~52%）
    bc_h = int(lh * 0.52)
    bc = render_barcode_pil(item.code)
    ratio = min((lw - 2 * pad) / bc.width, bc_h / bc.height)
    bc = bc.resize((int(bc.width * ratio), int(bc.height * ratio)))
    img.paste(bc, ((lw - bc.width) // 2, pad))
    y = pad + bc.height + mm(0.8)
    d.text(((lw - d.textlength(item.code, font=f_code)) / 2, y),
           item.code, fill="black", font=f_code)
    y += mm(4.2)
    name = item.name + (f"（{item.spec}）" if item.spec else "")
    while d.textlength(name, font=f_name) > lw - 2 * pad and len(name) > 4:
        name = name[:-2] + "…"
    d.text(((lw - d.textlength(name, font=f_name)) / 2, y),
           name, fill="black", font=f_name)
    y += mm(4.0)
    foot = item.category_name
    d.text(((lw - d.textlength(foot, font=f_foot)) / 2, y),
           foot, fill="#444444", font=f_foot)
    return img


def render_label(item: LabelItem, w: int, h: int, layout: str = "3col") -> Image.Image:
    """按版式渲染单枚标签。layout='3col'|'4col'。"""
    if layout == "3col":
        return render_label_3col(item, w, h)
    if layout == "4col":
        return render_label_4col(item, w, h)
    raise ValueError(f"未知版式: {layout}（支持 3col/4col）")
