from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Event
from typing import Any

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import BaseModel
from tests.unit.orchestration.test_workflow import (
    FakeSynthesis,
    Harness,
    _initial,
    _run_until_node,
    _run_until_terminal,
    _self_consistent_terminal_child_forgery,
    _validation_registry,
)

from medevidence.domain import SourceType, canonical_json
from medevidence.orchestration import (
    WORKFLOW_TOPOLOGY,
    CollectionFailureClassification,
    ReviewDecision,
    WorkflowDisposition,
    WorkflowNode,
    WorkflowTransitionError,
)
from medevidence.orchestration.langgraph_runtime import (
    _MAX_PAYLOAD_BYTES,
    _START_GUARDS,
    CHECKPOINT_NAMESPACE,
    LangGraphOrchestrationRuntime,
    _runtime_route,
    _validate_envelope,
)
from medevidence.tools.report_validation import SemanticSupport


def _runtime(
    harness: Harness | None = None,
) -> tuple[Harness, InMemorySaver, LangGraphOrchestrationRuntime]:
    bound = harness or Harness()
    saver = InMemorySaver()
    return (
        bound,
        saver,
        LangGraphOrchestrationRuntime(workflow=bound.workflow, checkpointer=saver),
    )


def _walk(value: object) -> Iterator[object]:
    yield value
    if type(value) is dict:
        for key, item in value.items():
            yield from _walk(key)
            yield from _walk(item)
    elif type(value) is list:
        for item in value:
            yield from _walk(item)


def _stored_payload(
    saver: InMemorySaver,
    run_id: str,
) -> dict[str, object]:
    result = saver.get_tuple(
        {
            "configurable": {
                "thread_id": run_id,
                "checkpoint_ns": CHECKPOINT_NAMESPACE,
            }
        }
    )
    assert result is not None
    payload = result.checkpoint["channel_values"]["state_payload"]
    assert type(payload) is dict
    return payload


def _swap_latest_stored_payload(
    saver: InMemorySaver,
    run_id: str,
    payload: dict[str, object],
) -> None:
    checkpoints = saver.storage[run_id][CHECKPOINT_NAMESPACE]
    latest_checkpoint_id = next(reversed(checkpoints))
    checkpoint = saver.serde.loads_typed(checkpoints[latest_checkpoint_id][0])
    assert type(checkpoint) is dict
    version = checkpoint["channel_versions"]["state_payload"]
    saver.blobs[(run_id, CHECKPOINT_NAMESPACE, "state_payload", version)] = saver.serde.dumps_typed(
        payload
    )


def test_graph_has_exact_nodes_one_interrupt_and_no_retry_policy() -> None:
    _, _, runtime = _runtime()
    edges = {(edge.source, edge.target) for edge in runtime._graph.get_graph().edges}

    assert set(runtime._graph.get_graph().nodes) == {
        "__start__",
        *(node.value for node in WORKFLOW_TOPOLOGY),
        "__end__",
    }
    assert runtime._graph.interrupt_before_nodes == [WorkflowNode.REQUEST_EXPORT_APPROVAL.value]
    assert runtime._graph.interrupt_after_nodes == []
    assert all(node.retry_policy is None for node in runtime._graph.nodes.values())
    assert ("__start__", WorkflowNode.SCOPE_AND_SAFETY.value) in edges
    assert not any(
        source == "__start__" and target != WorkflowNode.SCOPE_AND_SAFETY.value
        for source, target in edges
    )
    assert (WorkflowNode.COLLECT_EVIDENCE.value, WorkflowNode.COLLECT_EVIDENCE.value) in edges
    assert (
        WorkflowNode.REQUEST_EXPORT_APPROVAL.value,
        WorkflowNode.SYNTHESIZE_CLAIMS.value,
    ) in edges
    assert (
        WorkflowNode.SCOPE_AND_SAFETY.value,
        WorkflowNode.FINALIZE_AND_EXPORT.value,
    ) not in edges


