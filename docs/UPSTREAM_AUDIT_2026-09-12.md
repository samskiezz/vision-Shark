# Vision Shark upstream automotive audit — 2026-09-12

This audit compares Vision Shark against major open-source automotive communications, diagnostics, reverse-engineering, vehicle-data, measurement, safety and autonomy ecosystems. It is a broad representative feature/architecture review, not the impossible claim that every automotive repository on GitHub has been enumerated. Code was not blindly copied; patterns were reimplemented within Vision's passive/read-only production boundary and upstream licences remain applicable to any future direct reuse.

## Projects reviewed

### comma.ai openpilot / opendbc / panda
Useful patterns:
- explicit vehicle-port maturity rather than claiming universal compatibility;
- structural/firmware fingerprinting and fuzzy candidate matching;
- separation of low-level bus parsing from high-level vehicle state;
- silent-by-default hardware safety model;
- car-specific evidence rather than assuming family similarity;
- strong regression/static-analysis culture for safety-related code.

Vision adoption:
- passive structural fingerprint + fuzzy comparison;
- no BYD-family observation is promoted to Shark truth without evidence;
- raw transmit absent from production API;
- hardware/vehicle validation shown separately from software readiness.

### linux-can/can-utils + hardbyte/python-can
Useful patterns:
- SocketCAN as a kernel-defined transport boundary;
- classic CAN/CAN-FD capture, timestamps, RTR/extended-frame fidelity and replay/log interchange;
- unified backend concepts and platform-specific interface discovery.

Vision adoption:
- passive SocketCAN receiver with listen-only eligibility checks;
- kernel overflow/timestamp accounting;
- deterministic replay;
- candump/CSV/JSONL interchange;
- candump nanosecond, RTR, extended-ID and CAN-FD metadata round trips;
- cross-platform ENET discovery while preserving passive SocketCAN policy.

Remaining difference:
- Vision does not automatically enable arbitrary python-can/J2534 backends because generic availability does not prove the adapter is electrically passive/listen-only.

### pylessard/python-can-isotp
Useful patterns:
- ISO 15765 transport-state separation, bounded reassembly, addressing modes and sequence handling.

Vision adoption:
- passive receive-only ISO-TP assembler with no flow-control transmitter;
- normal and explicit extended addressing;
- independent address-extension streams;
- payload bounds, sequence validation, timeout and fail-closed stream supersession.

### pylessard/python-udsoncan
Useful patterns:
- UDS service separation and explicit positive/negative response semantics.

Vision adoption:
- bounded parser and allowlisted read services only (`0x19`, `0x22`);
- explicit negative-response evidence;
- no diagnostic-session mutation, security access, reset, routine control, IO control, download, transfer or coding API.

### jacobschaer/python-doipclient
Useful patterns:
- ISO 13400 discovery/routing separation;
- routing activation payload structure/response codes and logical addressing.

Vision adoption:
- cross-platform vehicle-identification discovery;
- standards-shaped routing activation including reserved bytes;
- routing response address validation;
- `0x10` activation success accepted;
- confirmation-required `0x11` fails closed because Vision does not implement the confirmation workflow;
- diagnostic response source/target logical addresses are validated;
- a vehicle-identification broadcast alone is never considered a proven working diagnostic session.

### cantools + canmatrix
Useful patterns:
- DBC parsing/decoding and database-format interoperability;
- signed values, Motorola/big-endian signals, multiplexing, extended identifiers and CAN-FD-size messages;
- conversion among DBC/ARXML/KCD/SYM/FIBEX and related engineering formats.

Vision adoption:
- internal lightweight DBC research decoder retained;
- differential conformance tests against cantools for little-endian, signed, Motorola, multiplexed, extended-ID and >8-byte message cases;
- fail-closed payload-length checks;
- broader database conversion remains optional rather than becoming a mandatory runtime dependency.

### danielhrisca/asammdf
Useful patterns:
- scalable ASAM MDF/MF4 measurement access and conversion for large engineering datasets.

Vision adoption:
- durable local capture storage and lightweight text interchange in the core product.

Remaining difference:
- MF4/Parquet remain optional interoperability work requiring a reviewed streaming design and dependency decision.

### SavvyCAN / Cabana-style reverse-engineering workflows
Useful patterns:
- side-by-side capture analysis;
- frame change/period inspection;
- correlation-oriented reverse engineering rather than arbitrary semantic guessing.

Vision adoption:
- message inventory, entropy/counter/checksum hypotheses, periodicity analysis, structural fingerprints, persistent evidence and replay.

### COVESA Vehicle Signal Specification + Eclipse KUKSA Databroker
Useful patterns:
- semantic vehicle signal namespace separated from physical CAN/Ethernet provider;
- provider/broker architecture and quality/timestamp metadata.

Vision adoption:
- `SemanticSignalBroker` separates high-level paths from raw transport;
- confidence, source, quality and timestamp metadata preserved;
- VSL keeps transport metadata so CAN bitrate is never confused with Ethernet/PHY frequency.

