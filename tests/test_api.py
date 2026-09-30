from fastapi.testclient import TestClient

from app.main import app


def _login(client: TestClient, username="admin", password="admin123"):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def test_health():
    with TestClient(app) as client:
        r = client.get("/api/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"


def test_login_rejects_bad_password():
    with TestClient(app) as client:
        r = client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
        assert r.status_code == 401


def test_applications_crud_comment_task_and_filters():
    with TestClient(app) as client:
        token = _login(client)
        headers = {"Authorization": "Bearer " + token}

        created = client.post(
            "/api/applications",
            headers=headers,
            json={
                "title": "Тестовая заявка оплаты",
                "description": "Клиент не может оплатить, ошибка 500, срочно",
                "client_name": "Тест Клиент",
                "priority": "medium",
                "category": "general",
                "source": "web",
                "due_date": "2000-01-01",
            },
        )
        assert created.status_code == 201, created.text
        app_id = created.json()["id"]
        assert created.json()["category"] in {"bug", "billing", "support", "general", "feature", "sales", "other"}

        listed = client.get("/api/applications?q=Тестовая заявка оплаты", headers=headers)
        assert listed.status_code == 200
        assert any(item["id"] == app_id for item in listed.json()["items"])

        overdue = client.get("/api/applications?overdue=true", headers=headers)
        assert overdue.status_code == 200
        assert any(item["id"] == app_id for item in overdue.json()["items"])

        patched = client.patch("/api/applications/" + str(app_id) + "/status", headers=headers, json={"status": "in_progress"})
        assert patched.status_code == 200
        assert patched.json()["status"] == "in_progress"

        comment = client.post(
            "/api/applications/" + str(app_id) + "/comments",
            headers=headers,
            json={"text": "Взял в работу", "is_internal": True},
        )
        assert comment.status_code == 200
        assert comment.json()["text"] == "Взял в работу"

        task = client.post(
            "/api/applications/" + str(app_id) + "/tasks",
            headers=headers,
            json={"title": "Проверить логи оплаты"},
        )
        assert task.status_code == 200
        task_id = task.json()["id"]

        done = client.patch("/api/tasks/" + str(task_id), headers=headers, json={"is_done": True})
        assert done.status_code == 200
        assert done.json()["is_done"] is True

        bulk = client.post("/api/applications/bulk-status", headers=headers, json={"ids": [app_id], "status": "done"})
        assert bulk.status_code == 200
        assert bulk.json()["updated"] == 1

        star = client.post("/api/applications/" + str(app_id) + "/star", headers=headers)
        assert star.status_code == 200

        search = client.get("/api/search?q=Тест", headers=headers)
        assert search.status_code == 200
        assert len(search.json()) >= 1

        deleted = client.delete("/api/applications/" + str(app_id), headers=headers)
        assert deleted.status_code == 204


def test_employee_cannot_create_user():
    with TestClient(app) as client:
        token = _login(client, "dev1", "emp12345")
        r = client.post(
            "/api/users",
            headers={"Authorization": "Bearer " + token},
            json={"username": "hacker", "email": "h@example.com", "full_name": "Hacker", "role": "admin", "password": "1234"},
        )
        assert r.status_code == 403


def test_web_pages_require_auth_and_render():
    with TestClient(app) as client:
        assert client.get("/applications", follow_redirects=False).status_code == 302
        token = _login(client)
        client.cookies.set("access_token", token)
        for path in [
            "/",
            "/applications",
            "/kanban",
            "/companies",
            "/contacts",
            "/tasks",
            "/reports",
            "/chat",
            "/bot",
            "/users",
            "/logs",
            "/settings",
        ]:
            r = client.get(path)
            assert r.status_code == 200, path
        page = client.get("/api/applications", headers={"Authorization": "Bearer " + token}).json()
        assert page["total"] >= 1
        app_id = page["items"][0]["id"]
        for path in ["/applications/" + str(app_id), "/companies/1", "/contacts/1"]:
            r = client.get(path)
            assert r.status_code == 200, path


def test_admin_only_sections():
    with TestClient(app) as client:
        employee = _login(client, "dev1", "emp12345")
        employee_headers = {"Authorization": "Bearer " + employee}
        assert client.get("/api/logs", headers=employee_headers).status_code == 403
        assert client.get("/api/bot/status", headers=employee_headers).status_code == 403
        assert client.get("/users", headers=employee_headers, follow_redirects=False).status_code == 403

        admin = _login(client)
        admin_headers = {"Authorization": "Bearer " + admin}
        logs = client.get("/api/logs?limit=5", headers=admin_headers)
        assert logs.status_code == 200
        assert isinstance(logs.json(), list)
        status = client.get("/api/bot/status", headers=admin_headers)
        assert status.status_code == 200
        assert "commands" in status.json()
