from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import threading
import time
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from .anomaly import compare_anomaly

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}$")
_MAX_JSON_BYTES = 512 * 1024

ClaimGrade = Literal["A", "B", "C", "X"]
ValidationState = Literal[
    "hypothesis",
    "needs_physical_validation",
    "partially_validated",
    "validated",
    "rejected",
]


def _clean_id(value: str, label: str) -> str:
    value = str(value).strip()
    if not _ID_RE.fullmatch(value):
        raise ValueError(f"invalid {label}")
    return value


def _canonical(value: dict) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    if len(payload.encode("utf-8")) > _MAX_JSON_BYTES:
        raise ValueError("research object exceeds 512 KiB")
    return payload


def _sha(payload: str) -> str:
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class ResearchSource(BaseModel):
    source_id: str
    kind: Literal["creator", "vendor_product", "independent", "community", "physical_capture"]
    title: str = Field(min_length=1, max_length=300)
    url: str | None = Field(default=None, max_length=1000)
    grade: ClaimGrade
    published_date: str | None = Field(default=None, max_length=32)
    video_id: str | None = Field(default=None, max_length=32)
    claim_summary: str = Field(default="", max_length=4000)

    @field_validator("source_id")
    @classmethod
    def validate_source_id(cls, value: str) -> str:
        return _clean_id(value, "source id")


class TrailerContext(BaseModel):
    physically_attached: bool | None = None
    detected_by_vehicle: bool | None = None
    tow_mode_observed: bool | None = None
    estimated_mass_kg: float | None = Field(default=None, ge=0, le=10_000)
    notes: str = Field(default="", max_length=1000)


class SessionContext(BaseModel):
    vehicle_id: str
    model: str = Field(default="BYD Shark 6", min_length=1, max_length=100)
    variant: str = Field(default="unknown", min_length=1, max_length=100)
    model_year: int | None = Field(default=None, ge=2020, le=2100)
    firmware: str = Field(default="unknown", min_length=1, max_length=160)
    profile_pack_id: str | None = Field(default=None, max_length=96)
    profile_version: int | None = Field(default=None, ge=1)
    preproduction: bool = False
    purpose: str = Field(default="general", min_length=1, max_length=100)
    terrain: str = Field(default="unknown", min_length=1, max_length=100)
    route: str = Field(default="", max_length=300)
    weather: str = Field(default="", max_length=300)
    ambient_c: float | None = Field(default=None, ge=-60, le=80)
    tyres: str = Field(default="unknown", min_length=1, max_length=200)
    tyre_pressures_kpa: dict[str, float] = Field(default_factory=dict)
    payload_kg: float | None = Field(default=None, ge=0, le=5000)
    trailer: TrailerContext = Field(default_factory=TrailerContext)
    modification_ids: list[str] = Field(default_factory=list, max_length=128)
    operator_notes: str = Field(default="", max_length=6000)
    provenance: list[dict] = Field(default_factory=list, max_length=128)

    @field_validator("vehicle_id")
    @classmethod
    def validate_vehicle_id(cls, value: str) -> str:
        return _clean_id(value, "vehicle id")

    @field_validator("profile_pack_id")
    @classmethod
    def validate_pack_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _clean_id(value, "profile pack id")

    @field_validator("modification_ids")
    @classmethod
    def validate_modification_ids(cls, values: list[str]) -> list[str]:
        return [_clean_id(value, "modification id") for value in values]

    @field_validator("tyre_pressures_kpa")
    @classmethod
    def validate_pressures(cls, value: dict[str, float]) -> dict[str, float]:
        if len(value) > 12:
            raise ValueError("too many tyre pressure entries")
        result = {}
        for key, pressure in value.items():
            name = str(key).strip().lower()
            if not name or len(name) > 32:
                raise ValueError("invalid tyre pressure key")
            pressure = float(pressure)
            if not 20 <= pressure <= 800:
                raise ValueError("tyre pressure must be between 20 and 800 kPa")
            result[name] = pressure
        return result


class VehicleModification(BaseModel):
    mod_id: str
    vehicle_id: str
    category: str = Field(min_length=1, max_length=80)
    part: str = Field(min_length=1, max_length=240)
    installed_at: str | None = Field(default=None, max_length=64)
    removed_at: str | None = Field(default=None, max_length=64)
    geometry_notes: str = Field(default="", max_length=2000)
    electrical_notes: str = Field(default="", max_length=2000)
    evidence_refs: list[str] = Field(default_factory=list, max_length=128)

    @field_validator("mod_id")
    @classmethod
    def validate_mod_id(cls, value: str) -> str:
        return _clean_id(value, "modification id")

    @field_validator("vehicle_id")
    @classmethod
    def validate_vehicle_id(cls, value: str) -> str:
        return _clean_id(value, "vehicle id")


