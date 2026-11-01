"""仪表盘测试：统计卡、今日出入库、待盘点、低库存预警、最近流水、权限。"""
from datetime import datetime

from app.models import Inventory, Item, StockMovement, Stocktake, utcnow


def _mk_item(db, name, barcode, category_id=1):
    it = Item(name=name, barcode=barcode, category_id=category_id)
    db.add(it)
    db.flush()
    return it


def _seed(db):
    a = _mk_item(db, "仪表教材A", "21010200")
    _mk_item(db, "仪表教材B", "21010201")
    _mk_item(db, "仪表耗材C", "21040200", category_id=4)
    db.add(Inventory(item_id=a.id, location_id=1, qty_on_hand=100, qty_reserved=7))
    db.add(Inventory(item_id=a.id, location_id=2, qty_on_hand=5, safety_stock=10))
    db.commit()
    return a


def test_dashboard_basic_cards(client, admin_headers, db_session):
    _seed(db_session)
    r = client.get("/api/reports/dashboard", headers=admin_headers)
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["item_count"] == 3
    assert d["total_qty"] == 105
    assert d["total_reserved"] == 7
    assert d["stocktake_count"] == 0
    assert d["pending_stocktakes"] == 0
    assert d["today_in_count"] == 0 and d["today_out_count"] == 0
    # 各库位汇总
    loc1 = next(x for x in d["by_location"] if x["location_id"] == 1)
    assert loc1["sku_count"] == 1 and loc1["total_qty"] == 100
    loc2 = next(x for x in d["by_location"] if x["location_id"] == 2)
    assert loc2["total_qty"] == 5


def test_dashboard_stocktake_counts(client, admin_headers, db_session):
    _seed(db_session)
    db_session.add(Stocktake(doc_no="STK-20261019-001", location_id=1, state="done"))
    db_session.add(Stocktake(doc_no="STK-20261019-002", location_id=2, state="counting"))
    db_session.commit()
    r = client.get("/api/reports/dashboard", headers=admin_headers)
    d = r.json()["data"]
    assert d["stocktake_count"] == 2
    assert d["pending_stocktakes"] == 1


def test_dashboard_today_counts_and_recent(client, admin_headers, db_session):
    a = _seed(db_session)
    today = utcnow()
    db_session.add(StockMovement(item_id=a.id, location_id=1, change_qty=8,
                                 qty_before=0, qty_after=8, doc_type="inbound",
                                 doc_no="IN-TODAY", created_at=today))
    db_session.add(StockMovement(item_id=a.id, location_id=1, change_qty=-2,
                                 qty_before=8, qty_after=6, doc_type="outbound",
                                 doc_no="OUT-TODAY", created_at=today))
    db_session.commit()
    r = client.get("/api/reports/dashboard", headers=admin_headers)
    d = r.json()["data"]
    assert d["today_in_count"] == 1 and d["today_out_count"] == 1
    # 最近流水：默认倒序取最新
    assert len(d["recent_movements"]) == 2
    assert d["recent_movements"][0]["doc_no"] == "OUT-TODAY"
    # recent_limit 可调
    r = client.get("/api/reports/dashboard", headers=admin_headers,
                   params={"recent_limit": 1})
    assert len(r.json()["data"]["recent_movements"]) == 1


def test_dashboard_low_stock(client, admin_headers, db_session):
    _seed(db_session)
    r = client.get("/api/reports/dashboard", headers=admin_headers)
    low = r.json()["data"]["low_stock"]
    assert len(low) == 1
    assert low[0]["qty_on_hand"] == 5 and low[0]["safety_stock"] == 10
    assert low[0]["location_name"] == "金城校区"


def test_dashboard_requires_login(client, db_session):
    _seed(db_session)
    assert client.get("/api/reports/dashboard").status_code == 401


def test_dashboard_operator_can_access(client, operator_headers, db_session):
    _seed(db_session)
    r = client.get("/api/reports/dashboard", headers=operator_headers)
    assert r.status_code == 200
    assert r.json()["data"]["item_count"] == 3
