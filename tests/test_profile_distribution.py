from __future__ import annotations

import base64
import json
import zipfile
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from vision_shark.domain import VehiclePack
from vision_shark.profile_distribution import (
    ProfileFleetRegistry,
    TrustedPublishers,
    build_fleet_sync_plan,
    create_profile_bundle,
    sign_fleet_catalog,
    sync_from_peer_directory,
    verify_fleet_catalog,
    verify_profile_bundle,
)


def _trust(tmp_path: Path, publisher: str = "Vision Lab", key_id: str = "lab-key"):
    tmp_path.mkdir(parents=True, exist_ok=True)
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
    path = tmp_path / "trust.json"
    path.write_text(
        json.dumps(
            {
                "schema": "vision-shark-trust-v1",
                "keys": {
                    key_id: {
                        "publisher": publisher,
                        "public_key": base64.b64encode(public).decode("ascii"),
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    return private, TrustedPublishers.from_file(path), path


def _pack(pack_id: str = "shark-au-research") -> VehiclePack:
    return VehiclePack(
        pack_id=pack_id,
        name="Australian Shark research profile",
        scope="research-unvalidated",
        signals=[{"name": "Vehicle.Speed", "status": "hypothesis"}],
        fingerprints=[{"kind": "structural", "status": "hypothesis"}],
        evidence=[{"name": "capture-note.txt", "purpose": "operator evidence"}],
    )


def _bundle(
    root: Path,
    private: Ed25519PrivateKey,
    *,
    version: int,
    evidence_text: str,
    pack_id: str = "shark-au-research",
) -> Path:
    path = root / f"source-v{version}-{evidence_text}.vsp"
    create_profile_bundle(
        _pack(pack_id),
        version,
        "Vision Lab",
        "lab-key",
        private,
        path,
        evidence={"capture-note.txt": evidence_text.encode("utf-8")},
        created_ns=1_800_000_000_000_000_000 + version,
    )
    return path


def _rewrite_member(source: Path, target: Path, member: str, replacement: bytes) -> None:
    with zipfile.ZipFile(source, "r") as original, zipfile.ZipFile(target, "w") as modified:
        for info in original.infolist():
            payload = replacement if info.filename == member else original.read(info.filename)
            modified.writestr(info.filename, payload)


def test_signed_profile_bundle_roundtrip_and_evidence_hashes(tmp_path):
    private, trust, _ = _trust(tmp_path)
    bundle = _bundle(tmp_path, private, version=1, evidence_text="capture-a")

    verified = verify_profile_bundle(bundle, trust)
    assert verified["pack_id"] == "shark-au-research"
    assert verified["version"] == 1
    assert verified["profile"]["scope"] == "research-unvalidated"
    assert verified["evidence"][0]["name"] == "capture-note.txt"
    assert verified["evidence"][0]["bytes"] == len(b"capture-a")
    assert len(verified["bundle_sha256"]) == 64


def test_bundle_tampering_and_publisher_mismatch_fail_closed(tmp_path):
    private, trust, _ = _trust(tmp_path)
    bundle = _bundle(tmp_path, private, version=1, evidence_text="original")
    tampered = tmp_path / "tampered.vsp"
    _rewrite_member(bundle, tampered, "evidence/capture-note.txt", b"altered")

    with pytest.raises(ValueError, match="integrity failure"):
        verify_profile_bundle(tampered, trust)

    _, wrong_trust, _ = _trust(tmp_path / "other", publisher="Another Publisher")
    with pytest.raises(ValueError, match="publisher does not match"):
        verify_profile_bundle(bundle, wrong_trust)


def test_registry_is_idempotent_and_active_profile_never_rolls_back(tmp_path):
    private, trust, _ = _trust(tmp_path)
    registry = ProfileFleetRegistry(tmp_path / "registry", trust)
    try:
        v2 = _bundle(tmp_path, private, version=2, evidence_text="new")
        v1 = _bundle(tmp_path, private, version=1, evidence_text="old")
        first = registry.import_bundle(v2)
        historical = registry.import_bundle(v1)
        repeated = registry.import_bundle(v2)

        assert first["status"] == "imported"
        assert historical["status"] == "imported_historical"
        assert historical["active"] is False
        assert repeated["status"] == "present"
        catalog = registry.catalog()
        active = [row for row in catalog["profiles"] if row["active"]]
        assert [(row["pack_id"], row["version"]) for row in active] == [
            ("shark-au-research", 2)
        ]

        conflicting = _bundle(tmp_path, private, version=2, evidence_text="different")
        with pytest.raises(ValueError, match="conflicts"):
            registry.import_bundle(conflicting)
    finally:
        registry.close()


def test_signed_fleet_catalog_syncs_bundles_and_vehicle_assignments(tmp_path):
    private, trust, _ = _trust(tmp_path)
    origin = ProfileFleetRegistry(tmp_path / "origin", trust)
    target = ProfileFleetRegistry(tmp_path / "target", trust)
    try:
        origin.import_bundle(_bundle(tmp_path, private, version=1, evidence_text="one"))
        origin.import_bundle(_bundle(tmp_path, private, version=2, evidence_text="two"))
        origin.assign_vehicle("shark-001", "shark-au-research", 2)
        origin.assign_vehicle("shark-002", "shark-au-research", 1)

        catalog_path = tmp_path / "origin" / "fleet-catalog.json"
        signed = sign_fleet_catalog(
            origin,
            "project-solar-fleet",
            7,
            "Vision Lab",
            "lab-key",
            private,
            catalog_path,
            generated_ns=1_900_000_000_000_000_000,
        )
        verified = verify_fleet_catalog(catalog_path, trust)
        before = build_fleet_sync_plan(target, verified)
        assert len(before["bundles_required"]) == 2
        assert len(before["assignment_changes"]) == 2
        assert before["digest_conflicts"] == []

        result = sync_from_peer_directory(
            target,
            tmp_path / "origin",
            catalog_path,
            apply_assignments=True,
        )
        assert result["sequence"] == 7
        assert len(result["imported"]) == 2
        assert len(result["assignments_applied"]) == 2
        assert result["remaining_plan"]["bundles_required"] == []
        assert result["remaining_plan"]["assignment_changes"] == []
        assert signed["catalog_sha256"] == result["catalog_sha256"]

        target_catalog = target.catalog()
        assignments = {row["vehicle_id"]: row for row in target_catalog["assignments"]}
        assert assignments["shark-001"]["version"] == 2
        assert assignments["shark-002"]["version"] == 1
        active = [row for row in target_catalog["profiles"] if row["active"]]
        assert active[0]["version"] == 2
    finally:
        origin.close()
        target.close()


def test_fleet_sequence_replay_and_same_sequence_equivocation_are_rejected(tmp_path):
    private, trust, _ = _trust(tmp_path)
    origin = ProfileFleetRegistry(tmp_path / "origin", trust)
    target = ProfileFleetRegistry(tmp_path / "target", trust)
    try:
        origin.import_bundle(_bundle(tmp_path, private, version=1, evidence_text="one"))
        current = tmp_path / "origin" / "current.json"
        sign_fleet_catalog(
            origin,
            "fleet-a",
            10,
            "Vision Lab",
            "lab-key",
            private,
            current,
            generated_ns=100,
        )
        sync_from_peer_directory(target, tmp_path / "origin", current)

        old = tmp_path / "origin" / "old.json"
        sign_fleet_catalog(
            origin,
            "fleet-a",
            9,
            "Vision Lab",
            "lab-key",
            private,
            old,
            generated_ns=90,
        )
        with pytest.raises(ValueError, match="rollback"):
            sync_from_peer_directory(target, tmp_path / "origin", old)

        equivocation = tmp_path / "origin" / "equivocation.json"
        sign_fleet_catalog(
            origin,
            "fleet-a",
            10,
            "Vision Lab",
            "lab-key",
            private,
            equivocation,
            generated_ns=101,
        )
        with pytest.raises(ValueError, match="sequence conflicts"):
            sync_from_peer_directory(target, tmp_path / "origin", equivocation)
    finally:
        origin.close()
        target.close()


def test_catalog_signature_tampering_is_rejected(tmp_path):
    private, trust, _ = _trust(tmp_path)
    registry = ProfileFleetRegistry(tmp_path / "registry", trust)
    try:
        registry.import_bundle(_bundle(tmp_path, private, version=1, evidence_text="one"))
        catalog = tmp_path / "catalog.json"
        sign_fleet_catalog(
            registry,
            "fleet-a",
            1,
            "Vision Lab",
            "lab-key",
            private,
            catalog,
            generated_ns=100,
        )
        document = json.loads(catalog.read_text())
        document["payload"]["sequence"] = 2
        catalog.write_text(json.dumps(document), encoding="utf-8")
        with pytest.raises(ValueError, match="signature verification"):
            verify_fleet_catalog(catalog, trust)
    finally:
        registry.close()