class ResearchClaim(BaseModel):
    claim_id: str
    statement: str = Field(min_length=1, max_length=6000)
    domain: str = Field(min_length=1, max_length=100)
    source_refs: list[str] = Field(default_factory=list, max_length=256)
    grade: ClaimGrade
    confidence: float = Field(ge=0, le=1)
    validation_state: ValidationState = "hypothesis"
    required_evidence: list[str] = Field(default_factory=list, max_length=128)
    linked_recordings: list[int] = Field(default_factory=list, max_length=256)

    @field_validator("claim_id")
    @classmethod
    def validate_claim_id(cls, value: str) -> str:
        return _clean_id(value, "claim id")

    @field_validator("source_refs")
    @classmethod
    def validate_source_refs(cls, values: list[str]) -> list[str]:
        return [_clean_id(value, "source reference") for value in values]

    @field_validator("linked_recordings")
    @classmethod
    def validate_recordings(cls, values: list[int]) -> list[int]:
        result = [int(value) for value in values]
        if any(value < 1 for value in result):
            raise ValueError("recording ids must be positive")
        return result


class ClaimEvent(BaseModel):
    state: ValidationState
    note: str = Field(default="", max_length=6000)
    evidence_refs: list[str] = Field(default_factory=list, max_length=256)
    actor: str = Field(default="operator", min_length=1, max_length=100)


class Incident(BaseModel):
    incident_id: str
    vehicle_id: str
    recording_id: int | None = Field(default=None, ge=1)
    timestamp_ns: int = Field(ge=0)
    incident_type: str = Field(min_length=1, max_length=100)
    warning_snapshot: dict = Field(default_factory=dict)
    dtc_snapshot: list[dict] = Field(default_factory=list, max_length=256)
    context_window_ms: int = Field(default=30_000, ge=100, le=3_600_000)
    notes: str = Field(default="", max_length=6000)
    repair_evidence: list[dict] = Field(default_factory=list, max_length=128)
    resolution_state: Literal["open", "inspected", "repaired", "closed", "unknown"] = "open"

    @field_validator("incident_id")
    @classmethod
    def validate_incident_id(cls, value: str) -> str:
        return _clean_id(value, "incident id")

    @field_validator("vehicle_id")
    @classmethod
    def validate_vehicle_id(cls, value: str) -> str:
        return _clean_id(value, "vehicle id")


class ResearchFeedback(BaseModel):
    feedback_id: str
    cohort: str = Field(min_length=1, max_length=100)
    release: str = Field(min_length=1, max_length=100)
    vehicle_id: str
    recording_id: int | None = Field(default=None, ge=1)
    subjective_ratings: dict[str, float] = Field(default_factory=dict)
    notes: str = Field(default="", max_length=6000)
    evidence_attachments: list[dict] = Field(default_factory=list, max_length=128)
    repeatability: Literal["unknown", "one_off", "repeatable", "not_repeatable"] = "unknown"

    @field_validator("feedback_id")
    @classmethod
    def validate_feedback_id(cls, value: str) -> str:
        return _clean_id(value, "feedback id")

    @field_validator("vehicle_id")
    @classmethod
    def validate_vehicle_id(cls, value: str) -> str:
        return _clean_id(value, "vehicle id")

    @field_validator("subjective_ratings")
    @classmethod
    def validate_ratings(cls, values: dict[str, float]) -> dict[str, float]:
        if len(values) > 32:
            raise ValueError("too many feedback ratings")
        result = {}
        for key, score in values.items():
            key = str(key).strip()
            score = float(score)
            if not key or len(key) > 64 or not 0 <= score <= 10:
                raise ValueError("feedback ratings must use names <=64 chars and scores from 0 to 10")
            result[key] = score
        return result


class RecordingCompareRequest(BaseModel):
    baseline_id: int = Field(ge=1)
    candidate_id: int = Field(ge=1)

    @model_validator(mode="after")
    def distinct_recordings(self):
        if self.baseline_id == self.candidate_id:
            raise ValueError("baseline and candidate recordings must differ")
        return self


