"""健康检查、docs、种子数据与幂等性测试。"""
from sqlalchemy import func, select

from app.models import BarcodeSequence, Category, Location, User
from app.seed import run_seed


def test_healthz(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["data"]["status"] == "ok"
    assert body["data"]["database"] is True


def test_api_healthz(client):
    r = client.get("/api/healthz")
    assert r.status_code == 200


def test_docs_accessible(client):
    r = client.get("/docs")
    assert r.status_code == 200


def test_seed_content(db_session):
    cats = db_session.scalars(select(Category).order_by(Category.sort_order)).all()
    assert [(c.digit, c.name) for c in cats] == [
        ("1", "教材"), ("2", "书籍"), ("3", "辅材"),
        ("4", "耗材"), ("5", "礼品"), ("9", "其他"),
    ]
    locs = db_session.scalars(select(Location).order_by(Location.sort_order)).all()
    assert [(l.code, l.name) for l in locs] == [
        ("HQ", "总校办仓库"), ("JC", "金城校区"), ("ST", "社坛校区"),
        ("HD", "海东校区"), ("MZ", "麻章校区"), ("KFQ", "开发区校区"),
    ]
    hq = next(l for l in locs if l.code == "HQ")
    assert hq.type == "warehouse" and hq.is_front_warehouse is True
    assert all(l.type == "campus" and not l.is_front_warehouse for l in locs if l.code != "HQ")

    # DESIGN §2 存量流水种子：教材33 书籍1 辅材43 耗材56 礼品11 其他15
    expected = {"1": 33, "2": 1, "3": 43, "4": 56, "5": 11, "9": 15}
    for c in cats:
        seq = db_session.scalar(
            select(BarcodeSequence).where(BarcodeSequence.category_id == c.id))
        assert seq is not None
        assert seq.next_seq == expected[c.digit], f"类目 {c.name} 流水种子错误"

    admin = db_session.scalar(select(User).where(User.username == "admin"))
    assert admin is not None and admin.role == "admin" and admin.is_active


def test_seed_idempotent(db_session):
    run_seed(db_session)   # fixture 已跑过一次，再跑一次不应重复插入
    run_seed(db_session)
    assert db_session.scalar(select(func.count(Category.id))) == 6
    assert db_session.scalar(select(func.count(Location.id))) == 6
    assert db_session.scalar(select(func.count(BarcodeSequence.category_id))) == 6
    assert db_session.scalar(select(func.count(User.id))) == 1
