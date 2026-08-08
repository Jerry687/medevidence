"""Separately authorized, single-shot live PubMed smoke test (disabled by default)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import httpx
import pytest

from medevidence.api.contracts import ResearchPubMedApiRequest
from medevidence.api.routes import REQUEST_EXAMPLE
from medevidence.catalog import load_production_catalog
from medevidence.connectors.pubmed import PubMedClientIdentity, PubMedConnector
from medevidence.connectors.pubmed.policy import PubMedConnectorConfig
from medevidence.ingestion.snapshots import SnapshotStore
from medevidence.tools.pubmed import build_pubmed_query, query_identity

pytestmark = [pytest.mark.live_api, pytest.mark.enable_socket]


def test_live_pubmed_one_page_one_record() -> None:
    if os.environ.get("MEDEVIDENCE_RUN_LIVE_PUBMED") != "1":
        pytest.skip("live PubMed requires explicit Owner-run opt-in")
    email = os.environ.get("NCBI_EMAIL")
    if email is None or not email.strip():
        pytest.fail("NCBI_EMAIL must be supplied by the Owner for the live gate")
    root_value = os.environ.get("MEDEVIDENCE_LIVE_SNAPSHOT_ROOT")
    if root_value is None:
        pytest.fail("MEDEVIDENCE_LIVE_SNAPSHOT_ROOT outside Git is required")
    root = Path(root_value).resolve()
    repository_root = Path(__file__).resolve().parents[2]
    if root == repository_root or repository_root in root.parents:
        pytest.fail("live raw bytes must be stored outside the Git repository")

    request = ResearchPubMedApiRequest.model_validate_json(json.dumps(REQUEST_EXAMPLE))
    catalog = load_production_catalog()
    scope = request.to_scope(catalog)
    query = build_pubmed_query(scope, catalog.resolve_scope(scope))
    query_id = query_identity(scope, query)
    config = PubMedConnectorConfig(
        page_size=1,
        max_pages=1,
        max_records=1,
        max_attempts=1,
        max_redirects=1,
    )
    connector = PubMedConnector(
        httpx.HTTPTransport(retries=0),
        config,
        identity=PubMedClientIdentity(email=email),
    )
    store = SnapshotStore(root)
    try:
        search = connector.search(query, query_id=query_id)
        responses = list(search.raw_responses)
        if search.pmids:
            fetch = connector.fetch(search.pmids[:1], query_id=query_id)
            responses.extend(fetch.raw_responses)
        with store.writer():
            for response in responses:
                store.store_raw_body(response.body)
        assert len(search.pmids) <= 1
    finally:
        connector.close()