DEFAULT_TEST_PROTOCOLS = [
    {
        "protocol_id": "sand-dune-v1",
        "question": "Thermal and traction behaviour on soft surface",
        "minimum_context": ["tyres/psi", "ambient", "SOC", "mode", "speed", "grade", "wheel deltas", "power/regen", "warnings"],
        "comparison_rule": "Repeat the same dune or segment when safe and retain failed or aborted attempts.",
    },
    {
        "protocol_id": "steep-hill-articulation-v1",
        "question": "Low-speed traction and response on steep or cross-axle terrain",
        "minimum_context": ["grade", "mode", "ESC/TCS state", "wheel deltas", "driver annotations", "SOC", "firmware"],
        "comparison_rule": "Separate all-wheels-ground climbs from cross-axle articulation.",
    },
    {
        "protocol_id": "rock-rut-crawl-v1",
        "question": "Precision and minimum controllable speed",
        "minimum_context": ["speed", "pitch/roll", "wheel deltas", "driver annotations", "regen"],
        "comparison_rule": "Vision remains observational; do not use the gateway for active control.",
    },
    {
        "protocol_id": "towing-highway-v1",
        "question": "Sustained energy use and reserve under trailer load",
        "minimum_context": ["trailer mass", "tow detection/mode", "speed", "wind", "SOC", "fuel", "engine/generator", "grade"],
        "comparison_rule": "Report energy per distance only with route and load context.",
    },
    {
        "protocol_id": "towing-offroad-v1",
        "question": "Mode interlocks and traction under trailer load",
        "minimum_context": ["trailer detection", "available terrain modes", "selected mode", "grade", "wheel deltas", "SOC"],
        "comparison_rule": "Explicitly record when a mode is unavailable and do not guess the cause.",
    },
    {
        "protocol_id": "corrugation-v1",
        "question": "Warnings and mechanical follow-up after rough-road exposure",
        "minimum_context": ["speed", "roughness proxy", "tyre pressure", "warnings/DTC", "post-run inspection"],
        "comparison_rule": "Use an incident freeze window and compare again after documented repair.",
    },
    {
        "protocol_id": "camp-aux-power-v1",
        "question": "12 V/HV runtime and generator events while parked",
        "minimum_context": ["aux watts/duty cycle", "SOC", "12 V voltage", "ambient", "generator starts"],
        "comparison_rule": "Keep measured values separate from estimates and assumptions.",
    },
    {
        "protocol_id": "ota-ab-v1",
        "question": "Behaviour change across vehicle software versions",
        "minimum_context": ["same route/test", "same tyres/load where possible", "software before", "software after"],
        "comparison_rule": "Show context mismatches before presenting analytical differences.",
    },
    {
        "protocol_id": "post-mod-baseline-v1",
        "question": "Changes after wheel, suspension, bar or electrical modifications",
        "minimum_context": ["modification ID", "warnings", "ride height", "tyres", "same reference route"],
        "comparison_rule": "Record ADAS calibration status but do not assert calibration validity without an approved procedure.",
    },
]


