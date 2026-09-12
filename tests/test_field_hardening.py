import pytest
from fastapi.testclient import TestClient

from vision_shark.api import create_app
from vision_shark.research_context import (
    FieldResearchStore,
    Incident,
    IncidentEvent,
    ResearchClaim,
    ResearchFeedback,
    SessionContext,
    compare_contexts,
)


def _context(**overrides):
    payload = {
        "vehicle_id": "shark-001",
        "model": "BYD Shark 6",
        "variant": "Premium",
        "model_year": 2025,
        "firmware": "56.1.2.2411280.1 V1.0.0",
        "profile_pack_id": "shark-au-research",
        "profile_version": 2,
        "preproduction": False,
        "purpose": "ota-ab",
        "terrain": "steep-hill",
        "route": "reference-hill-a",
        "weather": "dry",
        "ambient_c": 28,
        "tyres": "265/65R18 AT",
        "tyre_pressures_kpa": {"fl": 240, "fr": 240, "rl": 245, "rr": 245},
        "payload_kg": 120,
        "trailer": {"physically_attached": False, "detected_by_vehicle": False},
        "modification_ids": ["tyres-at-v1"],
    }
    payload.update(overrides)
    return payload


def _import_recording(client):
    response = client.post(
        "/api/interchange/import",
        json={
            "format": "candump",
            "content": "(1.000000000) can0 123#0102\n(1.100000000) can0 123#0304\n",
            "metadata": {"source": "field-hardening-test"},
        },
    )
    assert response.status_code == 200
    return response.json()["recording_id"]


def test_context_normalizes_set_like_fields_and_blocks_duplicate_modifications():
    context = SessionContext.model_validate(
        _context(
            modification_ids=["suspension-v2", "tyres-at-v1"],
            tyre_pressures_kpa={"rr": 245, "fl": 240, "rl": 245, "fr": 240},
        )
    )
    assert context.modification_ids == ["suspension-v2", "tyres-at-v1"]
    assert list(context.tyre_pressures_kpa) == ["fl", "fr", "rl", "rr"]

    with pytest.raises(ValueError, match="duplicate modification ids"):
        SessionContext.model_validate(
            _context(modification_ids=["tyres-at-v1", "tyres-at-v1"])
        )


def test_context_comparison_flags_preproduction_route_and_pressure_drift():
    baseline = SessionContext.model_validate(_context())
    candidate = SessionContext.model_validate(
        _context(
            preproduction=True,
            route="different-hill",
            tyre_pressures_kpa={"fl": 210, "fr": 210, "rl": 215, "rr": 215},
        )
    )
    report = compare_contexts(baseline, candidate)
    fields = {item["field"] for item in report["mismatches"]}
    assert report["comparable"] is False
    assert report["critical_mismatches"] == 1
    assert {"preproduction", "route", "tyre_pressures_kpa"} <= fields


def test_claim_store_rejects_unknown_source_references(tmp_path):
    store = FieldResearchStore(tmp_path)
    try:
        claim = ResearchClaim(
            claim_id="unknown-source-claim",
            statement="This claim must not enter the graph without its referenced source.",
            domain="provenance",
            source_refs=["missing-source"],
            grade="C",
            confidence=0.2,
        )
        with pytest.raises(ValueError, match="unknown sources"):
            store.put_claim(claim)
    finally:
        store.close()


def test_incident_resolution_is_append_only(tmp_path):
    store = FieldResearchStore(tmp_path)
    try:
        incident = Incident(
            incident_id="rough-road-warning-001",
            vehicle_id="shark-001",
            timestamp_ns=1_000_000,
            incident_type="warning-on-rough-road",
            warning_snapshot={"operator_text": "warning observed"},
            notes="No diagnosis inferred from warning alone.",
        )
        store.put_incident(incident)
        store.add_incident_event(
            incident.incident_id,
            IncidentEvent(
                state="inspected",
                note="Workshop inspection completed.",
                evidence_refs=["inspection:001"],
            ),
        )
        store.add_incident_event(
            incident.incident_id,
            IncidentEvent(
                state="repaired",
                note="Repair evidence attached without rewriting the original incident.",
                evidence_refs=["repair:001"],
                repair_evidence=[{"kind": "work-order", "ref": "WO-001"}],
            ),
        )
        loaded = store.get_incident(incident.incident_id)
        assert loaded["incident"]["resolution_state"] == "open"
        assert loaded["effective_resolution_state"] == "repaired"
        assert len(loaded["events"]) == 2
        assert loaded["events"][0]["event"]["state"] == "inspected"
    finally:
        store.close()


def test_incident_feedback_and_unknown_source_api_paths(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        recording_id = _import_recording(client)

        rejected_claim = client.post(
            "/api/research/claims",
            json={
                "claim_id": "bad-provenance",
                "statement": "Missing source should fail closed.",
                "domain": "provenance",
                "source_refs": ["not-loaded"],
                "grade": "C",
                "confidence": 0.1,
                "linked_recordings": [recording_id],
            },
        )
        assert rejected_claim.status_code == 409
        assert "unknown sources" in rejected_claim.json()["detail"]

        incident = client.post(
            "/api/research/incidents",
            json={
                "incident_id": "warning-api-001",
                "vehicle_id": "shark-001",
                "recording_id": recording_id,
                "timestamp_ns": 1_050_000_000,
                "incident_type": "vehicle-warning",
                "warning_snapshot": {"operator_text": "warning on cluster"},
                "notes": "Captured for later inspection correlation.",
            },
        )
        assert incident.status_code == 200

        event = client.post(
            "/api/research/incidents/warning-api-001/events",
            json={
                "state": "inspected",
                "note": "Inspection complete.",
                "evidence_refs": ["inspection:api-001"],
                "actor": "technician",
            },
        )
        assert event.status_code == 200
        loaded = client.get("/api/research/incidents/warning-api-001")
        assert loaded.status_code == 200
        assert loaded.json()["effective_resolution_state"] == "inspected"
        assert len(loaded.json()["events"]) == 1

        feedback = ResearchFeedback(
            feedback_id="feedback-api-001",
            cohort="high-country",
            release="profile-v2",
            vehicle_id="shark-001",
            recording_id=recording_id,
            subjective_ratings={"predictability": 8.0, "confidence": 7.0},
            notes="Subjective feedback remains separate from capture measurements.",
            repeatability="repeatable",
        )
        assert client.post("/api/research/feedback", json=feedback.model_dump(mode="json")).status_code == 200
        listed = client.get("/api/research/feedback?vehicle_id=shark-001")
        assert listed.status_code == 200
        assert listed.json()["feedback"][0]["feedback"]["feedback_id"] == "feedback-api-001"

        summary = client.get("/api/research/summary")
        assert summary.status_code == 200
        assert summary.json()["incident_states"] == {"inspected": 1}
        assert summary.json()["feedback"] == 1

        assert client.get("/api/research/incidents/missing-incident").status_code == 404
        assert client.post(
            "/api/research/incidents/missing-incident/events",
            json={"state": "closed", "note": "must fail"},
        ).status_code == 404
