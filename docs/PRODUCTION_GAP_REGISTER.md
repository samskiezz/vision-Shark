# Vision Shark 0.9.0 production gap register

## Closed in software

- Durable SQLite WAL recording storage with capture-integrity/drop metadata.
- Cross-platform IPv4 ENET/ISO 13400 discovery on Windows, macOS and Linux.
- DoIP discovery is an explicit operator/probe action rather than a hidden side effect of passive connect; normal adapter inventory and passive auto-connect do not broadcast ISO 13400 discovery.
- UDP discovery identity fields are treated as untrusted metadata; routed read-only UDS proof is required before diagnostic readiness or observed DoIP identity evidence is promoted.
- DoIP sessions fail closed unless routing activation and a bounded read-only UDS exchange are proven.
- Read-only DoIP DID/DTC requests; no security access, programming, coding, routine control, reset or arbitrary transmit API.
- Disconnect invalidates stale DoIP endpoint/proof state so later diagnostic calls cannot silently reconnect to an old vehicle.
- Passive Linux SocketCAN/CAN-FD with driver-reported listen-only enforcement, kernel receive-overflow accounting and timestamp handling.
- Windows J2534 provider inventory without automatically loading vendor DLLs or claiming passive safety.
- VSL1 transport/unit normalization for CAN, CAN-FD, J2534 records, ISO-TP and DoIP.
- Passive ISO-TP reconstruction with normal and explicit extended addressing, independent address-extension streams, sequence/length/timeout validation and fail-closed supersession of abandoned streams.
- Runtime DBC research decoding with differential cantools coverage for little-endian, signed, Motorola/big-endian, multiplexing, extended identifiers and >8-byte CAN-FD-length messages.
- candump, CSV and JSONL import/export plus deterministic recording replay; candump nanosecond timestamps, low-valued extended IDs, CAN-FD flags and RTR semantics are preserved.
- Vector ASC and PCAN TRC trace import paths for passive engineering captures.
- Streaming Parquet import/export for very large engineering captures through the optional `analytics` extra. The path uses bounded SQLite iteration, bounded Arrow batches/row groups, per-frame model validation, Vision-owned schema metadata, SHA-256 export evidence and atomic output replacement.
- MDF/MF4 inspection and bounded raw-CAN import through the optional `measurement` extra. Vision Shark only reconstructs frames from MDF4 channel groups explicitly marked as bus events, sourced as CAN and exposing `CAN_DataFrame` with BusChannel/ID/IDE/DataLength/DataBytes/EDL semantics. Record reads use bounded `record_offset`/`record_count` chunks. Generic measurement channels are never guessed into CAN frames. `CAN_RemoteFrame` and `CAN_ErrorFrame` groups are detected and reported but not silently collapsed into the current `Frame` model where their source semantics cannot be preserved completely.
- Reviewed DBC/ARXML/KCD/SYM/FIBEX CAN-database inspection and normalization through the optional `database` extra. Source format is explicit, generic XML is rejected as ambiguous, DTD/entity declarations are rejected before XML parsing, source/output SHA-256 evidence is emitted, multi-matrix inputs become isolated DBC outputs with safe filenames, and generated DBCs are reloaded for core semantic comparison plus separately checked against Vision Shark's bounded runtime decoder subset.
- Signed external vehicle-profile/evidence bundles with Ed25519 publisher trust, SHA-256 member integrity, bounded ZIP contents, path/symlink defenses, immutable version/digest conflict detection and rollback-safe active-profile selection.
- Signed fleet catalogs with sequence replay/equivocation rejection, exact bundle-digest matching, transport-agnostic peer-directory synchronization, optional vehicle-assignment application and idempotent repeated synchronization. This synchronizes research/profile metadata only and does not add vehicle actuation or ECU programming.
- Dossier-driven Shark Field Intelligence: immutable per-recording run context for vehicle/variant/firmware/profile/tyres/load/trailer/terrain/modifications, modification ledger, evidence-graded source/claim graph with append-only validation events, incident and cohort-feedback records, context-gated A/B recording comparison, and nine passive field-test protocols.
- Machine-readable All Terrain Action EV / EVX research seed carrying the dossier video/source register and first hypothesis set. Seed loading is explicit, audited and idempotent; creator/vendor/community evidence is graded separately from target-vehicle physical validation state.
- Operator Research Run Card starts a normal passive recording and immediately binds its immutable context; if context persistence fails, the UI stops the newly created recording rather than silently continuing an uncontextualised research run.
- Passive changed-byte sniffer, event-anchored bit discovery, timing/entropy anomaly comparison and ECU clock-skew clustering; inferred signals/ECU membership remain hypotheses.
- Content-free structural CAN fingerprinting, platform signature comparison and fuzzy matching. Identity remains evidence-gated.
- Decoder-based drive/charge/idle segmentation is available as an analysis hypothesis when a reviewed decoder is attached.
- UDS DID/NRC standards reference and bounded agent-policy/emergency simulation surfaces are available without adding a transmit path.
- Persistent knowledge store plus append-only SHA-256-chained operational audit log.
- Durable OpenClaw provider-intent queue with explicit pending/acknowledged/completed/failed/cancelled lifecycle; queued intent is never presented as executed.
- Bounded request bodies with absolute upload deadline.
- Semantic signal broker, shared-memory data-plane primitive, sensor health and clock-quality services.
- Calibration registry and covariance-aware localisation core for replay/shadow workflows.
- Immutable dataset/model provenance registry.
- Driver-monitoring state evaluator, ODD/fallback supervisor and executable shadow-autonomy pipeline.
- Deterministic scenario regression support.
- Signed rollback-protected staging for application/model/pack/gateway artifacts; this is not vehicle ECU programming.
- Live OpenClaw-compatible read/emergency API with explicit denial of direct driving authority and minimum-risk driving handoff isolated to `validated_vehicle_controller`.
- Component/system-health reporting that distinguishes software readiness from physical vehicle communication proof; SocketCAN readiness requires observed traffic and DoIP readiness requires routed UDS proof.
- Proof-driven operator UI showing adapter -> vehicle -> communications proof -> ready instead of treating discovery as successful vehicle communication.
- CLI `doctor` and `probe --prove-diagnostics` for pre-trip adapter/network/DoIP validation.
- CLI `parquet-export` and `parquet-import` for bounded large-capture interchange without routing multi-gigabyte files through the HTTP request-body path.
- CLI `mf4-inspect` and `mf4-import-can` for local ASAM MDF4 engineering captures without relaxing the HTTP upload boundary or inventing CAN traffic from measurement signals.
- CLI `db-inspect` and `db-convert` for reviewed local CAN-database artifacts without enabling a vehicle transmit path.
- CLI `profile-bundle-create`, `profile-bundle-verify`, `profile-import`, `fleet-assign`, `fleet-status`, `fleet-catalog-export`, `fleet-catalog-verify` and `fleet-sync` for trusted profile/evidence distribution and multi-vehicle registry synchronization.
- Supported `vision-shark serve` path is loopback-only and authenticated: startup/admin token, optional viewer role, HttpOnly SameSite=Strict session cookie, CSRF enforcement, mandatory request-bound idempotency keys for state-changing API calls, protected operational APIs/metrics and security audit events. The lower-level `create_app()` factory remains an explicit embedded development/test surface rather than the supported production launch path.
- LAN exposure remains outside the default CLI and requires a separately reviewed authenticated/TLS deployment.
- Deterministic application shutdown disconnects active transport and closes recording, audit and provider-intent SQLite stores; lifecycle closure is regression-tested.
- CI: pytest, compile, all packaged operator JavaScript syntax, Ruff, dependency resolution, implementation-marker rejection, pip-audit and CycloneDX SBOM.
- Runtime repository fetching retired with explicit HTTP 410 migration responses.
- Requirements files aligned with the hardened `pyproject.toml` dependency set.

