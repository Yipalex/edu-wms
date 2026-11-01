"""物品档案测试：CRUD、搜索筛选、软删保护、照片上传、别名、批量导入。"""
import io

from app.models import Inventory


def _mk_item(client, headers, **kw):
    payload = {"name": "测试物品", "category_id": 1, **kw}
    r = client.post("/api/items", headers=headers, json=payload)
    assert r.status_code == 200, r.text
    return r.json()["data"]


def test_create_item_without_barcode(client, admin_headers):
    d = _mk_item(client, admin_headers, name="待编码教材")
    assert d["barcode"] is None
    assert d["status"] == "active"


def test_create_item_with_external_barcode(client, admin_headers):
    d = _mk_item(client, admin_headers, name="北太墨汁", category_id=4,
                 barcode="6950898000191")
    assert d["barcode_origin"] == "external"


def test_create_item_bad_barcode(client, admin_headers):
    r = client.post("/api/items", headers=admin_headers,
                    json={"name": "坏码", "category_id": 1, "barcode": "abc123"})
    assert r.status_code == 400
    assert r.json()["code"] == "ERR_BAD_BARCODE"


def test_get_item_detail(client, admin_headers):
    d = _mk_item(client, admin_headers, name="详情教材", barcode="21010050")
    r = client.get(f"/api/items/{d['id']}", headers=admin_headers)
    assert r.status_code == 200
    body = r.json()["data"]
    assert body["name"] == "详情教材"
    assert "photos" in body and "inventory" in body and "barcode_history" in body


def test_list_search_and_filters(client, admin_headers):
    _mk_item(client, admin_headers, name="毛笔大号", category_id=4, barcode="21040060")
    _mk_item(client, admin_headers, name="墨汁小瓶", category_id=4, barcode="21040061")
    # q 搜名称
    r = client.get("/api/items", headers=admin_headers, params={"q": "毛笔"})
    assert r.json()["meta"]["total"] == 1
    # q 搜条码
    r2 = client.get("/api/items", headers=admin_headers, params={"q": "21040061"})
    assert r2.json()["meta"]["total"] == 1
    # category 筛选
    r3 = client.get("/api/items", headers=admin_headers, params={"category_id": 4})
    assert r3.json()["meta"]["total"] >= 2
    # 分页 meta
    assert r3.json()["meta"]["page"] == 1 and r3.json()["meta"]["page_size"] == 20


def test_list_search_by_alias(client, admin_headers):
    d = _mk_item(client, admin_headers, name="泽曦定制书包", category_id=5)
    r = client.post(f"/api/items/{d['id']}/aliases", headers=admin_headers,
                    json={"alias": "双肩包", "source": "migration"})
    assert r.status_code == 200
    r2 = client.get("/api/items", headers=admin_headers, params={"q": "双肩包"})
    assert r2.json()["meta"]["total"] == 1
    assert r2.json()["data"][0]["id"] == d["id"]


def test_patch_item(client, admin_headers):
    d = _mk_item(client, admin_headers, name="旧名称")
    r = client.patch(f"/api/items/{d['id']}", headers=admin_headers,
                     json={"name": "新名称", "spec": "大号", "suggest_price": 5.7})
    assert r.status_code == 200
    body = r.json()["data"]
    assert body["name"] == "新名称" and body["spec"] == "大号"
    assert body["suggest_price"] == 5.7


def test_delete_item_soft(client, admin_headers):
    d = _mk_item(client, admin_headers, name="待删物品")
    r = client.delete(f"/api/items/{d['id']}", headers=admin_headers)
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "retired"


def test_delete_item_blocked_by_stock(client, admin_headers, db_session):
    d = _mk_item(client, admin_headers, name="有库存物品", barcode="21010070")
    loc = 1
    db_session.add(Inventory(item_id=d["id"], location_id=loc, qty_on_hand=5))
    db_session.commit()
    r = client.delete(f"/api/items/{d['id']}", headers=admin_headers)
    assert r.status_code == 409
    assert r.json()["code"] == "ERR_ITEM_HAS_STOCK"
    assert "库存" in r.json()["detail"]


def test_delete_requires_admin(client, admin_headers, operator_headers):
    d = _mk_item(client, admin_headers, name="权限测试物品")
    r = client.delete(f"/api/items/{d['id']}", headers=operator_headers)
    assert r.status_code == 403


def test_upload_photo_and_delete(client, admin_headers):
    d = _mk_item(client, admin_headers, name="带照片物品")
    # 带 PNG 魔数的测试字节流（上传接口只校验扩展名/MIME/大小，不做像素级校验）
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
    r = client.post(f"/api/items/{d['id']}/photos", headers=admin_headers,
                    files={"file": ("test.png", io.BytesIO(png), "image/png")})
    assert r.status_code == 200, r.text
    photo = r.json()["data"]
    assert photo["url"].startswith("/api/uploads/items/")
    assert photo["is_primary"] is True

    # 列表 has_photo 筛选
    r2 = client.get("/api/items", headers=admin_headers, params={"has_photo": "true"})
    assert any(i["id"] == d["id"] for i in r2.json()["data"])

    # 照片可访问
    r3 = client.get(photo["url"].replace("/api/uploads/", "/api/uploads/"))
    assert r3.status_code == 200

    # 非图片被拒
    r4 = client.post(f"/api/items/{d['id']}/photos", headers=admin_headers,
                     files={"file": ("evil.exe", io.BytesIO(b"MZ..."), "application/octet-stream")})
    assert r4.status_code == 400
    assert r4.json()["code"] == "ERR_BAD_FILE_TYPE"

    # 删除照片
    r5 = client.delete(f"/api/items/{d['id']}/photos/{photo['id']}", headers=admin_headers)
    assert r5.status_code == 200


def test_upload_path_traversal_blocked(client, admin_headers):
    r = client.get("/api/uploads/../../app/config.py")
    assert r.status_code in (400, 404)


def test_batch_import_xlsx(client, admin_headers):
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.append(["条码号", "物品名称", "分类", "规格", "建议售价", "印刷方式"])
    ws.append(["21030100", "练习本A", "辅材", "16开", 5.5, "贴标"])
    ws.append(["", "待编码新书", "书籍", "", "", "扫码卡"])
    ws.append(["21030100", "重复码行", "辅材", "", "", "贴标"])
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    r = client.post("/api/items/batch", headers=admin_headers,
                    files={"file": ("items.xlsx", buf, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert d["created_count"] == 2
    assert d["skipped_count"] == 1   # 重复条码行被幂等跳过
    assert d["error_count"] == 0


def test_batch_import_csv_bad_category(client, admin_headers):
    csv_text = "条码号,物品名称,分类\n21090001,测试,不存在的类\n"
    r = client.post("/api/items/batch", headers=admin_headers,
                    files={"file": ("items.csv", io.BytesIO(csv_text.encode("utf-8")), "text/csv")})
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["error_count"] == 1
    assert "分类" in d["errors"][0]["error"]


def test_batch_requires_admin(client, operator_headers):
    csv_text = "物品名称\n测试\n"
    r = client.post("/api/items/batch", headers=operator_headers,
                    files={"file": ("i.csv", io.BytesIO(csv_text.encode("utf-8")), "text/csv")})
    assert r.status_code == 403
