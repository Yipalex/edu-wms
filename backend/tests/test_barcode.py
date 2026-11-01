"""条码引擎与条码路由测试（编码规则、连续性、防重、重分配、历史）。"""
import pytest

from app.models import BarcodeRule
from app.services import barcode as bc


@pytest.fixture()
def rule(db_session) -> BarcodeRule:
    return bc.get_rule(db_session)


# ---------- 引擎单元 ----------

def test_build_code():
    assert bc.build_code("2", "10", "1", 1) == "21010001"
    assert bc.build_code("2", "10", "4", 55, 4) == "21040055"


def test_build_code_seq_overflow():
    with pytest.raises(bc.BizError):
        bc.build_code("2", "10", "1", 10000, 4)


def test_parse_internal(rule):
    p = bc.parse_code("21010013", rule)
    assert p.is_internal and p.prefix == "2" and p.region == "10"
    assert p.category_digit == "1" and p.seq == 13


def test_parse_external(rule):
    p = bc.parse_code("6950898000191", rule)
    assert p.is_internal is False


def test_is_valid(rule):
    assert bc.is_valid("21010001", rule)[0]
    assert bc.is_valid("6950898000191", rule)[0]           # 外部码 8~14 纯数字
    assert not bc.is_valid("2101001", rule)[0]              # 7 位太短
    assert not bc.is_valid("210100001234567", rule)[0]      # 15 位太长
    assert not bc.is_valid("2101000A", rule)[0]             # 含字母
    # 8 位、以 2 开头但地区码不是 10 → 非法
    assert not bc.is_valid("29910001", rule)[0]


def test_allocate_sequential(db_session):
    """教材 next_seq=33 → 连续两个码 21010033/21010034，不重复。"""
    codes = bc.allocate(db_session, 1, 2)
    assert codes == ["21010033", "21010034"]
    db_session.commit()
    # 再分配接着走
    codes2 = bc.allocate(db_session, 1, 1)
    assert codes2 == ["21010035"]
    db_session.commit()


def test_preview_does_not_consume(db_session):
    codes = bc.preview_next(db_session, 1)
    assert codes == ["21010033"]
    db_session.commit()
    # preview 之后 allocate 仍从 33 开始
    assert bc.allocate(db_session, 1, 1) == ["21010033"]
    db_session.commit()


def test_allocate_conflict_with_existing_item(db_session):
    """存量物品占了 21010033 → 分配自动推进到 34。"""
    from app.models import Item
    db_session.add(Item(name="占位教材", category_id=1, barcode="21010033",
                        barcode_origin="internal", status="active"))
    db_session.commit()
    codes = bc.allocate(db_session, 1, 1)
    assert codes == ["21010034"]
    db_session.commit()


# ---------- API ----------

def test_get_barcode_rules(client, admin_headers):
    r = client.get("/api/barcode-rules", headers=admin_headers)
    assert r.status_code == 200
    data = r.json()["data"]
    assert data == {**data, "prefix": "2", "region_code": "10",
                    "seq_width": 4, "total_length": 8, "allow_external": True}


def test_update_barcode_rules_requires_numeric(client, admin_headers):
    r = client.put("/api/barcode-rules", headers=admin_headers, json={
        "prefix": "A2", "region_code": "10", "seq_width": 4,
        "total_length": 8, "allow_external": True,
    })
    assert r.status_code == 422   # pydantic pattern 拒绝非数字


def test_update_barcode_rules_ok(client, admin_headers):
    r = client.put("/api/barcode-rules", headers=admin_headers, json={
        "prefix": "2", "region_code": "20", "seq_width": 4,
        "total_length": 8, "allow_external": True,
    })
    assert r.status_code == 200
    assert r.json()["data"]["region_code"] == "20"


def test_preview_api(client, admin_headers):
    r = client.post("/api/barcode/preview", headers=admin_headers,
                    json={"category_id": 4, "count": 3})
    assert r.status_code == 200
    # 耗材 next_seq=56 → 21040056..58
    assert r.json()["data"]["codes"] == ["21040056", "21040057", "21040058"]


def test_allocate_for_item_api(client, admin_headers):
    # 建一个待编码物品（书籍类 id=2, next_seq=1）
    r = client.post("/api/items", headers=admin_headers,
                    json={"name": "测试书籍", "category_id": 2})
    assert r.status_code == 200
    item_id = r.json()["data"]["id"]
    assert r.json()["data"]["barcode"] is None

    r2 = client.post("/api/barcode/allocate", headers=admin_headers,
                     json={"item_id": item_id})
    assert r2.status_code == 200
    assert r2.json()["data"]["codes"] == ["21020001"]

    r3 = client.get(f"/api/items/{item_id}", headers=admin_headers)
    assert r3.json()["data"]["barcode"] == "21020001"
    assert r3.json()["data"]["barcode_origin"] == "internal"


