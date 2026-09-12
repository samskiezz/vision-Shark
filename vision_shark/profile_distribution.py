from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import sqlite3
import stat
import tempfile
import threading
import time
import zipfile
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from pydantic import ValidationError

from .domain import VehiclePack

_BUNDLE_SCHEMA = "vision-shark-profile-bundle-v1"
_TRUST_SCHEMA = "vision-shark-trust-v1"
_FLEET_SCHEMA = "vision-shark-fleet-catalog-v1"
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,95}$")
_EVIDENCE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MAX_PROFILE_BYTES = 2 * 1024 * 1024
_MAX_EVIDENCE_FILE_BYTES = 16 * 1024 * 1024
_MAX_EVIDENCE_TOTAL_BYTES = 64 * 1024 * 1024
_MAX_BUNDLE_BYTES = 80 * 1024 * 1024
_MAX_MANIFEST_BYTES = 256 * 1024
_MAX_CATALOG_BYTES = 4 * 1024 * 1024
_MAX_ZIP_MEMBERS = 68


def _canonical(value) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _token(value: str, label: str) -> str:
    text = str(value)
    if not _ID.fullmatch(text):
        raise ValueError(f"invalid {label}")
    return text


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _atomic_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".profile-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _atomic_copy(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".bundle-", dir=target.parent)
    try:
        with source.open("rb") as src, os.fdopen(fd, "wb") as dst:
            for block in iter(lambda: src.read(1024 * 1024), b""):
                dst.write(block)
            dst.flush()
            os.fsync(dst.fileno())
        os.replace(temporary, target)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100600 << 16
    info.create_system = 3
    return info


def _safe_member(name: str) -> bool:
    if not name or name.startswith(("/", "\\")) or "\\" in name:
        return False
    parts = name.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        return False
    return all(_EVIDENCE_NAME.fullmatch(part) for part in parts)


def _read_zip_member(archive: zipfile.ZipFile, name: str, limit: int) -> bytes:
    with archive.open(name, "r") as handle:
        payload = handle.read(limit + 1)
    if len(payload) > limit:
        raise ValueError(f"bundle member exceeds limit: {name}")
    return payload


def _hash_zip_member(archive: zipfile.ZipFile, name: str, limit: int) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with archive.open(name, "r") as handle:
        while True:
            block = handle.read(1024 * 1024)
            if not block:
                break
            size += len(block)
            if size > limit:
                raise ValueError(f"bundle member exceeds limit: {name}")
            digest.update(block)
    return digest.hexdigest(), size


class TrustedPublishers:
    def __init__(self, keys: dict[str, dict]):
        validated: dict[str, dict] = {}
        for key_id, item in keys.items():
            key_id = _token(key_id, "key id")
            if not isinstance(item, dict):
                raise ValueError("trust-store key entry must be an object")
            publisher = str(item.get("publisher", "")).strip()
            if not publisher or len(publisher) > 128:
                raise ValueError("invalid trusted publisher")
            try:
                raw = base64.b64decode(str(item["public_key"]), validate=True)
                key = Ed25519PublicKey.from_public_bytes(raw)
            except (KeyError, ValueError, TypeError) as exc:
                raise ValueError(f"invalid public key for {key_id}") from exc
            validated[key_id] = {
                "publisher": publisher,
                "public_key": key,
                "public_key_raw": raw,
            }
        if not validated:
            raise ValueError("trust store contains no keys")
        self.keys = validated

    @classmethod
    def from_file(cls, path: str | Path) -> "TrustedPublishers":
        source = Path(path)
        if not source.is_file() or source.stat().st_size > 64 * 1024:
            raise ValueError("trust store must be a regular JSON file no larger than 64 KiB")
        try:
            document = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("invalid trust-store JSON") from exc
        if document.get("schema") != _TRUST_SCHEMA or not isinstance(document.get("keys"), dict):
            raise ValueError("unsupported trust-store schema")
        return cls(document["keys"])

    def resolve(self, key_id: str, publisher: str) -> Ed25519PublicKey:
        key_id = _token(key_id, "key id")
        item = self.keys.get(key_id)
        if item is None:
            raise ValueError(f"untrusted signing key: {key_id}")
        if item["publisher"] != publisher:
            raise ValueError("publisher does not match trusted signing key")
        return item["public_key"]


