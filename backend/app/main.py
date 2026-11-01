"""FastAPI 应用入口。

- CORS 读配置
- 统一异常处理：BizError/HTTPException → {"detail":"中文","code":"ERR_XXX"}；
  ValidationError → 中文汇总；SQLAlchemyError → 500 中文
- **路由自动发现**：扫描 app/routers/ 下所有暴露 `router` 的模块并挂到 /api 前缀。
  各 router 文件自带 APIRouter(prefix=..., tags=...)，main 不管具体路径；
  单个模块导入失败只记 warning 不崩（并行开发期某个 router 未就绪也能启动）。
- GET /healthz 与 /api/healthz（含 DB 连通 SELECT 1 + label 字体自检）
- startup 自动跑幂等 seed（AUTO_SEED=true 时）
"""
import importlib
import logging
import pkgutil
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import routers
from app.config import settings
from app.db import Base, SessionLocal, engine
from app.schemas.common import BizError
from app.seed import run_seed

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("wms")


def register_routers(app: FastAPI) -> None:
    """自动发现 app/routers/ 下所有暴露 `router` 的模块并注册到 /api 前缀。

    - 模块名以 "_" 开头的跳过（内部辅助模块）
    - 单个模块导入失败只记 warning，不拖垮整个 app
    - 注意：app/routers/__init__.py 必须保持空文件，否则 pkgutil 遍历时
      会连带 import 全部模块，失去容错意义
    """
    registered: list[str] = []
    failed: list[str] = []
    for m in sorted(pkgutil.iter_modules(routers.__path__), key=lambda x: x.name):
        if m.name.startswith("_"):
            continue
        try:
            mod = importlib.import_module(f"app.routers.{m.name}")
        except Exception:
            logger.exception("router 模块导入失败，已跳过: %s", m.name)
            failed.append(m.name)
            continue
        r = getattr(mod, "router", None)
        if r is None:
            logger.warning("router 模块 %s 未暴露 `router`，已跳过", m.name)
            continue
        app.include_router(r, prefix="/api")
        registered.append(m.name)
    logger.info("已注册路由模块 %d 个: %s", len(registered), ", ".join(registered))
    if failed:
        logger.warning("以下路由模块导入失败未注册: %s", ", ".join(failed))


def _label_fonts_check():
    """label 字体自检：模块缺失/字体缺失都不能让健康检查崩溃。"""
    try:
        from app.label import fonts as _lf
        return _lf.self_check()
    except Exception:
        return "not_installed"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 本地 sqlite 兜底建表（生产 PG 走 alembic upgrade head；create_all 幂等无害）
    import app.models  # noqa: F401  确保全部模型注册进 metadata
    Base.metadata.create_all(engine)
    if settings.AUTO_SEED:
        db = SessionLocal()
        try:
            run_seed(db)
        except Exception:
            db.rollback()
            logger.exception("自动 seed 失败（不影响启动，可手动执行 python -m app.seed）")
        finally:
            db.close()
    Path(settings.UPLOAD_DIR).mkdir(parents=True, exist_ok=True)
    logger.info("WMS 后端启动完成（DB=%s，UPLOAD_DIR=%s）",
                settings.DATABASE_URL.split("://")[0], settings.UPLOAD_DIR)
    yield


app = FastAPI(title="泽曦书画仓储管理系统", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------- 统一异常处理 ----------

@app.exception_handler(BizError)
async def biz_error_handler(request: Request, exc: BizError):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail, "code": getattr(exc, "code", "ERR_BIZ")},
    )


@app.exception_handler(StarletteHTTPException)
async def http_error_handler(request: Request, exc: StarletteHTTPException):
    zh = {
        401: "未登录或登录已过期", 403: "权限不足", 404: "接口或资源不存在",
        405: "请求方法不允许", 409: "数据冲突", 413: "上传内容过大",
        422: "请求参数校验失败", 500: "服务器内部错误，请联系管理员",
    }
    detail = exc.detail if isinstance(exc.detail, str) and exc.detail else zh.get(exc.status_code, "请求失败")
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": detail, "code": "ERR_HTTP_%s" % exc.status_code},
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    msgs = []
    for err in exc.errors()[:5]:
        loc = ".".join(str(x) for x in err.get("loc", []) if x not in ("body", "query"))
        msg = err.get("msg", "参数不合法")
        msgs.append(f"{loc}: {msg}" if loc else msg)
    return JSONResponse(
        status_code=422,
        content={"detail": "请求参数校验失败：" + "；".join(msgs), "code": "ERR_VALIDATION"},
    )


@app.exception_handler(SQLAlchemyError)
async def db_error_handler(request: Request, exc: SQLAlchemyError):
    logger.exception("数据库错误: %s", exc)
    return JSONResponse(
        status_code=500,
        content={"detail": "数据库操作失败，请稍后重试或联系管理员", "code": "ERR_DB"},
    )


# ---------- 路由注册（自动发现，统一前缀 /api） ----------

register_routers(app)


# ---------- 健康检查（公开） ----------

def _healthz_payload() -> JSONResponse:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        db_ok = True
    except Exception:  # pragma: no cover
        logger.exception("健康检查：数据库连通失败")
        db_ok = False
    label_fonts = _label_fonts_check()
    return JSONResponse(
        status_code=200 if db_ok else 503,
        content={
            "data": {
                "status": "ok" if db_ok else "degraded",
                "database": db_ok,
                "label_fonts": label_fonts,
            },
            "meta": None,
        },
    )


@app.get("/healthz")
def healthz_root():
    return _healthz_payload()


@app.get("/api/healthz")
def healthz_api():
    return _healthz_payload()
