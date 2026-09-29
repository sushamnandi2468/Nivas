from unittest.mock import patch

from django.db.utils import OperationalError


def test_liveness_does_not_require_authentication(client):
    response = client.get("/api/v1/health/live/")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "nivasops-api"}


def test_liveness_ignores_invalid_authentication_headers(client):
    response = client.get(
        "/api/v1/health/live/",
        HTTP_AUTHORIZATION="Bearer stale-token",
        HTTP_X_SOCIETY_ID="not-a-uuid",
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "nivasops-api"}


def test_readiness_reports_database_failure(client):
    with patch("django.db.utils.ConnectionHandler.__getitem__") as get_connection:
        get_connection.return_value.cursor.side_effect = OperationalError

        response = client.get("/api/v1/health/ready/")

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable", "database": "unreachable"}