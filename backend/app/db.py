"""SQLAlchemy 2.0 engine / sessionmaker / get_db 依赖。

同时兼容 SQLite（本地开发/测试）与 PostgreSQL（生产）：
- SQLite 需要 check_same_thread=False（FastAPI 多线程访问同一连接池）
- SQLite 默认不开外键约束，通过 event 监听 PRAGMA foreign_keys=ON
- SQLite 没有内置 REGEXP，注册 Python 实现，使契约中的正则 CHECK 约束
  （barcode/prefix/region 纯数字）在 SQLite 下同样生效（PG 侧用 `~`）
- 内存库使用 StaticPool 保证所有 Session 共享同一连接
"""
import re
from typing import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings


def _sqlite_regexp(pattern: str, value) -> bool:
    if value is None:
        return False
    return re.search(pattern, str(value)) is not None


def create_db_engine(url: str) -> Engine:
    """按 URL 创建 engine（测试可复用此函数建自己的 engine）。"""
    if url.startswith("sqlite"):
        kwargs: dict = {"connect_args": {"check_same_thread": False}}
        if ":memory:" in url or url in ("sqlite://", "sqlite:///"):
            kwargs["poolclass"] = StaticPool
        engine = create_engine(url, **kwargs)

        @event.listens_for(engine, "connect")
        def _set_sqlite_pragma(dbapi_conn, _record):
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()
            dbapi_conn.create_function("regexp", 2, _sqlite_regexp)

        return engine
    # PostgreSQL 等
    return create_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=10)


class Base(DeclarativeBase):
    """所有 ORM 模型的基类。"""


engine = create_db_engine(settings.DATABASE_URL)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    """FastAPI 依赖：每请求一个 Session，异常自动回滚，结束关闭。"""
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