def test_start_interrupts_before_approval_then_resume_exports_exactly_once() -> None:
    harness, saver, runtime = _runtime()
    initial = _initial()

    interrupted = runtime.start(initial)

    assert interrupted.terminal is False
    assert interrupted.interrupted_before is WorkflowNode.REQUEST_EXPORT_APPROVAL
    assert interrupted.state.current_node is WorkflowNode.REQUEST_EXPORT_APPROVAL
    assert harness.approval.calls == 0
    assert harness.export.calls == 0
    assert harness.collector.replay_calls
    replay_count = len(harness.collector.replay_calls)
    assert runtime.inspect(initial.run_id) == interrupted
    assert len(harness.collector.replay_calls) == replay_count + 1
    assert tuple(saver.storage[initial.run_id]) == (CHECKPOINT_NAMESPACE,)
    assert (
        saver.get_tuple({"configurable": {"thread_id": initial.run_id, "checkpoint_ns": ""}})
        is None
    )

    completed = runtime.resume(initial.run_id)
    inspected = runtime.inspect(initial.run_id)
    repeated = runtime.resume(initial.run_id)

    assert completed.terminal is True
    assert completed.state.disposition is WorkflowDisposition.EXPORTED
    assert completed == inspected == repeated
    assert harness.approval.calls == 1
    assert harness.export.calls == 1
    assert harness.collector.calls == [initial.original_scope.selected_sources[0]]


def test_pending_review_inspect_rejects_forged_terminal_source_before_effect() -> None:
    harness, saver, runtime = _runtime()
    initial = _initial()
    interrupted = runtime.start(initial)
    assert interrupted.state.current_node is WorkflowNode.REQUEST_EXPORT_APPROVAL
    forged = _self_consistent_terminal_child_forgery(interrupted.state)
    _swap_latest_stored_payload(saver, initial.run_id, forged.model_dump(mode="json"))
    before = (
        tuple(harness.events),
        harness.receipts.save_calls,
        harness.receipts.load_calls,
        harness.persistence.calls,
        harness.persistence.load_calls,
        harness.approval.calls,
        harness.export.calls,
        deepcopy(saver.storage),
    )

    with pytest.raises(WorkflowTransitionError, match="source terminal replay failed"):
        runtime.inspect(initial.run_id)
    assert before == (
        tuple(harness.events),
        harness.receipts.save_calls,
        harness.receipts.load_calls,
        harness.persistence.calls,
        harness.persistence.load_calls,
        harness.approval.calls,
        harness.export.calls,
        saver.storage,
    )


def test_collection_loops_existing_attempt_and_selected_tasks_remain_exact() -> None:
    harness, _, runtime = _runtime()

    result = runtime.start(_initial())

    assert harness.collector.attempts_seen == [(result.state.original_scope.selected_sources[0], 1)]
    assert tuple(item.source for item in result.state.source_tasks) == tuple(
        item.source for item in result.state.source_plan if item.planning_status.value == "selected"
    )
    assert all(item.status.value == "terminal" for item in result.state.source_tasks)


def test_edit_routes_back_to_synthesis_and_stops_at_same_interrupt() -> None:
    harness = Harness(decisions=[ReviewDecision.EDIT, ReviewDecision.APPROVE])
    alternate_registry = _validation_registry(
        harness.scope,
        None,
        support=SemanticSupport.SUPPORTED,
        claim_variant=1,
    )

    class EditingSynthesis(FakeSynthesis):
        def synthesize(self, **kwargs: Any) -> Any:
            if kwargs["prior_report_content_hash"] is not None:
                self.registry = alternate_registry
                harness.registry = alternate_registry
                harness.workflow = harness.new_workflow()
                runtime._workflow = harness.workflow
            return super().synthesize(**kwargs)

    harness.synthesis = EditingSynthesis(harness.events, harness.registry)
    harness.workflow = harness.new_workflow()
    _, _, runtime = _runtime(harness)
    run_id = _initial().run_id

    first = runtime.start(_initial())
    edited = runtime.resume(run_id)
    exported = runtime.resume(run_id)

    assert first.interrupted_before is WorkflowNode.REQUEST_EXPORT_APPROVAL
    assert edited.interrupted_before is WorkflowNode.REQUEST_EXPORT_APPROVAL
    assert edited.state.current_node is WorkflowNode.REQUEST_EXPORT_APPROVAL
    assert len(harness.synthesis.prior_hashes) == 2
    assert exported.terminal is True
    assert harness.approval.calls == 2
    assert harness.export.calls == 1
    assert len(harness.collector.calls) == 1