## Deliberately detected but not falsely enabled

- Windows J2534 providers can be discovered, but a generic live backend is not automatically enabled because installed-provider metadata alone does not prove listen-only/passive electrical behaviour.
- MDF4/MF4 support is deliberately raw-CAN evidence-bound rather than a generic signal-to-CAN converter. Normal MDF measurement channels can be inspected by the upstream measurement library but are not presented as original CAN frames unless explicit CAN bus-event records exist.
- MDF `CAN_RemoteFrame` and `CAN_ErrorFrame` records remain detectable interoperability cases rather than being falsely represented as fully preserved Vision `Frame` records; the current model does not preserve every remote/error-frame field.
- CAN-database conversion does not imply perfect preservation of every AUTOSAR/FIBEX vendor extension. The adapter reports core-semantic fidelity and runtime-subset compatibility separately rather than silently presenting normalization as exact full-schema equivalence.
- Signed fleet synchronization is deliberately metadata/profile-only. It verifies publisher trust and exact bundle content before import, and assignment application is opt-in; it does not remotely control a vehicle or program an ECU.
- All Terrain/EVX creator, vendor, independent and community material is stored as graded research evidence. A Grade A source is not automatically a physically validated Shark fact, and EVX active-control behaviour is not copied into the supported gateway.
- Terrain/towing/energy hypotheses remain context and evidence targets until exact Shark signals and firmware behavior are independently validated. The new comparison layer reports context mismatch instead of manufacturing causal attribution.
- OpenClaw provider intents are durable high-level handoffs; no fake lock/climate/phone/eCall/navigation backend is presented as physically executed until an actual provider acknowledges/completes the intent.
- The embedded `create_app()` factory is intentionally not presented as the secured deployment boundary. Integrators embedding the ASGI app must reproduce the secured wrapper or provide an equivalent authenticated reverse-proxy/security layer.

