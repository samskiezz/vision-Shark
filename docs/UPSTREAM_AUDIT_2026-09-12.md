# Vision Shark upstream automotive audit — 2026-09-12

This audit compares Vision Shark against major open-source automotive communications, diagnostics, reverse-engineering, vehicle-data and autonomy ecosystems. It is a feature/architecture review, not a claim that every automotive repository on GitHub has been enumerated. Code was not blindly copied; patterns were reimplemented within Vision's passive/read-only production boundary and upstream licences remain applicable to any future direct reuse.

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

### hardbyte/python-can
Useful patterns:
- unified backend abstraction;
- CAN-FD support;
- many capture readers/writers and playback;
- platform-specific interface discovery.

Vision adoption:
- transport-neutral VSL event model;
- deterministic replay;
- candump/CSV/JSONL interchange;
- cross-platform ENET discovery while preserving passive SocketCAN policy.

Remaining difference:
- Vision does not automatically enable arbitrary python-can/J2534 backends because generic availability does not prove the adapter is electrically passive/listen-only.

### pylessard/python-can-isotp
Useful patterns:
- ISO 15765 transport-state separation, bounded reassembly and sequence handling.

Vision adoption:
- passive receive-only ISO-TP assembler with no flow-control transmitter, payload bounds, sequence validation and stream timeout.

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
- explicit routing activation response codes and logical addressing.

Vision adoption:
- cross-platform vehicle-identification discovery;
- routing response address validation;
- `0x10` activation success accepted;
- confirmation-required `0x11` fails closed because Vision does not implement the confirmation workflow;
- diagnostic response source/target logical addresses are validated;
- a vehicle-identification broadcast alone is never considered a proven working diagnostic session.

### cantools
Useful patterns:
- DBC parsing/decoding, multiplexing and diagnostic data handling;
- candump workflows;
- independent parser validation.

Vision adoption:
- internal DBC research decoder retained;
- differential conformance tests against cantools for the supported DBC subset;
- candump import/export.

### canmatrix / asammdf
Useful patterns:
- broad bus-description interchange;
- MF4/MDF measurement processing;
- large capture conversion to CSV/Parquet and analytical formats.

Vision adoption:
- core lightweight candump/CSV/JSONL interchange and durable SQLite capture storage.

Remaining difference:
- MF4/Parquet remain optional interoperability work, intentionally not hidden behind an unreviewed heavyweight production dependency.

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

### Autoware Universe
Useful patterns:
- modular localisation/perception/prediction/planning architecture;
- component health and readiness supervision;
- fallback/minimum-risk concepts;
- replay/scenario-driven validation before vehicle deployment.

Vision adoption:
- shadow-only autonomy runtime;
- calibration/localisation/world/ODD/fallback modules;
- system-health graph;
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
2. DoIP discovery was incorrectly close to being treated as a usable connection -> routed UDS proof is now required before READY.
3. Routing activation `0x11` was treated as complete success -> now fails closed because confirmation is not implemented.
4. DoIP source/target logical addresses were not fully validated -> routing and diagnostic addresses are now checked.
5. OpenClaw existed as isolated code -> live read/emergency API and audit integration added.
6. Operational decisions lacked durable tamper-evident evidence -> SHA-256 chained SQLite audit added.
7. Replay was advertised but absent from the stripped runtime -> receive-only replay restored.
8. Capture interchange was too narrow -> candump/CSV/JSONL import/export restored.
9. Passive ISO-TP reconstruction was absent -> bounded receive-only assembler added.
10. Vehicle identification only counted frames/IDs -> structural fingerprinting and fuzzy comparison added.
11. Product health did not express routed diagnostic proof -> health/readiness now separate software state from physical vehicle proof.
12. `requirements.txt` still installed an obsolete vulnerable dependency set -> aligned with hardened project dependencies.
13. CI lacked a Python static gate -> Ruff and `pip check` added alongside pytest, compile, pip-audit and SBOM.
14. The CLI did not provide a genuine pre-trip communications check -> `vision-shark probe --prove-diagnostics` added.

## Remaining software gaps

These are real software opportunities rather than vehicle facts:
- optional streaming MF4/Parquet adapters;
- provider-specific J2534 passive backend after a enforceable silent/listen-only policy is defined per provider;
- external navigation/phone/eCall/health-device adapters for OpenClaw;
- signed external evidence/profile distribution and multi-vehicle fleet operations;
- deeper DBC/ARXML/KCD/SYM interchange beyond the currently tested DBC subset.

## Remaining physical/evidence gates

No open-source repository can close these for the Australian Shark 6 without the target hardware:
- actual ENET/DoIP response from the user's adapter and Shark;
- exact Shark gateway logical address and downstream ECU inventory;
- supported Shark DIDs/firmware responses;
- exact CAN/CAN-FD pin exposure, buses and bitrates;
- Shark-specific signal definitions;
- production sensor mounting/calibration/model validation;
- validated deterministic steering/braking/propulsion controller, safety island, HIL/closed-course evidence and regulatory approval.
