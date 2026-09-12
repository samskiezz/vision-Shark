import pytest
from fastapi.testclient import TestClient

from vision_shark.api import create_app
from vision_shark.research_context import (
    ClaimEvent,
    FieldResearchStore,
    Incident,
    ResearchClaim,
    ResearchFeedback,
    ResearchSource,
    SessionContext,
    VehicleModification,
    compare_contexts,
)


def _context(**overrides):
    data = {
        "vehicle_id": "shark-001",
        "variant": "Premium",
        "model_year": 2025,
        "firmware": "56.1.2.2411280.1 V1.0.0",
        "profile_pack_id": "shark-au-research",
        "profile_version": 2,
        "purpose": "ota-ab",
        "terrain": "steep-hill",
        "ambient_c": 28,
        "tyres": "265/65R18 AT",
        "tyre_pressures_kpa": {"fl": 240, "fr": 240, "rl": 245, "rr": 245},
        "modification_ids": ["tyres-at-v1"],
        "trailer": {"physically_attached": False, "detected_by_vehicle": False},
    }
    data.update(overrides)
    return data


def _import_recording(client, first="0102", second="0304"):
    capture = (
        f"(1.000000000) can0 123#{first}\n"
        f"(1.100000000) can0 123#{second}\n"
    )
    response = client.post(
        "/api/interchange/import",
        json={"format": "candump", "content": capture, "metadata": {"source": "field-test"}},
    )
    assert response.status_code == 200
    return response.json()["recording_id"]


def test_session_context_validation_and_comparability():
    baseline = SessionContext.model_validate(_context())
    matched = SessionContext.model_validate(_context(ambient_c=31))
    report = compare_contexts(baseline, matched)
    assert report["comparable"] is True
    assert report["critical_mismatches"] == 0
    assert report["score"] == 100.0

    changed = SessionContext.model_validate(
        _context(vehicle_id="shark-002", variant="Performance", firmware="2026-new")
    )
    report = compare_contexts(baseline, changed)
    assert report["comparable"] is False
    assert report["critical_mismatches"] == 3
    assert {item["field"] for item in report["mismatches"]} >= {
        "vehicle_id",
        "variant",
        "firmware",
    }

    with pytest.raises(ValueError):
        SessionContext.model_validate(_context(tyre_pressures_kpa={"fl": 1000}))


def test_research_store_is_immutable_and_tracks_claim_state(tmp_path):
    store = FieldResearchStore(tmp_path)
    try:
        source = ResearchSource(
            source_id="yt-hill-fix",
            kind="creator",
            title="Hill revisit / software-fix proof",
            url="https://www.youtube.com/watch?v=hm6bx70UT6w",
            grade="A",
            video_id="hm6bx70UT6w",
            claim_summary="Creator identifies a software-fix retest and displays a specific vehicle software version.",
        )
        first = store.put_source(source)
        assert first["status"] == "stored"
        assert store.put_source(source)["status"] == "present"
        with pytest.raises(ValueError):
            store.put_source(source.model_copy(update={"title": "conflicting content"}))

        claim = ResearchClaim(
            claim_id="firmware-affects-hill-behaviour",
            statement="Vehicle software revision may materially change observed hill behaviour.",
            domain="firmware",
            source_refs=[source.source_id],
            grade="A",
            confidence=0.7,
            validation_state="needs_physical_validation",
            required_evidence=["matched route before/after OTA", "same tyres/load where possible"],
        )
        store.put_claim(claim)
        event = store.add_claim_event(
            claim.claim_id,
            ClaimEvent(
                state="partially_validated",
                note="Matched physical captures collected on one target vehicle.",
                evidence_refs=["capture:101", "capture:102"],
            ),
        )
        assert event["event_id"] > 0
        loaded = store.get_claim(claim.claim_id)
        assert loaded["effective_validation_state"] == "partially_validated"
        assert loaded["claim"]["validation_state"] == "needs_physical_validation"
    finally:
        store.close()


def test_modification_incident_and_feedback_objects_persist(tmp_path):
    store = FieldResearchStore(tmp_path)
    try:
        mod = VehicleModification(
            mod_id="tyres-at-v1",
            vehicle_id="shark-001",
            category="wheel-tyre",
            part="265/65R18 all-terrain tyre set",
            geometry_notes="No suspension geometry claim recorded.",
            evidence_refs=["operator:fitment-photo"],
        )
        assert store.put_modification(mod)["status"] == "stored"
        assert store.list_modifications("shark-001")[0]["modification"]["mod_id"] == "tyres-at-v1"

        incident = Incident(
            incident_id="corrugation-warning-001",
            vehicle_id="shark-001",
            timestamp_ns=123456789,
            incident_type="warning-on-rough-road",
            warning_snapshot={"text": "brake warning observed"},
            notes="Observation only; mechanical cause not inferred from software evidence.",
        )
        assert store.put_incident(incident)["status"] == "stored"
        assert store.list_incidents("shark-001")[0]["incident"]["incident_id"] == incident.incident_id

        feedback = ResearchFeedback(
            feedback_id="cohort-001-response-001",
            cohort="high-country",
            release="profile-v2",
            vehicle_id="shark-001",
            subjective_ratings={"predictability": 8.0},
            notes="Operator feedback is kept separate from measured capture evidence.",
            repeatability="repeatable",
        )
        assert store.put_feedback(feedback)["status"] == "stored"
    finally:
        store.close()


