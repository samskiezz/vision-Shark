from __future__ import annotations

from typing import Any

SOURCE_NOTE = "User-supplied extraction of the BYD Shark 6 Pickup Truck Circuit Atlas; source-claimed until independently or physically validated."

CONNECTOR_TYPES = {
    "01": "Standard clip + stuck-point; lift clip and release from stuck-point",
    "02": "Clip + stuck-point side entry; push clip sideways",
    "03": "Purple lever + blue clip; press purple lever and pull blue clip",
    "04": "Push-in circular; press clip and pull out",
    "holding_lock_plate": "SRS/airbag/seat-belt style; release lock plate before disconnect and restore after connect",
    "locking_piece": "Press or lift locking piece",
    "slider_lock": "Press or pull out slider",
    "rod_lock": "Move rod to stop position to release",
}

BODY_MODULE_REFERENCE = {
    "KG64(J)": {
        "module": "Left Domain Control Unit",
        "pin_count": 58,
        "pins": {
            1: "Rear left/right door locks LOCK",
            2: "Seat belt reminder signal",
            3: "Driver seat cushion heater power",
            6: "Vehicle button backlight 2",
            8: "Left signal acquisition",
            9: "Rear left/right door locks UNLOCK",
            11: "Intermediate signal acquisition",
            12: "Rear right seat belt reminder signal",
            13: "Driver seat cushion NTC",
            14: "Driver seat fan power supply",
        },
    },
    "PG86(C)": {
        "module": "Right Domain Control Unit roof interface",
        "pin_count": 36,
        "pins": {
            2: "Anti-glare drive + (PGRM)",
            5: "DOOR signal",
            6: "Interior light master ON",
            7: "Interior light master OFF",
            17: "Rear light intensity sensor power (PGRM)",
            18: "Sunroof switch signal",
            19: "Sunroof switch signal",
            20: "Sunroof switch signal",
            21: "Sunroof switch signal",
            23: "Light intensity sensor signal (PGRM)",
            31: "Ground (PGRM)",
            34: "Interior light power",
            35: "Backlight power",
        },
    },
    "G01": {"module": "Instrument Panel Cluster", "pins": {1: "Body CAN_L", 2: "Body CAN_H", 3: "Ground", 4: "Constant power"}},
    "G01(A)": {"module": "Instrument Panel Cluster IDS", "pins": {1: "Power", 2: "Ground", 3: "High data", 4: "Low data"}},
    "G01(B)": {"module": "Instrument Panel Cluster OIDS screen", "pins": {1: "Screen 12 V", 2: "Screen ground", 3: "Signal", 4: "Shielding"}},
    "G01(C)": {"module": "Instrument Panel Cluster OIDS smart access", "pins": {1: "Smart Access CAN_H", 2: "Smart Access CAN_L"}},
}

OTHER_BODY_MODULES = {
    "G07(A-S)": "Infotainment: Smart Access CAN, Chassis CAN, Energy CAN, USB",
    "Ga91": "Wireless charging: power, ground, Body CAN_L/H",
    "GaT21": "Interior smart access: NFC power, NFC ground, IA CAN_L/H",
    "GB34": "PTC air heater: IG4 power, Energy CAN, ground",
    "P13": "Multi-purpose camera: ground, IG1, Radar CAN, ADAS CAN",
    "DB60": "Front mmWave radar: Radar CAN, ADAS CAN, IG1, ground",
    "G48": "USB module: ground, detection, 12 V",
    "K11(A/B/C)": "Power amplifier: constant power, AMP_CTRL, A2B",
    "K12": "High-frequency module: Smart Access CAN, constant power, ground",
}

ROOF_HARNESS = {
    "diagram_id": "DT778466",
    "connectors": {
        "P01": {"component": "Front interior light", "pins": 24},
        "P02": {"component": "Anti-glare rearview mirror", "pins": 5},
        "P03(A)": {"component": "Main vanity mirror light", "pins": 2},
        "P03(B)": {"component": "Auxiliary vanity mirror light", "pins": 2},
        "P04(A)": {"component": "Left vanity mirror switch", "pins": 2},
        "P04(B)": {"component": "Auxiliary vanity mirror switch", "pins": 2},
        "P10(A)": {"component": "Rear left interior light", "pins": 8},
        "P10(B)": {"component": "Rear right interior light", "pins": 8},
        "P13": {"component": "Multi-purpose camera", "pins": 8},
        "P16": {"component": "ETC", "pins": 3},
        "PG04": {"component": "Four-in-one sensor", "pins": 3},
        "PG86(C)": {"component": "Right domain control unit", "pins": 36},
        "PG87": {"component": "ADAS network terminal resistor", "pins": 2},
    },
    "P01_pin_map": {
        1: "Ground",
        2: "Constant power",
        3: "Clearance light +",
        4: "IG1",
        5: "DOOR",
        6: "MIC L+",
        7: "MIC L-",
        8: "MIC L shield",
        9: "MIC R+",
        10: "MIC R-",
        11: "MIC R shield",
        14: "Interior light master ON",
        15: "Ground",
        16: "Sunroof switch signal",
        17: "Sunroof switch signal",
        18: "Sunroof switch signal",
        19: "Sunroof switch signal",
        20: "Reading light status / master OFF",
        21: "Reading light status / master OFF",
        22: "Reading light status / master OFF",
        23: "Reading light status / master OFF",
        24: "Reading light status / master OFF",
    },
}

