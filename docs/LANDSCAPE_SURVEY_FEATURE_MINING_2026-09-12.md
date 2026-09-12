# Vision Shark landscape survey and feature-mining register — 12 September 2026

This register surveys open-source and research projects adjacent to Vision Shark: CAN reverse-engineering tools, loggers/analysers, diagnostics stacks, EV telemetry, autonomy/middleware, in-vehicle IDS research, and LLM-agent/vehicle integrations. It records useful patterns, the original Vision Shark implementation inspired by those patterns, and what was deliberately excluded.

No upstream code is represented as Vision Shark code unless its licence and provenance are explicitly handled. The implementations described here were written for this repository under its own licence. “Every repository ever made” is not a bounded or auditable set; this register concentrates on high-relevance projects and research families.

## 1. CAN reverse-engineering and analysis

| Project | Licence | What it does well | Vision Shark adoption | Deliberately excluded / remaining |
| --- | --- | --- | --- | --- |
| `collin80/SavvyCAN` | MIT | Sniffer byte-change display, frame details, temporal analysis, comparison workflows, ISO-TP/UDS inspection, many log formats | Passive sniffer byte-change ages, recording comparison/anomaly semantics, temporal statistics, ASC/TRC import | Fuzzing/custom sender and active UDS scan are outside the passive product boundary; gateway DBC editing is not exposed |
| comma.ai Cabana/openpilot tooling | MIT | Event-correlated signal discovery, route replay and visual signal analysis | Event-anchored bit discovery (`event_diff.py`) and replay-oriented analysis | Live unreviewed DBC editing is not promoted into the supported runtime |
| `commaai/opendbc` | MIT | Structural car fingerprints, per-platform DBCs, firmware/DID evidence | Structural platform matching and fingerprint primitives; vehicle identity remains evidence-gated | Active firmware querying at connect and vehicle-control ports |
| `commaai/panda` | MIT | Hardware safety policy and explicit TX allowlists/rate limits | Architectural reference for separating an AI/research layer from a validated controller | Vehicle-transmit implementation is intentionally absent from the supported passive gateway |
| `linux-can/can-utils` | GPL-2.0 | `candump`, `cansniffer`, replay, ISO-TP utilities | Independent candump import/export, replay pacing and sniffer semantics | GPL code is not copied; generators/transmit utilities are excluded |
| `cantools` | MIT | DBC/KCD/SYM/ARXML parsing and conformance reference | Differential DBC conformance tests against the supported internal decoder subset | Encoding/transmit path; full format conversion is optional integration work |
| `canmatrix` | BSD-2 | Broad database conversion | Reference for future reviewed ARXML/KCD/SYM/FIBEX interchange | Not a mandatory runtime dependency |
| CaringCaribou | GPL-3.0 | UDS discovery, DoIP/XCP, listener/dump and fuzzing | UDS NRC/DID semantics and DoIP architectural comparison | Active enumeration/fuzzing and GPL code |
| CANalyzat0r | GPL-3.0 | Background-vs-action comparison, project analysis, scanning/fuzzing | Baseline/observed anomaly comparison | Active scan/fuzz paths |
| cangaroo / BUSMASTER / Kayak | mixed GPL/open source | Graphing, replay and operator analysis UI | Signal-analysis and replay UX patterns | No GPL source reuse |
| BYD community reverse engineering | community/mixed | BYD-family head-unit/CAN/gateway observations | Hypothesis and attack-surface reference only | No other BYD model is treated as Australian Shark 6 evidence |

## 2. Diagnostics, formats and EV telemetry