def load_private_key_file(path: str | Path) -> Ed25519PrivateKey:
    payload = Path(path).read_bytes()
    raw = payload if len(payload) == 32 else None
    if raw is None:
        try:
            raw = base64.b64decode(payload.strip(), validate=True)
        except (ValueError, TypeError) as exc:
            raise ValueError("private key file must contain 32 raw bytes or base64") from exc
    if len(raw) != 32:
        raise ValueError("Ed25519 private key must be 32 bytes")
    return Ed25519PrivateKey.from_private_bytes(raw)


def create_profile_bundle(
    profile: VehiclePack | dict,
    version: int,
    publisher: str,
    key_id: str,
    private_key: Ed25519PrivateKey,
    target: str | Path,
    *,
    evidence: dict[str, bytes] | None = None,
    created_ns: int | None = None,
) -> dict:
    try:
        pack = profile if isinstance(profile, VehiclePack) else VehiclePack.model_validate(profile)
    except ValidationError as exc:
        raise ValueError(f"invalid vehicle profile: {exc}") from exc
    pack_id = _token(pack.pack_id, "pack id")
    version = int(version)
    if version < 1:
        raise ValueError("profile version must be positive")
    publisher = str(publisher).strip()
    if not publisher or len(publisher) > 128:
        raise ValueError("invalid publisher")
    key_id = _token(key_id, "key id")
    created_ns = time.time_ns() if created_ns is None else int(created_ns)
    if created_ns < 0:
        raise ValueError("created_ns must be non-negative")

    profile_bytes = _canonical(pack.model_dump(mode="json"))
    if len(profile_bytes) > _MAX_PROFILE_BYTES:
        raise ValueError("profile JSON exceeds 2 MiB")
    content: dict[str, bytes] = {"profile.json": profile_bytes}
    evidence = dict(evidence or {})
    if len(evidence) > 64:
        raise ValueError("profile bundle contains too many evidence files")
    evidence_total = 0
    for name in sorted(evidence):
        if not _EVIDENCE_NAME.fullmatch(name):
            raise ValueError(f"invalid evidence name: {name}")
        payload = bytes(evidence[name])
        if len(payload) > _MAX_EVIDENCE_FILE_BYTES:
            raise ValueError(f"evidence file exceeds 16 MiB: {name}")
        evidence_total += len(payload)
        if evidence_total > _MAX_EVIDENCE_TOTAL_BYTES:
            raise ValueError("profile evidence exceeds 64 MiB total")
        content[f"evidence/{name}"] = payload

    files = {
        name: {"sha256": _sha256_bytes(payload), "bytes": len(payload)}
        for name, payload in sorted(content.items())
    }
    manifest = {
        "schema": _BUNDLE_SCHEMA,
        "pack_id": pack_id,
        "version": version,
        "publisher": publisher,
        "key_id": key_id,
        "created_ns": created_ns,
        "files": files,
    }
    manifest_bytes = _canonical(manifest)
    signature = private_key.sign(manifest_bytes)
    destination = Path(target)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".vsp-", suffix=".zip", dir=destination.parent)
    os.close(fd)
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            archive.writestr(_zip_info("manifest.json"), manifest_bytes)
            for name in sorted(content):
                archive.writestr(_zip_info(name), content[name])
            archive.writestr(_zip_info("signature.ed25519"), signature)
        os.replace(temporary, destination)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
    if destination.stat().st_size > _MAX_BUNDLE_BYTES:
        destination.unlink(missing_ok=True)
        raise ValueError("profile bundle exceeds 80 MiB")
    return {
        "pack_id": pack_id,
        "version": version,
        "publisher": publisher,
        "key_id": key_id,
        "bundle_sha256": _sha256_path(destination),
        "bundle_bytes": destination.stat().st_size,
        "evidence_files": len(evidence),
        "path": str(destination),
    }


