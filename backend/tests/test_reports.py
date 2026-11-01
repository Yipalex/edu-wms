"""报表与导出测试：库存多维报表、流水汇总、CSV 导出（BOM+中文表头）、权限。"""
from datetime import datetime

from app.models import Inventory, Item, StockMovement


def _mk_item(db, name, barcode, category_id=1, suggest_price=None):
    it = Item(name=name, barcode=barcode, category_id=category_id,
              suggest_price=suggest_price)
    db.add(it)
    db.flush()
    return it


def _mk_inv(db, item_id, location_id, qty, safety=0, reserved=0):
    inv = Inventory(item_id=item_id, location_id=location_id,
                    qty_on_hand=qty, safety_stock=safety, qty_reserved=reserved)
    db.add(inv)
    db.flush()
    return inv


def _mk_mv(db, item_id, location_id, change_qty, doc_type="inbound",
           created_at=None, doc_no=None):
    mv = StockMovement(
        item_id=item_id, location_id=location_id, change_qty=change_qty,
        qty_before=0, qty_after=change_qty, doc_type=doc_type,
        doc_no=doc_no, created_at=created_at,
    )
    db.add(mv)
    db.flush()
    return mv


def _seed_stock(db):
    a = _mk_item(db, "报表教材A", "21010100", 1, suggest_price=5.0)
    b = _mk_item(db, "报表耗材B", "21040100", 4, suggest_price=2.0)
    _mk_inv(db, a.id, 1, 100)
    _mk_inv(db, a.id, 2, 20, safety=30)          # 低库存
    _mk_inv(db, b.id, 1, 50, reserved=5)
    db.commit()
    return a, b


def _seed_movements(db, a, b):
    _mk_mv(db, a.id, 1, 10, "inbound", datetime(2026, 10, 1, 9), "IN-1")
    _mk_mv(db, a.id, 1, -4, "outbound", datetime(2026, 10, 2, 9), "OUT-1")
    _mk_mv(db, b.id, 2, 6, "transfer", datetime(2026, 10, 3, 9), "TR-1")
    db.commit()


# ---------- /reports/stock ----------

