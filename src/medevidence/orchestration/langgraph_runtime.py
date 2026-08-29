"""Bounded LangGraph coordination for the canonical M3 orchestration state."""

from __future__ import annotations

import json
import math
from _thread import LockType
from collections.abc import Callable, Hashable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from threading import Lock
from typing import Any, TypedDict, cast

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import (
    BaseCheckpointSaver,
    ChannelVersions,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
)
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from pydantic import TypeAdapter, ValidationError

from medevidence.domain import RunId, canonical_json

from .contracts import OrchestrationState, WorkflowDisposition, WorkflowNode
from .workflow import ControlledOrchestrationWorkflow, WorkflowTransitionError

CHECKPOINT_NAMESPACE = "m3.orchestration-state.v2"

_MAX_PAYLOAD_BYTES = 2_000_000
_MAX_PAYLOAD_DEPTH = 32
_MAX_PAYLOAD_NODES = 50_000
_MAX_CONTAINER_ITEMS = 8_192
_MAX_KEY_BYTES = 16_384
_MAX_STRING_BYTES = 1_000_000
_MAX_GRAPH_STEPS = 80
_RUN_ID_ADAPTER: TypeAdapter[str] = TypeAdapter(RunId)
_START_GUARDS_LOCK = Lock()
_START_GUARDS: dict[str, tuple[LockType, int]] = {}


class _GraphState(TypedDict):
    state_payload: dict[str, object]


@dataclass(frozen=True, slots=True)
class LangGraphRunResult:
    """A reconstructed application state and its bounded runtime status."""

    state: OrchestrationState
    terminal: bool
    interrupted_before: WorkflowNode | None


class _PrimitiveBudget:
    __slots__ = ("bytes", "nodes", "parents")

    def __init__(self) -> None:
        self.bytes = 0
        self.nodes = 0
        self.parents: set[int] = set()


def _consume_bytes(budget: _PrimitiveBudget, amount: int) -> None:
    budget.bytes += amount
    if budget.bytes > _MAX_PAYLOAD_BYTES:
        raise WorkflowTransitionError("checkpoint payload exceeds the canonical byte bound")


def _json_string_sizes(value: str) -> tuple[int, int]:
    raw_bytes = 0
    encoded_bytes = 2
    for character in value:
        try:
            character_bytes = len(character.encode("utf-8"))
        except UnicodeEncodeError as error:
            raise WorkflowTransitionError("checkpoint payload contains invalid Unicode") from error
        raw_bytes += character_bytes
        codepoint = ord(character)
        if character in {'"', "\\"} or character in {"\b", "\f", "\n", "\r", "\t"}:
            encoded_bytes += 2
        elif codepoint < 0x20:
            encoded_bytes += 6
        else:
            encoded_bytes += character_bytes
    return raw_bytes, encoded_bytes


