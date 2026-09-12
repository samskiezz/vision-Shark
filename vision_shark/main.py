import argparse
import importlib.util
import json
import os
import platform
import secrets
import shutil
import socket
import sys
from pathlib import Path

from . import __version__


def _doctor_report():
    from .adapter_discovery import discover_j2534_registry, network_interfaces

    interfaces = network_interfaces()
    j2534 = discover_j2534_registry()
    return {
        "app_version": __version__,
        "python": platform.python_version(),
        "python_supported": sys.version_info >= (3, 11),
        "os": platform.platform(),
        "network_interfaces": interfaces,
        "ethernet_ipv4_ready": any(x.get("ipv4") for x in interfaces),
        "socketcan_os_available": hasattr(socket, "AF_CAN"),
        "linux_ip_tool": bool(shutil.which("ip")),
        "parquet_interchange_available": importlib.util.find_spec("pyarrow") is not None,
        "database_interchange_available": importlib.util.find_spec("canmatrix") is not None,
        "mf4_interchange_available": importlib.util.find_spec("asammdf") is not None,
        "j2534_providers": [
            {"interface": x.interface, "endpoint": x.endpoint, "metadata": x.metadata}
            for x in j2534
        ],
        "vehicle_validation": "not_performed",
        "server_security": "token session + role + CSRF + idempotency on vision-shark serve",
        "next_step": "connect the OBD adapter and vehicle, then run vision-shark probe --prove-diagnostics",
    }


def _parquet_export(args) -> int:
    from .large_interchange import LargeInterchangeUnavailable, write_parquet
    from .storage import RecordingStore

    store = RecordingStore(Path(args.data_dir))
    try:
        if not any(row["id"] == args.recording_id for row in store.list_recordings()):
            print(f"recording {args.recording_id} does not exist", file=sys.stderr)
            return 2
        result = write_parquet(
            store.iter_frames(args.recording_id, batch_size=args.batch_size),
            Path(args.output),
            row_group_size=args.row_group_size,
        )
        result["recording_id"] = args.recording_id
        print(json.dumps(result, indent=2))
        return 0
    except (LargeInterchangeUnavailable, OSError, ValueError) as exc:
        print(f"Parquet export failed: {exc}", file=sys.stderr)
        return 2
    finally:
        store.close()


def _parquet_import(args) -> int:
    from .large_interchange import LargeInterchangeUnavailable, iter_parquet, parquet_info
    from .storage import RecordingStore

    source = Path(args.input)
    store = RecordingStore(Path(args.data_dir))
    recording_id = None
    try:
        info = parquet_info(source)
        recording_id = store.start_recording(
            "import",
            "parquet",
            {
                "import_format": "parquet",
                "source_path": str(source),
                "frame_count_expected": info["rows"],
                "schema": info["format"],
            },
        )
        count = store.append_frames_streaming(
            recording_id,
            iter_parquet(source, batch_size=args.batch_size, max_frames=args.max_frames),
            batch_size=args.batch_size,
        )
        store.stop_recording(
            recording_id,
            {"capture_complete": True, "imported": True, "imported_frames": count},
        )
        print(json.dumps({"recording_id": recording_id, "frames": count, "source": str(source), "schema": info["format"]}, indent=2))
        return 0
    except (LargeInterchangeUnavailable, OSError, ValueError) as exc:
        if recording_id is not None:
            store.stop_recording(recording_id, {"capture_complete": False, "imported": True, "import_error": str(exc)})
        print(f"Parquet import failed: {exc}", file=sys.stderr)
        return 2
    finally:
        store.close()


