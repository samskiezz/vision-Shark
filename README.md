# Vision Shark 0.9.0

Vision Shark is a local-first passive vehicle intelligence, evidence, read-only diagnostics, learning and shadow-autonomy R&D platform. It deliberately distinguishes **software readiness** from **physical vehicle communication proof**.

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

## Secure local launch

The HTTP API is secured by default and the normal CLI remains loopback-only.

```bash
vision-shark serve
```

If you have not configured a role token, the CLI generates a high-entropy local **admin** token and prints it once. Open `http://127.0.0.1:8787` and enter that token in the Gateway access panel.

For persistent role credentials, set one or more environment variables before launch:

- `VISION_VIEWER_TOKEN` — read-only data and research/simulation reads.
- `VISION_OPERATOR_TOKEN` — viewer access plus normal vehicle/recording/read-only diagnostic operations.
- `VISION_ADMIN_TOKEN` — operator access plus reviewed decoder configuration and explicit active adapter discovery.

Configured tokens must be at least 24 characters. Browser login creates a bounded HttpOnly, SameSite=Strict session and uses CSRF protection for mutations. Bearer tokens are supported for automation and `/metrics`. Side-effecting operator/admin requests require an `Idempotency-Key`; the browser supplies these automatically.

`VISION_SECURITY_DISABLED=1` is an explicit test/development escape hatch. It is not the production default.

## ENET / DoIP

With the OBD ENET adapter connected to the computer **and the vehicle**, you can pre-test from the CLI:

```bash
vision-shark probe --prove-diagnostics
```

The probe performs bounded ISO 13400 discovery, attempts routing activation and performs one allowlisted read-only UDS identification exchange. It succeeds only when a routed diagnostic exchange is proven. A UDP identification response by itself is **not** vehicle identity evidence.

The browser workflow is intentionally explicit:

1. Sign in as **admin**.
2. Set `VISION_ALLOW_DOIP_DISCOVERY=1` before launching if you want browser discovery enabled.
3. Press **DISCOVER ENET / DOIP**. This sends an ISO 13400 discovery broadcast and is audited as a transmission.
4. Vision selects a discovered DoIP endpoint and performs routed read-only UDS proof.
5. The session becomes READY only when that proof succeeds.

Normal **CONNECT VEHICLE / PASSIVE CAN** does **not** send DoIP discovery traffic. It selects simulator or a driver-reported passive SocketCAN interface only.

## Vehicle transports

- Explicit cross-platform IPv4 ENET/ISO 13400 DoIP discovery on Windows, macOS and Linux.
- Routed DoIP proof before diagnostics are marked ready.
- Read-only UDS DID and DTC requests after proof; no security access, programming, coding, routine control, ECU reset or firmware flashing.
- Passive Linux SocketCAN/CAN-FD observation requires driver-reported listen-only mode.
- Windows J2534 providers are inventoried but are **not** automatically activated because installed-provider metadata does not prove passive/listen-only electrical behaviour.
- VSL1 normalizes CAN, CAN-FD, ISO-TP, J2534 records and DoIP diagnostic events without confusing PHY frequency with bus bitrate.

## Analysis and evidence

- SQLite WAL recording store with receive-drop evidence and deterministic replay.
- candump, CSV and JSONL import/export plus reviewed Vector ASC / PCAN TRC import subsets.
- Passive cansniffer-style per-byte change ages and changed-only filtering.
- Event-anchored bit discovery, timing/entropy anomaly comparison and ECU clock-skew membership hypotheses.
- Passive ISO-TP reassembly with bounds, sequence validation, timeout handling, normal/extended addressing and fail-closed supersession.
- DBC decoding and differential conformance tests against cantools for the supported subset.
- Structural platform/fingerprint comparison remains a hypothesis until bound to exact-vehicle evidence.
- Decoder-bound drive/charge/idle segmentation.
- Persistent vehicle knowledge and tamper-evident local operational audit chain.
- Low-cardinality Prometheus `/metrics` without VIN/interface/payload labels.
- Component/system health that separates healthy software from proven vehicle communication.

## OpenClaw

The API exposes bounded OpenClaw-compatible read, policy-simulation and emergency-orchestration surfaces. High-level convenience/navigation/emergency actions are durable provider intents, not claims that a vehicle function physically executed.

OpenClaw has **no direct steering, braking, propulsion, gear or parking-brake authority**. Any future minimum-risk motion request remains a typed handoff to a separately validated deterministic vehicle controller.

## Shadow autonomy

The repository contains a non-actuating autonomy R&D pipeline with typed ego/object/world/trajectory data, localisation input fusion, perception normalization, ODD/health evaluation, classical trajectory generation, controlled-stop fallback, trajectory safety checks and abstract control targets. It reports `live_actuation=false` and has no raw vehicle-transmit primitive.

## Production truth

The release scope is `production-passive-shadow`. CI checks dependency resolution, Ruff/static correctness, pytest, Python compilation, JavaScript syntax, dependency vulnerabilities, CycloneDX SBOM generation, unresolved implementation markers and version consistency.

**No repository test can prove an Australian BYD Shark 6 will answer your ENET adapter.** Exact Shark bus topology, J1962 pinout, bitrates, ECU logical addresses, supported DIDs, firmware variants, signal definitions and any physical actuation path remain evidence gates until measured on the target vehicle.

BYD-family/open-source material is engineering reference only. Observations from Atto 3, Dolphin, Tang or other platforms are never promoted to Shark facts without Shark-specific evidence.