def _validate_primitive(value: object, *, depth: int, budget: _PrimitiveBudget) -> None:
    if depth > _MAX_PAYLOAD_DEPTH:
        raise WorkflowTransitionError("checkpoint payload exceeds the depth bound")
    budget.nodes += 1
    if budget.nodes > _MAX_PAYLOAD_NODES:
        raise WorkflowTransitionError("checkpoint payload exceeds the node bound")
    if value is None:
        _consume_bytes(budget, 4)
        return
    if type(value) is bool:
        _consume_bytes(budget, 4 if value else 5)
        return
    if type(value) is int:
        try:
            _consume_bytes(budget, len(str(value)))
        except ValueError as error:
            raise WorkflowTransitionError("checkpoint integer exceeds the byte bound") from error
        return
    if type(value) is float:
        if not math.isfinite(value):
            raise WorkflowTransitionError("checkpoint payload contains a non-finite number")
        _consume_bytes(budget, len(json.dumps(value)))
        return
    if type(value) is str:
        raw_bytes, encoded_bytes = _json_string_sizes(value)
        if raw_bytes > _MAX_STRING_BYTES:
            raise WorkflowTransitionError("checkpoint payload string exceeds the byte bound")
        _consume_bytes(budget, encoded_bytes)
        return
    if type(value) not in {dict, list}:
        raise WorkflowTransitionError("checkpoint payload contains a non-JSON runtime object")
    identity = id(value)
    if identity in budget.parents:
        raise WorkflowTransitionError("checkpoint payload contains a reference cycle")
    budget.parents.add(identity)
    try:
        if type(value) is dict:
            mapping = cast(dict[object, object], value)
            if len(mapping) > _MAX_CONTAINER_ITEMS:
                raise WorkflowTransitionError("checkpoint mapping exceeds the cardinality bound")
            _consume_bytes(budget, 2)
            for index, (key, item) in enumerate(mapping.items()):
                if type(key) is not str:
                    raise WorkflowTransitionError("checkpoint mapping keys must be exact strings")
                raw_bytes, encoded_bytes = _json_string_sizes(key)
                if raw_bytes > _MAX_KEY_BYTES:
                    raise WorkflowTransitionError("checkpoint mapping key exceeds the byte bound")
                _consume_bytes(budget, encoded_bytes + 1 + (1 if index else 0))
                _validate_primitive(item, depth=depth + 1, budget=budget)
        else:
            items = cast(list[object], value)
            if len(items) > _MAX_CONTAINER_ITEMS:
                raise WorkflowTransitionError("checkpoint sequence exceeds the cardinality bound")
            _consume_bytes(budget, 2)
            for index, item in enumerate(items):
                if index:
                    _consume_bytes(budget, 1)
                _validate_primitive(item, depth=depth + 1, budget=budget)
    finally:
        budget.parents.remove(identity)


def _validate_envelope(value: object) -> dict[str, object]:
    if type(value) is not dict:
        raise WorkflowTransitionError("LangGraph state must be an exact mapping")
    envelope = cast(dict[object, object], value)
    if set(envelope) != {"state_payload"} or any(type(key) is not str for key in envelope):
        raise WorkflowTransitionError("LangGraph state must contain only state_payload")
    payload = envelope["state_payload"]
    if type(payload) is not dict:
        raise WorkflowTransitionError("state_payload must be an exact mapping")
    budget = _PrimitiveBudget()
    _validate_primitive(payload, depth=0, budget=budget)
    try:
        encoded = canonical_json(payload).encode("utf-8")
    except (TypeError, ValueError, OverflowError) as error:
        raise WorkflowTransitionError("checkpoint payload is not canonical JSON") from error
    if len(encoded) != budget.bytes:
        raise WorkflowTransitionError("checkpoint payload byte accounting drift")
    if len(encoded) > _MAX_PAYLOAD_BYTES:
        raise WorkflowTransitionError("checkpoint payload exceeds the canonical byte bound")
    return cast(dict[str, object], payload)


def _reconstruct_state(value: object, *, expected_run_id: str | None = None) -> OrchestrationState:
    payload = _validate_envelope(value)
    try:
        state = OrchestrationState.model_validate_json(canonical_json(payload), strict=True)
    except (ValidationError, ValueError, TypeError) as error:
        raise WorkflowTransitionError("checkpoint state reconstruction failed") from error
    if expected_run_id is not None and state.run_id != expected_run_id:
        raise WorkflowTransitionError("checkpoint state belongs to another run")
    return state


def _state_envelope(state: OrchestrationState) -> _GraphState:
    if type(state) is not OrchestrationState:
        raise WorkflowTransitionError("runtime input must use the exact orchestration state type")
    payload = json.loads(canonical_json(state.model_dump(mode="json")))
    envelope: object = {"state_payload": payload}
    return cast(_GraphState, {"state_payload": _validate_envelope(envelope)})


def _root_config(run_id: str) -> RunnableConfig:
    return {
        "recursion_limit": _MAX_GRAPH_STEPS,
        "configurable": {"thread_id": run_id},
    }


def _validated_run_id(value: object) -> str:
    try:
        return _RUN_ID_ADAPTER.validate_python(value, strict=True)
    except ValidationError as error:
        raise WorkflowTransitionError("runtime run_id is invalid") from error


