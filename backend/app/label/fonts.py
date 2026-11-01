"""中文字体解析（容器化关键）。

现有 barcode-tool 脚本硬编码 macOS 的
`/System/Library/Fonts/Hiragino Sans GB.ttc`（index 0 = W3 常规、index 2 = W6 粗体），
Linux 容器里没有该文件，直接用会出「豆腐块」。本模块按优先级探测候选字体：

1. 环境变量/配置显式指定（LABEL_FONT_REGULAR / LABEL_FONT_BOLD）—— 最高优先
2. Linux Noto Sans CJK（Debian fonts-noto-cjk 包，.ttc 需要 index）
3. 文泉驿正黑 wqy-zenhei.ttc（只有常规字重，bold 复用同一文件）
4. macOS Hiragino Sans GB.ttc（index 0 / 2）—— 本地开发用
5. macOS PingFang.ttc（实测结论见下）
6. 兜底 PIL ImageFont.load_default() + WARNING（只能显示 ASCII，中文全是豆腐块）

PingFang 实测说明（2026-10，macOS 26 / Python 3.11 / Pillow 11）：
    老版 `/System/Library/Fonts/PingFang.ttc` 在新系统上已不存在；实际文件位于
    `/System/Library/AssetsV2/com_apple_MobileAsset_Font8/<hash>.asset/AssetData/PingFang.ttc`
    或 `/System/Library/PrivateFrameworks/FontServices.framework/Versions/A/Resources/Reserved/PingFangUI.ttc`。
    **PIL 是可以按 index 加载的**（与旧脚本注释「取不到索引」不符，实测可加载）：
    该 ttc 内 24 个子字体，PingFang SC Regular = index 3，PingFang SC Semibold = index 11。
    但 hash 路径随系统更新变化，不可靠，故排在 Hiragino 之后作次选，且用 glob 探测。

本模块**零 app 依赖**（不 import app.config），通过环境变量读取配置，
以便 CLI 工具与纯引擎自测直接使用；Web 侧由 app.config 把配置写入环境变量
或在启动时调用 configure()。
"""
from __future__ import annotations

import glob
import logging
import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

ENV_REGULAR = "LABEL_FONT_REGULAR"
ENV_BOLD = "LABEL_FONT_BOLD"

# Hiragino Sans GB.ttc 实测：index 0 = ('Hiragino Sans GB', 'W3')，index 2 = ('Hiragino Sans GB', 'W6')
HIRAGINO = "/System/Library/Fonts/Hiragino Sans GB.ttc"

# Noto Sans CJK：fonts-noto-cjk 包（Debian/Ubuntu）两种可能路径。
# NotoSansCJK-Regular.ttc 内 index 0..: 通常 2 = SC 或全部子字体均含完整 CJK 字形，
# 对标签上的简体中文而言任意 index 均可正确显示，这里取已验证安全的 index：
#   Regular.ttc / Bold.ttc 分开两个文件时各取 index 0；
#   若只有 NotoSansCJK.ttc（老包），常规与粗体分别对应 index 0 / 1（Noto Sans CJK SC 家族排序）。
NOTO_CANDIDATES: Tuple[Tuple[str, int, int], ...] = (
    # (文件路径, regular_index, bold_index)；两个独立文件时 bold_index 无意义（下面分开处理）
    ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", 0, 0),
    ("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc", 0, 0),
    ("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc", 0, 0),
    ("/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc", 0, 0),
    ("/usr/share/fonts/opentype/noto/NotoSansCJK.ttc", 0, 1),
    ("/usr/share/fonts/truetype/noto/NotoSansCJK.ttc", 0, 1),
)

WQY = ("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc", 0, 0)

PINGFANG_GLOBS = (
    "/System/Library/Fonts/PingFang.ttc",                       # 老系统
    "/System/Library/AssetsV2/com_apple_MobileAsset_Font*/*.asset/AssetData/PingFang.ttc",
    "/System/Library/PrivateFrameworks/FontServices.framework/Versions/A/Resources/Reserved/PingFangUI.ttc",
)
# PingFang.ttc 实测：index 3 = PingFang SC Regular，index 11 = PingFang SC Semibold（作粗体用）
PINGFANG_REGULAR_IDX = 3
PINGFANG_BOLD_IDX = 11


@dataclass(frozen=True)
class FontSpec:
    """一个可加载的字体规格：文件路径 + ttc 内索引。"""
    path: str
    index: int
    source: str  # env / noto / wqy / hiragino / pingfang / default

    def load(self, size_px: int) -> ImageFont.FreeTypeFont:
        return ImageFont.truetype(self.path, size_px, index=self.index)


# ---------------------------------------------------------------------------
# 探测
# ---------------------------------------------------------------------------

