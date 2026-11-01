# =============================================================
# 泽曦书画 WMS · 后端镜像
# Python 3.11 slim + Noto CJK 字体（标签渲染硬依赖，见 DESIGN §8）
#
# 目录结构假定（与 backend worker 对齐）：
#   backend/requirements.txt   —— pip 依赖清单
#   backend/app/main.py        —— FastAPI 入口（app.main:app）
#   backend/alembic.ini        —— 迁移配置（位于 /app 工作目录）
#   backend/alembic/           —— 迁移脚本目录
#
# 说明：
#   - 数据库驱动走 psycopg[binary]（预编译 wheel），因此【不需要】
#     build-essential / libpq-dev，镜像更小、构建更快。
#   - libzbar0 一并安装（约 100KB）：若 label/扫码链路用 pyzbar 做
#     条码可扫性自校验（DESIGN §8 要求生成后验证可扫），有备无患；
#     pyzbar 本身是 pip 依赖，系统库缺了会在 import 时报错，装上零风险。
# =============================================================
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Asia/Shanghai

# ---- 系统依赖：CJK 字体（标签 PDF 必需，缺了中文全是豆腐块） ----
# 与 label-engine 约定：其字体探测默认命中下面两个 .ttc 路径，并会在 ttc 内
# 自动枚举挑选「SC + 字重匹配」的子字体索引；也可用 LABEL_FONT_REGULAR/BOLD
# 环境变量覆盖（支持 `路径:index` 写法）。
# 下方 test -f 是刻意加的硬校验：字体路径一旦因基础镜像变更而漂移，build 直接失败，
# 而不是等到线上打出一页豆腐块才发现。
# 国内 VPS：apt 源切阿里云镜像（海外 deb.debian.org 实测 ~35KB/s，不可接受）
RUN sed -i 's|deb.debian.org|mirrors.aliyun.com|g; s|security.debian.org|mirrors.aliyun.com|g' \
        /etc/apt/sources.list.d/debian.sources 2>/dev/null || true \
    && apt-get update && apt-get install -y --no-install-recommends \
        fonts-noto-cjk \
        libzbar0 \
    && rm -rf /var/lib/apt/lists/* \
    # 确认字体安装到位（路径与 config.py 默认值、compose 环境变量一致）
    && test -f /usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc \
    && test -f /usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc

# ---- 健康检查脚本（compose healthcheck 调用；兼容 /healthz 与 /api/healthz） ----
RUN printf '%s\n' \
    'import sys, urllib.request, urllib.error' \
    'ok = False' \
    'for url in ("http://127.0.0.1:8080/healthz", "http://127.0.0.1:8080/api/healthz"):' \
    '    try:' \
    '        urllib.request.urlopen(url, timeout=3)' \
    '        ok = True' \
    '        break' \
    '    except urllib.error.HTTPError as e:' \
    '        if e.code < 500:' \
    '            ok = True' \
    '            break' \
    '    except Exception:' \
    '        continue' \
    'sys.exit(0 if ok else 1)' \
    > /opt/healthcheck.py

WORKDIR /app

# ---- 先装依赖（利用 Docker 分层缓存，代码改动不触发重装） ----
# 国内 VPS：pip 走阿里云 PyPI 镜像
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    -i https://mirrors.aliyun.com/pypi/simple/

# ---- 再拷代码 ----
COPY . .

# ---- 非 root 用户运行；uploads 目录可写 ----
RUN useradd --create-home --uid 10001 wms \
    && mkdir -p /data/uploads \
    && chown -R wms:wms /app /data/uploads
USER wms

EXPOSE 8080

HEALTHCHECK --interval=15s --timeout=5s --retries=5 --start-period=30s \
    CMD python /opt/healthcheck.py

# 实际启动命令由 docker-compose.yml 的 command 指定（uvicorn --workers 2）
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