def test_allocate_twice_rejected(client, admin_headers):
    r = client.post("/api/items", headers=admin_headers,
                    json={"name": "书籍A", "category_id": 2, "barcode": "21020099"})
    assert r.status_code == 200
    item_id = r.json()["data"]["id"]
    # 已有条码再分配 → 409
    r2 = client.post("/api/barcode/allocate", headers=admin_headers, json={"item_id": item_id})
    assert r2.status_code == 409


def test_duplicate_barcode_rejected(client, admin_headers):
    r1 = client.post("/api/items", headers=admin_headers,
                     json={"name": "耗材A", "category_id": 4, "barcode": "21040001"})
    assert r1.status_code == 200
    r2 = client.post("/api/items", headers=admin_headers,
                     json={"name": "耗材B", "category_id": 4, "barcode": "21040001"})
    assert r2.status_code == 409
    assert r2.json()["code"] == "ERR_BARCODE_DUP"


def test_barcode_category_digit_mismatch(client, admin_headers):
    # 21010088 分类位=1（教材），却挂到书籍类（digit=2）→ 400
    r = client.post("/api/items", headers=admin_headers,
                    json={"name": "错位物品", "category_id": 2, "barcode": "21010088"})
    assert r.status_code == 400
    assert r.json()["code"] == "ERR_BARCODE_CAT_MISMATCH"
    assert "分类位" in r.json()["detail"]


def test_reassign_and_history(client, admin_headers):
    r = client.post("/api/items", headers=admin_headers,
                    json={"name": "礼品X", "category_id": 5, "barcode": "21050001"})
    item_id = r.json()["data"]["id"]
    # 重分配（自动新码；礼品 next_seq=11）
    r2 = client.post(f"/api/items/{item_id}/reassign-barcode", headers=admin_headers,
                     json={"reason": "标签破损"})
    assert r2.status_code == 200
    d = r2.json()["data"]
    assert d["old_barcode"] == "21050001"
    assert d["new_barcode"] == "21050011"
    # 历史有 reassign 记录
    r3 = client.get(f"/api/items/{item_id}/barcode-history", headers=admin_headers)
    hist = r3.json()["data"]
    assert any(h["change_type"] == "reassign" and h["old_barcode"] == "21050001"
               and h["new_barcode"] == "21050011" and h["reason"] == "标签破损" for h in hist)
    # 旧码可在全局历史中查到（且旧码不释放：不能给新物品用）
    r4 = client.get("/api/barcode/history", headers=admin_headers, params={"change_type": "reassign"})
    assert r4.status_code == 200
    assert r4.json()["meta"]["total"] >= 1


def test_reassign_requires_reason(client, admin_headers):
    r = client.post("/api/items", headers=admin_headers,
                    json={"name": "礼品Y", "category_id": 5})
    item_id = r.json()["data"]["id"]
    r2 = client.post(f"/api/items/{item_id}/reassign-barcode", headers=admin_headers, json={})
    assert r2.status_code == 422


def test_operator_can_allocate_but_not_reassign(client, admin_headers, operator_headers):
    r = client.post("/api/items", headers=admin_headers,
                    json={"name": "其他Z", "category_id": 6})
    item_id = r.json()["data"]["id"]
    # operator 可分配（AO）
    r2 = client.post("/api/barcode/allocate", headers=operator_headers, json={"item_id": item_id})
    assert r2.status_code == 200
    # operator 不可重分配（A）
    r3 = client.post(f"/api/items/{item_id}/reassign-barcode", headers=operator_headers,
                     json={"reason": "试图改码"})
    assert r3.status_code == 403
    # operator 不可查全局历史（A）
    r4 = client.get("/api/barcode/history", headers=operator_headers)
    assert r4.status_code == 403


def test_category_digit_change_needs_confirm(client, admin_headers):
    # 类目列表拿一个 id
    r = client.get("/api/categories", headers=admin_headers)
    cat_id = next(c["id"] for c in r.json()["data"] if c["digit"] == "9")
    r2 = client.patch(f"/api/categories/{cat_id}", headers=admin_headers, json={"digit": "8"})
    assert r2.status_code == 400
    body = r2.json()
    assert body["code"] == "ERR_DIGIT_CONFIRM_REQUIRED"
    assert body["detail"] == "修改分类位会影响后续新条码构成，请确认后重试"
    # 带确认参数则成功
    r3 = client.patch(f"/api/categories/{cat_id}", headers=admin_headers,
                      params={"confirm_digit": "true"}, json={"digit": "8"})
    assert r3.status_code == 200
    assert r3.json()["data"]["digit"] == "8"
