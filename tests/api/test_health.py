from fastapi.testclient import TestClient

from spotwise.api.main import app
from spotwise.api.routes.health import get_db_check


def test_health_ok_when_db_reachable() -> None:
    app.dependency_overrides[get_db_check] = lambda: True
    try:
        response = TestClient(app).get("/health")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "db": "ok"}


def test_health_503_when_db_unreachable() -> None:
    app.dependency_overrides[get_db_check] = lambda: False
    try:
        response = TestClient(app).get("/health")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 503
    assert response.json() == {"status": "degraded", "db": "unreachable"}
