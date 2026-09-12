from pathlib import Path

from fastapi.testclient import TestClient

from vision_shark.api import create_app


def test_metrics_are_low_cardinality_and_operational(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        response=client.get('/metrics')
        assert response.status_code==200
        assert response.headers['content-type'].startswith('text/plain')
        text=response.text
        for name in ('vision_gateway_up','vision_vehicle_ready','vision_frames_seen_total','vision_receive_drops_total','vision_audit_chain_ok'):
            assert name in text
        assert 'LGX' not in text and 'vin=' not in text.lower()


def test_operator_page_exposes_explicit_enet_and_passive_sniffer_controls():
    root=Path(__file__).resolve().parents[1]/'vision_shark'/'web'
    html=(root/'index.html').read_text()
    script=(root/'app.js').read_text()
    assert 'DISCOVER ENET / DOIP' in html
    assert 'VISION_ALLOW_DOIP_DISCOVERY=1' in html
    assert 'id="sniffer"' in html and 'id="changedOnly"' in html
    assert "/api/discovery/adapters" in script
    assert "/api/vision/connect-doip" in script
    assert "/api/sniffer?changed_only=" in script
    assert "ENET/DoIP discovery and passive CAN/CAN-FD are detected automatically" not in html
