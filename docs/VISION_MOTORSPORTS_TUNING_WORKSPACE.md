# Vision Motorsports Calibration Workspace

Vision Shark now contains a real offline calibration-file authoring core rather than treating passive CAN capture as the tuning product.

## Supported artifact formats

- Raw binary (`bin`) with an explicit base address.
- Intel HEX (`ihex`) with record-length, checksum, EOF, overlap and extended-address validation.
- Motorola S-record (`srec`) with record-length, checksum and overlap validation.

All parsed artifacts become an address-aware `MemoryImage`. Candidate artifacts can be rendered back to BIN, Intel HEX or S-record deterministically.

## Calibration definitions

A reviewed calibration definition describes known maps without guessing them from arbitrary bytes. Each map includes:

- stable `map_id` and name;
- scalar, axis or table shape;
- absolute address;
- rows and columns;
- element width (1, 2 or 4 bytes);
- byte order;
- signed/unsigned encoding;
- engineering factor and offset;
- optional engineering minimum/maximum;
- engineering unit.

Example:

```json
{
  "definition_id": "engine.v1",
  "name": "Engine calibration",
  "maps": [
    {
      "map_id": "torque.limit",
      "name": "Torque limit",
      "kind": "table",
      "address": 0,
      "rows": 1,
      "cols": 4,
      "element_width": 2,
      "byte_order": "big",
      "signed": false,
      "factor": 0.1,
      "offset": 0,
      "minimum": 0,
      "maximum": 1000,
      "unit": "Nm"
    }
  ]
}
```

Edits are explicit and typed:

```json
[
  {"map_id": "torque.limit", "values": [400, 420, 440, 460]}
]
```

The patch builder validates the exact original bytes before applying an edit, rejects overlapping edited maps, rejects values outside declared engineering/encoding ranges, and produces exact changed-byte regions with baseline and candidate SHA-256 identities.

## Browser workspace

Run `vision-shark serve`, authenticate as an admin, then use **Vision Motorsports Calibration Workspace** in the operator UI. It can:

- inspect a calibration file;
- decode all maps in a reviewed definition;
- validate edited engineering values;
- build an exact byte patch;
- render a candidate BIN/IHEX/S-record file;
- save the candidate locally;
- retain audit evidence for each operation.

The browser path is capped at 6 MiB per artifact because it goes through the bounded HTTP request path.

## Local CLI

For workshop files up to the 32 MiB calibration-artifact limit, use the local CLI.

```bash
vision-shark-tune inspect --input stock.bin --format bin --base-address 0x0
```

```bash
vision-shark-tune decode \
  --input stock.bin \
  --format bin \
  --definition engine-definition.json
```

```bash
vision-shark-tune build \
  --input stock.bin \
  --format bin \
  --definition engine-definition.json \
  --edits stage1-edits.json \
  --output stage1.bin
```

```bash
vision-shark-tune diff \
  --baseline stock.bin \
  --candidate stage1.bin \
  --baseline-format bin \
  --candidate-format bin
```

```bash
vision-shark-tune checksum --input stage1.bin --format bin --algorithm sha256
```

## Scope

This workspace is the calibration/binary authoring foundation. It does not guess unknown OEM map locations, checksum algorithms or calibration semantics. Those belong in reviewed ECU/software-family definitions backed by evidence.

Vehicle-side raw transmit, SecurityAccess bypass, firmware programming and voltage-fault injection are not implemented by this workspace.