def test_early_terminal_policy_state_does_not_reach_other_capabilities() -> None:
    harness, _, runtime = _runtime(Harness(blocked=True))

    result = runtime.start(_initial())
    repeated = runtime.resume(result.state.run_id)

    assert result == repeated
    assert result.terminal is True
    assert result.state.disposition is WorkflowDisposition.POLICY_BLOCKED
    assert harness.events == ["scope_and_safety"]


@pytest.mark.parametrize("node", WORKFLOW_TOPOLOGY[1:])
def test_start_rejects_every_noninitial_node_before_checkpoint_or_capability(
    node: WorkflowNode,
) -> None:
    harness = Harness()
    advanced = _run_until_node(harness.workflow, _initial(), node)
    events = tuple(harness.events)
    effects = (
        harness.receipts.save_calls,
        harness.receipts.load_calls,
        harness.persistence.calls,
        harness.persistence.load_calls,
        harness.approval.calls,
        harness.export.calls,
    )
    _, saver, runtime = _runtime(harness)

    with pytest.raises(WorkflowTransitionError, match="exact pristine initial state"):
        runtime.start(advanced)

    assert tuple(harness.events) == events
    assert (
        harness.receipts.save_calls,
        harness.receipts.load_calls,
        harness.persistence.calls,
        harness.persistence.load_calls,
        harness.approval.calls,
        harness.export.calls,
    ) == effects
    assert not saver.storage


@pytest.mark.parametrize(
    ("case", "expected"),
    [
        ("policy", WorkflowDisposition.POLICY_BLOCKED),
        ("collection", WorkflowDisposition.COLLECTION_BLOCKED),
        ("validation", WorkflowDisposition.VALIDATION_BLOCKED),
        ("rejected", WorkflowDisposition.REJECTED),
        ("exported", WorkflowDisposition.EXPORTED),
    ],
)
def test_start_rejects_every_terminal_topology_before_checkpoint_or_capability(
    case: str,
    expected: WorkflowDisposition,
) -> None:
    if case == "policy":
        harness = Harness(blocked=True)
    elif case == "collection":
        harness = Harness(
            typed_failures={SourceType.PUBMED: [CollectionFailureClassification.PERMANENT]}
        )
    elif case == "validation":
        harness = Harness(validation_passed=False)
    elif case == "rejected":
        harness = Harness(decisions=[ReviewDecision.REJECT])
    else:
        harness = Harness()
    terminal = _run_until_terminal(harness.workflow, _initial())
    assert terminal.disposition is expected
    events = tuple(harness.events)
    effects = (
        harness.receipts.save_calls,
        harness.receipts.load_calls,
        harness.persistence.calls,
        harness.persistence.load_calls,
        harness.approval.calls,
        harness.export.calls,
    )
    _, saver, runtime = _runtime(harness)

    with pytest.raises(WorkflowTransitionError, match="exact pristine initial state"):
        runtime.start(terminal)

    assert tuple(harness.events) == events
    assert (
        harness.receipts.save_calls,
        harness.receipts.load_calls,
        harness.persistence.calls,
        harness.persistence.load_calls,
        harness.approval.calls,
        harness.export.calls,
    ) == effects
    assert not saver.storage


