# Vision Shark 0.9.0

Vision Shark is a local-first passive vehicle intelligence, evidence, read-only diagnostics, learning and shadow-autonomy R&D platform. The operator workflow deliberately distinguishes **software readiness** from **physical vehicle communication proof**.

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

The probe performs explicit bounded IPv4 ISO 13400 discovery, validates the responding DoIP entity, attempts routing activation and performs one allowlisted read-only UDS identification exchange. It exits successfully only when a routed diagnostic exchange is proven. A vehicle-identification broadcast by itself is **not** treated as vehicle identity evidence or a working diagnostic connection.

## Start the operator server

```bash
vision-shark serve
```

The supported CLI server is loopback-only and authenticated. If `VISION_API_TOKEN` is not set, Vision Shark generates a strong admin token and prints it once at startup. Open `http://127.0.0.1:8787` and paste that token into the login screen. You can provide persistent tokens instead:

```bash
export VISION_API_TOKEN='a-long-random-admin-token'
export VISION_VIEWER_TOKEN='an-optional-read-only-token'
vision-shark serve
```

Use the platform-equivalent environment-variable syntax on Windows. The admin/viewer tokens are never returned by an HTTP endpoint.

The supported server uses an HttpOnly `SameSite=Strict` session cookie. State-changing requests require the admin role, a per-session CSRF token and an `Idempotency-Key`; duplicate matching requests replay the cached response and conflicting key reuse is rejected. Operational APIs and `/metrics` require an authenticated session. Security decisions are written to the chained audit log.

The lower-level Python `create_app()` factory remains available for embedded development and test harnesses and does **not** imply the secured CLI deployment boundary. Production/operator launch should use `vision-shark serve` or reproduce the secured wrapper behind authenticated TLS infrastructure.

## Vehicle workflow

Passive CAN/CAN-FD and ENET are intentionally different flows:

- `CONNECT PASSIVE CAN` inventories/selects only driver-reported passive SocketCAN interfaces and does not broadcast DoIP discovery.
- `DISCOVER ENET / DOIP` is an explicit operator action. It sends ISO 13400 discovery only when `VISION_ALLOW_DOIP_DISCOVERY=1`, records that transmission in audit evidence, and treats the discovery VIN as untrusted metadata.
- The explicit DoIP bind then requires routed read-only UDS proof before diagnostics become READY. A VIN is promoted as observed identity evidence only when obtained through the proven routed diagnostic exchange.
- `SOFTWARE DEMO` is an explicit simulator path and is never a fallback for a failed physical connection.

## Vehicle transports

- Cross-platform IPv4 ENET/ISO 13400 DoIP discovery on Windows, macOS and Linux, only through explicit discovery/probe flows.
- Routed DoIP proof before the diagnostic session can become READY.
- Read-only UDS DID and DTC requests after proof; no security access, programming session, routine control, ECU reset, coding or flashing.
- Passive Linux SocketCAN/CAN-FD observation requires driver-reported listen-only mode.
- Windows J2534 providers are inventoried but are **not** automatically activated because generic J2534 discovery does not prove a provider is electrically passive/listen-only.
- VSL1 normalizes CAN, CAN-FD, ISO-TP, J2534 records and DoIP diagnostic events without confusing PHY frequency with transport bitrate.

## Analysis and evidence

- SQLite WAL recording store with receive-drop evidence and deterministic replay.
- candump, CSV, JSONL, Vector ASC and PCAN TRC import paths.
- Passive changed-byte sniffer view.
- Event-anchored bit-change discovery, timing/entropy anomaly comparison and ECU clock-skew membership hypotheses.
- Passive ISO-TP reassembly with normal/extended addressing, bounds, sequence validation and timeout/supersession handling.
- DBC decoding with differential cantools conformance tests for the supported subset.
- Structural platform/fingerprint comparison. Matching remains a hypothesis until independent exact-vehicle evidence confirms it.
- Decoder-based drive/charge/idle segmentation.
- UDS DID/NRC reference annotations.
- Persistent vehicle knowledge, Prometheus metrics and tamper-evident local operational audit chain.
- Component/system health that distinguishes software state from actual vehicle communication proof.

## OpenClaw

The running API exposes bounded OpenClaw-compatible read, policy-simulation and emergency-orchestration surfaces. It can inspect Vision state, readiness, recordings and knowledge, evaluate emergency observations, and create durable high-level provider intents.

OpenClaw has **no direct steering, braking, propulsion, gear or parking-brake authority**. Minimum-risk motion requests are typed handoffs to a separately validated deterministic vehicle controller; queued provider intent is never described as physically executed unless a provider explicitly completes it.

## Shadow autonomy

The repository contains an executable non-actuating autonomy R&D pipeline with typed ego/object/world/trajectory data, localisation input fusion, perception normalization, ODD/health evaluation, classical trajectory generation, controlled-stop fallback, trajectory safety checks and abstract control targets. It reports `live_actuation=false` and has no raw vehicle-transmit primitive.

## Production truth

The software release scope is `production-passive-shadow`. CI validates Python tests, compileability, JavaScript syntax, dependency resolution, Ruff static checks, dependency vulnerability audit, CycloneDX SBOM generation, implementation-marker rejection and version consistency.

**No repository test can prove an Australian BYD Shark 6 will answer your ENET adapter.** That proof requires the actual vehicle/adapter. Exact Shark bus topology, ECU logical addresses, supported DIDs, firmware variants, signal definitions and any physical actuation path remain evidence gates until measured on the target vehicle.

BYD-family/open-source material is used as engineering reference only. Atto 3, Dolphin, Tang or other BYD observations are never promoted to Shark facts without Shark evidence.