class FieldResearchStore:
    def __init__(self, root: str | Path):
        root = Path(root)
        root.mkdir(parents=True, exist_ok=True)
        self.path = root / "vision_research.sqlite3"
        self._lock = threading.RLock()
        self._db = sqlite3.connect(self.path, check_same_thread=False)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=FULL")
        self._db.execute("PRAGMA foreign_keys=ON")
        self._db.executescript(
            "CREATE TABLE IF NOT EXISTS session_contexts("
            "recording_id INTEGER PRIMARY KEY,payload_json TEXT NOT NULL,sha256 TEXT NOT NULL,created_ns INTEGER NOT NULL);"
            "CREATE TABLE IF NOT EXISTS research_sources("
            "source_id TEXT PRIMARY KEY,payload_json TEXT NOT NULL,sha256 TEXT NOT NULL,created_ns INTEGER NOT NULL);"
            "CREATE TABLE IF NOT EXISTS vehicle_modifications("
            "mod_id TEXT PRIMARY KEY,vehicle_id TEXT NOT NULL,payload_json TEXT NOT NULL,sha256 TEXT NOT NULL,created_ns INTEGER NOT NULL);"
            "CREATE INDEX IF NOT EXISTS vehicle_modifications_vehicle_idx ON vehicle_modifications(vehicle_id);"
            "CREATE TABLE IF NOT EXISTS research_claims("
            "claim_id TEXT PRIMARY KEY,payload_json TEXT NOT NULL,sha256 TEXT NOT NULL,created_ns INTEGER NOT NULL);"
            "CREATE TABLE IF NOT EXISTS claim_events("
            "id INTEGER PRIMARY KEY AUTOINCREMENT,claim_id TEXT NOT NULL,event_json TEXT NOT NULL,created_ns INTEGER NOT NULL,"
            "FOREIGN KEY(claim_id) REFERENCES research_claims(claim_id));"
            "CREATE INDEX IF NOT EXISTS claim_events_claim_idx ON claim_events(claim_id,id);"
            "CREATE TABLE IF NOT EXISTS incidents("
            "incident_id TEXT PRIMARY KEY,vehicle_id TEXT NOT NULL,recording_id INTEGER,payload_json TEXT NOT NULL,sha256 TEXT NOT NULL,created_ns INTEGER NOT NULL);"
            "CREATE INDEX IF NOT EXISTS incidents_vehicle_idx ON incidents(vehicle_id,created_ns);"
            "CREATE TABLE IF NOT EXISTS research_feedback("
            "feedback_id TEXT PRIMARY KEY,vehicle_id TEXT NOT NULL,payload_json TEXT NOT NULL,sha256 TEXT NOT NULL,created_ns INTEGER NOT NULL);"
        )
        self._db.commit()

    def _insert_immutable(self, table: str, key_column: str, key: str | int, payload: dict, extra_columns=()):
        encoded = _canonical(payload)
        digest = _sha(encoded)
        with self._lock:
            row = self._db.execute(
                f"SELECT sha256 FROM {table} WHERE {key_column}=?",
                (key,),
            ).fetchone()
            if row:
                if row[0] != digest:
                    raise ValueError(f"immutable {table} key conflicts with existing content")
                return {"status": "present", "sha256": digest}
            columns = [key_column]
            values = [key]
            for name, value in extra_columns:
                columns.append(name)
                values.append(value)
            columns.extend(["payload_json", "sha256", "created_ns"])
            values.extend([encoded, digest, time.time_ns()])
            placeholders = ",".join("?" for _ in columns)
            self._db.execute(
                f"INSERT INTO {table}({','.join(columns)}) VALUES({placeholders})",
                tuple(values),
            )
            self._db.commit()
        return {"status": "stored", "sha256": digest}

    def put_session_context(self, recording_id: int, context: SessionContext | dict) -> dict:
        recording_id = int(recording_id)
        if recording_id < 1:
            raise ValueError("recording id must be positive")
        value = context if isinstance(context, SessionContext) else SessionContext.model_validate(context)
        result = self._insert_immutable(
            "session_contexts",
            "recording_id",
            recording_id,
            value.model_dump(mode="json"),
        )
        return {"recording_id": recording_id, **result, "context": value.model_dump(mode="json")}

    def get_session_context(self, recording_id: int) -> dict | None:
        with self._lock:
            row = self._db.execute(
                "SELECT payload_json,sha256,created_ns FROM session_contexts WHERE recording_id=?",
                (int(recording_id),),
            ).fetchone()
        if row is None:
            return None
        return {
            "recording_id": int(recording_id),
            "context": json.loads(row[0]),
            "sha256": row[1],
            "created_ns": row[2],
        }

    def put_source(self, source: ResearchSource | dict) -> dict:
        value = source if isinstance(source, ResearchSource) else ResearchSource.model_validate(source)
        result = self._insert_immutable(
            "research_sources",
            "source_id",
            value.source_id,
            value.model_dump(mode="json"),
        )
        return {"source_id": value.source_id, **result}

    def list_sources(self) -> list[dict]:
        with self._lock:
            rows = self._db.execute(
                "SELECT payload_json,sha256,created_ns FROM research_sources ORDER BY source_id"
            ).fetchall()
        return [{"source": json.loads(row[0]), "sha256": row[1], "created_ns": row[2]} for row in rows]

    def put_modification(self, modification: VehicleModification | dict) -> dict:
        value = modification if isinstance(modification, VehicleModification) else VehicleModification.model_validate(modification)
        result = self._insert_immutable(
            "vehicle_modifications",
            "mod_id",
            value.mod_id,
            value.model_dump(mode="json"),
            (("vehicle_id", value.vehicle_id),),
        )
        return {"mod_id": value.mod_id, **result}

    def list_modifications(self, vehicle_id: str) -> list[dict]:
        vehicle_id = _clean_id(vehicle_id, "vehicle id")
        with self._lock:
            rows = self._db.execute(
                "SELECT payload_json,sha256,created_ns FROM vehicle_modifications WHERE vehicle_id=? ORDER BY created_ns,mod_id",
                (vehicle_id,),
            ).fetchall()
        return [{"modification": json.loads(row[0]), "sha256": row[1], "created_ns": row[2]} for row in rows]

    def put_claim(self, claim: ResearchClaim | dict) -> dict:
        value = claim if isinstance(claim, ResearchClaim) else ResearchClaim.model_validate(claim)
        result = self._insert_immutable(
            "research_claims",
            "claim_id",
            value.claim_id,
            value.model_dump(mode="json"),
        )
        return {"claim_id": value.claim_id, **result}

    def add_claim_event(self, claim_id: str, event: ClaimEvent | dict) -> dict:
        claim_id = _clean_id(claim_id, "claim id")
        value = event if isinstance(event, ClaimEvent) else ClaimEvent.model_validate(event)
        encoded = _canonical(value.model_dump(mode="json"))
        with self._lock:
            exists = self._db.execute(
                "SELECT 1 FROM research_claims WHERE claim_id=?",
                (claim_id,),
            ).fetchone()
            if not exists:
                raise KeyError(claim_id)
            created_ns = time.time_ns()
            cur = self._db.execute(
                "INSERT INTO claim_events(claim_id,event_json,created_ns) VALUES(?,?,?)",
                (claim_id, encoded, created_ns),
            )
            self._db.commit()
        return {"event_id": int(cur.lastrowid), "claim_id": claim_id, "created_ns": created_ns, "event": value.model_dump(mode="json")}

    def get_claim(self, claim_id: str) -> dict | None:
        claim_id = _clean_id(claim_id, "claim id")
        with self._lock:
            row = self._db.execute(
                "SELECT payload_json,sha256,created_ns FROM research_claims WHERE claim_id=?",
                (claim_id,),
            ).fetchone()
            events = self._db.execute(
                "SELECT id,event_json,created_ns FROM claim_events WHERE claim_id=? ORDER BY id",
                (claim_id,),
            ).fetchall()
        if row is None:
            return None
        claim = json.loads(row[0])
        event_rows = [
            {"event_id": item[0], "event": json.loads(item[1]), "created_ns": item[2]}
            for item in events
        ]
        effective = event_rows[-1]["event"]["state"] if event_rows else claim["validation_state"]
        return {
            "claim": claim,
            "sha256": row[1],
            "created_ns": row[2],
            "events": event_rows,
            "effective_validation_state": effective,
        }

    def list_claims(self) -> list[dict]:
        with self._lock:
            ids = [row[0] for row in self._db.execute("SELECT claim_id FROM research_claims ORDER BY claim_id").fetchall()]
        return [self.get_claim(claim_id) for claim_id in ids]

    def put_incident(self, incident: Incident | dict) -> dict:
        value = incident if isinstance(incident, Incident) else Incident.model_validate(incident)
        result = self._insert_immutable(
            "incidents",
            "incident_id",
            value.incident_id,
            value.model_dump(mode="json"),
            (("vehicle_id", value.vehicle_id), ("recording_id", value.recording_id)),
        )
        return {"incident_id": value.incident_id, **result}

    def list_incidents(self, vehicle_id: str | None = None) -> list[dict]:
        with self._lock:
            if vehicle_id is None:
                rows = self._db.execute(
                    "SELECT payload_json,sha256,created_ns FROM incidents ORDER BY created_ns DESC"
                ).fetchall()
            else:
                vehicle_id = _clean_id(vehicle_id, "vehicle id")
                rows = self._db.execute(
                    "SELECT payload_json,sha256,created_ns FROM incidents WHERE vehicle_id=? ORDER BY created_ns DESC",
                    (vehicle_id,),
                ).fetchall()
        return [{"incident": json.loads(row[0]), "sha256": row[1], "created_ns": row[2]} for row in rows]

    def put_feedback(self, feedback: ResearchFeedback | dict) -> dict:
        value = feedback if isinstance(feedback, ResearchFeedback) else ResearchFeedback.model_validate(feedback)
        result = self._insert_immutable(
            "research_feedback",
            "feedback_id",
            value.feedback_id,
            value.model_dump(mode="json"),
            (("vehicle_id", value.vehicle_id),),
        )
        return {"feedback_id": value.feedback_id, **result}

    def close(self) -> None:
        with self._lock:
            self._db.close()


