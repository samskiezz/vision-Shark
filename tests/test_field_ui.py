from fastapi.testclient import TestClient

from vision_shark.api import create_app


def test_operator_ui_exposes_research_run_card_and_field_script(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        response = client.get("/")
        assert response.status_code == 200
        html = response.text
        assert "Research Run Card" in html
        assert 'id="runVehicleId"' in html
        assert 'id="runFirmware"' in html
        assert 'id="runTrailerMass"' in html
        assert 'id="runMods"' in html
        assert 'src="/static/field.js"' in html

        script = client.get("/static/field.js")
        assert script.status_code == 200
        assert "/api/research/session-context/" in script.text
        assert "START RESEARCH RUN" in script.text
        assert "/api/recordings/stop" in script.text