SENSORS = {
    "A02": "Desorption pressure sensor",
    "A04": "Intake manifold temperature and pressure sensor",
    "A05": "Electronic throttle",
    "A06": "Intake header pressure sensor",
    "A07": "High-pressure fuel pressure sensor",
    "A08": "Engine oil pressure sensor",
    "A13": "Knock sensor",
    "A15": "EGR temperature sensor",
    "A17": "Engine coolant temperature sensor",
    "A23": "VGT turbocharger actuator",
    "A24": "Rear heated oxygen sensor",
    "A25": "High-pressure oil pump solenoid",
    "A26": "Camshaft position sensor",
    "A28": "Front heated oxygen sensor",
    "A29/A30": "EVVT",
    "A31": "Crankshaft position sensor",
    "A39": "Main oil circuit pressure sensor",
    "A41": "Generator rotary crossing temperature",
    "A42": "Oil temperature sensor",
    "A43": "Clutch pressure sensor",
    "A44(A/B)": "Drive motor rotary / temperature sensor",
    "A45": "GPF differential pressure sensor",
    "A46": "GPF temperature sensor",
    "A47": "Pressure sensor",
    "G05": "Interior temperature sensor",
    "G75(A/B)": "Face-level vent temperature sensor",
    "G99(A/B)": "Footwell vent temperature sensor",
    "DB11(A/B)": "Front corner probe",
    "R01-R04": "Rear corner probes",
    "KG44": "Accelerator pedal",
    "KG28": "Stop light switch",
}

FULL_DIAGRAM_INDEX = {
    "DT778370": "Vehicle Control (UMC)",
    "DT778374": "Charging System (European)",
    "DT778375": "Infotainment",
    "DT778376": "Horn",
    "DT778378": "Charging System (Chinese)",
    "DT778379": "Load and Four-in-one Sensor (PAHA)",
    "DT778382": "Battery Management",
    "DT778383": "Instrument Panel Cluster",
    "DT778384": "Fuel Pump",
    "DT778385": "Side Mirror Electric Adjustment",
    "DT778386": "Engine",
    "DT778387": "Charging and Distribution Ground",
    "DT778388": "Side Mirror and Rear Windshield Heating",
    "DT778389": "Roof Ground",
    "DT778390": "Rear Bumper Layout",
    "DT778391": "Electronic Control Subnet",
    "DT778392": "Front Passenger Seat Vent/Heat",
    "DT778393": "SRS",
    "DT778394": "Driver Power Seat",
    "DT778395": "A/C System",
    "DT778396": "Front Passenger Power Seat",
    "DT778397": "Energy Network",
    "DT778399": "Smart Access Network",
    "DT778400": "Instrument Panel Wiring II",
    "DT778401": "Blind Spot Detection",
    "DT778406": "Electronic Injection Subnet",
    "DT778407": "EPB",
    "DT778409": "Chassis Network",
    "DT778410": "Parking Assist",
    "DT778412": "Body Network",
    "DT778413": "IPB",
    "DT778414": "DP-EPS",
    "DT778416": "ADAS Network",
    "DT778417": "Gearshift Control",
    "DT778418": "Rear Drive Motor Control",
    "DT778419": "Rear Motor Ground",
    "DT778421": "On-board Charger Ground",
    "DT778422": "Anti-glare Interior Mirror",
    "DT778423": "Frame Ground",
    "DT778424": "Engine Ground",
    "DT778425": "ETC and Anti-glare Mirror",
    "DT778426": "Front Compartment Fuse Box Power",
    "DT778430": "Interior Light",
    "DT778431": "Floor Wiring Ground",
    "DT778432": "Side Mirror Puddle Light",
    "DT778433": "Driver Seat Vent/Heat",
    "DT778436": "Turn Signal and Warning",
    "DT778437": "Instrument Panel Ground",
    "DT778438": "Stop Light",
    "DT778439": "Roof Wiring Layout",
    "DT778441": "Fog Light and Reverse Light",
    "DT778442": "Front Left Door Layout",
    "DT778443": "Front Compartment Ground",
    "DT778444": "Position Light and DRL",
    "DT778445": "Rear Left Door Layout",
    "DT778446": "USB Charging and Backup Power",
    "DT778448": "Low/High Beam",
    "DT778449": "Front Right Door Layout",
    "DT778450": "Positive Fuse Box System",
    "DT778451": "Door Lock Motor and Hood Lock",
    "DT778452": "Rear Right Door Layout",
    "DT778453": "Window Regulator",
    "DT778454": "Floor Wiring Layout",
    "DT778455": "Wiper and Washer",
    "DT778456": "Instrument Panel Layout",
    "DT778457": "Seat Belt Reminder (Comfort)",
    "DT778458": "Instrument Panel Fuse Box",
    "DT778459": "Seat Belt Reminder (Loaded)",
    "DT778460": "Front Compartment Layout",
    "DT778461": "HUD",
    "DT778462": "Dual MCU",
    "DT778464": "Instrument Panel Fuse Box Power",
    "DT778466": "Roof Wiring Harness",
}