def verify_profile_bundle(path: str | Path, trust: TrustedPublishers) -> dict:
    source = Path(path)
    if not source.is_file():
        raise ValueError("profile bundle must be an existing regular file")
    if source.stat().st_size > _MAX_BUNDLE_BYTES:
        raise ValueError("profile bundle exceeds 80 MiB")
    try:
        archive = zipfile.ZipFile(source, "r")
    except (zipfile.BadZipFile, OSError) as exc:
        raise ValueError("invalid profile bundle ZIP") from exc
    with archive:
        infos = archive.infolist()
        if len(infos) > _MAX_ZIP_MEMBERS:
            raise ValueError("profile bundle contains too many members")
        names = [info.filename for info in infos]
        if len(set(names)) != len(names):
            raise ValueError("profile bundle contains duplicate member names")
        total_uncompressed = 0
        for info in infos:
            if not _safe_member(info.filename):
                raise ValueError(f"unsafe profile bundle member: {info.filename}")
            mode = info.external_attr >> 16
            if mode and stat.S_ISLNK(mode):
                raise ValueError("profile bundle may not contain symbolic links")
            total_uncompressed += info.file_size
            if total_uncompressed > _MAX_EVIDENCE_TOTAL_BYTES + _MAX_PROFILE_BYTES + _MAX_MANIFEST_BYTES + 1024:
                raise ValueError("profile bundle uncompressed content exceeds limit")
        required = {"manifest.json", "profile.json", "signature.ed25519"}
        if not required <= set(names):
            raise ValueError("profile bundle is missing required members")

        manifest_bytes = _read_zip_member(archive, "manifest.json", _MAX_MANIFEST_BYTES)
        try:
            manifest = json.loads(manifest_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("invalid profile bundle manifest") from exc
        if not isinstance(manifest, dict) or manifest.get("schema") != _BUNDLE_SCHEMA:
            raise ValueError("unsupported profile bundle schema")
        pack_id = _token(manifest.get("pack_id", ""), "pack id")
        key_id = _token(manifest.get("key_id", ""), "key id")
        publisher = str(manifest.get("publisher", "")).strip()
        version = int(manifest.get("version", 0))
        if version < 1 or not publisher or len(publisher) > 128:
            raise ValueError("invalid profile bundle identity metadata")
        signature = _read_zip_member(archive, "signature.ed25519", 64)
        if len(signature) != 64:
            raise ValueError("invalid Ed25519 signature length")
        key = trust.resolve(key_id, publisher)
        try:
            key.verify(signature, _canonical(manifest))
        except InvalidSignature as exc:
            raise ValueError("profile bundle signature verification failed") from exc

        files = manifest.get("files")
        if not isinstance(files, dict) or "profile.json" not in files or len(files) > 65:
            raise ValueError("invalid profile bundle file manifest")
        expected_names = set(files) | {"manifest.json", "signature.ed25519"}
        if set(names) != expected_names:
            raise ValueError("profile bundle members do not match signed manifest")
        evidence_rows = []
        for name, spec in files.items():
            if name != "profile.json":
                if not name.startswith("evidence/") or not _safe_member(name):
                    raise ValueError("signed manifest contains an invalid evidence path")
            if not isinstance(spec, dict):
                raise ValueError("invalid signed file metadata")
            expected_sha = str(spec.get("sha256", ""))
            expected_size = int(spec.get("bytes", -1))
            if not _SHA256.fullmatch(expected_sha) or expected_size < 0:
                raise ValueError("invalid signed file digest metadata")
            limit = _MAX_PROFILE_BYTES if name == "profile.json" else _MAX_EVIDENCE_FILE_BYTES
            actual_sha, actual_size = _hash_zip_member(archive, name, limit)
            if actual_sha != expected_sha or actual_size != expected_size:
                raise ValueError(f"profile bundle member integrity failure: {name}")
            if name != "profile.json":
                evidence_rows.append({"name": name.removeprefix("evidence/"), "sha256": actual_sha, "bytes": actual_size})

        profile_bytes = _read_zip_member(archive, "profile.json", _MAX_PROFILE_BYTES)
        try:
            profile = VehiclePack.model_validate_json(profile_bytes)
        except (ValidationError, ValueError) as exc:
            raise ValueError(f"invalid signed vehicle profile: {exc}") from exc
        if profile.pack_id != pack_id:
            raise ValueError("signed manifest pack id does not match profile")
    return {
        "pack_id": pack_id,
        "version": version,
        "publisher": publisher,
        "key_id": key_id,
        "created_ns": int(manifest.get("created_ns", 0)),
        "bundle_sha256": _sha256_path(source),
        "bundle_bytes": source.stat().st_size,
        "profile": profile.model_dump(mode="json"),
        "manifest": manifest,
        "evidence": sorted(evidence_rows, key=lambda row: row["name"]),
    }


class ProfileFleetRegistry:
    def __init__(self, root: str | Path, trust: TrustedPublishers):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.trust = trust
        self.path = self.root / "profiles.sqlite3"
        self._lock = threading.RLock()
        self._db = sqlite3.connect(self.path, check_same_thread=False)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=FULL")
        self._db.execute("PRAGMA foreign_keys=ON")
        self._db.executescript(
            "CREATE TABLE IF NOT EXISTS profiles("
            "pack_id TEXT NOT NULL,version INTEGER NOT NULL,bundle_sha TEXT NOT NULL UNIQUE,"
            "publisher TEXT NOT NULL,key_id TEXT NOT NULL,bundle_relpath TEXT NOT NULL,"
            "profile_json TEXT NOT NULL,manifest_json TEXT NOT NULL,imported_ns INTEGER NOT NULL,"
            "PRIMARY KEY(pack_id,version));"
            "CREATE TABLE IF NOT EXISTS active_profiles("
            "pack_id TEXT PRIMARY KEY,version INTEGER NOT NULL,bundle_sha TEXT NOT NULL);"
            "CREATE TABLE IF NOT EXISTS assignments("
            "vehicle_id TEXT PRIMARY KEY,pack_id TEXT NOT NULL,version INTEGER NOT NULL,"
            "bundle_sha TEXT NOT NULL,updated_ns INTEGER NOT NULL);"
            "CREATE TABLE IF NOT EXISTS peer_state("
            "fleet_id TEXT NOT NULL,publisher TEXT NOT NULL,key_id TEXT NOT NULL,"
            "last_sequence INTEGER NOT NULL,catalog_sha TEXT NOT NULL,assignments_applied INTEGER NOT NULL,"
            "PRIMARY KEY(fleet_id,publisher,key_id));"
        )
        self._db.commit()

    def import_bundle(self, path: str | Path) -> dict:
        verified = verify_profile_bundle(path, self.trust)
        pack_id = verified["pack_id"]
        version = verified["version"]
        digest = verified["bundle_sha256"]
        with self._lock:
            existing = self._db.execute(
                "SELECT bundle_sha,bundle_relpath FROM profiles WHERE pack_id=? AND version=?",
                (pack_id, version),
            ).fetchone()
            if existing:
                if existing[0] != digest:
                    raise ValueError("signed profile version conflicts with an installed digest")
                return {
                    "status": "present",
                    "pack_id": pack_id,
                    "version": version,
                    "bundle_sha256": digest,
                    "path": str(self.root / existing[1]),
                }
            active = self._db.execute(
                "SELECT version FROM active_profiles WHERE pack_id=?", (pack_id,)
            ).fetchone()
            historical = bool(active and version < int(active[0]))
            relative = Path("bundles") / pack_id / f"{version}-{digest}.vsp"
            target = self.root / relative
            _atomic_copy(Path(path), target)
            if _sha256_path(target) != digest:
                target.unlink(missing_ok=True)
                raise ValueError("copied profile bundle digest changed")
            try:
                self._db.execute(
                    "INSERT INTO profiles(pack_id,version,bundle_sha,publisher,key_id,bundle_relpath,profile_json,manifest_json,imported_ns) "
                    "VALUES(?,?,?,?,?,?,?,?,?)",
                    (
                        pack_id,
                        version,
                        digest,
                        verified["publisher"],
                        verified["key_id"],
                        relative.as_posix(),
                        json.dumps(verified["profile"], sort_keys=True, separators=(",", ":")),
                        json.dumps(verified["manifest"], sort_keys=True, separators=(",", ":")),
                        time.time_ns(),
                    ),
                )
                if active is None or version > int(active[0]):
                    self._db.execute(
                        "INSERT INTO active_profiles(pack_id,version,bundle_sha) VALUES(?,?,?) "
                        "ON CONFLICT(pack_id) DO UPDATE SET version=excluded.version,bundle_sha=excluded.bundle_sha",
                        (pack_id, version, digest),
                    )
                self._db.commit()
            except Exception:
                self._db.rollback()
                target.unlink(missing_ok=True)
                raise
        return {
            "status": "imported_historical" if historical else "imported",
            "pack_id": pack_id,
            "version": version,
            "bundle_sha256": digest,
            "path": str(target),
            "active": not historical,
        }

    def assign_vehicle(self, vehicle_id: str, pack_id: str, version: int | None = None) -> dict:
        vehicle_id = _token(vehicle_id, "vehicle id")
        pack_id = _token(pack_id, "pack id")
        with self._lock:
            if version is None:
                row = self._db.execute(
                    "SELECT p.version,p.bundle_sha FROM active_profiles a "
                    "JOIN profiles p ON p.pack_id=a.pack_id AND p.version=a.version "
                    "WHERE a.pack_id=?",
                    (pack_id,),
                ).fetchone()
            else:
                row = self._db.execute(
                    "SELECT version,bundle_sha FROM profiles WHERE pack_id=? AND version=?",
                    (pack_id, int(version)),
                ).fetchone()
            if row is None:
                raise ValueError("requested vehicle profile version is not installed")
            version = int(row[0])
            digest = row[1]
            self._db.execute(
                "INSERT INTO assignments(vehicle_id,pack_id,version,bundle_sha,updated_ns) VALUES(?,?,?,?,?) "
                "ON CONFLICT(vehicle_id) DO UPDATE SET pack_id=excluded.pack_id,version=excluded.version,"
                "bundle_sha=excluded.bundle_sha,updated_ns=excluded.updated_ns",
                (vehicle_id, pack_id, version, digest, time.time_ns()),
            )
            self._db.commit()
        return {"vehicle_id": vehicle_id, "pack_id": pack_id, "version": version, "bundle_sha256": digest}

    def catalog(self) -> dict:
        with self._lock:
            profiles = self._db.execute(
                "SELECT p.pack_id,p.version,p.bundle_sha,p.publisher,p.key_id,p.bundle_relpath,"
                "CASE WHEN a.version=p.version THEN 1 ELSE 0 END "
                "FROM profiles p LEFT JOIN active_profiles a ON a.pack_id=p.pack_id "
                "ORDER BY p.pack_id,p.version"
            ).fetchall()
            assignments = self._db.execute(
                "SELECT vehicle_id,pack_id,version,bundle_sha FROM assignments ORDER BY vehicle_id"
            ).fetchall()
        return {
            "profiles": [
                {
                    "pack_id": row[0],
                    "version": row[1],
                    "bundle_sha256": row[2],
                    "publisher": row[3],
                    "key_id": row[4],
                    "bundle_relpath": row[5],
                    "active": bool(row[6]),
                }
                for row in profiles
            ],
            "assignments": [
                {"vehicle_id": row[0], "pack_id": row[1], "version": row[2], "bundle_sha256": row[3]}
                for row in assignments
            ],
        }

    def peer_state(self, fleet_id: str, publisher: str, key_id: str) -> dict | None:
        with self._lock:
            row = self._db.execute(
                "SELECT last_sequence,catalog_sha,assignments_applied FROM peer_state "
                "WHERE fleet_id=? AND publisher=? AND key_id=?",
                (fleet_id, publisher, key_id),
            ).fetchone()
        if row is None:
            return None
        return {"last_sequence": row[0], "catalog_sha256": row[1], "assignments_applied": bool(row[2])}

    def record_peer_state(self, payload: dict, catalog_sha: str, assignments_applied: bool) -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO peer_state(fleet_id,publisher,key_id,last_sequence,catalog_sha,assignments_applied) "
                "VALUES(?,?,?,?,?,?) ON CONFLICT(fleet_id,publisher,key_id) DO UPDATE SET "
                "last_sequence=excluded.last_sequence,catalog_sha=excluded.catalog_sha,"
                "assignments_applied=MAX(peer_state.assignments_applied,excluded.assignments_applied)",
                (
                    payload["fleet_id"],
                    payload["publisher"],
                    payload["key_id"],
                    payload["sequence"],
                    catalog_sha,
                    1 if assignments_applied else 0,
                ),
            )
            self._db.commit()

    def close(self) -> None:
        with self._lock:
            self._db.close()


