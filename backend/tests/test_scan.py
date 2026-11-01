"""扫码解析测试（DESIGN §4 四级解析）。"""


def _mk_item(client, headers, **kw):
    payload = {"name": "测试物品", "category_id": 1, **kw}
    r = client.post("/api/items", headers=headers, json=payload)
    assert r.status_code == 200, r.text
    return r.json()["data"]


def test_resolve_hit_active(client, admin_headers, db_session):
    from app.models import Inventory
    d = _mk_item(client, admin_headers, name="实用性书写教材下", barcode="21010013")
    db_session.add(Inventory(item_id=d["id"], location_id=1, qty_on_hand=708))
    db_session.commit()

    r = client.get("/api/scan/resolve", headers=admin_headers, params={"code": "21010013"})
    assert r.status_code == 200
    body = r.json()["data"]
    assert body["resolved"] is True
    assert body["code_type"] == "internal"
    assert body["item"]["name"] == "实用性书写教材下"
    assert body["item"]["category"] == "教材"
    assert body["total_qty"] == 708
    assert body["inventory"][0]["location_name"] == "总校办仓库"
    assert body["hint"] is None


def test_resolve_external_code_type(client, admin_headers):
    _mk_item(client, admin_headers, name="北太墨汁", category_id=4, barcode="6950898000191")
    r = client.get("/api/scan/resolve", headers=admin_headers, params={"code": "6950898000191"})
    body = r.json()["data"]
    assert body["resolved"] is True
    assert body["code_type"] == "external"


def test_resolve_merged_redirect(client, admin_headers, db_session):
    keeper = _mk_item(client, admin_headers, name="保留物品", category_id=3, barcode="21030200")
    merged = _mk_item(client, admin_headers, name="被合并物品", category_id=3, barcode="21030201")
    # 直接改库模拟合并后状态（status=merged + merged_into_id，契约要求两者一致）
    from app.models import Item
    m = db_session.get(Item, merged["id"])
    m.status = "merged"
    m.merged_into_id = keeper["id"]
    m.barcode = None   # 唯一索引让位（契约 §5.2 第 9 步）
    db_session.commit()
    # 合并退役历史：旧码 → 保留项新码
    from app.models import BarcodeHistory
    db_session.add(BarcodeHistory(
        item_id=merged["id"], old_barcode="21030201", new_barcode="21030200",
        change_type="merge_retire", reason="合并",
    ))
    db_session.commit()

    r = client.get("/api/scan/resolve", headers=admin_headers, params={"code": "21030201"})
    body = r.json()["data"]
    # barcode 已置 NULL，走历史溯源分支
    assert body["resolved"] is False
    assert "21030200" in body["hint"]


def test_resolve_reassigned_old_code(client, admin_headers):
    d = _mk_item(client, admin_headers, name="重分配测试", category_id=5, barcode="21050050")
    r = client.post(f"/api/items/{d['id']}/reassign-barcode", headers=admin_headers,
                    json={"reason": "换标签"})
    assert r.status_code == 200
    # 扫旧码 → 停用溯源提示
    r2 = client.get("/api/scan/resolve", headers=admin_headers, params={"code": "21050050"})
    body = r2.json()["data"]
    assert body["resolved"] is False
    assert "已停用" in body["hint"]
    assert "重分配" in body["hint"]
    # 扫新码 → 命中
    r3 = client.get("/api/scan/resolve", headers=admin_headers, params={"code": "21050011"})
    assert r3.json()["data"]["resolved"] is True


def test_resolve_retired(client, admin_headers):
    d = _mk_item(client, admin_headers, name="待停用", barcode="21010090")
    r = client.delete(f"/api/items/{d['id']}", headers=admin_headers)
    assert r.status_code == 200
    r2 = client.get("/api/scan/resolve", headers=admin_headers, params={"code": "21010090"})
    body = r2.json()["data"]
    assert body["resolved"] is False
    assert "停用" in body["hint"]


def test_resolve_unknown(client, admin_headers):
    r = client.get("/api/scan/resolve", headers=admin_headers, params={"code": "21090999"})
    body = r.json()["data"]
    assert body["resolved"] is False
    assert body["hint"] == "未登记的条码"
    assert body["item"] is None


def test_resolve_requires_auth(client):
    r = client.get("/api/scan/resolve", params={"code": "21010001"})
    assert r.status_code == 401