def test_stock_report_by_item(client, admin_headers, db_session):
    _seed_stock(db_session)
    r = client.get("/api/reports/stock", headers=admin_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["meta"]["total"] == 3
    row = body["data"][0]
    for k in ("barcode", "item_name", "location_name", "qty_on_hand",
              "stock_value", "below_safety"):
        assert k in row
    # 筛选 + 分页
    r = client.get("/api/reports/stock", headers=admin_headers,
                   params={"below_safety": "true"})
    assert r.json()["meta"]["total"] == 1
    assert r.json()["data"][0]["location_id"] == 2
    r = client.get("/api/reports/stock", headers=admin_headers,
                   params={"location_id": 1, "page_size": 1, "page": 2})
    body = r.json()
    assert body["meta"]["total"] == 2 and len(body["data"]) == 1


def test_stock_report_group_by_location_and_category(client, admin_headers, db_session):
    _seed_stock(db_session)
    r = client.get("/api/reports/stock", headers=admin_headers,
                   params={"group_by": "location"})
    data = r.json()["data"]
    loc1 = next(x for x in data if x["location_id"] == 1)
    assert loc1["sku_count"] == 2 and loc1["total_qty"] == 150
    assert loc1["total_value"] == 100 * 5.0 + 50 * 2.0

    r = client.get("/api/reports/stock", headers=admin_headers,
                   params={"group_by": "category"})
    data = r.json()["data"]
    cat1 = next(x for x in data if x["category_id"] == 1)
    assert cat1["sku_count"] == 1 and cat1["total_qty"] == 120


# ---------- /reports/movements ----------

def test_movements_report_by_doc_type(client, admin_headers, db_session):
    a, b = _seed_stock(db_session)
    _seed_movements(db_session, a, b)
    r = client.get("/api/reports/movements", headers=admin_headers)
    assert r.status_code == 200
    body = r.json()["data"]
    assert body["group_by"] == "doc_type"
    overall = body["overall"]
    assert overall["movement_count"] == 3
    assert overall["in_qty"] == 16 and overall["out_qty"] == 4
    by_type = {row["doc_type"]: row for row in body["rows"]}
    assert by_type["inbound"]["in_qty"] == 10
    assert by_type["outbound"]["out_qty"] == 4
    assert by_type["transfer"]["in_qty"] == 6


def test_movements_report_by_date_and_filters(client, admin_headers, db_session):
    a, b = _seed_stock(db_session)
    _seed_movements(db_session, a, b)
    r = client.get("/api/reports/movements", headers=admin_headers,
                   params={"group_by": "date"})
    rows = r.json()["data"]["rows"]
    assert [row["date"] for row in rows] == ["2026-10-01", "2026-10-02", "2026-10-03"]
    r = client.get("/api/reports/movements", headers=admin_headers,
                   params={"start": "2026-10-02", "end": "2026-10-03"})
    assert r.json()["data"]["overall"]["movement_count"] == 2
    r = client.get("/api/reports/movements", headers=admin_headers,
                   params={"group_by": "item"})
    rows = {row["item_id"]: row for row in r.json()["data"]["rows"]}
    assert rows[a.id]["net_qty"] == 6 and rows[b.id]["net_qty"] == 6
    r = client.get("/api/reports/movements", headers=admin_headers,
                   params={"group_by": "location"})
    rows = {row["location_id"]: row for row in r.json()["data"]["rows"]}
    assert rows[1]["net_qty"] == 6 and rows[2]["net_qty"] == 6


# ---------- /exports/{kind} ----------

def test_export_items_csv(client, admin_headers, db_session):
    _seed_stock(db_session)
    r = client.get("/api/exports/items", headers=admin_headers)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"]
    text = r.content.decode("utf-8")
    assert text.startswith("\ufeff")            # BOM：Excel 直接打开不乱码
    assert "条码" in text.splitlines()[0] and "物品名称" in text.splitlines()[0]
    assert "报表教材A" in text


def test_export_inventory_csv(client, admin_headers, db_session):
    _seed_stock(db_session)
    r = client.get("/api/exports/inventory", headers=admin_headers,
                   params={"location_id": 2})
    text = r.content.decode("utf-8")
    lines = text.splitlines()
    assert "库位" in lines[0] and "当前库存" in lines[0]
    assert len(lines) == 1 + 1                  # 表头 + 1 行（库位 2 仅一条）
    r = client.get("/api/exports/inventory", headers=admin_headers,
                   params={"below_safety": "true"})
    assert len(r.content.decode("utf-8").splitlines()) == 2


def test_export_movements_csv(client, admin_headers, db_session):
    a, b = _seed_stock(db_session)
    _seed_movements(db_session, a, b)
    r = client.get("/api/exports/movements", headers=admin_headers)
    text = r.content.decode("utf-8")
    lines = text.splitlines()
    assert "变动数量" in lines[0] and "操作人" in lines[0]
    assert len(lines) == 1 + 3
    # 时间范围筛选
    r = client.get("/api/exports/movements", headers=admin_headers,
                   params={"start": "2026-10-03"})
    assert len(r.content.decode("utf-8").splitlines()) == 2


def test_export_bad_kind(client, admin_headers, db_session):
    r = client.get("/api/exports/nonsense", headers=admin_headers)
    assert r.status_code == 400
    assert r.json()["code"] == "ERR_BAD_EXPORT_KIND"


# ---------- 权限 ----------

def test_reports_and_exports_require_login(client, db_session):
    _seed_stock(db_session)
    for path in ("/api/reports/stock", "/api/reports/movements", "/api/exports/items"):
        assert client.get(path).status_code == 401


def test_operator_can_access(client, operator_headers, db_session):
    _seed_stock(db_session)
    for path in ("/api/reports/stock", "/api/reports/movements",
                 "/api/exports/items", "/api/exports/movements"):
        r = client.get(path, headers=operator_headers)
        assert r.status_code == 200, path
