"""销售对接 API 测试：扣减、幂等重放、库存不足、条码未登记、在售清单。"""
from sqlalchemy import select

from app.models import Inventory, Location, OutboundOrder, StockMovement


def _category_id(client, headers) -> int:
    r = client.get("/api/categories", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["data"][0]["id"]


def _mk_item(client, headers, name: str, barcode: str) -> dict:
    r = client.post("/api/items", headers=headers, json={
        "barcode": barcode, "name": name, "category_id": _category_id(client, headers),
    })
    assert r.status_code == 200, r.text
    return r.json()["data"]


def _hq_id(db_session) -> int:
    return db_session.scalar(select(Location.id).where(Location.code == "HQ"))


def test_deduct_and_idempotent_replay(client, admin_headers, db_session):
    item = _mk_item(client, admin_headers, "画纸", "69300001")
    db_session.add(Inventory(item_id=item["id"], location_id=_hq_id(db_session),
                             qty_on_hand=5, qty_reserved=0, safety_stock=0))
    db_session.commit()

    body = {"barcode": "69300001", "location_code": "HQ", "qty": 2, "sale_ref": "S-1"}
    r = client.post("/api/sales/deduct", headers=admin_headers, json=body)
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert d["duplicated"] is False
    assert d["doc_no"].startswith("OUT-")
    assert d["item_id"] == item["id"]
    assert d["item_name"] == "画纸"
    assert d["location_name"] == "总校办仓库"
    assert d["qty"] == 2
    assert d["qty_after"] == 3

    # 库存流水（doc_type=outbound，issue 领用消耗只减 from）
    mv = db_session.scalar(select(StockMovement).where(
        StockMovement.doc_no == d["doc_no"]))
    assert mv is not None
    assert mv.change_qty == -2 and mv.qty_after == 3 and mv.doc_type == "outbound"
    # 单据已过账、备注带幂等键
    order = db_session.scalar(select(OutboundOrder).where(
        OutboundOrder.doc_no == d["doc_no"]))
    assert order.state == "posted" and order.kind == "issue"
    assert order.remark == "yj销售|S-1"

    # 同 sale_ref 重放：duplicated=true，不二次扣
    r = client.post("/api/sales/deduct", headers=admin_headers, json=body)
    assert r.status_code == 200
    d2 = r.json()["data"]
    assert d2["duplicated"] is True
    assert d2["doc_no"] == d["doc_no"]
    assert d["qty_after"] == 3  # 库存不变
    assert db_session.scalar(select(StockMovement.id).where(
        StockMovement.doc_no == d["doc_no"])) == mv.id

    # check 端点
    r = client.get("/api/sales/deduct/check", headers=admin_headers,
                   params={"sale_ref": "S-1"})
    assert r.json()["data"] == {"deducted": True, "doc_no": d["doc_no"]}
    r = client.get("/api/sales/deduct/check", headers=admin_headers,
                   params={"sale_ref": "S-404"})
    assert r.json()["data"] == {"deducted": False, "doc_no": None}


def test_deduct_errors(client, admin_headers, db_session):
    item = _mk_item(client, admin_headers, "毛毡", "69300011")
    db_session.add(Inventory(item_id=item["id"], location_id=_hq_id(db_session),
                             qty_on_hand=1, qty_reserved=0, safety_stock=0))
    db_session.commit()

    # 库存不足 → 409（中文提示），且不留下单据
    r = client.post("/api/sales/deduct", headers=admin_headers, json={
        "barcode": "69300011", "location_code": "HQ", "qty": 5, "sale_ref": "S-2",
    })
    assert r.status_code == 409
    assert "库存不足" in r.json()["detail"]
    r = client.get("/api/sales/deduct/check", headers=admin_headers,
                   params={"sale_ref": "S-2"})
    assert r.json()["data"]["deducted"] is False

    # 条码未登记 → 404
    r = client.post("/api/sales/deduct", headers=admin_headers, json={
        "barcode": "69999999", "location_code": "HQ", "qty": 1, "sale_ref": "S-3",
    })
    assert r.status_code == 404
    assert "条码未登记" in r.json()["detail"]

    # 库位编码不存在 → 404
    r = client.post("/api/sales/deduct", headers=admin_headers, json={
        "barcode": "69300011", "location_code": "XX", "qty": 1, "sale_ref": "S-4",
    })
    assert r.status_code == 404

    # 停用物品 → 409（用无库存的独立物品）
    retired = _mk_item(client, admin_headers, "旧物品", "69300012")
    r = client.delete(f"/api/items/{retired['id']}", headers=admin_headers)
    assert r.status_code == 200, r.text
    r = client.post("/api/sales/deduct", headers=admin_headers, json={
        "barcode": "69300012", "location_code": "HQ", "qty": 1, "sale_ref": "S-5",
    })
    assert r.status_code == 409

    # 非法条码格式 → 422
    r = client.post("/api/sales/deduct", headers=admin_headers, json={
        "barcode": "abc", "location_code": "HQ", "qty": 1, "sale_ref": "S-6",
    })
    assert r.status_code == 422


def test_catalog(client, admin_headers, db_session):
    item = _mk_item(client, admin_headers, "颜料", "69300021")
    db_session.add(Inventory(item_id=item["id"], location_id=_hq_id(db_session),
                             qty_on_hand=7, qty_reserved=0, safety_stock=0))
    db_session.commit()

    r = client.get("/api/sales/catalog", headers=admin_headers)
    assert r.status_code == 200
    rows = r.json()["data"]
    row = next(x for x in rows if x["item_id"] == item["id"])
    assert row["barcode"] == "69300021"
    assert row["name"] == "颜料"
    assert row["category_name"]
    assert row["stock_by_location"] == {"HQ": 7}
    assert row["total_qty"] == 7

    # q 模糊过滤
    r = client.get("/api/sales/catalog", headers=admin_headers,
                   params={"q": "颜料"})
    assert len(r.json()["data"]) == 1
    r = client.get("/api/sales/catalog", headers=admin_headers,
                   params={"q": "不存在的物品"})
    assert r.json()["data"] == []