def _normalise_context(value: dict | SessionContext | None) -> dict | None:
    if value is None:
        return None
    if isinstance(value, SessionContext):
        return value.model_dump(mode="json")
    return SessionContext.model_validate(value).model_dump(mode="json")


def compare_contexts(baseline: dict | SessionContext | None, candidate: dict | SessionContext | None) -> dict:
    left = _normalise_context(baseline)
    right = _normalise_context(candidate)
    if left is None or right is None:
        return {
            "score": 0.0,
            "comparable": False,
            "critical_mismatches": 1,
            "mismatches": [{"field": "session_context", "severity": "critical", "baseline": left, "candidate": right}],
        }
    rules = [
        ("vehicle_id", 20, "critical"),
        ("variant", 15, "critical"),
        ("model_year", 8, "high"),
        ("firmware", 15, "critical"),
        ("profile_pack_id", 8, "high"),
        ("profile_version", 8, "high"),
        ("tyres", 7, "high"),
        ("modification_ids", 7, "high"),
        ("purpose", 3, "medium"),
        ("terrain", 3, "medium"),
        ("payload_kg", 2, "medium"),
        ("trailer", 4, "high"),
    ]
    mismatches = []
    penalty = 0
    critical = 0
    for field, weight, severity in rules:
        if left.get(field) != right.get(field):
            penalty += weight
            if severity == "critical":
                critical += 1
            mismatches.append(
                {
                    "field": field,
                    "severity": severity,
                    "baseline": left.get(field),
                    "candidate": right.get(field),
                }
            )
    ambient_delta = None
    if left.get("ambient_c") is not None and right.get("ambient_c") is not None:
        ambient_delta = abs(float(left["ambient_c"]) - float(right["ambient_c"]))
        if ambient_delta > 10:
            penalty += 2
            mismatches.append(
                {
                    "field": "ambient_c",
                    "severity": "medium",
                    "baseline": left["ambient_c"],
                    "candidate": right["ambient_c"],
                    "delta_c": ambient_delta,
                }
            )
    score = max(0.0, 100.0 - float(penalty))
    return {
        "score": score,
        "comparable": critical == 0 and score >= 70,
        "critical_mismatches": critical,
        "mismatches": mismatches,
        "ambient_delta_c": ambient_delta,
    }