@pytest.mark.parametrize(
    "field",
    [
        "interpreted_scope",
        "safety_decision",
        "source_plan",
        "source_tasks",
        "synthesis",
        "validation",
        "validation_receipt_ref",
        "report_status",
        "pending_draft",
        "review_history",
        "active_approval",
        "export_record",
        "edit_base_content_hash",
        "completed_nodes",
        "current_node",
        "disposition",
    ],
)
def test_start_rejects_each_noninitial_durable_field_without_effect(field: str) -> None:
    fixture = Harness()
    terminal = _run_until_terminal(fixture.workflow, _initial())
    residuals: dict[str, object] = {
        name: getattr(terminal, name)
        for name in (
            "interpreted_scope",
            "safety_decision",
            "source_plan",
            "source_tasks",
            "synthesis",
            "validation",
            "validation_receipt_ref",
            "report_status",
            "pending_draft",
            "review_history",
            "active_approval",
            "export_record",
            "completed_nodes",
            "current_node",
            "disposition",
        )
    }
    residuals["edit_base_content_hash"] = "sha256:" + "7" * 64
    if field == "current_node":
        residuals[field] = WorkflowNode.PLAN_SOURCES
    bound, saver, runtime = _runtime()
    forged = _initial().model_copy(update={field: residuals[field]})

    with pytest.raises(WorkflowTransitionError):
        runtime.start(forged)

    assert bound.events == []
    assert not saver.storage


def test_start_rejects_reviewer_reset_topology_with_retained_foreign_data() -> None:
    harness = Harness()
    collected = _run_until_node(
        harness.workflow,
        _initial(),
        WorkflowNode.SYNTHESIZE_CLAIMS,
    )
    reset = collected.model_copy(
        update={
            "completed_nodes": (),
            "current_node": WorkflowNode.SCOPE_AND_SAFETY,
            "disposition": WorkflowDisposition.ACTIVE,
        }
    )
    events = tuple(harness.events)
    effects = (
        harness.receipts.save_calls,
        harness.receipts.load_calls,
        harness.persistence.calls,
        harness.persistence.load_calls,
        harness.approval.calls,
        harness.export.calls,
    )
    _, saver, runtime = _runtime(harness)

    with pytest.raises(WorkflowTransitionError, match="exact pristine initial state"):
        runtime.start(reset)

    assert tuple(harness.events) == events
    assert (
        harness.receipts.save_calls,
        harness.receipts.load_calls,
        harness.persistence.calls,
        harness.persistence.load_calls,
        harness.approval.calls,
        harness.export.calls,
    ) == effects
    assert not saver.storage


class _UnexpectedModel(BaseModel):
    value: str


def _excessive_depth() -> dict[str, object]:
    root: dict[str, object] = {}
    cursor = root
    for _ in range(34):
        nested: dict[str, object] = {}
        cursor["nested"] = nested
        cursor = nested
    return {"state_payload": root}


def test_checkpoint_budget_accepts_exact_maximum_and_rejects_max_plus_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exact_payload = {"a": "x" * 999_999, "b": "y" * 999_986}
    assert len(canonical_json(exact_payload).encode("utf-8")) == _MAX_PAYLOAD_BYTES
    assert _validate_envelope({"state_payload": exact_payload}) == exact_payload

    excessive_payload = {"a": "x" * 999_999, "b": "y" * 999_987}
    assert len(canonical_json(excessive_payload).encode("utf-8")) == (_MAX_PAYLOAD_BYTES + 1)
    monkeypatch.setattr(
        "medevidence.orchestration.langgraph_runtime.canonical_json",
        lambda _value: pytest.fail("whole-payload canonical allocation was reached"),
    )
    with pytest.raises(WorkflowTransitionError, match="canonical byte bound"):
        _validate_envelope({"state_payload": excessive_payload})


def test_checkpoint_budget_counts_aggregate_mapping_keys_and_values_before_encoding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {f"{index:04d}" + "k" * 112: "v" * 125 for index in range(8_192)}
    assert len(payload) == 8_192
    assert max(len(key.encode("utf-8")) for key in payload) < 16_384
    assert max(len(value.encode("utf-8")) for value in payload.values()) < 1_000_000
    monkeypatch.setattr(
        "medevidence.orchestration.langgraph_runtime.canonical_json",
        lambda _value: pytest.fail("whole-payload canonical allocation was reached"),
    )

    with pytest.raises(WorkflowTransitionError, match="canonical byte bound"):
        _validate_envelope({"state_payload": payload})


