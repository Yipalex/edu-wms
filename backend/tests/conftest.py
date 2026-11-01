"""pytest 公共 fixture：sqlite 内存库 + TestClient + 种子数据 + 登录 token。"""
import os

# 必须在导入 app 之前设置环境变量
os.environ.setdefault("DATABASE_URL", "sqlite://")          # 内存库
os.environ.setdefault("AUTO_SEED", "false")                 # seed 由 fixture 显式跑
os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("ADMIN_INIT_PASSWORD", "Test@2026")
os.environ.setdefault("UPLOAD_DIR", os.path.join(os.path.dirname(__file__), "_uploads"))

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import StaticPool, create_engine, event
from sqlalchemy.orm import sessionmaker

from app.db import Base, _sqlite_regexp, get_db
from app.main import app
from app.seed import run_seed


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _pragma(dbapi_conn, _record):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()
        dbapi_conn.create_function("regexp", 2, _sqlite_regexp)

    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    session = TestingSession()
    try:
        run_seed(session)
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


@pytest.fixture()
def client(db_session):
    def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    # lifespan 会在 TestClient 上下文里跑 create_all+seed，AUTO_SEED=false 已关 seed，
    # create_all 用的是 app.db.engine（另一个空库），不影响被 override 的会话
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _login(client: TestClient, username: str, password: str) -> str:
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["data"]["access_token"]


@pytest.fixture()
def admin_token(client) -> str:
    return _login(client, "admin", "Test@2026")


@pytest.fixture()
def admin_headers(admin_token) -> dict:
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture()
def operator_headers(client, db_session, admin_headers) -> dict:
    """建一个 operator 用户并登录。"""
    r = client.post("/api/users", headers=admin_headers, json={
        "username": "op1", "password": "Op@12345678",
        "display_name": "操作员一号", "role": "operator",
    })
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {_login(client, 'op1', 'Op@12345678')}"}
