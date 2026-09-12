# Vision Shark 0.9.0 production gap register

## Closed in software

- Durable SQLite WAL recording storage with capture-integrity/drop metadata.
- Cross-platform IPv4 ENET/ISO 13400 discovery on Windows, macOS and Linux.
- DoIP sessions fail closed unless routing activation and a bounded read-only UDS exchange are proven.
- Read-only DoIP DID/DTC requests; no security access, programming, coding, routine control, reset or arbitrary transmit API.
- Passive Linux SocketCAN/CAN-FD with driver-reported listen-only enforcement, kernel receive-overflow accounting and timestamp handling.
- Windows J2534 provider inventory without automatically loading vendor DLLs or claiming passive safety.
- VSL1 transport/unit normalization for CAN, CAN-FD, J2534 records, ISO-TP and DoIP.
- Passive ISO-TP reconstruction with sequence, length and timeout validation.
- Runtime DBC research decoding and differential conformance coverage against cantools for the supported subset.
- candump, CSV and JSONL import/export plus deterministic recording replay.
- Content-free structural CAN fingerprinting and fuzzy comparison. Identity remains evidence-gated.
- Persistent knowledge store plus append-only SHA-256-chained operational audit log.
- Bounded request bodies with absolute upload deadline.
- Semantic signal broker, shared-memory data-plane primitive, sensor health and clock-quality services.
- Calibration registry and covariance-aware localisation core for replay/shadow workflows.
- Immutable dataset/model provenance registry.
- Driver-monitoring state evaluator, ODD/fallback supervisor and executable shadow-autonomy pipeline.
- Deterministic scenario regression support.
- Signed rollback-protected staging for application/model/pack/gateway artifacts; this is not vehicle ECU programming.
- Live OpenClaw-compatible read/emergency API with explicit denial of direct driving authority.
- Component/system-health reporting that distinguishes software readiness from physical vehicle communication proof.
- CLI `doctor` and `probe --prove-diagnostics` for pre-trip adapter/network/DoIP validation.
- CI: pytest, compile, JavaScript syntax, Ruff, dependency resolution, implementation-marker rejection, pip-audit and CycloneDX SBOM.
- Runtime repository fetching retired with explicit HTTP 410 migration responses.
- Requirements files aligned with the hardened `pyproject.toml` dependency set.

## Deliberately detected but not falsely enabled

- Windows J2534 providers can be discovered, but a generic live backend is not automatically enabled because installed-provider metadata alone does not prove listen-only/passive electrical behaviour.
- MF4/Parquet are recognized interoperability gaps. Core release interchange is candump/CSV/JSONL; optional large-measurement format support should use a separately reviewed data dependency and streaming design.
- OpenClaw convenience/navigation/emergency adapters are high-level extension points; no fake lock/climate/call/navigation backend is presented as working until an actual provider is configured.

## Evidence gates software cannot truthfully invent

1. Australian BYD Shark 6 physical ENET/DoIP response and exact gateway behaviour.
2. Exact Shark 6 CAN/CAN-FD topology, bitrates, pinout and which networks are exposed at J1962/OBD.
3. Exact ECU identities, firmware variants, diagnostic/logical addresses and supported DIDs for the target build.
4. Validated Shark signal definitions and vehicle profiles backed by independent captures and repeatable fingerprints.
5. Production camera/radar/lidar hardware drivers, time synchronisation and measured calibration.
6. Trained perception/prediction models with licensed datasets and independent evaluation.
7. Any physical steering, braking or propulsion interface plus independent deterministic safety controller/watchdog.
8. Closed-loop HIL, closed-course testing, ISO 26262/SOTIF/ISO 21434 evidence and applicable Australian approval.
9. Automotive gateway DV/PV, secure/measured boot and hardware-backed attestation.
10. Full Uptane/A-B update deployment and power-cut recovery testing.

`production-passive-shadow` means the software can be released for passive acquisition, evidence, read-only diagnostics, decoding, learning, replay, analysis and non-actuating shadow evaluation. It does **not** mean autonomous driving or BYD Shark 6 compatibility has been physically validated.