def test_checkpoint_budget_bounds_individual_mapping_key_by_utf8_bytes() -> None:
    oversized_utf8_key = "药" * 5_462
    assert len(oversized_utf8_key) < 16_384
    assert len(oversized_utf8_key.encode("utf-8")) > 16_384

    with pytest.raises(WorkflowTransitionError, match="mapping key exceeds"):
        _validate_envelope({"state_payload": {oversized_utf8_key: None}})


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {"state_payload": {}, "extra": {}},
        {"state_payload": []},
        {"state_payload": {1: "value"}},
        {"state_payload": {"value": ("tuple",)}},
        {"state_payload": {"value": {"set"}}},
        {"state_payload": {"value": b"bytes"}},
        {"state_payload": {"value": _UnexpectedModel(value="model")}},
        {"state_payload": {"value": lambda: None}},
        {"state_payload": {"value": float("nan")}},
        {"state_payload": {"value": float("inf")}},
        {"state_payload": {"value": [None] * 8_193}},
        {"state_payload": {"value": "x" * 1_000_001}},
        {"state_payload": {"value": [[None] * 8 for _ in range(7_000)]}},
        _excessive_depth(),
    ],
)
def test_route_rejects_nonprimitive_or_unbounded_payload_before_capability(
    payload: object,
) -> None:
    harness, _, runtime = _runtime()

    with pytest.raises(WorkflowTransitionError):
        _runtime_route(runtime, payload)

    assert harness.events == []


def test_route_reconstructs_and_follows_current_node_only() -> None:
    harness, _, runtime = _runtime()
    initial = _initial()
    payload = initial.model_dump(mode="json")

    assert (
        _runtime_route(runtime, {"state_payload": payload}) == WorkflowNode.SCOPE_AND_SAFETY.value
    )
    assert harness.events == []

    payload["current_node"] = WorkflowNode.PLAN_SOURCES.value
    with pytest.raises(WorkflowTransitionError):
        _runtime_route(runtime, {"state_payload": payload})
    assert harness.events == []


def test_cross_run_checkpoint_fails_before_dispatch() -> None:
    harness, _, runtime = _runtime()
    initial = _initial()
    foreign_run = "run:87654321-4321-4321-8321-cba987654321"
    payload = initial.model_dump(mode="json")
    runtime._graph.update_state(
        {"configurable": {"thread_id": foreign_run}},
        {"state_payload": payload},
        as_node="__start__",
    )

    with pytest.raises(WorkflowTransitionError, match="another run"):
        runtime.inspect(foreign_run)

    assert harness.events == []


@pytest.mark.parametrize("entrypoint", ["inspect", "resume"])
@pytest.mark.parametrize(
    ("replacement", "scheduler", "queued"),
    [
        (
            "active",
            "approval",
            (WorkflowNode.REQUEST_EXPORT_APPROVAL.value,),
        ),
        ("active", "terminal", ()),
        (
            "terminal",
            "approval",
            (WorkflowNode.REQUEST_EXPORT_APPROVAL.value,),
        ),
    ],
)
def test_swapped_payload_and_scheduler_topology_fails_without_effect(
    entrypoint: str,
    replacement: str,
    scheduler: str,
    queued: tuple[str, ...],
) -> None:
    harness, saver, runtime = _runtime()
    run_id = _initial().run_id
    runtime.start(_initial())
    if scheduler == "terminal":
        runtime.resume(run_id)
    fixture = Harness()
    swapped = (
        _run_until_node(
            fixture.workflow,
            _initial(),
            WorkflowNode.SYNTHESIZE_CLAIMS,
        )
        if replacement == "active"
        else _run_until_terminal(fixture.workflow, _initial())
    )
    _swap_latest_stored_payload(
        saver,
        run_id,
        swapped.model_dump(mode="json"),
    )
    snapshot = runtime._graph.get_state({"configurable": {"thread_id": run_id}})
    assert snapshot.next == queued
    if replacement == "active":
        assert swapped.current_node is WorkflowNode.SYNTHESIZE_CLAIMS
    else:
        assert swapped.current_node is None
    events = tuple(harness.events)
    effects = (
        harness.receipts.save_calls,
        harness.receipts.load_calls,
        harness.persistence.calls,
        harness.persistence.load_calls,
        harness.approval.calls,
        harness.export.calls,
    )
    storage = deepcopy(saver.storage)

    with pytest.raises(WorkflowTransitionError, match="scheduling topology drift"):
        getattr(runtime, entrypoint)(run_id)

    assert tuple(harness.events) == events
    assert (
        harness.receipts.save_calls,
        harness.receipts.load_calls,
        harness.persistence.calls,
        harness.persistence.load_calls,
        harness.approval.calls,
        harness.export.calls,
    ) == effects
    assert saver.storage == storage


