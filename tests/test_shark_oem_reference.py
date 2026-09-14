from fastapi.testclient import TestClient

from vision_shark.api import create_app
from vision_shark.shark_oem_reference import CONNECTORS, NETWORKS, connector, search_reference, summary


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


def test_search_finds_pin_network_module_and_diagram():
    pin_hits = search_reference('main relay control')
    assert any(item['kind'] == 'pin' and item['key'] == 'A01(A):23' for item in pin_hits)

    network_hits = search_reference('energy network')
    assert any(item['kind'] == 'network' and item['key'] == 'energy_network' for item in network_hits)

    module_hits = search_reference('Battery Pack')
    assert any(item['kind'] == 'module' and item['key'] == 'BK51' for item in module_hits)

    diagram_hits = search_reference('Electronic Injection Subnet')
    assert any(item['kind'] == 'diagram' and item['key'] == 'DT778406' for item in diagram_hits)


def test_reference_api_exposes_searchable_passive_evidence(tmp_path):
    app = create_app(tmp_path)
    with TestClient(app) as client:
        summary_response = client.get('/api/reference/shark6/summary')
        assert summary_response.status_code == 200
        assert summary_response.json()['machine_executable_fault_injection'] is False

        dlc = client.get('/api/reference/shark6/connectors/G03')
        assert dlc.status_code == 200
        assert dlc.json()['module'] == 'OBD2 / DLC'

        network = client.get('/api/reference/shark6/networks/diagnostic_network')
        assert network.status_code == 200
        assert network.json()['members'][0]['can_h_pin'] == 6
        assert network.json()['members'][0]['can_l_pin'] == 14

        search = client.get('/api/reference/shark6/search', params={'q': 'VCU'})
        assert search.status_code == 200
        assert search.json()['results']

        assert client.get('/api/reference/shark6/connectors/not-real').status_code == 404


def test_reference_api_exposes_supporting_tables(tmp_path):
    app = create_app(tmp_path)
    with TestClient(app) as client:
        assert client.get('/api/reference/shark6/modules').json()['modules']
        assert client.get('/api/reference/shark6/diagrams').json()['diagrams']
        assert client.get('/api/reference/shark6/harnesses').json()['harnesses']
        assert client.get('/api/reference/shark6/wire-colors').json()['wire_colors']
        assert client.get('/api/reference/shark6/grounds').json()['ground_groups']
        assert client.get('/api/reference/shark6/junctions').json()['junctions']
        assert client.get('/api/reference/shark6/power-distribution').json()['instrument_panel_fuse_box_outputs']
        assert client.get('/api/reference/shark6/engine-components').json()['components']
