"""Existing workflow tests now run as the seeded administrator, using real login."""

import json

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def local_test_login(request, monkeypatch):
    if request.module.__name__.endswith("test_accounts_publications"):
        return
    from mindchime.db import Database

    original_reset = Database.reset

    def reset(database, path):
        result = original_reset(database, path)
        from mindchime.auth import initialize

        initialize()
        return result

    monkeypatch.setattr(Database, "reset", reset)
    original = TestClient.__enter__

    def enter(client):
        result = original(client)
        from mindchime import main

        if client.app is main.app:
            from mindchime.db import db

            accounts = json.loads((db.path.parent / "local-accounts.json").read_text())
            admin = next(a for a in accounts if a["username"] == "admin")
            response = client.post("/api/v1/auth/login", json=admin)
            assert response.status_code == 200
        return result

    monkeypatch.setattr(TestClient, "__enter__", enter)
