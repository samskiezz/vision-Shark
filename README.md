# Vision Shark 0.9.0

Vision Shark is a local-first passive vehicle intelligence, evidence, read-only diagnostics, learning and shadow-autonomy R&D platform. The normal operator workflow hides low-level transport details, but the software deliberately distinguishes **software readiness** from **physical vehicle communication proof**.

## Install

Requires Python 3.11+.

```bash
git clone https://github.com/samskiezz/vision-Shark.git
cd vision-Shark
python -m venv .venv
```

Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e .
vision-shark doctor
```

macOS/Linux:

```bash
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e .
vision-shark doctor
```

## ENET / DoIP pre-trip proof

With the OBD ENET adapter connected to the computer **and the vehicle**, run:

```bash
vision-shark probe --prove-diagnostics
```

The probe performs bounded IPv4 ISO 13400 discovery, validates the discovered DoIP entity, attempts routing activation and performs one allowlisted read-only UDS identification exchange. It exits successfully only when a routed diagnostic exchange is proven. A vehicle-identification broadcast by itself is **not** treated as a working diagnostic connection.

If the proof passes, launch:

```bash
vision-shark serve
```

and open `http://127.0.0.1:8787`.

The automatic workflow is:

`CONNECT VEHICLE -> transport discovery -> DoIP/SocketCAN proof -> IDENTIFY -> evidence/knowledge -> LEARN/shadow workflows`.

## Vehicle transports

- Cross-platform IPv4 ENET/ISO 13400 DoIP discovery on Windows, macOS and Linux.
- Routed DoIP proof before the session can become READY.
- Read-only UDS DID and DTC requests after proof; no security access, session programming, routine control, ECU reset, coding or flashing.
- Passive Linux SocketCAN/CAN-FD observation requires driver-reported listen-only mode.
- Windows J2534 providers are inventoried but are **not** automatically activated because generic J2534 discovery does not prove a provider is physically silent/passive.
- VSL1 normalizes CAN, CAN-FD, ISO-TP, J2534 records and DoIP diagnostic events without pretending PHY frequency and bitrate are the same measurement.

## Analysis and evidence

- SQLite WAL recording store with receive-drop evidence.
- Deterministic recording replay.
- candump, CSV and JSONL import/export.
- Passive ISO-TP reassembly with bounds, sequence validation and timeout handling.
- DBC decoding and differential conformance tests against cantools for the supported subset.
- Content-free structural vehicle fingerprints plus fuzzy comparison. Fingerprints are observations, not model identity claims, until bound to vehicle-specific evidence.
- Persistent vehicle knowledge and tamper-evident local operational audit chain.
- Component/system health endpoint that distinguishes healthy, degraded and failed dependencies.

## OpenClaw

The running API exposes OpenClaw-compatible read and emergency-orchestration surfaces. It can inspect Vision state, readiness, recordings and knowledge, evaluate emergency observations, and produce high-level navigation/emergency intents. External non-driving convenience/navigation adapters can be injected when independently implemented and validated.

OpenClaw has **no direct steering, braking, propulsion, gear or parking-brake authority**. Any future minimum-risk manoeuvre is a typed handoff to a separately validated deterministic vehicle controller.

## Shadow autonomy

The repository contains an executable non-actuating autonomy R&D pipeline with typed ego/object/world/trajectory data, localisation input fusion, perception normalization, ODD/health evaluation, classical trajectory generation, controlled-stop fallback, trajectory safety checks and abstract control targets. It reports `live_actuation=false` and has no raw vehicle-transmit primitive.

## Production truth

The software release scope is `production-passive-shadow`. CI validates Python tests, compileability, JavaScript syntax, dependency resolution, Ruff static checks, dependency vulnerability audit, CycloneDX SBOM generation, implementation-marker rejection and version consistency.

**No repository test can prove an Australian BYD Shark 6 will answer your ENET adapter.** That proof requires the actual vehicle/adapter. Exact Shark bus topology, ECU logical addresses, supported DIDs, firmware variants, signal definitions and any physical actuation path remain evidence gates until measured on the target vehicle.

BYD-family/open-source material is used as engineering reference only. Atto 3, Dolphin, Tang or other BYD observations are never promoted to Shark facts without Shark evidence.