@contextmanager
def _serialized_start(run_id: str) -> Iterator[None]:
    with _START_GUARDS_LOCK:
        entry = _START_GUARDS.get(run_id)
        guard, users = (Lock(), 0) if entry is None else entry
        _START_GUARDS[run_id] = (guard, users + 1)
    acquired = False
    try:
        guard.acquire()
        acquired = True
        yield
    finally:
        if acquired:
            guard.release()
        with _START_GUARDS_LOCK:
            registered, users = _START_GUARDS[run_id]
            if registered is not guard:
                raise RuntimeError("start guard identity drift")
            if users == 1:
                del _START_GUARDS[run_id]
            else:
                _START_GUARDS[run_id] = (guard, users - 1)


def _require_pristine_initial(state: OrchestrationState) -> None:
    pristine = OrchestrationState(
        workflow_id=state.workflow_id,
        checkpoint_id=state.checkpoint_id,
        run_id=state.run_id,
        report_id=state.report_id,
        original_scope=state.original_scope,
        permissions=state.permissions,
        destination=state.destination,
    )
    if state != pristine:
        raise WorkflowTransitionError("start requires the exact pristine initial state")


def _with_namespace(config: RunnableConfig) -> RunnableConfig:
    configurable = dict(config.get("configurable", {}))
    configurable["checkpoint_ns"] = CHECKPOINT_NAMESPACE
    return {**config, "configurable": configurable}


def _without_namespace(config: RunnableConfig | None) -> RunnableConfig | None:
    if config is None:
        return None
    configurable = dict(config.get("configurable", {}))
    configurable["checkpoint_ns"] = ""
    return {**config, "configurable": configurable}


