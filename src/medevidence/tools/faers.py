"""Stable structured FAERS aggregate operation over injected consumer ports."""

from __future__ import annotations

from medevidence.domain import FaersAggregateQueryV1, FaersAggregateRequestV1, FaersAggregateResult

from .contracts import FaersAggregateExecution, PersistedFaersAggregate
from .ports import FaersExecutionPort, FaersPersistencePort


def fetch_faers_aggregate(
    request: FaersAggregateRequestV1,
    *,
    execution: FaersExecutionPort,
    persistence: FaersPersistencePort,
) -> FaersAggregateResult:
    """Execute and persist one exact provider-count aggregate before returning it."""

    validated_request = FaersAggregateRequestV1.model_validate(request.model_dump(mode="python"))
    if validated_request != request:
        raise ValueError("FAERS tool request differs from closed validation")
    query = FaersAggregateQueryV1.create(validated_request)
    executed = FaersAggregateExecution.model_validate(
        execution.execute(query).model_dump(mode="python")
    )
    if executed.request != validated_request or executed.result.query != query:
        raise ValueError("FAERS execution belongs to another exact request or query")
    persisted = PersistedFaersAggregate.model_validate(
        persistence.persist(executed).model_dump(mode="python")
    )
    if persisted.execution != executed:
        raise ValueError("persisted FAERS evidence differs from the exact execution")
    return FaersAggregateResult.model_validate(persisted.execution.result.model_dump(mode="python"))