def sign_fleet_catalog(
    registry: ProfileFleetRegistry,
    fleet_id: str,
    sequence: int,
    publisher: str,
    key_id: str,
    private_key: Ed25519PrivateKey,
    target: str | Path,
    *,
    generated_ns: int | None = None,
) -> dict:
    fleet_id = _token(fleet_id, "fleet id")
    key_id = _token(key_id, "key id")
    publisher = str(publisher).strip()
    sequence = int(sequence)
    if not publisher or len(publisher) > 128 or sequence < 1:
        raise ValueError("invalid fleet catalog identity metadata")
    catalog = registry.catalog()
    payload = {
        "schema": _FLEET_SCHEMA,
        "fleet_id": fleet_id,
        "sequence": sequence,
        "publisher": publisher,
        "key_id": key_id,
        "generated_ns": time.time_ns() if generated_ns is None else int(generated_ns),
        "profiles": catalog["profiles"],
        "assignments": catalog["assignments"],
    }
    signature = private_key.sign(_canonical(payload))
    envelope = {"payload": payload, "signature": base64.b64encode(signature).decode("ascii")}
    encoded = _canonical(envelope)
    if len(encoded) > _MAX_CATALOG_BYTES:
        raise ValueError("fleet catalog exceeds 4 MiB")
    destination = Path(target)
    _atomic_bytes(destination, encoded)
    return {
        "fleet_id": fleet_id,
        "sequence": sequence,
        "catalog_sha256": _sha256_bytes(encoded),
        "profiles": len(payload["profiles"]),
        "assignments": len(payload["assignments"]),
        "path": str(destination),
    }


