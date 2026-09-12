# Shark Field Intelligence — dossier-driven implementation

Date: 13 September 2026

This tranche converts the All Terrain Action EV / EVX research dossier into executable Vision Shark product structure. The goal is not to copy EVX active-control behaviour. The goal is to make Vision Shark a stronger passive evidence, context, comparison and field-research platform for the Australian BYD Shark 6.

## Product principles

1. **Context is part of the measurement.** Firmware, variant, tyres, tyre pressure, modifications, trailer/load, terrain and environment can materially change a Shark result. A CAN capture without this context is weaker evidence.
2. **Source quality and vehicle validation are different dimensions.** A direct creator or vendor source can be Grade A while the underlying Shark behaviour still requires physical validation on the target vehicle and firmware.
3. **No cross-variant silent promotion.** Premium, Dynamic, Performance, model-year, production/pre-production state and OTA differences remain explicit.
4. **Comparison is guarded by context.** Before an A/B report is interpreted as firmware, mode or modification behaviour, Vision reports critical run mismatches.
5. **Incidents are timelines, not diagnoses.** Warnings, DTC snapshots, rough-road context, inspection notes and repair evidence can be correlated without inferring a mechanical cause beyond evidence.
6. **Vision remains passive/read-only at the supported vehicle boundary.** This work adds no throttle, regen, traction, steering, braking, propulsion, ECU-coding or firmware-flashing path.

## Implemented capability

### Research Run Card

`SessionContext` is an immutable recording envelope containing:

- vehicle ID, model, variant and model year;
- vehicle firmware/software version;
- signed profile pack/version reference;
- production/pre-production context;
- test purpose, terrain, route, weather and ambient temperature;
- tyres and per-corner pressure values;
- payload and trailer state/mass;
- modification IDs;
- operator notes and provenance.

The operator web UI now presents a **Research Run Card** before capture. Starting a research run creates the normal recording, then immediately stores its immutable context. If context persistence fails, the UI stops the newly started recording rather than silently continuing with an uncontextualised research session. Set-like fields such as modification IDs and tyre-pressure keys are canonicalised before hashing so semantically identical context is stable, while duplicate modification IDs are rejected.

### Modification ledger

`VehicleModification` records part/category, install/removal timing, geometry/electrical notes and evidence references. The ledger supports before/after baselines for tyres, suspension, bull bars, electrical accessories and other changes that can invalidate direct comparisons.

### Evidence Lab

`ResearchSource` and `ResearchClaim` provide a small claim graph:

- source kind: creator, vendor product, independent, community or physical capture;
- evidence grade: A, B, C or X;
- claim confidence;
- validation state: hypothesis, needs physical validation, partially validated, validated or rejected;
- required evidence;
- linked recordings;
- append-only claim-state events.

The initial claim object is immutable. Validation progress is represented by append-only events so later promotion or rejection does not rewrite the original research statement. A claim cannot be inserted with a source reference that is absent from the research-source store; this prevents orphaned provenance links.

### Matched-recording comparison

`POST /api/research/recordings/compare` compares two saved captures and reports context compatibility before existing anomaly analytics are interpreted. Critical mismatches include vehicle ID, model, variant, production/pre-production state and firmware. High-weight mismatches include model year, signed profile, tyres/pressures, route, modifications and trailer state. The comparison result includes SHA-256 identities for both immutable context objects.

A comparison is not presented as cleanly comparable when critical identity/context variables differ or the overall context score is below the configured threshold.

### Incident timeline

`Incident` stores the immutable first observation: recording/time reference, warning snapshot, DTC snapshot, evidence window, notes and initial resolution state. Inspection, repair and closure progress is then recorded through append-only `IncidentEvent` entries. The effective state is calculated from the event history rather than rewriting the original incident. This supports corrugation/warning, post-impact and mechanical follow-up workflows without turning correlation into diagnosis.

### Research feedback / cohorts

`ResearchFeedback` stores cohort, release/profile reference, vehicle/recording reference, 0–10 subjective ratings, evidence attachments and repeatability. Feedback can be listed globally or per vehicle and remains separate from measured capture evidence. It is designed to sit on top of the signed profile/fleet distribution already present in Vision Shark.

### Standard field protocols

The API exposes nine dossier-derived protocols:

