# BYD Shark 6 Circuit Atlas Reference Integration

Vision Shark now contains a structured, searchable reference layer derived from the supplied **BYD Shark 6 Pickup Truck Circuit Atlas** extraction.

## Provenance

The current dataset is marked:

- `source_kind = user_provided_oem_extraction`
- `document = BYD Shark 6 Pickup Truck Circuit Atlas`
- `verification = source_claimed_oem_not_independently_verified`
- `physical_validation = false`

This is deliberate. The reference can be used immediately for engineering lookup and passive capture planning without silently promoting supplied documentation into physically verified facts.

## Data represented

The registry currently exposes:

- harness codes and harness names;
- wire-colour codes;
- named CAN/network segments;
- DLC / OBD2 connector mapping;
- ECM A01(A) and A01(B) pins;
- VCU K49(A) and K49(B) pins;
- BMS BK51 pins;
- rear-drive Ka76(A) pins;
- Dual MCU A36 pins;
- SRS KG10 pins;
- ADAS P13 and PG87 CAN pins;
- engine sensor/actuator connector summaries;
- ground-point groups;
- harness junction cross references;
- fuse-box identities and G82 output mapping;
- module index;
- circuit-diagram index.

The reference API is read-only and machine searchable.

## API

- `GET /api/reference/shark6/summary`
- `GET /api/reference/shark6/connectors`
- `GET /api/reference/shark6/connectors/{connector_id}`
- `GET /api/reference/shark6/networks`
- `GET /api/reference/shark6/networks/{network_name}`
- `GET /api/reference/shark6/search?q=...`
- `GET /api/reference/shark6/modules`
- `GET /api/reference/shark6/diagrams`
- `GET /api/reference/shark6/harnesses`
- `GET /api/reference/shark6/wire-colors`
- `GET /api/reference/shark6/grounds`
- `GET /api/reference/shark6/junctions`
- `GET /api/reference/shark6/power-distribution`
- `GET /api/reference/shark6/engine-components`

Authenticated browser view:

- `GET /reference/shark6`

## Engineering use

The data is designed to support:

1. connector identification;
2. passive CAN/CAN-FD measurement planning;
3. comparison of observed traffic against documented network membership;
4. wiring fault diagnosis and continuity/voltage-reference work;
5. evidence-backed connector records for future VehiclePacks;
6. linking captured recordings to the exact connector/network described by the service documentation.

## Validation states

Every current pin record defaults to `source_claimed`. A future physical-validation layer can promote individual records to states such as:

- `physically_validated`;
- `oem_documented_and_measured`;
- `variant_confirmed`;
- `firmware_build_confirmed`.

Validation should happen per connector/pin/network rather than promoting the entire atlas at once.

## Deliberately not operationalized

The source material also contained a fault-injection target map. Vision Shark does **not** turn those entries into executable voltage-glitch, power-cycling, security-bypass or live ECU-write routines. The structured reference keeps the wiring and diagnostic evidence useful while the application remains explicit about what has and has not been physically validated.