Remaining difference:
- Vision's internal semantic broker is not presented as a KUKSA wire-protocol server.

### Autoware Universe
Useful patterns:
- modular localisation/perception/prediction/planning architecture;
- component health and readiness supervision;
- fallback/minimum-risk concepts;
- replay/scenario-driven validation before vehicle deployment.

Vision adoption:
- shadow-only autonomy runtime;
- calibration/localisation/world/ODD/fallback modules;
- evidence-backed system-health graph;
- deterministic scenario/replay support;
- OpenClaw emergency intent handed to a separately validated controller rather than direct AI actuation.

### BYD community research
Reviewed sources include BYDcar/opendbc-byd and public BYD Atto/Dolphin/Shark community projects.

Useful patterns:
- BYD vehicles expose multiple buses/gateways and model-specific diagnostic behaviour;
- exact DIDs, firmware-query identifiers, pin exposure and bitrates vary by platform/build;
- OBD-visible traffic may be filtered by a gateway.

Vision adoption:
- no Atto 3, Dolphin, Tang or other BYD address/DID/DBC value is hardcoded as a Shark fact;
- generic standards-based F190 is used only as a bounded proof read, and even a negative UDS response can count as proof that routing/UDS exchange works;
- downstream Shark ECU inventory remains evidence-driven rather than brute-force address scanning.

## Major defects found during audit and closed

1. ENET discovery was Linux-only -> Windows/macOS/Linux IPv4 enumeration added.
2. DoIP discovery could be mistaken for a working diagnostic connection -> routed UDS proof is required before READY.
3. DoIP routing activation payload was incomplete -> ISO-reserved bytes and response address validation added.
4. Routing activation `0x11` was treated too optimistically -> now fails closed because confirmation is not implemented.
5. DoIP source/target logical addresses were not fully validated -> routing and diagnostic addresses are checked.
6. Disconnect could leave stale DoIP proof/endpoint state -> disconnect atomically clears runtime and diagnostic authority.
7. OpenClaw existed as isolated code -> live API, durable provider-intent broker and audit integration added.
8. Queued OpenClaw actions could be confused with execution -> pending/acknowledged/completed/failed/cancelled states are explicit.
9. Operational decisions lacked durable tamper-evident evidence -> SHA-256 chained SQLite audit added.
10. Replay was advertised but absent from the stripped runtime -> receive-only replay restored.
11. Capture interchange was too narrow -> candump/CSV/JSONL import/export restored.
12. Candump import/export lost precision/semantics -> nanosecond timestamps, low-valued extended IDs, RTR and CAN-FD metadata are preserved.
13. Passive ISO-TP reconstruction was absent -> bounded receive-only normal/extended addressing assembler added.
14. Incomplete ISO-TP streams could survive a new transaction -> stream supersession now fails closed and is reported.
15. Vehicle identification only counted frames/IDs -> structural fingerprinting and fuzzy comparison added.
16. DBC differential coverage was too shallow -> signed, Motorola, multiplexed, extended-ID and CAN-FD-length cases are checked against cantools.
17. Product health could overstate readiness -> SocketCAN requires observed traffic and DoIP requires routed diagnostic proof.
18. The UI could display proven DoIP as disconnected and exposed raw JSON as the primary workflow -> proof-driven adapter/vehicle/comms/ready stages added.
19. Requirements installed an obsolete dependency set -> aligned with hardened project dependencies.
20. CI lacked a Python static/dependency-resolution gate -> Ruff and `pip check` added alongside pytest, compile, pip-audit and SBOM.
21. The CLI did not provide a genuine pre-trip communications check -> `vision-shark probe --prove-diagnostics` added.
22. Normal server launch could have been misused for unauthenticated LAN exposure -> production CLI is loopback-only.
23. Long-running application shutdown did not explicitly close all persistent resources -> FastAPI lifespan now disconnects transport and closes intent/audit/recording stores.

## Remaining optional software integrations

These are genuine extensions but are not hidden as completed core capabilities:
- streaming MF4/MDF4 and Parquet adapters;
- reviewed ARXML/KCD/SYM/FIBEX database conversion adapter;
- provider-specific J2534 live backend only where passive/listen-only behaviour can be enforced and validated;
- real navigation, phone/eCall, health-device and vehicle-convenience providers behind the durable OpenClaw intent interface;
- signed external evidence/profile distribution and multi-vehicle fleet synchronization;
- KUKSA wire-protocol interoperability if external VSS clients are required.

## Remaining physical/evidence gates

No open-source repository can close these for the Australian Shark 6 without the target hardware:
- actual ENET/DoIP response from the user's adapter and Shark;
- exact Shark gateway logical address and downstream ECU inventory;
- supported Shark DIDs/firmware responses;
- exact CAN/CAN-FD pin exposure, buses and bitrates;
- Shark-specific signal definitions;
- production sensor mounting/calibration/model validation;
- validated deterministic steering/braking/propulsion controller, safety island, HIL/closed-course evidence and regulatory approval.
