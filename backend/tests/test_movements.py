"""库存流水查询测试：多维筛选、分页边界、详情、只读保护、权限。"""
from datetime import datetime

from sqlalchemy import select

from app.models import Item, StockMovement, User


def _mk_item(db, name, barcode, category_id=1):
    it = Item(name=name, barcode=barcode, category_id=category_id)
    db.add(it)
    db.flush()
    return it


def _mk_mv(db, item_id, location_id, change_qty, doc_type="inbound",
           created_at=None, operator_id=None, doc_no=None, note=""):
    before = 0
    after = before + change_qty
    mv = StockMovement(
        item_id=item_id, location_id=location_id, change_qty=change_qty,
        qty_before=before, qty_after=after, doc_type=doc_type,
        doc_no=doc_no, operator_id=operator_id, note=note, created_at=created_at,
    )
    db.add(mv)
    db.flush()
    return mv


def _seed(db):
    a = _mk_item(db, "流水教材A", "21010090", category_id=1)
    b = _mk_item(db, "流水耗材B", "21040090", category_id=4)
    admin = db.scalar(select(User).where(User.username == "admin"))
    m1 = _mk_mv(db, a.id, 1, 10, "inbound", datetime(2026, 9, 1, 10), admin.id, "IN-20260901-001")
    m2 = _mk_mv(db, a.id, 2, -3, "transfer", datetime(2026, 10, 5, 10), admin.id, "OUT-20261005-001")
    m3 = _mk_mv(db, b.id, 1, 5, "inbound", datetime(2026, 10, 15, 10), admin.id, "IN-20261015-001")
    db.commit()
    return a, b, m1, m2, m3


def test_list_basic_and_meta(client, admin_headers, db_session):
    _seed(db_session)
    r = client.get("/api/movements", headers=admin_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["meta"]["total"] == 3
    assert len(body["data"]) == 3
    row = body["data"][0]
    for k in ("id", "item_name", "barcode", "location_name", "change_qty",
              "qty_before", "qty_after", "doc_type", "doc_no",
              "operator_name", "created_at"):
        assert k in row
    # 默认按 id 倒序：最新一条在最前
    assert body["data"][0]["doc_no"] == "IN-20261015-001"


def test_filter_by_doc_type_location_item(client, admin_headers, db_session):
    a, b, *_ = _seed(db_session)
    r = client.get("/api/movements", headers=admin_headers, params={"doc_type": "inbound"})
    assert r.json()["meta"]["total"] == 2
    r = client.get("/api/movements", headers=admin_headers, params={"location_id": 2})
    assert r.json()["meta"]["total"] == 1
    assert r.json()["data"][0]["change_qty"] == -3
    r = client.get("/api/movements", headers=admin_headers, params={"item_id": b.id})
    assert r.json()["meta"]["total"] == 1


def test_filter_by_operator_and_date_range(client, admin_headers, db_session):
    _seed(db_session)
    admin_id = db_session.scalar(select(User.id).where(User.username == "admin"))
    r = client.get("/api/movements", headers=admin_headers, params={"operator_id": admin_id})
    assert r.json()["meta"]["total"] == 3
    r = client.get("/api/movements", headers=admin_headers,
                   params={"start": "2026-10-01", "end": "2026-10-31"})
    assert r.json()["meta"]["total"] == 2
    r = client.get("/api/movements", headers=admin_headers, params={"start": "2026-10-06"})
    assert r.json()["meta"]["total"] == 1
    r = client.get("/api/movements", headers=admin_headers, params={"end": "2026-09-30"})
    assert r.json()["meta"]["total"] == 1


def test_search_by_doc_no_and_item_name(client, admin_headers, db_session):
    _seed(db_session)
    r = client.get("/api/movements", headers=admin_headers, params={"q": "OUT-20261005"})
    assert r.json()["meta"]["total"] == 1
    r = client.get("/api/movements", headers=admin_headers, params={"q": "耗材"})
    assert r.json()["meta"]["total"] == 1


def test_pagination_boundary(client, admin_headers, db_session):
    _seed(db_session)
    r = client.get("/api/movements", headers=admin_headers, params={"page": 2, "page_size": 2})
    body = r.json()
    assert body["meta"]["page"] == 2 and body["meta"]["page_size"] == 2
    assert len(body["data"]) == 1
    # 越界页：空列表但 total 保持
    r = client.get("/api/movements", headers=admin_headers, params={"page": 99, "page_size": 20})
    body = r.json()
    assert body["data"] == [] and body["meta"]["total"] == 3
    # page=0 归一化为 1
    r = client.get("/api/movements", headers=admin_headers, params={"page": 0})
    assert r.json()["meta"]["page"] == 1


def test_detail_and_404(client, admin_headers, db_session):
    *_, m3 = _seed(db_session)
    r = client.get(f"/api/movements/{m3.id}", headers=admin_headers)
    assert r.status_code == 200
    assert r.json()["data"]["doc_no"] == "IN-20261015-001"
    r = client.get("/api/movements/99999", headers=admin_headers)
    assert r.status_code == 404
    assert r.json()["code"] == "ERR_NOT_FOUND"


def test_readonly_no_write_routes(client, admin_headers, db_session):
    _seed(db_session)
    r = client.post("/api/movements", headers=admin_headers, json={})
    assert r.status_code in (405, 404)
    r = client.patch("/api/movements/1", headers=admin_headers, json={})
    assert r.status_code in (405, 404)
    r = client.delete("/api/movements/1", headers=admin_headers)
    assert r.status_code in (405, 404)


def test_requires_login(client, admin_headers, db_session):
    _seed(db_session)
    r = client.get("/api/movements")
    assert r.status_code == 401
    r = client.get("/api/movements/1")
    assert r.status_code == 401


def test_operator_can_access(client, operator_headers, db_session):
    _seed(db_session)
    r = client.get("/api/movements", headers=operator_headers)
    assert r.status_code == 200
    assert r.json()["meta"]["total"] == 3
