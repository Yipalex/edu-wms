"""去重合并测试（DESIGN §5）：相似分组、十步合并、回滚。"""
from sqlalchemy import select

from app.models import (
    BarcodeHistory, Inventory, Item, ItemAlias, ItemMergeLog, Location,
    OutboundItem, StockMovement,
)


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


def test_duplicates_space_variant(client, admin_headers, db_session):
    """「墨水」/「墨 水」归一化后完全相等 → space_variant 组；无关物品不进组。"""
    a = _mk_item(client, admin_headers, "墨水", "69000001")
    b = _mk_item(client, admin_headers, "墨 水", "69000002")
    _mk_item(client, admin_headers, "铅笔", "69000003")

    r = client.get("/api/items/duplicates", headers=admin_headers)
    assert r.status_code == 200, r.text
    groups = r.json()["data"]
    assert len(groups) == 1
    g = groups[0]
    assert g["match_type"] == "space_variant"
    assert g["confidence"] == 0.99
    assert g["suggested_name"] == "墨水"
    member_ids = {m["id"] for m in g["members"]}
    assert member_ids == {a["id"], b["id"]}
    for m in g["members"]:
        assert "total_qty" in m and "alias_count" in m and "photo_url" in m

    # operator 无权访问
    from tests.conftest import _login  # noqa: PLC0415
    r = client.post("/api/users", headers=admin_headers, json={
        "username": "op_dup", "password": "Op@12345678",
        "display_name": "操作员", "role": "operator",
    })
    op_headers = {"Authorization": f"Bearer {_login(client, 'op_dup', 'Op@12345678')}"}
    r = client.get("/api/items/duplicates", headers=op_headers)
    assert r.status_code == 403


def test_duplicates_fuzzy(client, admin_headers):
    """「墨水」/「蓝墨水」桶内 fuzzy 命中（ratio=0.8 >= 0.7）。"""
    a = _mk_item(client, admin_headers, "墨水", "69000011")
    b = _mk_item(client, admin_headers, "蓝墨水", "69000012")
    r = client.get("/api/items/duplicates", headers=admin_headers)
    groups = r.json()["data"]
    assert len(groups) == 1
    g = groups[0]
    assert g["match_type"] == "fuzzy"
    assert g["confidence"] >= 0.7
    assert {m["id"] for m in g["members"]} == {a["id"], b["id"]}


def _setup_merge(client, admin_headers, db_session):
    keeper = _mk_item(client, admin_headers, "墨水", "69100001")
    m1 = _mk_item(client, admin_headers, "墨 水", "69100002")
    m2 = _mk_item(client, admin_headers, "蓝墨水", "69100003")
    hq = _hq_id(db_session)
    jc = db_session.scalar(select(Location.id).where(Location.code == "JC"))

    # 直接造库存行（保留项 HQ=10/JC=5；m1 HQ=3；m2 JC=2）
    for item_id, loc_id, qty in ((keeper["id"], hq, 10), (keeper["id"], jc, 5),
                                 (m1["id"], hq, 3), (m2["id"], jc, 2)):
        db_session.add(Inventory(item_id=item_id, location_id=loc_id,
                                 qty_on_hand=qty, qty_reserved=0, safety_stock=0))
    db_session.commit()

    # 给 m1 一张已过账入库单（产生 stock_movements 行，验证第⑤步改指）
    r = client.post("/api/inbound-orders", headers=admin_headers, json={
        "location_id": hq, "items": [{"item_id": m1["id"], "qty": 1}],
    })
    assert r.status_code == 200, r.text
    inb_id = r.json()["data"]["id"]
    r = client.post(f"/api/inbound-orders/{inb_id}/post", headers=admin_headers)
    assert r.status_code == 200, r.text

    # 给 m2 一张草稿出库单（产生 outbound_items 行，验证第④步改指）
    r = client.post("/api/outbound-orders", headers=admin_headers, json={
        "kind": "issue", "from_location_id": jc,
        "items": [{"item_id": m2["id"], "qty": 1}],
    })
    assert r.status_code == 200, r.text
    return keeper, m1, m2, hq, jc


