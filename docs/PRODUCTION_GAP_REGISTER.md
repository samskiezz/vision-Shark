# Vision Shark 0.9.0 production gap register

## Closed in software

- Secure-by-default HTTP access control with `viewer`, `operator` and `admin` roles. Role tokens are constant-time verified and the normal loopback CLI generates an ephemeral high-entropy admin token when none is configured.
- Browser authentication uses bounded HttpOnly, SameSite=Strict sessions plus CSRF protection for cookie-authenticated mutations. Bearer tokens support automation and authenticated Prometheus access.
- Side-effecting operator/admin HTTP requests require bounded `Idempotency-Key` handling with same-request response replay, conflict detection and in-progress protection. Authentication, authorization, CSRF, idempotency and authenticated mutations are written to the tamper-evident operational audit.
- Security response policy includes CSP, frame denial, no-referrer and content-type sniffing protection. `VISION_SECURITY_DISABLED=1` is an explicit test/development escape hatch rather than the default.
- Durable SQLite WAL recording storage with capture-integrity/drop metadata.
- DoIP discovery is an explicit audited opt-in action rather than part of normal auto-connect. `/api/adapters` and `CONNECT VEHICLE / PASSIVE CAN` remain non-transmitting.
- Cross-platform IPv4 ENET/ISO 13400 discovery on Windows, macOS and Linux when explicitly enabled; discovery results are marked as transmitted and are not treated as vehicle identity evidence.
- DoIP sessions fail closed unless routing activation and a bounded read-only UDS exchange are proven. A discovery VIN remains untrusted unless routed diagnostics independently prove identity.
- Read-only DoIP DID/DTC requests; no security access, programming, coding, routine control, reset or arbitrary transmit API.
- Disconnect invalidates stale DoIP endpoint/proof state so later diagnostic calls cannot silently reconnect to an old vehicle.
- Passive Linux SocketCAN/CAN-FD with driver-reported listen-only enforcement, kernel receive-overflow accounting and timestamp handling.
- Windows J2534 provider inventory without automatically loading vendor DLLs or claiming passive safety.
- VSL1 transport/unit normalization for CAN, CAN-FD, J2534 records, ISO-TP and DoIP.
- Passive cansniffer-style per-byte change-age analysis with changed-only filtering.
- Event-anchored bit-change discovery for operator-labelled windows; results remain signal hypotheses.
- Passive timing/identifier anomaly comparison: new/missing identifiers, length changes, rate shifts, entropy shifts and jitter increases.
- ECU clock-skew/timing clustering is implemented as membership hypotheses only, with timestamp-jitter and spoofing limitations surfaced in output.
- Passive ISO-TP reconstruction with normal and explicit extended addressing, independent address-extension streams, sequence/length/timeout validation and fail-closed supersession of abandoned streams.
- Runtime DBC research decoding with differential cantools coverage for little-endian, signed, Motorola/big-endian, multiplexing, extended identifiers and >8-byte CAN-FD-length messages.
- candump, CSV and JSONL import/export plus deterministic recording replay; candump nanosecond timestamps, low-valued extended IDs, CAN-FD flags and RTR semantics are preserved.
- Reviewed Vector ASC and PCAN TRC passive import subsets.
- Content-free structural CAN fingerprints and caller-supplied platform-signature comparison. Identity remains evidence-gated; a structural match is a hypothesis, not a model claim.
- Decoder-bound drive/charge/idle segmentation with explicit hypothesis status.
- UDS standard DID/NRC reference tables for annotated read-only analysis; supported DIDs remain vehicle-specific.
- Persistent knowledge store plus append-only SHA-256-chained operational audit log.
- Durable OpenClaw provider-intent queue with explicit pending/acknowledged/completed/failed/cancelled lifecycle; queued intent is never presented as executed.
- Agent policy/emergency simulation routes reuse the bounded OpenClaw authority model and never grant direct driving control.
- Bounded request bodies with absolute upload deadline.
- Semantic signal broker, shared-memory data-plane primitive, sensor health and clock-quality services.
- Calibration registry and covariance-aware localisation core for replay/shadow workflows.
- Immutable dataset/model provenance registry.
- Driver-monitoring state evaluator, ODD/fallback supervisor and executable shadow-autonomy pipeline.
- Deterministic scenario regression support.
- Signed rollback-protected staging for application/model/pack/gateway artifacts; this is not vehicle ECU programming.
- Live OpenClaw-compatible read/emergency API with explicit denial of direct driving authority and minimum-risk driving handoff isolated to `validated_vehicle_controller`.
- Component/system-health reporting that distinguishes software readiness from physical vehicle communication proof; SocketCAN readiness requires observed traffic and DoIP readiness requires routed UDS proof.
- Proof-driven operator UI showing adapter -> vehicle -> communications proof -> ready, explicit admin ENET discovery, role state, and a live passive changed-byte sniffer.
- Low-cardinality Prometheus `/metrics` endpoint excludes VINs, interfaces and diagnostic payload labels.
- CLI `doctor` and `probe --prove-diagnostics` for pre-trip adapter/network/DoIP validation.
- Normal CLI server binding is loopback-only; non-loopback deployment remains a separate authenticated/TLS architecture decision.
- Deterministic application shutdown disconnects active transport and closes recording, audit and provider-intent SQLite stores; lifecycle closure is regression-tested.
- CI: dependency resolution, Ruff/static checks, pytest, Python compile, JavaScript syntax, implementation-marker rejection, dependency vulnerability audit and CycloneDX SBOM.
- Runtime repository fetching retired with explicit HTTP 410 migration responses.
- Requirements files aligned with the hardened `pyproject.toml` dependency set.

## Deliberately detected but not falsely enabled

- Windows J2534 providers can be discovered, but a generic live backend is not automatically enabled because installed-provider metadata alone does not prove listen-only/passive electrical behaviour.
- MF4/Parquet are recognized interoperability gaps. Core release interchange is candump/CSV/JSONL plus reviewed ASC/TRC subsets; optional large-measurement format support should use a separately reviewed streaming design.
- ARXML/KCD/SYM/FIBEX/database conversion remains an optional interoperability layer rather than silently making canmatrix a mandatory runtime dependency.
- OpenClaw provider intents are durable high-level handoffs; no fake lock/climate/phone/eCall/navigation backend is presented as physically executed until an actual provider acknowledges/completes the intent.
- The internal semantic broker uses `Vehicle.*`-style paths but is not presented as a KUKSA wire-protocol server.

## Remaining software integration work

These can be implemented without inventing vehicle facts, but they are not required to claim the current passive/read-only core works:

- Optional streaming MF4/MDF4 and Parquet adapters for very large engineering captures.
- Optional reviewed ARXML/KCD/SYM/FIBEX interchange adapter.
- Provider-specific J2534 live backend only where passive/listen-only behaviour can be enforced and tested for that provider/device.
- Real navigation, phone/eCall, health-device and vehicle-convenience providers behind the existing durable OpenClaw intent interface.
- Signed external vehicle-profile/evidence distribution and multi-vehicle fleet synchronization.
- Full VSS/KUKSA wire-protocol interoperability.
- Production TLS/reverse-proxy deployment profile if Vision Shark is ever intentionally exposed beyond loopback.

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

`production-passive-shadow` means the software can be released for passive acquisition, evidence, bounded read-only diagnostics, decoding, learning, replay, analysis and non-actuating shadow evaluation. It does **not** mean autonomous driving or BYD Shark 6 compatibility has been physically validated.