def _database_inspect(args) -> int:
    from .database_interchange import DatabaseInterchangeUnavailable, inspect_database

    try:
        result = inspect_database(Path(args.input), args.format)
    except (DatabaseInterchangeUnavailable, OSError, ValueError) as exc:
        print(f"Database inspection failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 0


def _database_convert(args) -> int:
    from .database_interchange import DatabaseInterchangeUnavailable, convert_to_dbc

    if args.to.lower().lstrip(".") != "dbc":
        print("Database conversion currently normalizes reviewed inputs to DBC", file=sys.stderr)
        return 2
    try:
        result = convert_to_dbc(Path(args.input), args.format, Path(args.output_dir))
    except (DatabaseInterchangeUnavailable, OSError, ValueError) as exc:
        print(f"Database conversion failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 0 if result["all_core_semantics_preserved"] else 3


def _mf4_inspect(args) -> int:
    from .mf4_interchange import Mf4InterchangeUnavailable, inspect_mf4

    try:
        result = inspect_mf4(Path(args.input))
    except (Mf4InterchangeUnavailable, OSError, ValueError) as exc:
        print(f"MF4 inspection failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 0


def _mf4_import_can(args) -> int:
    from .mf4_interchange import Mf4InterchangeUnavailable, inspect_mf4, iter_mf4_can_frames
    from .storage import RecordingStore

    source = Path(args.input)
    store = RecordingStore(Path(args.data_dir))
    recording_id = None
    try:
        info = inspect_mf4(source)
        if info["importable_data_groups"] < 1:
            raise ValueError("MDF file has no importable explicit CAN_DataFrame bus-event groups")
        recording_id = store.start_recording(
            "import",
            "mf4-can",
            {
                "import_format": "mf4-can-bus-event",
                "source_path": str(source),
                "source_sha256": info["source_sha256"],
                "source_bytes": info["source_bytes"],
                "mdf_version": info["mdf_version"],
                "frame_count_expected": info["importable_data_cycles"],
                "remote_groups_detected_not_imported": info["remote_groups_detected_not_imported"],
                "error_groups_detected_not_imported": info["error_groups_detected_not_imported"],
            },
        )
        count = store.append_frames_streaming(
            recording_id,
            iter_mf4_can_frames(source, batch_size=args.batch_size, max_frames=args.max_frames),
            batch_size=args.batch_size,
        )
        store.stop_recording(
            recording_id,
            {
                "capture_complete": True,
                "imported": True,
                "imported_frames": count,
                "raw_can_scope": "CAN_DataFrame only",
            },
        )
        print(json.dumps({"recording_id": recording_id, "frames": count, "source_sha256": info["source_sha256"], "remote_groups_not_imported": info["remote_groups_detected_not_imported"], "error_groups_not_imported": info["error_groups_detected_not_imported"]}, indent=2))
        return 0
    except (Mf4InterchangeUnavailable, OSError, ValueError) as exc:
        if recording_id is not None:
            store.stop_recording(recording_id, {"capture_complete": False, "imported": True, "import_error": str(exc)})
        print(f"MF4 raw CAN import failed: {exc}", file=sys.stderr)
        return 2
    finally:
        store.close()


def main(argv=None):
    parser = argparse.ArgumentParser(prog="vision-shark")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve")
    serve.add_argument("--data-dir", default=os.getenv("VISION_DATA_DIR", "data"))
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8787)
    sub.add_parser("doctor")

    probe = sub.add_parser("probe")
    probe.add_argument("--prove-diagnostics", action="store_true")
    probe.add_argument("--timeout", type=float, default=0.75)

    parquet_export = sub.add_parser("parquet-export")
    parquet_export.add_argument("--data-dir", default=os.getenv("VISION_DATA_DIR", "data"))
    parquet_export.add_argument("--recording-id", type=int, required=True)
    parquet_export.add_argument("--output", required=True)
    parquet_export.add_argument("--batch-size", type=int, default=4096)
    parquet_export.add_argument("--row-group-size", type=int, default=65_536)

    parquet_import = sub.add_parser("parquet-import")
    parquet_import.add_argument("--data-dir", default=os.getenv("VISION_DATA_DIR", "data"))
    parquet_import.add_argument("--input", required=True)
    parquet_import.add_argument("--batch-size", type=int, default=4096)
    parquet_import.add_argument("--max-frames", type=int, default=10_000_000)

    db_inspect = sub.add_parser("db-inspect")
    db_inspect.add_argument("--input", required=True)
    db_inspect.add_argument("--format", required=True)

    db_convert = sub.add_parser("db-convert")
    db_convert.add_argument("--input", required=True)
    db_convert.add_argument("--format", required=True)
    db_convert.add_argument("--to", default="dbc")
    db_convert.add_argument("--output-dir", required=True)

    mf4_inspect = sub.add_parser("mf4-inspect")
    mf4_inspect.add_argument("--input", required=True)

    mf4_import = sub.add_parser("mf4-import-can")
    mf4_import.add_argument("--data-dir", default=os.getenv("VISION_DATA_DIR", "data"))
    mf4_import.add_argument("--input", required=True)
    mf4_import.add_argument("--batch-size", type=int, default=4096)
    mf4_import.add_argument("--max-frames", type=int, default=10_000_000)

    args = parser.parse_args(argv)

    if args.command == "doctor":
        print(json.dumps(_doctor_report(), indent=2))
        return 0
    if args.command == "parquet-export":
        return _parquet_export(args)
    if args.command == "parquet-import":
        return _parquet_import(args)
    if args.command == "db-inspect":
        return _database_inspect(args)
    if args.command == "db-convert":
        return _database_convert(args)
    if args.command == "mf4-inspect":
        return _mf4_inspect(args)
    if args.command == "mf4-import-can":
        return _mf4_import_can(args)

    if args.command == "probe":
        from .adapter_discovery import discover_adapters, discover_doip

        if args.timeout <= 0 or args.timeout > 10:
            parser.error("--timeout must be >0 and <=10 seconds")
        found = discover_adapters(include_doip=False, include_j2534=True)
        found.extend(x.as_dict() for x in discover_doip(args.timeout))
        found.sort(key=lambda x: (bool(x.get("usable")), x.get("confidence", 0)), reverse=True)
        report = {"adapters": found, "usable": sum(1 for x in found if x.get("usable", True)), "diagnostic_proofs": []}
        if args.prove_diagnostics:
            from .doip_transport import DoIPError, DoIPReadOnlyClient

            for item in found:
                if item.get("transport") != "doip" or not item.get("usable", True):
                    continue
                try:
                    proof = DoIPReadOnlyClient(item["endpoint"], item["logical_address"]).prove_readonly_session()
                    report["diagnostic_proofs"].append({"endpoint": item["endpoint"], "logical_address": item["logical_address"], "ok": True, "proof": proof})
                except (DoIPError, OSError, TimeoutError, ValueError) as exc:
                    report["diagnostic_proofs"].append({"endpoint": item.get("endpoint"), "logical_address": item.get("logical_address"), "ok": False, "error": f"{type(exc).__name__}: {exc}"})
        print(json.dumps(report, indent=2))
        if args.prove_diagnostics:
            return 0 if any(x.get("ok") for x in report["diagnostic_proofs"]) else 2
        return 0 if report["usable"] else 2

    if args.command == "serve":
        if args.host not in ("127.0.0.1", "localhost", "::1"):
            parser.error("This build is loopback-only; use a separately authenticated/TLS deployment for LAN access")
        admin_token = os.getenv("VISION_API_TOKEN")
        generated = not bool(admin_token)
        if generated:
            admin_token = secrets.token_urlsafe(32)
        viewer_token = os.getenv("VISION_VIEWER_TOKEN") or None
        from .secure_app import create_secured_app
        import uvicorn

        print(f"Vision Shark {__version__} | http://{args.host}:{args.port}", flush=True)
        if generated:
            print(f"Admin access token (shown once): {admin_token}", flush=True)
        else:
            print("Admin access token loaded from VISION_API_TOKEN.", flush=True)
        if viewer_token:
            print("Optional viewer role enabled from VISION_VIEWER_TOKEN.", flush=True)
        uvicorn.run(create_secured_app(Path(args.data_dir), admin_token, viewer_token), host=args.host, port=args.port, server_header=False)
        return 0
    return 1


def cli():
    raise SystemExit(main())


if __name__ == "__main__":
    cli()
