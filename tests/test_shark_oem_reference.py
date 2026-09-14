from fastapi.testclient import TestClient

from vision_shark.api import create_app
from vision_shark.shark_oem_reference import CONNECTORS, NETWORKS, connector, search_reference, summary
from vision_shark.shark_oem_supplement import FULL_DIAGRAM_INDEX, ROOF_HARNESS, SENSORS, search_supplement


def test_reference_summary_and_source_boundary():
    result = summary()
    assert result['vehicle'] == 'BYD Shark 6'
    assert result['powertrain'] == 'DMO PHEV'
    assert result['source']['source_kind'] == 'user_provided_oem_extraction'
    assert result['source']['physical_validation'] is False
    assert result['machine_executable_fault_injection'] is False
    assert result['counts']['network_segments'] == len(NETWORKS)
    assert result['counts']['connector_records'] == len(CONNECTORS)


def test_dlc_connector_and_ecm_can_pair_are_structured():
    dlc = connector('G03')
    assert dlc is not None
    pins = {str(item['pin']): item['function'] for item in dlc['pins']}
    assert pins['6'] == 'Diagnostic network CAN_H'
    assert pins['14'] == 'Diagnostic network CAN_L'
    assert pins['16'] == 'Constant +12 V supply'

    ecm = connector('A01(A)')
    ecm_pins = {str(item['pin']): item['function'] for item in ecm['pins']}
    assert ecm_pins['62'] == 'Electronic injection network CAN_H'
    assert ecm_pins['63'] == 'Electronic injection network CAN_L'


def test_search_finds_pin_network_module_diagram_and_roof_data():
    pin_hits = search_reference('main relay control')
    assert any(item['kind'] == 'pin' and item['key'] == 'A01(A):23' for item in pin_hits)

    network_hits = search_reference('energy_network')
    assert any(item['kind'] == 'network' and item['key'] == 'energy_network' for item in network_hits)

    module_hits = search_reference('Battery Pack')
    assert any(item['kind'] == 'module' and item['key'] == 'BK51' for item in module_hits)

    diagram_hits = search_reference('Electronic Injection Subnet')
    assert any(item['kind'] == 'diagram' and item['key'] == 'DT778406' for item in diagram_hits)

    roof_hits = search_supplement('sunroof switch')
    assert any(item['kind'] in {'body_pin', 'roof_pin'} for item in roof_hits)
    assert ROOF_HARNESS['diagram_id'] == 'DT778466'
    assert 'DT778462' in FULL_DIAGRAM_INDEX
    assert SENSORS['KG44'] == 'Accelerator pedal'


def test_reference_api_exposes_searchable_passive_evidence(tmp_path):
    app = create_app(tmp_path)
    with TestClient(app) as client:
        summary_response = client.get('/api/reference/shark6/summary')
        assert summary_response.status_code == 200
        summary_body = summary_response.json()
        assert summary_body['machine_executable_fault_injection'] is False
        assert summary_body['supplement']['diagram_records'] == len(FULL_DIAGRAM_INDEX)

        dlc = client.get('/api/reference/shark6/connectors/G03')
        assert dlc.status_code == 200
        assert dlc.json()['module'] == 'OBD2 / DLC'

        body_connector = client.get('/api/reference/shark6/connectors/PG86(C)')
        assert body_connector.status_code == 200
        assert body_connector.json()['module'].startswith('Right Domain Control Unit')

        network = client.get('/api/reference/shark6/networks/diagnostic_network')
        assert network.status_code == 200
        assert network.json()['members'][0]['can_h_pin'] == 6
        assert network.json()['members'][0]['can_l_pin'] == 14

        search = client.get('/api/reference/shark6/search', params={'q': 'VCU'})
        assert search.status_code == 200
        assert search.json()['results']

        roof_search = client.get('/api/reference/shark6/search', params={'q': 'sunroof switch'})
        assert roof_search.status_code == 200
        assert roof_search.json()['results']

        assert client.get('/api/reference/shark6/connectors/not-real').status_code == 404


def test_reference_api_exposes_supporting_tables(tmp_path):
    app = create_app(tmp_path)
    with TestClient(app) as client:
        assert client.get('/api/reference/shark6/modules').json()['modules']
        assert len(client.get('/api/reference/shark6/diagrams').json()['diagrams']) == len(FULL_DIAGRAM_INDEX)
        assert client.get('/api/reference/shark6/harnesses').json()['harnesses']
        assert client.get('/api/reference/shark6/wire-colors').json()['wire_colors']
        assert client.get('/api/reference/shark6/grounds').json()['ground_groups']
        assert client.get('/api/reference/shark6/junctions').json()['junctions']
        assert client.get('/api/reference/shark6/power-distribution').json()['instrument_panel_fuse_box_outputs']
        assert client.get('/api/reference/shark6/engine-components').json()['components']
        assert client.get('/api/reference/shark6/body-connectors').json()['connectors']
        assert client.get('/api/reference/shark6/roof-harness').json()['P01_pin_map']
        assert client.get('/api/reference/shark6/sensors').json()['sensors']
        assert client.get('/api/reference/shark6/connector-types').json()['connector_types']
        manual = client.get('/api/reference/shark6/manual-architecture').json()
        assert manual['dtc_engine']['inactive_class'] == 'dtc-inactive'
        assert manual['diagnostic_architecture']['diagnostic_can'] == {'can_h_pin': 6, 'can_l_pin': 14}
        page = client.get('/reference/shark6')
        assert page.status_code == 200
        assert 'SHARK 6 CIRCUIT ATLAS' in page.text