def test_forged_receipt_reference_fails_before_approval_or_export() -> None:
    harness, _, runtime = _runtime()
    run_id = _initial().run_id
    interrupted = runtime.start(_initial())
    payload = interrupted.state.model_dump(mode="json")
    payload["validation_receipt_ref"] = {
        "schema_version": "m3.validation-receipt-ref.v1",
        "receipt_id": "validation-receipt:sha256:" + "9" * 64,
        "receipt_content_hash": "sha256:" + "9" * 64,
    }
    runtime._graph.update_state(
        {"configurable": {"thread_id": run_id}},
        {"state_payload": payload},
        as_node=WorkflowNode.SAVE_PENDING_DRAFT.value,
    )

    with pytest.raises(WorkflowTransitionError):
        runtime.resume(run_id)

    assert harness.approval.calls == 0
    assert harness.export.calls == 0


def test_checkpoint_payload_is_only_canonical_primitives() -> None:
    _, saver, runtime = _runtime()
    initial = _initial()

    runtime.start(initial)
    payload = _stored_payload(saver, initial.run_id)

    assert set(payload) == set(initial.model_dump(mode="json"))
    assert all(
        value is None or type(value) in {dict, list, str, int, float, bool}
        for value in _walk(payload)
    )
    assert not any(isinstance(value, (BaseModel, InMemorySaver)) for value in _walk(payload))


def test_runtime_rejects_subclass_and_instance_shadowing_without_foreign_return() -> None:
    harness, _, runtime = _runtime()
    run_id = _initial().run_id
    runtime.start(_initial())
    terminal = runtime.resume(run_id)
    assert terminal.terminal
    effects = (harness.persistence.calls, harness.approval.calls, harness.export.calls)

    with pytest.raises(TypeError, match="must not be subclassed"):

        class ForgedRuntime(LangGraphOrchestrationRuntime):
            def inspect(self, run_id: str) -> object:
                del run_id
                return object()

    def forged(*_args: object, **_kwargs: object) -> object:
        return object()

    assert not hasattr(runtime, "__dict__")
    for attribute in (
        "_node",
        "_preflight",
        "_result",
        "_route",
        "inspect",
        "resume",
        "start",
    ):
        with pytest.raises(AttributeError):
            setattr(runtime, attribute, forged)

    runtime._checkpointer.load_frozen = forged  # type: ignore[method-assign]

    assert runtime.inspect(run_id) == terminal
    assert runtime.resume(run_id) == terminal
    assert (harness.persistence.calls, harness.approval.calls, harness.export.calls) == effects