SERVICE_MANUAL_STACK = {
    "toctree.js": "Master navigation index",
    "dtc-step.js": "DTC diagnostic step engine",
    "svg_topics.js": "SVG hotspot navigation",
    "imageScale.js": "Zoom/pan/drag schematics",
    "custom.js": "Table formatting",
    "treeview.js": "YUI TreeView integration",
    "yahoo.js": "YUI support",
    "tree.css": "Navigation styling",
    "dtc-style.css": "DTC visibility styling",
    "svg-topics.css": "SVG overlay-panel styling",
}

DTC_ENGINE = {
    "model": "step-based pre-rendered HTML decision tree",
    "step_attribute": "data-step",
    "branching": "Yes/No select options",
    "next_step_pattern": "next-stepN+1",
    "inactive_class": "dtc-inactive",
    "inactive_css": ".dtc-inactive { display:none }",
}

SVG_SYSTEM = {
    "overlay_width_px": 260,
    "default_svg_width_px": 608,
    "zoom_min": 0.1,
    "zoom_max": 10.0,
    "behavior": "Component hotspot links jump to terminal definitions",
}

CIRCUIT_TESTING = {
    "voltage_parallel": [
        "Use the voltage input and common/loop terminal on the meter",
        "Select DC voltage range",
        "Connect across the component",
        "Read measured voltage",
    ],
    "current_series": [
        "Use the current input and common/loop terminal on the meter",
        "Select an appropriate current range",
        "Connect meter in series with the circuit",
        "Read measured current",
    ],
    "resistance_unpowered": [
        "Use the resistance input and common/loop terminal",
        "Select resistance range",
        "Confirm circuit/component is unpowered and discharged",
        "Measure resistance",
    ],
    "diode": ["Select diode test", "Test both polarities", "A normal diode conducts primarily in one direction"],
}

DIAGNOSTIC_ARCHITECTURE = {
    "dlc_connector": "G03",
    "standards": ["ISO 15031-3", "SAE J1962"],
    "diagnostic_can": {"can_h_pin": 6, "can_l_pin": 14},
    "security_access_observation": "The supplied reference notes UDS service 0x27 for protected access; Vision Shark does not implement security bypass or unlock generation.",
}


def search_supplement(query: str, limit: int = 50) -> list[dict[str, Any]]:
    needle = str(query).strip().lower()
    if not needle:
        return []
    limit = max(1, min(200, int(limit)))
    rows: list[dict[str, Any]] = []

    def add(kind: str, key: str, text: str, payload: Any) -> None:
        if len(rows) >= limit:
            return
        if needle in f"{key} {text}".lower():
            rows.append({"kind": kind, "key": key, "text": text, "payload": payload})

    for key, value in BODY_MODULE_REFERENCE.items():
        add("body_connector", key, value["module"], {"connector_id": key, **value})
        for pin, function in value.get("pins", {}).items():
            add("body_pin", f"{key}:{pin}", f"{value['module']} {function}", {"connector_id": key, "pin": pin, "function": function})
    for key, value in OTHER_BODY_MODULES.items():
        add("body_module", key, value, {"module_id": key, "summary": value})
    for key, value in SENSORS.items():
        add("sensor", key, value, {"sensor_id": key, "name": value})
    for key, value in FULL_DIAGRAM_INDEX.items():
        add("diagram", key, value, {"diagram_id": key, "title": value})
    for key, value in ROOF_HARNESS["connectors"].items():
        add("roof_connector", key, value["component"], {"connector_id": key, **value})
    for pin, function in ROOF_HARNESS["P01_pin_map"].items():
        add("roof_pin", f"P01:{pin}", function, {"connector_id": "P01", "pin": pin, "function": function})
    for key, value in SERVICE_MANUAL_STACK.items():
        add("manual_software", key, value, {"file": key, "purpose": value})
    return rows[:limit]


def supplement_summary() -> dict[str, Any]:
    return {
        "source_note": SOURCE_NOTE,
        "body_connector_records": len(BODY_MODULE_REFERENCE),
        "other_body_module_records": len(OTHER_BODY_MODULES),
        "roof_connector_records": len(ROOF_HARNESS["connectors"]),
        "sensor_records": len(SENSORS),
        "diagram_records": len(FULL_DIAGRAM_INDEX),
        "manual_software_records": len(SERVICE_MANUAL_STACK),
    }