def test_field_intelligence_api_end_to_end(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        baseline_id = _import_recording(client, "0102", "0304")
        candidate_id = _import_recording(client, "0102", "0506")

        for recording_id in (baseline_id, candidate_id):
            response = client.post(
                f"/api/research/session-context/{recording_id}",
                json=_context(),
            )
            assert response.status_code == 200
            assert response.json()["context"]["firmware"] == "56.1.2.2411280.1 V1.0.0"

        compare = client.post(
            "/api/research/recordings/compare",
            json={"baseline_id": baseline_id, "candidate_id": candidate_id},
        )
        assert compare.status_code == 200
        report = compare.json()
        assert report["context"]["comparable"] is True
        assert report["baseline"]["frame_count"] == 2
        assert report["candidate"]["frame_count"] == 2
        assert report["raw_vehicle_tx"] is False
        assert report["anomaly"]

        protocols = client.get("/api/research/protocols")
        assert protocols.status_code == 200
        assert len(protocols.json()["protocols"]) == 9
        assert protocols.json()["raw_vehicle_tx"] is False

        summary = client.get("/api/research/summary")
        assert summary.status_code == 200
        assert summary.json()["test_protocols"] == 9


def test_context_conflict_and_missing_recording_fail_closed(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        recording_id = _import_recording(client)
        assert client.post(
            f"/api/research/session-context/{recording_id}", json=_context()
        ).status_code == 200
        conflict = client.post(
            f"/api/research/session-context/{recording_id}",
            json=_context(firmware="different-firmware"),
        )
        assert conflict.status_code == 409
        assert client.post(
            "/api/research/session-context/999999", json=_context()
        ).status_code == 404


def test_evidence_lab_api_keeps_source_grade_and_validation_state_separate(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        source = {
            "source_id": "yt-towing-modes",
            "kind": "creator",
            "title": "BYD Shark 6 Offroad Modes while Towing 1.8T",
            "url": "https://www.youtube.com/watch?v=m_8MI_TROvY",
            "grade": "A",
            "video_id": "m_8MI_TROvY",
            "claim_summary": "Primary creator material for towing and terrain-mode interaction.",
        }
        assert client.post("/api/research/sources", json=source).status_code == 200

        claim = {
            "claim_id": "trailer-mode-interlock",
            "statement": "Trailer state may affect terrain-mode availability on some Shark software variants.",
            "domain": "towing-interlock",
            "source_refs": ["yt-towing-modes"],
            "grade": "A",
            "confidence": 0.55,
            "validation_state": "needs_physical_validation",
            "required_evidence": ["target vehicle mode-availability observation", "firmware version"],
        }
        assert client.post("/api/research/claims", json=claim).status_code == 200
        event = client.post(
            "/api/research/claims/trailer-mode-interlock/events",
            json={
                "state": "partially_validated",
                "note": "Observed on one target vehicle; cross-version repeat remains required.",
                "evidence_refs": ["operator:target-run-1"],
                "actor": "test-operator",
            },
        )
        assert event.status_code == 200

        loaded = client.get("/api/research/claims/trailer-mode-interlock")
        assert loaded.status_code == 200
        body = loaded.json()
        assert body["claim"]["grade"] == "A"
        assert body["claim"]["validation_state"] == "needs_physical_validation"
        assert body["effective_validation_state"] == "partially_validated"
        assert client.get("/api/research/sources").json()["sources"][0]["source"]["video_id"] == "m_8MI_TROvY"


def test_api_modification_and_incident_ledger(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        mod = {
            "mod_id": "suspension-v1",
            "vehicle_id": "shark-001",
            "category": "suspension",
            "part": "aftermarket suspension setup",
            "geometry_notes": "Ride height changed; exact measurement attached separately.",
        }
        assert client.post("/api/research/modifications", json=mod).status_code == 200
        rows = client.get("/api/research/vehicles/shark-001/modifications")
        assert rows.status_code == 200
        assert rows.json()["modifications"][0]["modification"]["category"] == "suspension"

        recording_id = _import_recording(client)
        incident = {
            "incident_id": "warning-001",
            "vehicle_id": "shark-001",
            "recording_id": recording_id,
            "timestamp_ns": 1_050_000_000,
            "incident_type": "vehicle-warning",
            "warning_snapshot": {"operator_text": "warning seen on cluster"},
            "dtc_snapshot": [],
            "context_window_ms": 30000,
            "notes": "No mechanical diagnosis inferred.",
            "resolution_state": "open",
        }
        assert client.post("/api/research/incidents", json=incident).status_code == 200
        incidents = client.get("/api/research/incidents?vehicle_id=shark-001")
        assert incidents.status_code == 200
        assert incidents.json()["incidents"][0]["incident"]["recording_id"] == recording_id
