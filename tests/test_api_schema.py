import json
from pathlib import Path


def test_api_schema_documents_gateway_live_update_routes():
    schema_path = Path(__file__).parents[1] / "web_ui" / "api_schema.json"
    paths = json.loads(schema_path.read_text(encoding="utf-8"))["paths"]

    assert paths["/api/gateway/state"]["get"]["description"]
    assert paths["/api/gateway/ip"]["post"]["requestBody"]["required"] is True
    assert "ip_address" in paths["/api/gateway/ip"]["post"]["requestBody"]["schema"]["required"]
    assert paths["/api/gateway/ip/reset"]["post"]["description"]
    assert paths["/api/gateway/ip/undo"]["post"]["description"]
