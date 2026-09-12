from fastapi.testclient import TestClient

from vision_shark.secure_app import create_secured_app


ADMIN = "admin-token-for-field-tests-12345"
VIEWER = "viewer-token-for-field-tests-1234"


def _login(client, token):
    response = client.post("/api/auth/login", json={"token": token})
    assert response.status_code == 200
    return response.json()


def test_research_routes_inherit_supported_server_security(tmp_path):
    with TestClient(create_secured_app(tmp_path, ADMIN, VIEWER)) as client:
        assert client.get("/api/research/summary").status_code == 401

        viewer = _login(client, VIEWER)
        summary = client.get("/api/research/summary")
        assert summary.status_code == 200
        assert summary.json()["raw_vehicle_tx"] is False
        denied = client.post(
            "/api/research/seed/all-terrain-evx",
            headers={
                "X-CSRF-Token": viewer["csrf_token"],
                "Idempotency-Key": "viewer-seed-denied",
            },
        )
        assert denied.status_code == 403

        admin = _login(client, ADMIN)
        seeded = client.post(
            "/api/research/seed/all-terrain-evx",
            headers={
                "X-CSRF-Token": admin["csrf_token"],
                "Idempotency-Key": "admin-seed-1",
            },
        )
        assert seeded.status_code == 200
        replay = client.post(
            "/api/research/seed/all-terrain-evx",
            headers={
                "X-CSRF-Token": admin["csrf_token"],
                "Idempotency-Key": "admin-seed-1",
            },
        )
        assert replay.status_code == 200
        assert replay.json() == seeded.json()
