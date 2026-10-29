from collections.abc import Iterator
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from spotwise.api.main import app
from spotwise.db.models import QualityResult
from spotwise.db.session import get_session
from tests.quality.helpers import at


@pytest.fixture
def client(db_session: Session) -> Iterator[TestClient]:
    app.dependency_overrides[get_session] = lambda: db_session
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


@pytest.mark.db
def test_no_results_yet_is_unknown(client: TestClient) -> None:
    body = client.get("/quality/latest").json()
    assert body == {"overall": "unknown", "run_at": None, "checks": {}, "results": []}


@pytest.mark.db
def test_returns_only_latest_run_with_worst_status_per_check(
    client: TestClient, db_session: Session
) -> None:
    old, new = at("2025-11-01T12:00"), at("2025-11-02T12:00")
    db_session.add_all(
        [
            QualityResult(
                run_at=old, day=date(2025, 11, 1), check_name="completeness", status="fail"
            ),
            QualityResult(
                run_at=new, day=date(2025, 11, 1), check_name="completeness", status="pass"
            ),
            QualityResult(
                run_at=new, day=date(2025, 11, 2), check_name="completeness", status="pass"
            ),
            QualityResult(
                run_at=new,
                day=date(2025, 11, 3),
                check_name="staleness",
                status="warn",
                details={"published": False},
            ),
        ]
    )
    db_session.commit()

    response = client.get("/quality/latest")

    assert response.status_code == 200
    body = response.json()
    assert body["overall"] == "yellow"
    assert body["run_at"] == "2025-11-02T12:00:00+02:00"  # Helsinki time at the edge
    assert body["checks"] == {"completeness": "pass", "staleness": "warn"}
    assert len(body["results"]) == 3
    assert body["results"][-1]["details"] == {"published": False}