| Project / family | Vision Shark adoption | Remaining / excluded |
| --- | --- | --- |
| `python-udsoncan`, `python-doipclient` | Independent bounded ISO 13400/UDS implementation with positive/negative response semantics and read-only allowlist | SecurityAccess, programming, routines, arbitrary writes, ECU reset and coding remain excluded |
| `mercedes-benz/odxtools` | Reference for a future licensed ODX/PDX naming layer | Not implemented without an appropriate diagnostic data package |
| `asammdf` | Interface/roadmap reference for large MDF4 measurement workflows | Streaming MDF4/MF4 and Parquet remain optional integration work |
| MCAP / Foxglove ecosystem | Interchange/design reference for engineering telemetry | Full compressed/indexed MCAP pipeline is not a core dependency |
| TeslaMate / EV telemetry dashboards | Drive/charge/idle segmentation pattern; Prometheus-style observability landed in later hardening | Tesla cloud polling does not transfer to BYD without a supported API |
| CANedge data tooling | Decode-to-analytics pipeline pattern | Large-data Parquet/Influx pipeline remains optional |

## 3. Autonomy, simulation and middleware

| Project | Vision Shark adoption | Remaining / excluded |
| --- | --- | --- |
| Autoware Universe | Modular localisation/perception/prediction/planning separation, ODD/health gating, replay/scenario concepts | ROS 2 stack is not embedded in the gateway |
| Apollo | Typed subsystem boundaries influenced the shadow data-plane architecture | Cyber RT and production HD-map stack |
| CARLA / ScenarioRunner / OpenSCENARIO | Scenario/replay validation concepts | Full simulator bridge remains external integration work |
| Eclipse iceoryx | Shared-memory/data-plane design reference | Full cross-process production consumer stack |
| COVESA VSS / Eclipse KUKSA | Semantic `Vehicle.*` style namespace and provider/broker separation | Full KUKSA wire-protocol server remains optional |

## 4. Passive in-vehicle IDS research

The following are implemented as operator/research hypotheses, not attribution facts.

- **Clock-skew / ECU fingerprinting (CIDS family):** per-identifier period/skew estimates and clustering are exposed as likely membership groups. Host/kernel timestamp jitter and clock-aware spoofing are explicit limitations.
- **Timing/frequency/entropy IDS families:** sealed baseline versus observed capture analysis reports new/missing identifiers, rate shifts, length changes, entropy shifts and jitter increases. Driving-state changes can legitimately alter traffic, so findings are observations rather than attack declarations.
- **Voltage fingerprinting / Scission-style work:** requires physical ADC/front-end evidence and is not implemented by software alone.

## 5. LLM agents and vehicle integration

Vision Shark’s OpenClaw integration is a policy/orchestration layer, not a direct driving controller.

- The existing policy allows observation, configured non-driving convenience actions, navigation intents and emergency coordination.
- Steering, braking, propulsion, gear and parking-brake authority remain unavailable to the agent.
- Emergency motion becomes a typed handoff to a separately validated deterministic controller.
- Real phone/eCall/navigation/health-device/vehicle-convenience providers remain explicit integrations and are not reported as executed until a real provider acknowledges/completes an intent.

## 6. Passive feature-mining tranche now present in `main`

| Feature | Current implementation |
| --- | --- |
| Sniffer view with byte-change ages | `vision_shark/sniffer.py`, `/api/sniffer` |
| Event-anchored signal discovery | `vision_shark/event_diff.py`, recording event-diff API |
| ECU clock-skew grouping | `vision_shark/ecu_fingerprint.py`, recording ECU-cluster API |
| Timing/identifier/entropy anomaly comparison | `vision_shark/anomaly.py`, recording anomaly API |
| Structural platform signature matching | `vision_shark/platform_match.py`, recording platform-match API |
| Drive/charge/idle segmentation | `vision_shark/segmentation.py`, decoder-backed recording segmentation API |
| Vector ASC / PCAN TRC import | `vision_shark/trace_import.py`, trace import API |
| UDS DID/NRC reference | `vision_shark/uds_reference.py`, `/api/reference/uds` |
| Agent policy/emergency simulation | `vision_shark/agent_policy.py`, policy simulation API |
| Vision Signal Language | `vision_shark/signal_language.py` and `docs/VISION_SIGNAL_LANGUAGE.md` |
| Prometheus-style metrics | metrics route/module added in the subsequent operator hardening tranche |

These features remain passive/evidence-bound: structural overlap is not vehicle identity, ECU timing clusters are not ECU attribution, and decoded segmentation inherits the validity of the reviewed decoder supplied to it.

