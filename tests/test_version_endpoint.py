"""The /api/version probe the web client uses to detect a stale cached bundle."""
import importlib

from fastapi.testclient import TestClient


def _client():
    import api.router as router
    return TestClient(router.app)


def test_version_defaults_to_dev_without_env(monkeypatch):
    monkeypatch.delenv("APP_VERSION", raising=False)
    import api.router as router
    importlib.reload(router)
    resp = TestClient(router.app).get("/api/version")
    assert resp.status_code == 200
    assert resp.json() == {"version": "dev"}


def test_version_reports_baked_app_version(monkeypatch):
    monkeypatch.setenv("APP_VERSION", "v9.9.9")
    import api.router as router
    importlib.reload(router)
    try:
        resp = TestClient(router.app).get("/api/version")
        assert resp.status_code == 200
        assert resp.json() == {"version": "v9.9.9"}
    finally:
        # Reload once more with the env cleared so other tests see the default.
        monkeypatch.delenv("APP_VERSION", raising=False)
        importlib.reload(router)