def verify_fleet_catalog(path: str | Path, trust: TrustedPublishers) -> dict:
    source = Path(path)
    if not source.is_file() or source.stat().st_size > _MAX_CATALOG_BYTES:
        raise ValueError("fleet catalog must be a regular JSON file no larger than 4 MiB")
    encoded = source.read_bytes()
    try:
        envelope = json.loads(encoded.decode("utf-8"))
        payload = envelope["payload"]
        signature = base64.b64decode(envelope["signature"], validate=True)
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise ValueError("invalid signed fleet catalog") from exc
    if not isinstance(payload, dict) or payload.get("schema") != _FLEET_SCHEMA:
        raise ValueError("unsupported fleet catalog schema")
    fleet_id = _token(payload.get("fleet_id", ""), "fleet id")
    key_id = _token(payload.get("key_id", ""), "key id")
    publisher = str(payload.get("publisher", "")).strip()
    sequence = int(payload.get("sequence", 0))
    if sequence < 1 or not publisher or len(signature) != 64:
        raise ValueError("invalid fleet catalog identity metadata")
    key = trust.resolve(key_id, publisher)
    try:
        key.verify(signature, _canonical(payload))
    except InvalidSignature as exc:
        raise ValueError("fleet catalog signature verification failed") from exc

    profiles = payload.get("profiles")
    assignments = payload.get("assignments")
    if not isinstance(profiles, list) or not isinstance(assignments, list):
        raise ValueError("fleet catalog profiles and assignments must be arrays")
    profile_keys: set[tuple[str, int]] = set()
    profile_digests: dict[tuple[str, int], str] = {}
    active_by_pack: set[str] = set()
    for item in profiles:
        if not isinstance(item, dict):
            raise ValueError("invalid fleet profile entry")
        pack_id = _token(item.get("pack_id", ""), "pack id")
        version = int(item.get("version", 0))
        digest = str(item.get("bundle_sha256", ""))
        relpath = str(item.get("bundle_relpath", ""))
        _token(item.get("key_id", ""), "key id")
        if version < 1 or not _SHA256.fullmatch(digest) or not _safe_member(relpath):
            raise ValueError("invalid fleet profile metadata")
        expected_prefix = f"bundles/{pack_id}/"
        if not relpath.startswith(expected_prefix):
            raise ValueError("fleet bundle path does not match pack id")
        key = (pack_id, version)
        if key in profile_keys:
            raise ValueError("duplicate fleet profile version")
        profile_keys.add(key)
        profile_digests[key] = digest
        if bool(item.get("active")):
            if pack_id in active_by_pack:
                raise ValueError("fleet catalog has multiple active versions for one pack")
            active_by_pack.add(pack_id)
    vehicle_ids: set[str] = set()
    for item in assignments:
        if not isinstance(item, dict):
            raise ValueError("invalid fleet assignment entry")
        vehicle_id = _token(item.get("vehicle_id", ""), "vehicle id")
        pack_id = _token(item.get("pack_id", ""), "pack id")
        version = int(item.get("version", 0))
        digest = str(item.get("bundle_sha256", ""))
        if vehicle_id in vehicle_ids:
            raise ValueError("duplicate fleet vehicle assignment")
        vehicle_ids.add(vehicle_id)
        if profile_digests.get((pack_id, version)) != digest:
            raise ValueError("fleet assignment references a missing or mismatched profile")
    return {
        "fleet_id": fleet_id,
        "payload": payload,
        "catalog_sha256": _sha256_bytes(encoded),
        "path": str(source),
    }