def _explicit(env_key: str) -> Optional[FontSpec]:
    """环境变量显式指定：支持 `path` 或 `path:index` 写法（ttc 必须给 index）。"""
    raw = os.environ.get(env_key, "").strip()
    if not raw:
        return None
    path, _, idx = raw.rpartition(":")
    index = 0
    if path and idx.isdigit():
        index = int(idx)
    else:  # Windows 盘符 C:\... 或普通无 index 路径
        path, index = raw, 0
    if not os.path.exists(path):
        logger.warning("%s=%s 指向的文件不存在，忽略", env_key, raw)
        return None
    return FontSpec(path=path, index=index, source="env")


@lru_cache(maxsize=8)
def _find_subfont_index(path: str, want_bold: bool, fallback: int) -> int:
    """在 CJK ttc 内枚举子字体，优先选 SC（简体默认字形）且字重匹配的子字体索引。

    - NotoSansCJK.ttc 合并包内含 JP/KR/SC/TC/HK × Regular/Bold 多个子字体；
    - 独立 Regular/Bold ttc 内只有 5 个语言的同一字重；
    - 找不到精确匹配则退回 fallback（任意 index 都能显示简体，只是字形可能是 JP 变体）。
    """
    sc_any = None
    try:
        for i in range(64):
            try:
                family, style = ImageFont.truetype(path, 12, index=i).getname()
            except Exception:  # noqa: BLE001 - 索引越界，枚举结束
                break
            is_sc = " SC" in family or family.endswith("SC")
            is_bold = "bold" in style.lower() or "heavy" in style.lower() or "black" in style.lower()
            if is_sc and (is_bold == want_bold):
                return i
            if is_sc and sc_any is None:
                sc_any = i
    except Exception:  # noqa: BLE001
        pass
    if sc_any is not None:
        return sc_any
    return fallback


def _probe_noto() -> Tuple[Optional[FontSpec], Optional[FontSpec]]:
    """Noto：Regular/Bold 可能是两个独立 ttc，也可能是单个 NotoSansCJK.ttc。"""
    regular = bold = None
    for path, r_idx, b_idx in NOTO_CANDIDATES:
        if not os.path.exists(path):
            continue
        if path.endswith("NotoSansCJK-Regular.ttc"):
            regular = regular or FontSpec(path, _find_subfont_index(path, False, r_idx), "noto")
        elif path.endswith("NotoSansCJK-Bold.ttc"):
            bold = bold or FontSpec(path, _find_subfont_index(path, True, 0), "noto")
        else:  # 合并包 NotoSansCJK.ttc（Regular 与 Bold 在同一文件内）
            regular = regular or FontSpec(path, _find_subfont_index(path, False, r_idx), "noto")
            bold = bold or FontSpec(path, _find_subfont_index(path, True, b_idx), "noto")
    return regular, bold


def _probe_pingfang() -> Tuple[Optional[FontSpec], Optional[FontSpec]]:
    for pattern in PINGFANG_GLOBS:
        hits = sorted(glob.glob(pattern))
        for path in hits:
            # 实测可加载，但仍防御性验证 index 有效
            try:
                ImageFont.truetype(path, 12, index=PINGFANG_BOLD_IDX)
            except Exception:  # noqa: BLE001 - 索引不可用则整条候选作废
                try:
                    ImageFont.truetype(path, 12, index=0)
                    return FontSpec(path, 0, "pingfang"), FontSpec(path, 0, "pingfang")
                except Exception:  # noqa: BLE001
                    continue
            return (FontSpec(path, PINGFANG_REGULAR_IDX, "pingfang"),
                    FontSpec(path, PINGFANG_BOLD_IDX, "pingfang"))
    return None, None


@lru_cache(maxsize=1)
def resolve_fonts() -> Tuple[Optional[FontSpec], Optional[FontSpec]]:
    """返回 (regular_spec, bold_spec)。可能为 None（走 load_default 兜底）。"""
    reg = _explicit(ENV_REGULAR)
    bold = _explicit(ENV_BOLD)
    if reg and bold:
        return reg, bold

    n_reg, n_bold = _probe_noto()
    if os.path.exists(HIRAGINO):
        h_reg, h_bold = FontSpec(HIRAGINO, 0, "hiragino"), FontSpec(HIRAGINO, 2, "hiragino")
    else:
        h_reg = h_bold = None
    p_reg, p_bold = _probe_pingfang()

    w_reg = w_bold = None
    if os.path.exists(WQY[0]):
        w_reg = w_bold = FontSpec(WQY[0], WQY[1], "wqy")

    # 优先级：env > noto > wqy > hiragino > pingfang
    reg = reg or n_reg or w_reg or h_reg or p_reg
    bold = bold or n_bold or w_bold or h_bold or p_bold
    # 只探到一半时互相补齐（如 wqy 无独立 bold）
    bold = bold or reg
    reg = reg or bold
    return reg, bold