def test_merge_and_rollback(client, admin_headers, db_session):
    keeper, m1, m2, hq, jc = _setup_merge(client, admin_headers, db_session)

    r = client.post(f"/api/items/{keeper['id']}/merge", headers=admin_headers,
                    json={"merged_ids": [m1["id"], m2["id"]], "reason": "测试合并"})
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["keeper_id"] == keeper["id"]
    assert data["merged_ids"] == [m1["id"], m2["id"]]
    assert len(data["log_ids"]) == 2
    assert "2 个物品" in data["message"]

    # 库存并入：keeper HQ 10+3+1(入库过账)=14，JC 5+2=7；merged 行已删除
    def qty(item_id, loc_id):
        return db_session.scalar(
            select(Inventory.qty_on_hand).where(
                Inventory.item_id == item_id, Inventory.location_id == loc_id)) or 0

    assert qty(keeper["id"], hq) == 14
    assert qty(keeper["id"], jc) == 7
    assert db_session.scalar(select(Inventory.id).where(
        Inventory.item_id == m1["id"])) is None

    # 单据行与流水改指 keeper
    assert db_session.scalar(select(OutboundItem.item_id).where(
        OutboundItem.item_id == keeper["id"])) is not None
    mov = db_session.scalar(select(StockMovement).where(
        StockMovement.doc_type == "inbound"))
    assert mov.item_id == keeper["id"]
    # 合并产生的 adjust 流水（doc_type='adjust'，note=合并自 ...）
    adj = db_session.scalars(select(StockMovement).where(
        StockMovement.doc_type == "adjust")).all()
    assert len(adj) >= 2
    assert any("合并自" in (m.note or "") for m in adj)

    # merged 状态 / 条码置空 / 名称前缀 / 指向 keeper
    for mid, old_code in ((m1["id"], "69100002"), (m2["id"], "69100003")):
        item = db_session.get(Item, mid)
        assert item.status == "merged"
        assert item.merged_into_id == keeper["id"]
        assert item.barcode is None
        assert item.name.startswith("[已合并] ")
        # 条码退役历史（码不释放）
        hist = db_session.scalar(select(BarcodeHistory).where(
            BarcodeHistory.old_barcode == old_code,
            BarcodeHistory.change_type == "merge_retire"))
        assert hist is not None
        assert hist.new_barcode == "69100001"

    # 别名：merged 的 name 与 barcode 挂到 keeper（source='merge'）
    aliases = {a.alias: a.source for a in db_session.scalars(select(ItemAlias).where(
        ItemAlias.item_id == keeper["id"]))}
    assert aliases.get("墨 水") == "merge"
    assert aliases.get("69100002") == "merge"
    assert aliases.get("蓝墨水") == "merge"

    # 合并记录
    logs = db_session.scalars(select(ItemMergeLog).order_by(ItemMergeLog.id)).all()
    assert len(logs) == 2
    r = client.get("/api/items/merges", headers=admin_headers)
    assert r.status_code == 200
    rows = r.json()["data"]
    assert len(rows) == 2
    assert rows[0]["keeper_name"] == "墨水"
    assert rows[0]["operator_name"] == "系统管理员"
    assert rows[0]["merged_barcode"] in ("69100002", "69100003")

    # 回滚
    for log_id in data["log_ids"]:
        r = client.post(f"/api/items/merges/{log_id}/rollback", headers=admin_headers)
        assert r.status_code == 200, r.text
    # 重复回滚 → 409
    r = client.post(f"/api/items/merges/{data['log_ids'][0]}/rollback",
                    headers=admin_headers)
    assert r.status_code == 409

    # 复原校验
    assert qty(keeper["id"], hq) == 10
    assert qty(keeper["id"], jc) == 5
    assert qty(m1["id"], hq) == 4  # 3 + 1（入库过账）
    assert qty(m2["id"], jc) == 2
    for mid, name, code in ((m1["id"], "墨 水", "69100002"),
                            (m2["id"], "蓝墨水", "69100003")):
        item = db_session.get(Item, mid)
        assert item.status == "active"
        assert item.merged_into_id is None
        assert item.barcode == code
        assert item.name == name
    assert db_session.scalar(select(ItemAlias.id).where(
        ItemAlias.item_id == keeper["id"], ItemAlias.source == "merge")) is None
    mov = db_session.scalar(select(StockMovement).where(
        StockMovement.doc_type == "inbound"))
    assert mov.item_id == m1["id"]
    out_line = db_session.scalar(select(OutboundItem))
    assert out_line.item_id == m2["id"]


def test_merge_guards(client, admin_headers, db_session):
    keeper = _mk_item(client, admin_headers, "墨水", "69200001")
    other = _mk_item(client, admin_headers, "墨 水", "69200002")

    # 自合并 → 400
    r = client.post(f"/api/items/{keeper['id']}/merge", headers=admin_headers,
                    json={"merged_ids": [keeper["id"]], "reason": ""})
    assert r.status_code == 400
    # 空列表 → 422（pydantic min_length）
    r = client.post(f"/api/items/{keeper['id']}/merge", headers=admin_headers,
                    json={"merged_ids": [], "reason": ""})
    assert r.status_code == 422
    # 不存在 → 404
    r = client.post(f"/api/items/{keeper['id']}/merge", headers=admin_headers,
                    json={"merged_ids": [999999], "reason": ""})
    assert r.status_code == 404
    # 合并后再把 keeper 合并走 → keeper 非 active 409
    r = client.post(f"/api/items/{keeper['id']}/merge", headers=admin_headers,
                    json={"merged_ids": [other["id"]], "reason": "先合并"})
    assert r.status_code == 200, r.text
    log_id = r.json()["data"]["log_ids"][0]
    # keeper 仍 active：回滚成功；再把 keeper 自身合并到别人 → 回滚守卫 409
    third = _mk_item(client, admin_headers, "蓝墨水", "69200003")
    r = client.post(f"/api/items/{third['id']}/merge", headers=admin_headers,
                    json={"merged_ids": [keeper["id"]], "reason": "keeper 被合并走"})
    assert r.status_code == 200, r.text
    r = client.post(f"/api/items/merges/{log_id}/rollback", headers=admin_headers)
    assert r.status_code == 409
    assert "不是正常状态" in r.json()["detail"]
