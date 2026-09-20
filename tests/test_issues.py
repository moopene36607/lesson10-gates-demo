"""Issue Tracker 測試。test_get_by_id 為 demo 缺口，先標 xfail。"""
import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_create_and_list():
    r = client.post("/issues", json={"title": "first"})
    assert r.status_code == 201
    body = r.json()
    assert body["title"] == "first"
    assert body["status"] == "open"
    assert any(i["title"] == "first" for i in client.get("/issues").json())


def test_get_by_id():
    created = client.post("/issues", json={"title": "lookup"}).json()
    r = client.get(f"/issues/{created['id']}")
    assert r.status_code == 200
    assert r.json()["id"] == created["id"]
