"""彻底删除物品档案（superadmin）测试。

覆盖：
- 权限：operator / admin 均不可用；仅 superadmin 可用
- 二次确认：confirm_name 不匹配 → 400
- 有库存 + 有流水 + 有已过账单据的物品 → 可彻底删除
- 删除后：items 表无该行、条码释放、库存归零、流水保留、单据明细保留且快照完好
- 归档表记录正确
- 恢复：物品回到名录、条码回到档案、引用行改回

注：不依赖 conftest 的 admin 账号（容器 ADMIN_INIT_USERNAME 是手机号），
测试内直接建库内用户。
"""
import pytest
from sqlalchemy import select

from app.models import (
    BarcodeHistory, Category, DeletedItem, InboundItem, Inventory, Item, ItemPhoto,
    OutboundItem, StockMovement, User,
)
from app.security import hash_password


def _mk_user(db_session, username, role, password="Test@2026"):
    u = User(username=username, password_hash=hash_password(password),
             display_name=username, role=role, is_active=True)
    db_session.add(u)
    db_session.commit()
    return u


def _headers(client, username, password="Test@2026"):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['data']['access_token']}"}


@pytest.fixture()
def roles(client, db_session):
    """建三个角色用户，返回各自的请求头。"""
    _mk_user(db_session, "boss1", "superadmin")
    _mk_user(db_session, "adm1", "admin")
    _mk_user(db_session, "op1", "operator")
    return {
        "superadmin": _headers(client, "boss1"),
        "admin": _headers(client, "adm1"),
        "operator": _headers(client, "op1"),
    }


@pytest.fixture()
def messy_item(db_session):
    """造一个「库存乱填 + 有流水 + 有已过账入库单 + 照片 + 条码历史」的物品。"""
    from app.models import InboundOrder, Location
    # 复用 seed 建好的类目（categories.digit 唯一，不能自己造）
    cat = db_session.scalar(select(Category).limit(1))
    assert cat is not None, "seed 未创建类目"
    loc = db_session.scalar(select(Location).limit(1))
    assert loc is not None, "seed 未创建库位"
    order = InboundOrder(doc_no="IN-TEST-0001", supplier="测试供应商",
                          location_id=loc.id, state="posted", total_amount=50)
    db_session.add(order)
    db_session.flush()
    it = Item(barcode="21019999", name="乱填库存测试物品", category_id=cat.id,
              spec="", unit="件", need_label=True, print_mode="label",
              status="active", barcode_origin="internal", remark="测试")
    db_session.add(it)
    db_session.flush()
    db_session.add(Inventory(item_id=it.id, location_id=loc.id, qty_on_hand=888,
                              qty_reserved=0, safety_stock=0))
    db_session.add(StockMovement(item_id=it.id, location_id=loc.id, change_qty=888,
                                  qty_before=0, qty_after=888, doc_type="adjust",
                                  doc_id=None, doc_no="TEST-1", operator_id=None, note="乱填"))
    db_session.add(InboundItem(order_id=order.id, item_id=it.id, barcode_snapshot="21019999",
                                name_snapshot="乱填库存测试物品", spec_snapshot="",
                                qty=5, purchase_price=10, sale_price=20, sort_order=0))
    db_session.add(ItemPhoto(item_id=it.id, file_path="a/b.jpg", file_size=1,
                              sort_order=0, is_primary=True, source="upload"))
    db_session.add(BarcodeHistory(item_id=it.id, old_barcode=None, new_barcode="21019999",
                                  change_type="assign", reason="测试"))
    db_session.commit()
    return {"id": it.id, "name": "乱填库存测试物品", "barcode": "21019999"}


# ---------- 权限 ----------

def test_operator_cannot_purge(client, roles, messy_item):
    r = client.post(f"/api/items/{messy_item['id']}/purge", headers=roles["operator"],
                      json={"confirm_name": messy_item["name"]})
    assert r.status_code == 403, r.text


def test_admin_cannot_purge(client, roles, messy_item):
    r = client.post(f"/api/items/{messy_item['id']}/purge", headers=roles["admin"],
                      json={"confirm_name": messy_item["name"]})
    assert r.status_code == 403, r.text


def test_confirm_name_mismatch(client, roles, messy_item):
    r = client.post(f"/api/items/{messy_item['id']}/purge", headers=roles["superadmin"],
                      json={"confirm_name": "写错的名称"})
    assert r.status_code == 400, r.text
    assert "确认名称不匹配" in r.text


# ---------- 彻底删除 ----------

