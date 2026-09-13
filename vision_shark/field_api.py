from __future__ import annotations

from contextlib import contextmanager

from fastapi import HTTPException

from .all_terrain_research import seed_all_terrain_research
from .communication_lab import (
    COMMUNICATION_SAFETY_PROFILE,
    BenchVoltageProfile,
    DiagnosticObservation,
    analyze_diagnostic_observation,
    communication_health,
    simulate_voltage_profile,
)
from .research_context import (
    DEFAULT_TEST_PROTOCOLS,
    ClaimEvent,
    FieldResearchStore,
    Incident,
    IncidentEvent,
    RecordingCompareRequest,
    ResearchClaim,
    ResearchFeedback,
    ResearchSource,
    SessionContext,
    VehicleModification,
    matched_recording_report,
)
from .startup_comm_lab import (
    FlashTransportTrace,
    StartupCommunicationTrace,
    analyze_flash_transport_trace,
    analyze_startup_communication,
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

    @app.get("/api/research/communication/safety-profile")
    def communication_safety_profile():
        return COMMUNICATION_SAFETY_PROFILE

    @app.post("/api/research/communication/voltage-replay")
    def voltage_replay(body: BenchVoltageProfile):
        result = simulate_voltage_profile(body)
        audit.append(
            "research",
            "synthetic_voltage_replay",
            {
                "profile_id": body.profile_id,
                "environment": body.environment,
                "sample_rate_hz": body.sample_rate_hz,
                "duration_ms": body.duration_ms,
                "physical_vehicle_connected": False,
                "physical_voltage_output": False,
            },
        )
        return result

    @app.post("/api/research/communication/startup/analyze")
    def startup_communication_analysis(body: StartupCommunicationTrace):
        result = analyze_startup_communication(body)
        audit.append(
            "research",
            "startup_communication_trace_analyzed",
            {
                "trace_id": body.trace_id,
                "event_count": len(body.events),
                "voltage_samples": len(body.voltage),
                "physical_vehicle_connected": body.physical_vehicle_connected,
                "fault_injection_commanded": body.fault_injection_commanded,
                "raw_vehicle_tx": False,
            },
        )
        return result

    @app.post("/api/research/communication/flash-trace/analyze")
    def flash_transport_analysis(body: FlashTransportTrace):
        result = analyze_flash_transport_trace(body)
        audit.append(
            "research",
            "flash_transport_trace_analyzed",
            {
                "trace_id": body.trace_id,
                "transport": body.transport,
                "source": body.source,
                "event_count": len(body.events),
                "physical_vehicle_connected": body.physical_vehicle_connected,
                "generated_vehicle_requests": body.contains_generated_vehicle_requests,
                "raw_vehicle_tx": False,
                "flash_command_generation": False,
            },
        )
        return result

    @app.get("/api/research/recordings/{recording_id}/communication-health")
    def recording_communication_health(recording_id: int):
        require_recording(recording_id)
        result = communication_health(recording_store.load_frames(recording_id))
        result["recording_id"] = recording_id
        return result

    @app.post("/api/research/diagnostics/analyze-observation")
    def analyze_diagnostic_capture(body: DiagnosticObservation):
        result = analyze_diagnostic_observation(body)
        audit.append(
            "research",
            "diagnostic_observation_analyzed",
            {
                "source": body.source,
                "protocol": body.protocol,
                "module": body.module,
                "status": result["status"],
                "response_bytes": result["response_bytes"],
                "raw_vehicle_tx": False,
            },
        )
        return result

    @app.post("/api/research/seed/all-terrain-evx")
    def seed_research():
        try:
            with research_store() as research:
                result = seed_all_terrain_research(research)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        audit.append("research", "all_terrain_seed_loaded", result)
        return result

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

    @app.get("/api/research/incidents/{incident_id}")
    def get_incident(incident_id: str):
        try:
            with research_store() as research:
                result = research.get_incident(incident_id)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        if result is None:
            raise HTTPException(404, "research incident not found")
        return result

    @app.post("/api/research/incidents/{incident_id}/events")
    def add_incident_event(incident_id: str, body: IncidentEvent):
        try:
            with research_store() as research:
                result = research.add_incident_event(incident_id, body)
        except KeyError as exc:
            raise HTTPException(404, "research incident not found") from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        audit.append(
            "research",
            "incident_state_changed",
            {"incident_id": incident_id, "state": body.state, "event_id": result["event_id"]},
        )
        return result

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

    @app.get("/api/research/feedback")
    def list_feedback(vehicle_id: str | None = None):
        try:
            with research_store() as research:
                rows = research.list_feedback(vehicle_id)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"feedback": rows}

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
            feedback = research.list_feedback()
        states = {}
        for item in claims:
            state = item["effective_validation_state"]
            states[state] = states.get(state, 0) + 1
        incident_states = {}
        for item in incidents:
            state = item["effective_resolution_state"]
            incident_states[state] = incident_states.get(state, 0) + 1
        return {
            "sources": len(sources),
            "claims": len(claims),
            "claim_states": states,
            "incidents": len(incidents),
            "incident_states": incident_states,
            "feedback": len(feedback),
            "test_protocols": len(DEFAULT_TEST_PROTOCOLS),
            "raw_vehicle_tx": False,
        }