def build_fleet_sync_plan(registry: ProfileFleetRegistry, verified_catalog: dict) -> dict:
    remote = verified_catalog["payload"]
    local = registry.catalog()
    local_profiles = {(item["pack_id"], item["version"]): item for item in local["profiles"]}
    local_assignments = {item["vehicle_id"]: item for item in local["assignments"]}
    request = []
    conflicts = []
    for item in remote["profiles"]:
        key = (item["pack_id"], int(item["version"]))
        present = local_profiles.get(key)
        if present is None:
            request.append(item)
        elif present["bundle_sha256"] != item["bundle_sha256"]:
            conflicts.append({"pack_id": key[0], "version": key[1], "local": present["bundle_sha256"], "remote": item["bundle_sha256"]})
    assignment_changes = []
    for item in remote["assignments"]:
        current = local_assignments.get(item["vehicle_id"])
        if current != item:
            assignment_changes.append({"current": current, "remote": item})
    return {
        "fleet_id": remote["fleet_id"],
        "sequence": remote["sequence"],
        "bundles_required": sorted(request, key=lambda row: (row["pack_id"], row["version"])),
        "digest_conflicts": sorted(conflicts, key=lambda row: (row["pack_id"], row["version"])),
        "assignment_changes": sorted(assignment_changes, key=lambda row: row["remote"]["vehicle_id"]),
    }


