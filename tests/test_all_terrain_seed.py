from fastapi.testclient import TestClient

from vision_shark.all_terrain_research import ALL_TERRAIN_CLAIMS, ALL_TERRAIN_SOURCES
from vision_shark.api import create_app


def test_all_terrain_seed_is_explicit_idempotent_and_evidence_graded(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        first = client.post("/api/research/seed/all-terrain-evx")
        assert first.status_code == 200
        body = first.json()
        assert body["sources"] == len(ALL_TERRAIN_SOURCES)
        assert body["claims"] == len(ALL_TERRAIN_CLAIMS)
        assert body["sources_stored"] == len(ALL_TERRAIN_SOURCES)
        assert body["claims_stored"] == len(ALL_TERRAIN_CLAIMS)
        assert body["idempotent"] is False

        second = client.post("/api/research/seed/all-terrain-evx")
        assert second.status_code == 200
        assert second.json()["sources_stored"] == 0
        assert second.json()["claims_stored"] == 0
        assert second.json()["idempotent"] is True

        sources = client.get("/api/research/sources")
        assert sources.status_code == 200
        source_rows = sources.json()["sources"]
        assert len(source_rows) == len(ALL_TERRAIN_SOURCES)
        assert {row["source"]["grade"] for row in source_rows} <= {"A", "B", "C", "X"}

        claims = client.get("/api/research/claims")
        assert claims.status_code == 200
        claim_rows = claims.json()["claims"]
        assert len(claim_rows) == len(ALL_TERRAIN_CLAIMS)
        assert all(
            row["effective_validation_state"] in {
                "hypothesis",
                "needs_physical_validation",
                "partially_validated",
            }
            for row in claim_rows
        )
        assert all(row["effective_validation_state"] != "validated" for row in claim_rows)

        summary = client.get("/api/research/summary")
        assert summary.status_code == 200
        assert summary.json()["sources"] == len(ALL_TERRAIN_SOURCES)
        assert summary.json()["claims"] == len(ALL_TERRAIN_CLAIMS)
        assert summary.json()["raw_vehicle_tx"] is False


def test_seed_contains_key_dossier_video_ids_without_inventing_validation():
    by_id = {item["video_id"]: item for item in ALL_TERRAIN_SOURCES if item.get("video_id")}
    assert "hm6bx70UT6w" in by_id
    assert "m_8MI_TROvY" in by_id
    assert "THFdPtte59M" in by_id
    assert "PxzFOrnmt0U" in by_id
    assert by_id["THFdPtte59M"]["grade"] == "C"
    assert "diagnosis" in by_id["THFdPtte59M"]["claim_summary"].lower()
