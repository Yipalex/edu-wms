"""认证与权限测试。"""


def test_login_success(client):
    r = client.post("/api/auth/login", json={"username": "admin", "password": "Test@2026"})
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["access_token"] and data["refresh_token"]
    assert data["user"]["username"] == "admin"
    assert data["user"]["role"] == "admin"


def test_login_wrong_password(client):
    r = client.post("/api/auth/login", json={"username": "admin", "password": "wrong-pass"})
    assert r.status_code == 401
    body = r.json()
    assert body["code"] == "ERR_BAD_CREDENTIALS"
    assert "用户名或密码错误" in body["detail"]


def test_me_requires_token(client):
    r = client.get("/api/auth/me")
    assert r.status_code == 401
    assert r.json()["code"] == "ERR_UNAUTHORIZED"


def test_me_with_token(client, admin_headers):
    r = client.get("/api/auth/me", headers=admin_headers)
    assert r.status_code == 200
    assert r.json()["data"]["username"] == "admin"


def test_refresh_rotation(client):
    r = client.post("/api/auth/login", json={"username": "admin", "password": "Test@2026"})
    refresh = r.json()["data"]["refresh_token"]
    r2 = client.post("/api/auth/refresh", json={"refresh_token": refresh})
    assert r2.status_code == 200
    new_refresh = r2.json()["data"]["refresh_token"]
    assert new_refresh != refresh
    # 旧 refresh 已进黑名单，不能再用
    r3 = client.post("/api/auth/refresh", json={"refresh_token": refresh})
    assert r3.status_code == 401


def test_logout_blacklists_refresh(client, admin_headers):
    r = client.post("/api/auth/login", json={"username": "admin", "password": "Test@2026"})
    refresh = r.json()["data"]["refresh_token"]
    r2 = client.post("/api/auth/logout", headers=admin_headers, json={"refresh_token": refresh})
    assert r2.status_code == 200
    r3 = client.post("/api/auth/refresh", json={"refresh_token": refresh})
    assert r3.status_code == 401


def test_change_password(client, admin_headers):
    r = client.post("/api/auth/change-password", headers=admin_headers,
                    json={"old_password": "Test@2026", "new_password": "NewPass@2026"})
    assert r.status_code == 200
    # 新密码可登录
    r2 = client.post("/api/auth/login", json={"username": "admin", "password": "NewPass@2026"})
    assert r2.status_code == 200
    # 旧密码失败
    r3 = client.post("/api/auth/login", json={"username": "admin", "password": "Test@2026"})
    assert r3.status_code == 401


def test_change_password_wrong_old(client, admin_headers):
    r = client.post("/api/auth/change-password", headers=admin_headers,
                    json={"old_password": "bad-old", "new_password": "NewPass@2026"})
    assert r.status_code == 400
    assert r.json()["code"] == "ERR_BAD_OLD_PASSWORD"


def test_operator_cannot_access_users_admin(client, operator_headers):
    r = client.get("/api/users", headers=operator_headers)
    assert r.status_code == 403
    body = r.json()
    assert body["code"] == "ERR_FORBIDDEN"
    assert "权限不足" in body["detail"]


def test_operator_cannot_create_category(client, operator_headers):
    r = client.post("/api/categories", headers=operator_headers,
                    json={"digit": "7", "name": "测试类"})
    assert r.status_code == 403


def test_deactivated_user_cannot_login(client, admin_headers):
    r = client.post("/api/users", headers=admin_headers, json={
        "username": "op2", "password": "Op@12345678",
        "display_name": "操作员二号", "role": "operator",
    })
    assert r.status_code == 200
    uid = r.json()["data"]["id"]
    r2 = client.delete(f"/api/users/{uid}", headers=admin_headers)
    assert r2.status_code == 200
    assert r2.json()["data"]["is_active"] is False
    r3 = client.post("/api/auth/login", json={"username": "op2", "password": "Op@12345678"})
    assert r3.status_code == 403