## Remaining software integration work

These can be implemented without inventing vehicle facts, but they are not required to claim the current passive/read-only core works:

- Provider-specific J2534 live backend only where passive/listen-only behaviour can be enforced and tested for that provider/device.
- Real navigation, phone/eCall, health-device and vehicle-convenience providers behind the existing durable OpenClaw intent interface.
- Full VSS/KUKSA wire-protocol interoperability; the current semantic broker implements the internal provider/broker model but is not a KUKSA server.
- Hardened authenticated/TLS LAN deployment profile if remote operator access becomes a product requirement.
- Rich Terrain Observer, Tow & Energy and Camp Power visual dashboards once the required Shark-specific signals have passed the evidence gates below. The underlying session/evidence/incident structures and standard protocols are now present.

## Evidence gates software cannot truthfully invent

1. Australian BYD Shark 6 physical ENET/DoIP response and exact gateway behaviour.
2. Exact Shark 6 CAN/CAN-FD topology, bitrates, pinout and which networks are exposed at J1962/OBD.
3. Exact ECU identities, firmware variants, diagnostic/logical addresses and supported DIDs for the target build.
4. Validated Shark signal definitions and vehicle profiles backed by independent captures and repeatable fingerprints, including terrain mode state, wheel-speed/traction proxies, trailer detection/interlocks, SOC/generator/thermal signals and 12 V/HV/DC-DC parked behavior.
5. Production camera/radar/lidar hardware drivers, time synchronisation and measured calibration.
6. Trained perception/prediction models with licensed datasets and independent evaluation.
7. Any physical steering, braking or propulsion interface plus independent deterministic safety controller/watchdog.
8. Closed-loop HIL, closed-course testing, ISO 26262/SOTIF/ISO 21434 evidence and applicable Australian approval.
9. Automotive gateway DV/PV, secure/measured boot and hardware-backed attestation.
10. Full Uptane/A-B update deployment and power-cut recovery testing.

`production-passive-shadow` means the software can be released for passive acquisition, evidence, read-only diagnostics, decoding, learning, replay, analysis and non-actuating shadow evaluation. It does **not** mean autonomous driving or BYD Shark 6 compatibility has been physically validated.