def _frame_summary(frames) -> dict:
    if not frames:
        return {"frame_count": 0, "duration_ms": 0.0, "buses": [], "identifiers": []}
    identifiers = sorted({(frame.bus, frame.arbitration_id, frame.extended) for frame in frames})
    duration_ms = max(0.0, (frames[-1].ts_ns - frames[0].ts_ns) / 1_000_000)
    return {
        "frame_count": len(frames),
        "duration_ms": duration_ms,
        "buses": sorted({frame.bus for frame in frames}),
        "identifiers": [
            {"bus": bus, "arbitration_id": arbitration_id, "extended": extended}
            for bus, arbitration_id, extended in identifiers
        ],
    }


def matched_recording_report(recording_store, research_store: FieldResearchStore, baseline_id: int, candidate_id: int) -> dict:
    baseline_id = int(baseline_id)
    candidate_id = int(candidate_id)
    if baseline_id < 1 or candidate_id < 1 or baseline_id == candidate_id:
        raise ValueError("matched comparison requires two distinct positive recording ids")
    baseline_frames = recording_store.load_frames(baseline_id)
    candidate_frames = recording_store.load_frames(candidate_id)
    baseline_context = research_store.get_session_context(baseline_id)
    candidate_context = research_store.get_session_context(candidate_id)
    context_report = compare_contexts(
        baseline_context["context"] if baseline_context else None,
        candidate_context["context"] if candidate_context else None,
    )
    anomaly = compare_anomaly(baseline_frames, candidate_frames)
    return {
        "baseline_id": baseline_id,
        "candidate_id": candidate_id,
        "context": context_report,
        "baseline": _frame_summary(baseline_frames),
        "candidate": _frame_summary(candidate_frames),
        "anomaly": anomaly,
        "interpretation_guard": "Context mismatches must be reviewed before treating analytical differences as firmware, mode, modification or vehicle effects.",
        "raw_vehicle_tx": False,
    }
