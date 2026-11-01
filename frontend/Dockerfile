# =============================================================
# 泽曦书画 WMS · 前端镜像（多阶段构建）
# node:20-alpine 构建 Vite/React → nginx:alpine 托管 dist/
#
# 目录结构假定（与 frontend worker 对齐）：
#   frontend/package.json + package-lock.json —— npm ci 依赖清单
#   frontend/vite.config.ts                   —— base: '/'（新子域名根路径部署）
#   frontend/src/                             —— 源码
#   构建产物 → dist/
#
# API base：前端统一用【相对路径 /api】（推荐，理由见 deploy/README.md）：
#   - 同域部署无需构建期注入 API 地址，一个镜像可跑任意域名
#   - 避免开发/生产两套 .env 构建
#   如前端确实需要构建参数，保留 VITE_API_BASE 透传（默认空=相对路径）。
# =============================================================

# ---------- 阶段 1：构建 ----------
FROM node:20-alpine AS build
WORKDIR /build

# 先拷依赖清单，利用分层缓存
COPY package.json package-lock.json* ./
# 国内 VPS：npm 走 npmmirror；有 lock 文件用 npm ci（可复现），没有则退回 npm install
RUN npm config set registry https://registry.npmmirror.com \
    && if [ -f package-lock.json ]; then npm ci; else npm install; fi

COPY . .
ARG VITE_API_BASE=""
ENV VITE_API_BASE=${VITE_API_BASE}
RUN npm run build

# ---------- 阶段 2：托管 ----------
# 注：不能用 nginx:alpine —— 目标 VPS 是 CentOS 7（kernel 3.10），musl 二进制
# 命中 docker 默认 seccomp 白名单外的 syscall 直接 EPERM（pwrite pid 即崩），
# 实测 nginx:alpine 与 postgres:16-alpine 都会挂；bookworm（glibc）正常。
FROM nginx:1.27-bookworm
# 静态资源
COPY --from=build /build/dist /usr/share/nginx/html
# 容器内 nginx 站点配置（静态托管 + /api、/uploads 反代到 api:8080）
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
# healthcheck 由 compose 定义（wget /）
