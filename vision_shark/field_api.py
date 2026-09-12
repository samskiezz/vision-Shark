from __future__ import annotations

from contextlib import contextmanager

from fastapi import HTTPException

from .research_context import (
    DEFAULT_TEST_PROTOCOLS,
    ClaimEvent,
    FieldResearchStore,
    Incident,
    RecordingCompareRequest,
    ResearchClaim,
    ResearchFeedback,
    ResearchSource,
    SessionContext,
    VehicleModification,
    matched_recording_report,
)


def install_field_routes(app, recording_store, audit):
    root = recording_store.path.parent

    @contextmanager
    def research_store():
        store = FieldResearchStore(root)
        try:
            yield store
        finally:
            store.close()

    def require_recording(recording_id: int) -> None:
        recording_id = int(recording_id)
        if recording_id < 1:
            raise HTTPException(404, "recording not found")
        if not any(item["id"] == recording_id for item in recording_store.list_recordings()):
            raise HTTPException(404, "recording not found")

    @app.get("/api/research/protocols")
    def research_protocols():
        return {"protocols": DEFAULT_TEST_PROTOCOLS, "raw_vehicle_tx": False}

    @app.post("/api/research/session-context/{recording_id}")
    def put_session_context(recording_id: int, body: SessionContext):
        require_recording(recording_id)
        try:
            with research_store() as research:
                result = research.put_session_context(recording_id, body)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        audit.append(
            "research",
            "session_context_stored",
            {
                "recording_id": recording_id,
                "vehicle_id": body.vehicle_id,
                "variant": body.variant,
                "firmware": body.firmware,
                "sha256": result["sha256"],
            },
        )
        return result

    @app.get("/api/research/session-context/{recording_id}")
    def get_session_context(recording_id: int):
        require_recording(recording_id)
        with research_store() as research:
            result = research.get_session_context(recording_id)
        if result is None:
            raise HTTPException(404, "session context not found")
        return result

    @app.post("/api/research/sources")
    def put_research_source(body: ResearchSource):
        try:
            with research_store() as research:
                result = research.put_source(body)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        audit.append(
            "research",
            "source_stored",
            {"source_id": body.source_id, "kind": body.kind, "grade": body.grade, "sha256": result["sha256"]},
        )
        return result

    @app.get("/api/research/sources")
    def list_research_sources():
        with research_store() as research:
            return {"sources": research.list_sources()}

    @app.post("/api/research/modifications")
    def put_modification(body: VehicleModification):
        try:
            with research_store() as research:
                result = research.put_modification(body)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        audit.append(
            "research",
            "modification_stored",
            {"mod_id": body.mod_id, "vehicle_id": body.vehicle_id, "category": body.category, "sha256": result["sha256"]},
        )
        return result

    @app.get("/api/research/vehicles/{vehicle_id}/modifications")
    def list_modifications(vehicle_id: str):
        try:
            with research_store() as research:
                rows = research.list_modifications(vehicle_id)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"vehicle_id": vehicle_id, "modifications": rows}

    @app.post("/api/research/claims")
    def put_claim(body: ResearchClaim):
        for recording_id in body.linked_recordings:
            require_recording(recording_id)
        try:
            with research_store() as research:
                result = research.put_claim(body)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        audit.append(
            "research",
            "claim_stored",
            {
                "claim_id": body.claim_id,
                "domain": body.domain,
                "grade": body.grade,
                "validation_state": body.validation_state,
                "sha256": result["sha256"],
            },
        )
        return result

    @app.get("/api/research/claims")
    def list_claims():
        with research_store() as research:
            return {"claims": research.list_claims()}

    @app.get("/api/research/claims/{claim_id}")
    def get_claim(claim_id: str):
        try:
            with research_store() as research:
                result = research.get_claim(claim_id)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        if result is None:
            raise HTTPException(404, "research claim not found")
        return result

    @app.post("/api/research/claims/{claim_id}/events")
    def add_claim_event(claim_id: str, body: ClaimEvent):
        try:
            with research_store() as research:
                result = research.add_claim_event(claim_id, body)
        except KeyError as exc:
            raise HTTPException(404, "research claim not found") from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        audit.append(
            "research",
            "claim_state_changed",
            {"claim_id": claim_id, "state": body.state, "event_id": result["event_id"]},
        )
        return result

    @app.post("/api/research/incidents")
    def put_incident(body: Incident):
        if body.recording_id is not None:
            require_recording(body.recording_id)
        try:
            with research_store() as research:
                result = research.put_incident(body)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        audit.append(
            "research",
            "incident_stored",
            {
                "incident_id": body.incident_id,
                "vehicle_id": body.vehicle_id,
                "recording_id": body.recording_id,
                "incident_type": body.incident_type,
                "sha256": result["sha256"],
            },
        )
        return result

    @app.get("/api/research/incidents")
    def list_incidents(vehicle_id: str | None = None):
        try:
            with research_store() as research:
                rows = research.list_incidents(vehicle_id)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"incidents": rows}

    @app.post("/api/research/feedback")
    def put_feedback(body: ResearchFeedback):
        if body.recording_id is not None:
            require_recording(body.recording_id)
        try:
            with research_store() as research:
                result = research.put_feedback(body)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        audit.append(
            "research",
            "feedback_stored",
            {
                "feedback_id": body.feedback_id,
                "vehicle_id": body.vehicle_id,
                "cohort": body.cohort,
                "release": body.release,
                "sha256": result["sha256"],
            },
        )
        return result

    @app.post("/api/research/recordings/compare")
    def compare_recordings(body: RecordingCompareRequest):
        require_recording(body.baseline_id)
        require_recording(body.candidate_id)
        with research_store() as research:
            result = matched_recording_report(
                recording_store,
                research,
                body.baseline_id,
                body.candidate_id,
            )
        audit.append(
            "research",
            "recordings_compared",
            {
                "baseline_id": body.baseline_id,
                "candidate_id": body.candidate_id,
                "context_score": result["context"]["score"],
                "comparable": result["context"]["comparable"],
            },
        )
        return result

    @app.get("/api/research/summary")
    def research_summary():
        with research_store() as research:
            claims = research.list_claims()
            sources = research.list_sources()
            incidents = research.list_incidents()
        states = {}
        for item in claims:
            state = item["effective_validation_state"]
            states[state] = states.get(state, 0) + 1
        return {
            "sources": len(sources),
            "claims": len(claims),
            "claim_states": states,
            "incidents": len(incidents),
            "test_protocols": len(DEFAULT_TEST_PROTOCOLS),
            "raw_vehicle_tx": False,
        }
