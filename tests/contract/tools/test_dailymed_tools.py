"""Offline public-contract checks for the structured DailyMed tool."""

from __future__ import annotations

import inspect

from medevidence.tools import (
    DailyMedDiscoveryRequest,
    DailyMedDiscoveryResponse,
    DailyMedFetchRequest,
    DailyMedFetchResponse,
)
from medevidence.tools.dailymed import discover_dailymed_labels, fetch_dailymed_label


def test_dailymed_tool_contract_is_closed_and_source_neutral() -> None:
    for model in (
        DailyMedDiscoveryRequest,
        DailyMedDiscoveryResponse,
        DailyMedFetchRequest,
        DailyMedFetchResponse,
    ):
        schema = model.model_json_schema()
        assert schema["additionalProperties"] is False
        rendered = repr(schema).casefold()
        for forbidden in ("httpx", "sqlalchemy", "elementtree", "pathlib", "xml element"):
            assert forbidden not in rendered


def test_dailymed_tool_functions_depend_only_on_the_consumer_port() -> None:
    source = inspect.getsource(discover_dailymed_labels) + inspect.getsource(fetch_dailymed_label)
    assert "DailyMedConnector" not in source
    assert "httpx" not in source
    assert "sqlalchemy" not in source
    assert "Path(" not in source