- sand / dune;
- steep hill / articulation;
- rock / rut / crawl;
- towing highway;
- towing off-road;
- corrugation;
- camp / auxiliary power;
- OTA A/B;
- post-modification baseline.

Each protocol specifies the minimum context and comparison rule. They are research checklists, not vehicle-control routines.

## All Terrain / EVX machine-readable seed

`vision_shark/all_terrain_research.py` contains the dossier source register and first research claims in machine-readable form. It includes every Shark/EVX YouTube ID carried into the dossier register plus the EVX roadmap/shop/spec source pages.

The seed is loaded explicitly with:

```text
POST /api/research/seed/all-terrain-evx
```

Loading is idempotent. Existing source IDs or claim IDs cannot be silently changed to different content. Sources are loaded before claims so the provenance graph is complete, and the bundled claims are not marked physically validated.

Key initial hypotheses include:

- firmware may change observed terrain behaviour;
- trailer state may affect terrain-mode availability on some firmware/variant combinations;
- generator-assisted SOC recovery must be interpreted with load/route/thermal context;
- rough-road warnings require an incident timeline rather than immediate diagnosis;
- modification state is required comparison context.

## HTTP surfaces

```text
GET  /api/research/protocols
POST /api/research/seed/all-terrain-evx

POST /api/research/session-context/{recording_id}
GET  /api/research/session-context/{recording_id}

POST /api/research/sources
GET  /api/research/sources

POST /api/research/modifications
GET  /api/research/vehicles/{vehicle_id}/modifications

POST /api/research/claims
GET  /api/research/claims
GET  /api/research/claims/{claim_id}
POST /api/research/claims/{claim_id}/events

POST /api/research/incidents
GET  /api/research/incidents
GET  /api/research/incidents/{incident_id}
POST /api/research/incidents/{incident_id}/events

POST /api/research/feedback
GET  /api/research/feedback

POST /api/research/recordings/compare
GET  /api/research/summary
```

On the supported authenticated `vision-shark serve` path, the existing security middleware applies to these APIs: reads require an authenticated session and mutations require the admin role, CSRF token and request-bound idempotency key. The security regression suite verifies viewer/admin separation and idempotent replay on the research seed path.

## Evidence grades used by the dossier

| Grade | Meaning | Product treatment |
| --- | --- | --- |
| A | Primary creator/product evidence | Good product/research lead; does not automatically become a Shark vehicle fact. |
| B | Independent corroboration | Used to qualify or challenge vendor/creator statements. |
| C | Community/indexed cross-reference | Hypothesis/test lead only. |
| X | Physical validation required | Target-vehicle/firmware/bus/signal behaviour that repository research cannot prove. |

## Dossier video register carried into the seed

The machine-readable seed includes these video IDs from the research dossier:

`VspbGyxMZyo`, `XU5JnUxgfE4`, `P1Ca6onpjPo`, `g08V2Hf7EM0`, `dATBFZ3axyY`, `m5qzHvBv1Qc`, `m-2GBqEkYpM`, `hm6bx70UT6w`, `m_8MI_TROvY`, `snTpboghEZE`, `uetp2urd1lM`, `6IhfvNog-y4`, `WogPjcDcK_g`, `jfpaOGCmlcg`, `CvNKh5U_guc`, `h0FXa3pQ1Ok`, `D3GVrWj5bsg`, `EP85qjV7joM`, `End6ZU8GKdI`, `THFdPtte59M`, `LzORFvTfIMo`, `5RMPdJeU6k8`, `PxzFOrnmt0U`.

Entries whose public crawl did not expose direct creator metadata remain community-grade rather than having transcript text invented for them.

## Next physical validation targets

The software now has the structure to capture these questions, but target-vehicle evidence is still required before promoting them to Shark facts:

1. exact terrain-mode state identifiers and transitions;
2. trailer connection/detection versus mode availability by firmware;
3. wheel-speed / traction-intervention proxies;
4. SOC, engine/generator and validated thermal signals under tow load;
5. before/after OTA behaviour on a matched route/obstacle;
6. warning/DTC behaviour around naturally occurring incidents;
7. parked 12 V / HV / DC-DC behaviour under measured auxiliary load.

These findings should be published through the existing signed `VehiclePack` evidence workflow once independently validated on the intended Australian Shark variant/software version.