def test_checkpoint_listing_never_crosses_or_masks_foreign_namespaces() -> None:
    _, saver, runtime = _runtime()
    run_id = _initial().run_id
    runtime.start(_initial())
    fixed_count = len(
        list(
            saver.list(
                {
                    "configurable": {
                        "thread_id": run_id,
                        "checkpoint_ns": CHECKPOINT_NAMESPACE,
                    }
                }
            )
        )
    )
    fixed_storage = deepcopy(saver.storage[run_id][CHECKPOINT_NAMESPACE])
    saver.storage[run_id][""] = deepcopy(fixed_storage)
    saver.storage[run_id]["foreign"] = deepcopy(fixed_storage)

    with pytest.raises(WorkflowTransitionError, match="run-bound config"):
        list(runtime._checkpointer.list(None))

    listed = list(
        runtime._checkpointer.list(
            {
                "configurable": {
                    "thread_id": run_id,
                    "checkpoint_ns": "foreign",
                }
            }
        )
    )
    assert len(listed) == fixed_count
    assert (
        len(list(saver.list({"configurable": {"thread_id": run_id, "checkpoint_ns": ""}})))
        == fixed_count
    )
    assert (
        len(
            list(
                saver.list(
                    {
                        "configurable": {
                            "thread_id": run_id,
                            "checkpoint_ns": "foreign",
                        }
                    }
                )
            )
        )
        == fixed_count
    )


def test_duplicate_start_and_missing_inspection_fail_closed() -> None:
    harness, _, runtime = _runtime()
    initial = _initial()
    runtime.start(initial)
    events = list(harness.events)

    with pytest.raises(WorkflowTransitionError, match="already exists"):
        runtime.start(initial)
    with pytest.raises(WorkflowTransitionError, match="unavailable"):
        runtime.inspect("run:87654321-4321-4321-8321-cba987654321")

    assert harness.events == events


def test_concurrent_duplicate_start_is_serialized_across_runtime_instances() -> None:
    harness = Harness()
    entered = Event()
    release = Event()
    second_started = Event()
    evaluate = harness.scope_safety.evaluate

    def blocking_evaluate(scope: object) -> object:
        entered.set()
        assert release.wait(timeout=5)
        return evaluate(scope)  # type: ignore[arg-type]

    harness.scope_safety.evaluate = blocking_evaluate  # type: ignore[method-assign]
    saver = InMemorySaver()
    first_runtime = LangGraphOrchestrationRuntime(
        workflow=harness.workflow,
        checkpointer=saver,
    )
    second_runtime = LangGraphOrchestrationRuntime(
        workflow=harness.workflow,
        checkpointer=saver,
    )
    initial = _initial()

    def second_start() -> object:
        second_started.set()
        return second_runtime.start(initial)

    with ThreadPoolExecutor(max_workers=2) as executor:
        first_future = executor.submit(first_runtime.start, initial)
        assert entered.wait(timeout=5)
        second_future = executor.submit(second_start)
        assert second_started.wait(timeout=5)
        release.set()
        first_result = first_future.result(timeout=5)
        with pytest.raises(WorkflowTransitionError, match="already exists"):
            second_future.result(timeout=5)

    assert first_result.interrupted_before is WorkflowNode.REQUEST_EXPORT_APPROVAL
    assert harness.events.count("scope_and_safety") == 1
    assert len(harness.collector.calls) == 1
    assert len(harness.synthesis.prior_hashes) == 1
    assert len(harness.semantic.calls) == 1
    assert harness.receipts.save_calls == 1
    assert harness.persistence.calls == 1
    assert harness.approval.calls == 0
    assert harness.export.calls == 0
    with pytest.raises(WorkflowTransitionError, match="already exists"):
        first_runtime.start(initial)
    assert not _START_GUARDS


@pytest.mark.parametrize("run_id", ["foreign", "x" * 10_000])
def test_invalid_run_id_fails_before_checkpoint_lookup_or_capability(run_id: str) -> None:
    harness, saver, runtime = _runtime()

    with pytest.raises(WorkflowTransitionError, match="run_id is invalid"):
        runtime.inspect(run_id)

    assert not saver.storage
    assert harness.events == []


def test_foreign_topology_fails_before_workflow_capability() -> None:
    harness, _, runtime = _runtime()
    payload: dict[str, Any] = deepcopy(_initial().model_dump(mode="json"))
    payload["completed_nodes"] = [WorkflowNode.SCOPE_AND_SAFETY.value]

    with pytest.raises(WorkflowTransitionError):
        _runtime_route(runtime, {"state_payload": payload})

    assert harness.events == []
