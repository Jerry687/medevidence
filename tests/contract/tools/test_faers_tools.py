"""Offline public-contract checks for the structured FAERS aggregate tool."""

from __future__ import annotations

import inspect

from medevidence.tools import FaersAggregateExecution, PersistedFaersAggregate
from medevidence.tools.faers import fetch_faers_aggregate


def test_faers_tool_contracts_are_closed_narrative_free_and_source_neutral() -> None:
    for model in (FaersAggregateExecution, PersistedFaersAggregate):
        schema = model.model_json_schema()
        assert schema["additionalProperties"] is False
        rendered = repr(schema).casefold()
        for forbidden in (
            "httpx",
            "sqlalchemy",
            "pathlib",
            "patient narrative",
            "patient report",
            "reporter",
            "geography",
            "query url",
            "raw response",
        ):
            assert forbidden not in rendered


def test_faers_tool_depends_only_on_consumer_owned_ports() -> None:
    source = inspect.getsource(fetch_faers_aggregate)
    for forbidden in (
        "FaersConnector",
        "SnapshotStore",
        "PersistenceRepository",
        "httpx",
        "sqlalchemy",
        "Path(",
    ):
        assert forbidden not in source
    assert "persistence.persist(executed)" in source
