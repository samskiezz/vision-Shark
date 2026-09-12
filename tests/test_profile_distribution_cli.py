import base64
import json

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from vision_shark.main import main


def _signing_material(tmp_path, name="lab"):
    private = Ed25519PrivateKey.generate()
    private_raw = private.private_bytes(
        serialization.Encoding.Raw,
        serialization.PrivateFormat.Raw,
        serialization.NoEncryption(),
    )
    public_raw = private.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
    private_path = tmp_path / f"{name}.key"
    trust_path = tmp_path / f"{name}-trust.json"
    private_path.write_bytes(private_raw)
    trust_path.write_text(
        json.dumps(
            {
                "schema": "vision-shark-trust-v1",
                "keys": {
                    "lab-key": {
                        "publisher": "Vision Lab",
                        "public_key": base64.b64encode(public_raw).decode("ascii"),
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    return private_path, trust_path


def _profile_file(tmp_path):
    profile = tmp_path / "profile.json"
    profile.write_text(
        json.dumps(
            {
                "pack_id": "shark-au-research",
                "name": "Australian Shark research profile",
                "scope": "research-unvalidated",
                "signals": [{"name": "vehicle.speed", "status": "hypothesis"}],
                "fingerprints": [{"status": "hypothesis"}],
                "evidence": [{"kind": "capture-note"}],
            }
        ),
        encoding="utf-8",
    )
    return profile


def test_profile_and_fleet_cli_end_to_end(tmp_path, capsys):
    private_path, trust_path = _signing_material(tmp_path)
    profile_path = _profile_file(tmp_path)
    evidence_path = tmp_path / "capture-note.txt"
    evidence_path.write_text("bench capture evidence", encoding="utf-8")
    bundle_path = tmp_path / "shark-v1.vsp"

    assert main(
        [
            "profile-bundle-create",
            "--profile",
            str(profile_path),
            "--version",
            "1",
            "--publisher",
            "Vision Lab",
            "--key-id",
            "lab-key",
            "--private-key-file",
            str(private_path),
            "--trust-store",
            str(trust_path),
            "--output",
            str(bundle_path),
            "--evidence",
            f"capture-note.txt={evidence_path}",
        ]
    ) == 0
    created = json.loads(capsys.readouterr().out)
    assert created["verified"] is True
    assert created["pack_id"] == "shark-au-research"
    assert bundle_path.is_file()

    assert main(
        [
            "profile-bundle-verify",
            "--trust-store",
            str(trust_path),
            "--bundle",
            str(bundle_path),
        ]
    ) == 0
    verified = json.loads(capsys.readouterr().out)
    assert verified["verified"] is True
    assert verified["evidence"][0]["name"] == "capture-note.txt"

    origin = tmp_path / "origin"
    assert main(
        [
            "profile-import",
            "--registry-dir",
            str(origin),
            "--trust-store",
            str(trust_path),
            "--bundle",
            str(bundle_path),
        ]
    ) == 0
    imported = json.loads(capsys.readouterr().out)
    assert imported["version"] == 1

    assert main(
        [
            "fleet-assign",
            "--registry-dir",
            str(origin),
            "--trust-store",
            str(trust_path),
            "--vehicle-id",
            "shark-001",
            "--pack-id",
            "shark-au-research",
        ]
    ) == 0
    assignment = json.loads(capsys.readouterr().out)
    assert assignment["vehicle_id"] == "shark-001"

    assert main(
        [
            "fleet-status",
            "--registry-dir",
            str(origin),
            "--trust-store",
            str(trust_path),
        ]
    ) == 0
    origin_status = json.loads(capsys.readouterr().out)
    assert len(origin_status["profiles"]) == 1
    assert origin_status["profiles"][0]["active"] is True
    assert origin_status["assignments"][0]["vehicle_id"] == "shark-001"

    catalog_path = origin / "fleet.json"
    assert main(
        [
            "fleet-catalog-export",
            "--registry-dir",
            str(origin),
            "--trust-store",
            str(trust_path),
            "--fleet-id",
            "test-fleet",
            "--sequence",
            "1",
            "--publisher",
            "Vision Lab",
            "--key-id",
            "lab-key",
            "--private-key-file",
            str(private_path),
            "--output",
            str(catalog_path),
        ]
    ) == 0
    catalog = json.loads(capsys.readouterr().out)
    assert catalog["verified"] is True
    assert catalog["profiles"] == 1
    assert catalog["assignments"] == 1

    assert main(
        [
            "fleet-catalog-verify",
            "--trust-store",
            str(trust_path),
            "--catalog",
            str(catalog_path),
        ]
    ) == 0
    catalog_verify = json.loads(capsys.readouterr().out)
    assert catalog_verify["fleet_id"] == "test-fleet"
    assert catalog_verify["verified"] is True

    target = tmp_path / "target"
    assert main(
        [
            "fleet-sync",
            "--registry-dir",
            str(target),
            "--trust-store",
            str(trust_path),
            "--peer-root",
            str(origin),
            "--catalog",
            str(catalog_path),
            "--apply-assignments",
        ]
    ) == 0
    synced = json.loads(capsys.readouterr().out)
    assert len(synced["imported"]) == 1
    assert len(synced["assignments_applied"]) == 1
    assert synced["remaining_plan"]["bundles_required"] == []
    assert synced["remaining_plan"]["assignment_changes"] == []

    assert main(
        [
            "fleet-sync",
            "--registry-dir",
            str(target),
            "--trust-store",
            str(trust_path),
            "--peer-root",
            str(origin),
            "--catalog",
            str(catalog_path),
            "--apply-assignments",
        ]
    ) == 0
    repeated = json.loads(capsys.readouterr().out)
    assert repeated["idempotent_catalog"] is True
    assert repeated["imported"] == []


def test_profile_bundle_cli_rejects_untrusted_signer_and_removes_output(tmp_path, capsys):
    private_path, _ = _signing_material(tmp_path, "signer")
    _, wrong_trust = _signing_material(tmp_path, "wrong")
    profile_path = _profile_file(tmp_path)
    output = tmp_path / "should-not-remain.vsp"

    assert main(
        [
            "profile-bundle-create",
            "--profile",
            str(profile_path),
            "--version",
            "1",
            "--publisher",
            "Vision Lab",
            "--key-id",
            "lab-key",
            "--private-key-file",
            str(private_path),
            "--trust-store",
            str(wrong_trust),
            "--output",
            str(output),
        ]
    ) == 2
    captured = capsys.readouterr()
    assert "verification failed" in captured.err.lower()
    assert not output.exists()