def configure(regular: Optional[str] = None, bold: Optional[str] = None) -> None:
    """供 app.config 在启动时注入（等价于设置环境变量并清空缓存）。"""
    changed = False
    if regular is not None and os.environ.get(ENV_REGULAR, "") != regular:
        os.environ[ENV_REGULAR] = regular
        changed = True
    if bold is not None and os.environ.get(ENV_BOLD, "") != bold:
        os.environ[ENV_BOLD] = bold
        changed = True
    if changed:
        resolve_fonts.cache_clear()
        _font_cache.cache_clear()


@lru_cache(maxsize=256)
def _font_cache(kind: str, size_px: int):
    reg, bold = resolve_fonts()
    spec = reg if kind == "regular" else bold
    if spec is None:
        logger.warning("未找到任何中文字体，回退 PIL 默认位图字体（中文将显示为方块）；"
                       "请在镜像安装 fonts-noto-cjk 或设置 %s/%s", ENV_REGULAR, ENV_BOLD)
        return ImageFont.load_default()
    try:
        return spec.load(size_px)
    except Exception:  # noqa: BLE001 - 字体文件损坏/索引失效
        logger.warning("字体加载失败 %s(index=%s)，回退 PIL 默认字体", spec.path, spec.index)
        return ImageFont.load_default()


def font_regular(size_px: int):
    """常规字重字体（对应旧脚本 Hiragino W3 / font_light）。"""
    return _font_cache("regular", size_px)


def font_bold(size_px: int):
    """粗体字重字体（对应旧脚本 Hiragino W6 / font_bold）。"""
    return _font_cache("bold", size_px)


def font_info() -> dict:
    """字体探测结果（供 /labels/font-check 与 CLI --font-check）。"""
    reg, bold = resolve_fonts()
    out = {
        "regular": None,
        "bold": None,
        "fallback_default": reg is None and bold is None,
        "env_regular": os.environ.get(ENV_REGULAR, "") or None,
        "env_bold": os.environ.get(ENV_BOLD, "") or None,
    }
    for key, spec in (("regular", reg), ("bold", bold)):
        if spec is None:
            continue
        try:
            f = spec.load(24)
            out[key] = {
                "path": spec.path,
                "index": spec.index,
                "source": spec.source,
                "family": f.getname(),
                "loaded": True,
            }
        except Exception as e:  # noqa: BLE001
            out[key] = {"path": spec.path, "index": spec.index,
                        "source": spec.source, "loaded": False, "error": str(e)}
    return out


_SELF_CHECK_TEXT = "泽曦书画教材偏旁部首"


def self_check() -> bool:
    """启动自检：用当前字体渲染一行中文，确认字体可加载且能度量中文宽度。

    注意：「豆腐块」（缺字形时画方框）无法程序化检测——PIL 对缺失字形
    会静默用 .notdef 方框代替且 textlength 正常返回。本函数只能保证：
    a) 字体文件成功加载（非 load_default 兜底）；
    b) 中文字符宽度 > 英文字符宽度（真 CJK 字体的典型特征，位图兜底字体不满足）。
    最终验收必须在部署后打开 /labels/sample.pdf 样张**肉眼确认**。
    """
    try:
        reg, bold = resolve_fonts()
        if reg is None or bold is None:
            logger.warning("font self_check: 未解析到中文字体")
            return False
        f_reg, f_bold = font_regular(40), font_bold(40)
        img = Image.new("RGB", (600, 120), "white")
        d = ImageDraw.Draw(img)
        d.text((10, 10), _SELF_CHECK_TEXT, font=f_reg, fill="black")
        d.text((10, 60), _SELF_CHECK_TEXT, font=f_bold, fill="black")
        # 启发式：CJK 全角字符宽度应显著大于半角 '0'
        w_cjk = d.textlength("泽", font=f_bold)
        w_digit = d.textlength("0", font=f_bold)
        ok = w_cjk > w_digit * 1.5
        if not ok:
            logger.warning("font self_check: 中文字宽异常（泽=%.1f 0=%.1f），可能缺 CJK 字形",
                           w_cjk, w_digit)
        return ok
    except Exception:  # noqa: BLE001
        logger.exception("font self_check 失败")
        return False


if __name__ == "__main__":  # 手动排查：python -m app.label.fonts
    logging.basicConfig(level=logging.INFO)
    import json
    print(json.dumps(font_info(), ensure_ascii=False, indent=2))
    print("self_check:", self_check())
