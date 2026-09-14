from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException, Query
from fastapi.responses import FileResponse

from .shark_oem_reference import (
    CONNECTORS,
    DIAGRAMS,
    ENGINE_COMPONENTS,
    FUSE_BOXES,
    G82_OUTPUTS,
    GROUND_POINTS,
    HARNESS_CODES,
    JUNCTIONS,
    MODULES,
    NETWORKS,
    SOURCE,
    WIRE_COLORS,
    connector,
    network,
    search_reference,
    summary,
)
from .shark_oem_supplement import (
    BODY_MODULE_REFERENCE,
    CIRCUIT_TESTING,
    CONNECTOR_TYPES,
    DIAGNOSTIC_ARCHITECTURE,
    DTC_ENGINE,
    FULL_DIAGRAM_INDEX,
    OTHER_BODY_MODULES,
    ROOF_HARNESS,
    SENSORS,
    SERVICE_MANUAL_STACK,
    SVG_SYSTEM,
    search_supplement,
    supplement_summary,
)


def install_shark_oem_routes(app):
    web = Path(__file__).parent / 'web'

    @app.get('/reference/shark6')
    def shark6_reference_page():
        page = web / 'shark_reference.html'
        if not page.is_file():
            raise HTTPException(404, 'reference page unavailable')
        return FileResponse(page)

    @app.get('/api/reference/shark6/summary')
    def shark6_reference_summary():
        result = summary()
        result['supplement'] = supplement_summary()
        return result

    @app.get('/api/reference/shark6/connectors')
    def shark6_connectors():
        return {
            'source': dict(SOURCE),
            'connectors': [item.model_dump(mode='json') for _, item in sorted(CONNECTORS.items())],
        }

    @app.get('/api/reference/shark6/connectors/{connector_id}')
    def shark6_connector(connector_id: str):
        result = connector(connector_id)
        if result is None:
            supplement = BODY_MODULE_REFERENCE.get(connector_id)
            if supplement is not None:
                return {'connector_id': connector_id, **supplement, 'source': dict(SOURCE)}
            raise HTTPException(404, 'connector not found')
        return result

    @app.get('/api/reference/shark6/networks')
    def shark6_networks():
        return {'source': dict(SOURCE), 'networks': [item.model_dump(mode='json') for item in NETWORKS]}

    @app.get('/api/reference/shark6/networks/{network_name}')
    def shark6_network(network_name: str):
        result = network(network_name)
        if result is None:
            raise HTTPException(404, 'network not found')
        return result

    @app.get('/api/reference/shark6/search')
    def shark6_search(q: str = Query(min_length=1, max_length=120), limit: int = Query(default=50, ge=1, le=200)):
        primary = search_reference(q, limit)
        extra = search_supplement(q, limit)
        seen: set[tuple[str, str]] = set()
        merged = []
        for item in [*primary, *extra]:
            key = (item['kind'], item['key'])
            if key in seen:
                continue
            seen.add(key)
            merged.append(item)
            if len(merged) >= limit:
                break
        return {'query': q, 'results': merged, 'source': dict(SOURCE)}

    @app.get('/api/reference/shark6/modules')
    def shark6_modules():
        return {
            'source': dict(SOURCE),
            'modules': [{'module_id': key, 'name': value} for key, value in sorted(MODULES.items())],
            'body_module_summaries': [{'module_id': key, 'summary': value} for key, value in sorted(OTHER_BODY_MODULES.items())],
        }

    @app.get('/api/reference/shark6/diagrams')
    def shark6_diagrams():
        return {
            'source': dict(SOURCE),
            'diagrams': [{'diagram_id': key, 'title': value} for key, value in FULL_DIAGRAM_INDEX.items()],
            'core_diagrams': [{'diagram_id': item.diagram_id, 'title': item.title} for item in DIAGRAMS],
        }

    @app.get('/api/reference/shark6/harnesses')
    def shark6_harnesses():
        return {'source': dict(SOURCE), 'harnesses': [{'code': key, 'name': value} for key, value in HARNESS_CODES.items()]}

    @app.get('/api/reference/shark6/wire-colors')
    def shark6_wire_colors():
        return {'source': dict(SOURCE), 'wire_colors': [{'code': key, 'color': value} for key, value in WIRE_COLORS.items()]}

    @app.get('/api/reference/shark6/grounds')
    def shark6_grounds():
        return {'source': dict(SOURCE), 'ground_groups': GROUND_POINTS}

    @app.get('/api/reference/shark6/junctions')
    def shark6_junctions():
        return {'source': dict(SOURCE), 'junctions': JUNCTIONS}

    @app.get('/api/reference/shark6/power-distribution')
    def shark6_power_distribution():
        return {
            'source': dict(SOURCE),
            'fuse_boxes': FUSE_BOXES,
            'instrument_panel_fuse_box_outputs': [
                {'pin': pin, 'function': function} for pin, function in sorted(G82_OUTPUTS.items())
            ],
        }

    @app.get('/api/reference/shark6/engine-components')
    def shark6_engine_components():
        return {
            'source': dict(SOURCE),
            'components': [{'connector_id': key, **value} for key, value in sorted(ENGINE_COMPONENTS.items())],
        }

    @app.get('/api/reference/shark6/body-connectors')
    def shark6_body_connectors():
        return {'source': dict(SOURCE), 'connectors': [{'connector_id': key, **value} for key, value in sorted(BODY_MODULE_REFERENCE.items())]}

    @app.get('/api/reference/shark6/roof-harness')
    def shark6_roof_harness():
        return {'source': dict(SOURCE), **ROOF_HARNESS}

    @app.get('/api/reference/shark6/sensors')
    def shark6_sensors():
        return {'source': dict(SOURCE), 'sensors': [{'sensor_id': key, 'name': value} for key, value in sorted(SENSORS.items())]}

    @app.get('/api/reference/shark6/connector-types')
    def shark6_connector_types():
        return {'source': dict(SOURCE), 'connector_types': CONNECTOR_TYPES}

    @app.get('/api/reference/shark6/manual-architecture')
    def shark6_manual_architecture():
        return {
            'source': dict(SOURCE),
            'software_stack': SERVICE_MANUAL_STACK,
            'dtc_engine': DTC_ENGINE,
            'svg_system': SVG_SYSTEM,
            'diagnostic_architecture': DIAGNOSTIC_ARCHITECTURE,
            'circuit_testing': CIRCUIT_TESTING,
        }
