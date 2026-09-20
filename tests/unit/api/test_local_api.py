"""Local server delegates research routes without constructing source clients."""

import pytest
from fastapi.testclient import TestClient
from tests.unit.api.test_research_routes import FakeResearchApplication

from medevidence.local_api import create_local_research_app


@pytest.mark.allow_hosts(["127.0.0.1", "::1"])
def test_local_application_is_injected_and_documents_research_routes() -> None:
    application = FakeResearchApplication()
    app = create_local_research_app(application)
    with TestClient(app) as client:
        assert client.get("/openapi.json").status_code == 200
        response = client.get("/v1/research/runs", params={"limit": 10, "offset": 0})
    assert response.status_code == 200
    assert application.calls == ["list"]