def test_purge_removes_item_and_keeps_history(client, db_session, roles, messy_item):
    item_id = messy_item["id"]
    r = client.post(f"/api/items/{item_id}/purge", headers=roles["superadmin"],
                      json={"confirm_name": messy_item["name"], "reason": "库存乱填，作废"})
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["deleted"]["name"] == messy_item["name"]
    impact = data["impact"]
    assert impact["stock_rows"] == 1
    assert impact["stock_qty"] == 888
    assert impact["movements"] == 1
    assert impact["inbound_lines"] == 1
    assert impact["photos"] == 1

    # 物品行真的没了
    assert db_session.get(Item, item_id) is None

    # 归档表记录正确
    arch = db_session.get(DeletedItem, data["deleted"]["archive_id"])
    assert arch is not None and arch.barcode == "21019999"
    assert arch.reason == "库存乱填，作废"
    assert arch.operator_name == "boss1"

    # 库存行保留但归零（行改指占位档案——物品已从名录移除）
    ph_id = data["deleted"]["placeholder_item_id"]
    inv = db_session.scalars(select(Inventory).where(Inventory.item_id == ph_id)).all()
    assert len(inv) == 1 and inv[0].qty_on_hand == 0

    # 单据明细保留，快照完好
    lines = db_session.scalars(select(InboundItem).where(InboundItem.item_id == ph_id)).all()
    assert len(lines) == 1
    assert lines[0].name_snapshot == "乱填库存测试物品"
    assert lines[0].barcode_snapshot == "21019999"
    assert lines[0].qty == 5


def test_purge_keeps_movements_and_repoints(client, db_session, roles, messy_item):
    """流水/单据/照片改指占位档案，数据本身不丢。"""
    item_id = messy_item["id"]
    r = client.post(f"/api/items/{item_id}/purge", headers=roles["superadmin"],
                      json={"confirm_name": messy_item["name"]})
    assert r.status_code == 200, r.text
    ph_id = r.json()["data"]["deleted"]["placeholder_item_id"]

    ph = db_session.get(Item, ph_id)
    assert ph is not None and ph.status == "retired" and ph.barcode is None
    assert ph.name.startswith("【已删除物品】")

    # 流水保留（只是改指占位档案）
    movs = db_session.scalars(select(StockMovement).where(StockMovement.item_id == ph_id)).all()
    assert len(movs) == 1
    assert movs[0].qty_after == 888
    assert movs[0].note == "乱填"

    # 入库单明细保留
    lines = db_session.scalars(select(InboundItem).where(InboundItem.item_id == ph_id)).all()
    assert len(lines) == 1 and lines[0].qty == 5

    # 照片保留
    photos = db_session.scalars(select(ItemPhoto).where(ItemPhoto.item_id == ph_id)).all()
    assert len(photos) == 1

    # 条码历史保留
    hist = db_session.scalars(select(BarcodeHistory).where(BarcodeHistory.item_id == ph_id)).all()
    assert len(hist) == 1


def test_purged_item_gone_from_list(client, roles, messy_item):
    client.post(f"/api/items/{messy_item['id']}/purge", headers=roles["superadmin"],
                  json={"confirm_name": messy_item["name"]})
    r = client.get("/api/items", headers=roles["superadmin"],
                   params={"q": messy_item["name"], "page_size": 50})
    assert r.status_code == 200, r.text
    names = [x["name"] for x in r.json()["data"]]
    assert messy_item["name"] not in names


def test_deleted_list_and_restore(client, db_session, roles, messy_item):
    item_id = messy_item["id"]
    client.post(f"/api/items/{item_id}/purge", headers=roles["superadmin"],
                  json={"confirm_name": messy_item["name"], "reason": "作废"})
    r = client.get("/api/items/deleted/list", headers=roles["superadmin"])
    assert r.status_code == 200, r.text
    rows = r.json()["data"]
    assert len(rows) == 1
    assert rows[0]["name"] == messy_item["name"]
    assert rows[0]["restored_at"] is None
    archive_id = rows[0]["id"]

    # 恢复
    rr = client.post(f"/api/items/deleted/{archive_id}/restore",
                     headers=roles["superadmin"], json={})
    assert rr.status_code == 200, rr.text
    restored = rr.json()["data"]["restored"]
    assert restored["name"] == messy_item["name"]
    assert restored["barcode"] == "21019999"

    # 物品回到名录
    again = client.get("/api/items", headers=roles["superadmin"],
                       params={"q": messy_item["name"], "page_size": 50})
    names = [x["name"] for x in again.json()["data"]]
    assert messy_item["name"] in names

    # 引用行改回新物品
    new_id = restored["item_id"]
    movs = db_session.scalars(select(StockMovement).where(StockMovement.item_id == new_id)).all()
    assert len(movs) == 1
    lines = db_session.scalars(select(InboundItem).where(InboundItem.item_id == new_id)).all()
    assert len(lines) == 1


def test_deleted_list_requires_superadmin(client, roles):
    r = client.get("/api/items/deleted/list", headers=roles["admin"])
    assert r.status_code == 403, r.text


def test_restore_requires_superadmin(client, roles, messy_item):
    client.post(f"/api/items/{messy_item['id']}/purge", headers=roles["superadmin"],
                  json={"confirm_name": messy_item["name"]})
    r = client.post("/api/items/deleted/1/restore", headers=roles["admin"], json={})
    assert r.status_code == 403, r.text