def _peer_path(peer_root: Path, relative: str) -> Path:
    root = peer_root.resolve()
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError("fleet catalog bundle path escapes peer root") from exc
    return candidate


def sync_from_peer_directory(
    registry: ProfileFleetRegistry,
    peer_root: str | Path,
    catalog_path: str | Path,
    *,
    apply_assignments: bool = False,
) -> dict:
    verified = verify_fleet_catalog(catalog_path, registry.trust)
    payload = verified["payload"]
    prior = registry.peer_state(payload["fleet_id"], payload["publisher"], payload["key_id"])
    if prior:
        if payload["sequence"] < prior["last_sequence"]:
            raise ValueError("fleet catalog rollback rejected")
        if payload["sequence"] == prior["last_sequence"] and verified["catalog_sha256"] != prior["catalog_sha256"]:
            raise ValueError("fleet catalog sequence conflicts with previously accepted digest")
    plan = build_fleet_sync_plan(registry, verified)
    if plan["digest_conflicts"]:
        raise ValueError("fleet synchronization stopped on signed profile digest conflict")
    imported = []
    peer_root = Path(peer_root)
    for item in plan["bundles_required"]:
        bundle_path = _peer_path(peer_root, item["bundle_relpath"])
        result = registry.import_bundle(bundle_path)
        if result["bundle_sha256"] != item["bundle_sha256"]:
            raise ValueError("imported peer bundle digest does not match signed fleet catalog")
        imported.append(result)

    assignments = []
    if apply_assignments:
        for item in payload["assignments"]:
            row = registry._db.execute(
                "SELECT bundle_sha FROM profiles WHERE pack_id=? AND version=?",
                (item["pack_id"], int(item["version"])),
            ).fetchone()
            if row is None or row[0] != item["bundle_sha256"]:
                raise ValueError("fleet assignment cannot be applied before its exact profile bundle is installed")
            assignments.append(registry.assign_vehicle(item["vehicle_id"], item["pack_id"], int(item["version"])))
    registry.record_peer_state(payload, verified["catalog_sha256"], apply_assignments)
    after = build_fleet_sync_plan(registry, verified)
    return {
        "fleet_id": payload["fleet_id"],
        "sequence": payload["sequence"],
        "catalog_sha256": verified["catalog_sha256"],
        "imported": imported,
        "assignments_applied": assignments,
        "remaining_plan": after,
        "idempotent_catalog": bool(prior and payload["sequence"] == prior["last_sequence"]),
    }