## 7. Historical audit snapshot — `main` @ `640c3b9`

The following findings describe the older 12 September snapshot and are preserved for traceability. They must not be read as the current state of `main`.

1. **Critical — no authentication:** operational APIs were unauthenticated.
2. **High — hidden DoIP broadcast:** automatic connect could broadcast ISO 13400 identification on UP interfaces.
3. **High — discovery VIN overconfidence:** unauthenticated UDP identity data could be stored too strongly.
4. **Medium — duplicated DoIP policy:** parallel diagnostic paths risked divergent safety/deadline/address-validation behavior.
5. **Medium — OpenClaw adapter execution boundary:** injected adapters required a stronger provisioning/policy boundary.
6. **Medium — emergency false-positive risk:** real emergency-service adapters require validated DMS/debounce/confirmation UX.
7. **Low — partial J2534 protocol table:** vendor CAN-FD IDs vary.
8. **Low — DoIP learning semantics:** diagnostics must remain separate from raw CAN learning.

## 8. Current-main reconciliation

As of the current supported `main` snapshot reviewed on 13 September 2026:

- `main` is at `0180af1d79c752f8701a898860faa3dc97b34e60`.
- The passive landscape feature tranche from PR #5 is merged.
- Normal adapter inventory/auto-connect no longer needs hidden DoIP broadcast discovery; active DoIP discovery is an explicit audited opt-in path, and explicit DoIP binding requires routed read-only UDS proof.
- A discovery VIN is not sufficient vehicle identity evidence by itself.
- The supported gateway subsequently gained admin/viewer authentication, HttpOnly SameSite=Strict sessions, CSRF enforcement, request-bound idempotency, protected operational APIs/metrics and security audit events.
- OpenClaw remains separated from direct driving authority; real providers remain explicit integrations.

### Current measured CI

For `main` commit `0180af1d79c752f8701a898860faa3dc97b34e60`, GitHub Actions production gate passed:

- dependency resolution: PASS;
- Ruff correctness/static checks: PASS;
- pytest: **109 passed**;
- Python compile: PASS;
- JavaScript syntax: PASS;
- `pip-audit`: no known dependency vulnerabilities found in audited third-party packages;
- CycloneDX SBOM generation/upload: PASS;
- unresolved implementation-marker gate: PASS;
- release metadata/version consistency: PASS.

Older counts such as `396 passed, 28 skipped` belong to an earlier/local verification context and are not presented here as the measured current-main CI count.

## 9. Remaining optional software integrations

These remain genuine future integrations rather than hidden “completed” capabilities:

- streaming MDF4/MF4 and Parquet adapters for large engineering captures;
- reviewed ARXML/KCD/SYM/FIBEX database-conversion adapter;
- provider-specific live J2534 backend only where passive/listen-only behavior can be enforced and validated;
- full KUKSA wire-protocol interoperability;
- real maps/navigation, phone/eCall, health-device and vehicle-convenience OpenClaw providers;
- signed external vehicle-profile/evidence distribution and fleet synchronization.

## 10. Remaining physical/evidence gates

No GitHub survey can close these without the target Australian BYD Shark 6 and hardware:

1. actual ENET/DoIP response with the intended adapter;
2. exact Shark gateway behavior/logical addresses and supported DIDs;
3. exact CAN/CAN-FD topology, J1962 pin exposure and bitrates;
4. exact ECU identities/firmware variants;
5. independently validated Shark-specific signal definitions and profiles;
6. production camera/radar/lidar mounting, synchronization, calibration and evaluated models;
7. any physical steering/braking/propulsion controller, watchdog/safety island, HIL/closed-course evidence and applicable regulatory approval;
8. hardware-backed secure/measured boot and device attestation where required;
9. full update/recovery validation for production deployment.

`production-passive-shadow` therefore means the software can support passive acquisition, evidence, read-only diagnostics, decoding, reverse-engineering analysis, replay, learning and non-actuating shadow evaluation. It does not mean BYD Shark 6 physical compatibility or autonomous driving has been proven by repository tests.