class _FixedNamespaceSaver(BaseCheckpointSaver[Any]):
    """Keep the infrastructure namespace fixed while LangGraph runs a root graph."""

    def __init__(self, delegate: BaseCheckpointSaver[Any]) -> None:
        super().__init__(serde=delegate.serde)
        self._delegate = delegate

    @property
    def config_specs(self) -> list[Any]:
        return self._delegate.config_specs

    def get_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        result = self._delegate.get_tuple(_with_namespace(config))
        if result is None:
            return None
        return CheckpointTuple(
            config=cast(RunnableConfig, _without_namespace(result.config)),
            checkpoint=result.checkpoint,
            metadata=result.metadata,
            parent_config=_without_namespace(result.parent_config),
            pending_writes=result.pending_writes,
        )

    def list(
        self,
        config: RunnableConfig | None,
        *,
        filter: dict[str, Any] | None = None,
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ) -> Iterator[CheckpointTuple]:
        if config is None:
            raise WorkflowTransitionError("checkpoint listing requires a run-bound config")
        namespaced = _with_namespace(config)
        namespaced_before = None if before is None else _with_namespace(before)
        for result in self._delegate.list(
            namespaced,
            filter=filter,
            before=namespaced_before,
            limit=limit,
        ):
            yield CheckpointTuple(
                config=cast(RunnableConfig, _without_namespace(result.config)),
                checkpoint=result.checkpoint,
                metadata=result.metadata,
                parent_config=_without_namespace(result.parent_config),
                pending_writes=result.pending_writes,
            )

    def put(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        stored = self._delegate.put(_with_namespace(config), checkpoint, metadata, new_versions)
        return cast(RunnableConfig, _without_namespace(stored))

    def put_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        self._delegate.put_writes(_with_namespace(config), writes, task_id, task_path)

    def get_next_version(self, current: Any | None, channel: None) -> Any:
        return self._delegate.get_next_version(current, channel)

    def load_frozen(self, run_id: str) -> CheckpointTuple | None:
        return self._delegate.get_tuple(
            {"configurable": {"thread_id": run_id, "checkpoint_ns": CHECKPOINT_NAMESPACE}}
        )


class LangGraphOrchestrationRuntime:
    """Run the exact eight-node workflow with internally derived checkpoint identity."""

    __slots__ = ("_checkpointer", "_graph", "_workflow")

    def __init_subclass__(cls, **kwargs: Any) -> None:
        del cls, kwargs
        raise TypeError("LangGraphOrchestrationRuntime must not be subclassed")

    def __init__(
        self,
        *,
        workflow: ControlledOrchestrationWorkflow,
        checkpointer: BaseCheckpointSaver[Any],
    ) -> None:
        self._workflow = workflow
        self._checkpointer = _FixedNamespaceSaver(checkpointer)
        builder = StateGraph(_GraphState)
        methods = {
            WorkflowNode.SCOPE_AND_SAFETY: ControlledOrchestrationWorkflow.scope_and_safety,
            WorkflowNode.PLAN_SOURCES: ControlledOrchestrationWorkflow.plan_sources,
            WorkflowNode.COLLECT_EVIDENCE: ControlledOrchestrationWorkflow.collect_evidence,
            WorkflowNode.SYNTHESIZE_CLAIMS: ControlledOrchestrationWorkflow.synthesize_claims,
            WorkflowNode.VALIDATE_REPORT: ControlledOrchestrationWorkflow.validate_report,
            WorkflowNode.SAVE_PENDING_DRAFT: ControlledOrchestrationWorkflow.save_pending_draft,
            WorkflowNode.REQUEST_EXPORT_APPROVAL: (
                ControlledOrchestrationWorkflow.request_export_approval
            ),
            WorkflowNode.FINALIZE_AND_EXPORT: (ControlledOrchestrationWorkflow.finalize_and_export),
        }
        for node, method in methods.items():
            builder.add_node(node.value, cast(Any, _bind_node(self, method, node)))
        node_destinations: dict[WorkflowNode, dict[Hashable, str]] = {
            WorkflowNode.SCOPE_AND_SAFETY: {
                WorkflowNode.PLAN_SOURCES.value: WorkflowNode.PLAN_SOURCES.value,
                END: END,
            },
            WorkflowNode.PLAN_SOURCES: {
                WorkflowNode.COLLECT_EVIDENCE.value: WorkflowNode.COLLECT_EVIDENCE.value,
            },
            WorkflowNode.COLLECT_EVIDENCE: {
                WorkflowNode.COLLECT_EVIDENCE.value: WorkflowNode.COLLECT_EVIDENCE.value,
                WorkflowNode.SYNTHESIZE_CLAIMS.value: WorkflowNode.SYNTHESIZE_CLAIMS.value,
                END: END,
            },
            WorkflowNode.SYNTHESIZE_CLAIMS: {
                WorkflowNode.VALIDATE_REPORT.value: WorkflowNode.VALIDATE_REPORT.value,
            },
            WorkflowNode.VALIDATE_REPORT: {
                WorkflowNode.SAVE_PENDING_DRAFT.value: WorkflowNode.SAVE_PENDING_DRAFT.value,
                END: END,
            },
            WorkflowNode.SAVE_PENDING_DRAFT: {
                WorkflowNode.REQUEST_EXPORT_APPROVAL.value: (
                    WorkflowNode.REQUEST_EXPORT_APPROVAL.value
                ),
            },
            WorkflowNode.REQUEST_EXPORT_APPROVAL: {
                WorkflowNode.FINALIZE_AND_EXPORT.value: (WorkflowNode.FINALIZE_AND_EXPORT.value),
                WorkflowNode.SYNTHESIZE_CLAIMS.value: WorkflowNode.SYNTHESIZE_CLAIMS.value,
                END: END,
            },
            WorkflowNode.FINALIZE_AND_EXPORT: {END: END},
        }
        builder.add_edge(START, WorkflowNode.SCOPE_AND_SAFETY.value)
        route = _bind_route(self)
        for node, destinations in node_destinations.items():
            builder.add_conditional_edges(node.value, route, destinations)
        self._graph: CompiledStateGraph[_GraphState, None, _GraphState, _GraphState] = (
            builder.compile(
                checkpointer=self._checkpointer,
                interrupt_before=[WorkflowNode.REQUEST_EXPORT_APPROVAL.value],
            )
        )

    def start(self, state: OrchestrationState) -> LangGraphRunResult:
        """Start one new run under its internally derived thread identity."""
        return _runtime_start(self, state)

    def inspect(self, run_id: str) -> LangGraphRunResult:
        """Inspect only a reconstructed, run-bound checkpoint state."""
        return _runtime_result(self, _validated_run_id(run_id))

    def resume(self, run_id: str) -> LangGraphRunResult:
        """Resume an active checkpoint or idempotently verify a terminal checkpoint."""
        return _runtime_resume(self, _validated_run_id(run_id))


_WorkflowMethod = Callable[
    [ControlledOrchestrationWorkflow, OrchestrationState], OrchestrationState
]


def _runtime_preflight(
    runtime: LangGraphOrchestrationRuntime,
    value: object,
    *,
    expected_run_id: str | None = None,
) -> OrchestrationState:
    state = _reconstruct_state(value, expected_run_id=expected_run_id)
    return ControlledOrchestrationWorkflow._validate_durable_state(runtime._workflow, state)


def _bind_node(
    runtime: LangGraphOrchestrationRuntime,
    method: _WorkflowMethod,
    expected: WorkflowNode,
) -> Callable[[_GraphState], _GraphState]:
    def execute(value: _GraphState) -> _GraphState:
        state = _runtime_preflight(runtime, value)
        if state.current_node is not expected:
            raise WorkflowTransitionError("LangGraph node does not bind current topology")
        return _state_envelope(method(runtime._workflow, state))

    return execute


def _runtime_route(runtime: LangGraphOrchestrationRuntime, value: object) -> str:
    state = _runtime_preflight(runtime, value)
    return END if state.current_node is None else state.current_node.value


def _bind_route(
    runtime: LangGraphOrchestrationRuntime,
) -> Callable[[_GraphState], str]:
    def route(value: _GraphState) -> str:
        return _runtime_route(runtime, value)

    return route


def _runtime_start(
    runtime: LangGraphOrchestrationRuntime,
    state: OrchestrationState,
) -> LangGraphRunResult:
    initial = _state_envelope(state)
    rebuilt = _runtime_preflight(runtime, initial, expected_run_id=state.run_id)
    _require_pristine_initial(rebuilt)
    with _serialized_start(rebuilt.run_id):
        if _FixedNamespaceSaver.load_frozen(runtime._checkpointer, rebuilt.run_id) is not None:
            raise WorkflowTransitionError("a checkpoint already exists for this run")
        runtime._graph.invoke(initial, _root_config(rebuilt.run_id))
        return _runtime_result(runtime, rebuilt.run_id)


def _runtime_resume(
    runtime: LangGraphOrchestrationRuntime,
    run_id: str,
) -> LangGraphRunResult:
    before = _runtime_result(runtime, run_id)
    if before.terminal:
        return before
    runtime._graph.invoke(None, _root_config(run_id))
    return _runtime_result(runtime, run_id)


def _runtime_result(
    runtime: LangGraphOrchestrationRuntime,
    run_id: str,
) -> LangGraphRunResult:
    stored = _FixedNamespaceSaver.load_frozen(runtime._checkpointer, run_id)
    if stored is None:
        raise WorkflowTransitionError("checkpoint is unavailable for this run")
    configurable = stored.config.get("configurable", {})
    if (
        configurable.get("thread_id") != run_id
        or configurable.get("checkpoint_ns") != CHECKPOINT_NAMESPACE
    ):
        raise WorkflowTransitionError("checkpoint identity or namespace drift")
    values: object = {
        "state_payload": stored.checkpoint.get("channel_values", {}).get("state_payload")
    }
    state = _runtime_preflight(runtime, values, expected_run_id=run_id)
    snapshot = runtime._graph.get_state(_root_config(run_id))
    terminal = state.disposition is not WorkflowDisposition.ACTIVE
    if terminal != (state.current_node is None):
        raise WorkflowTransitionError("checkpoint terminal topology drift")
    expected_next = () if terminal else (cast(WorkflowNode, state.current_node).value,)
    queued_tasks = tuple(task.name for task in snapshot.tasks)
    if (
        snapshot.next != expected_next
        or queued_tasks != expected_next
        or snapshot.interrupts
        or any(task.error is not None or task.interrupts for task in snapshot.tasks)
    ):
        raise WorkflowTransitionError("checkpoint scheduling topology drift")
    interrupted = (
        WorkflowNode.REQUEST_EXPORT_APPROVAL
        if expected_next == (WorkflowNode.REQUEST_EXPORT_APPROVAL.value,)
        else None
    )
    if terminal:
        verified = ControlledOrchestrationWorkflow.run_next(runtime._workflow, state)
        if verified != state:
            raise WorkflowTransitionError("terminal workflow verification changed state")
    return LangGraphRunResult(
        state=state,
        terminal=terminal,
        interrupted_before=interrupted,
    )
