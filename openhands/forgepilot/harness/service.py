from __future__ import annotations

import inspect
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Mapping

from openhands.forgepilot.audit.schema import AuditEvent
from openhands.forgepilot.harness.action_schema import action_from_runtime_action
from openhands.forgepilot.harness.audit import audit_event_from_observation
from openhands.forgepilot.harness.confirmation import ConfirmationGate
from openhands.forgepilot.harness.observation import (
    HarnessObservation,
    HarnessObservationStatus,
    redact_payload,
    status_from_runtime_output,
    summarize_runtime_output,
)
from openhands.forgepilot.harness.policy import HarnessPolicy, PolicyDecision
from openhands.forgepilot.tool_registry.schema import ToolPermission


@dataclass(frozen=True)
class HarnessExecutionResult:
    observation: HarnessObservation
    audit_event: AuditEvent
    runtime_observation: Any | None = None


class ExecutionHarness:
    def __init__(
        self,
        *,
        policy: HarnessPolicy | None = None,
        confirmation_gate: ConfirmationGate | None = None,
        task_id: str | None = None,
        mcp_permissions: Mapping[str, str | ToolPermission | Mapping[str, Any]]
        | None = None,
    ) -> None:
        self.policy = policy or HarnessPolicy()
        self.confirmation_gate = confirmation_gate or ConfirmationGate()
        self.task_id = task_id
        self.mcp_permissions = mcp_permissions or {}
        self._audit_events: list[AuditEvent] = []

    @property
    def audit_events(self) -> list[AuditEvent]:
        return list(self._audit_events)

    def execute(
        self,
        action: Any,
        executor: Callable[[Any], Any],
        *,
        confirmation_token: str | None = None,
        task_id: str | None = None,
        mcp_permissions: Mapping[str, str | ToolPermission | Mapping[str, Any]]
        | None = None,
    ) -> HarnessExecutionResult:
        harness_action = action_from_runtime_action(
            action,
            mcp_permissions=mcp_permissions or self.mcp_permissions,
        )
        decision = self.policy.evaluate(harness_action)
        preflight = self._preflight_result(
            action,
            harness_action,
            decision,
            confirmation_token=confirmation_token,
            task_id=task_id,
        )
        if preflight is not None:
            return preflight

        started = time.perf_counter()
        try:
            runtime_observation = executor(action)
        except Exception as exc:
            latency_ms = int((time.perf_counter() - started) * 1000)
            return self._record_result(
                harness_action,
                status=HarnessObservationStatus.ERROR,
                latency_ms=latency_ms,
                output_summary='',
                error=str(exc),
                task_id=task_id,
            )

        latency_ms = int((time.perf_counter() - started) * 1000)
        return self._record_result(
            harness_action,
            status=status_from_runtime_output(runtime_observation),
            latency_ms=latency_ms,
            output_summary=summarize_runtime_output(runtime_observation),
            error=_runtime_error_text(runtime_observation),
            runtime_observation=runtime_observation,
            task_id=task_id,
        )

    async def execute_async(
        self,
        action: Any,
        executor: Callable[[Any], Awaitable[Any] | Any],
        *,
        confirmation_token: str | None = None,
        task_id: str | None = None,
        mcp_permissions: Mapping[str, str | ToolPermission | Mapping[str, Any]]
        | None = None,
    ) -> HarnessExecutionResult:
        harness_action = action_from_runtime_action(
            action,
            mcp_permissions=mcp_permissions or self.mcp_permissions,
        )
        decision = self.policy.evaluate(harness_action)
        preflight = self._preflight_result(
            action,
            harness_action,
            decision,
            confirmation_token=confirmation_token,
            task_id=task_id,
        )
        if preflight is not None:
            return preflight

        started = time.perf_counter()
        try:
            maybe_result = executor(action)
            runtime_observation = (
                await maybe_result
                if inspect.isawaitable(maybe_result)
                else maybe_result
            )
        except Exception as exc:
            latency_ms = int((time.perf_counter() - started) * 1000)
            return self._record_result(
                harness_action,
                status=HarnessObservationStatus.ERROR,
                latency_ms=latency_ms,
                output_summary='',
                error=str(exc),
                task_id=task_id,
            )

        latency_ms = int((time.perf_counter() - started) * 1000)
        return self._record_result(
            harness_action,
            status=status_from_runtime_output(runtime_observation),
            latency_ms=latency_ms,
            output_summary=summarize_runtime_output(runtime_observation),
            error=_runtime_error_text(runtime_observation),
            runtime_observation=runtime_observation,
            task_id=task_id,
        )

    def _preflight_result(
        self,
        action: Any,
        harness_action: Any,
        decision: PolicyDecision,
        *,
        confirmation_token: str | None,
        task_id: str | None,
    ) -> HarnessExecutionResult | None:
        if not decision.allowed:
            return self._record_result(
                harness_action,
                status=HarnessObservationStatus.DENIED,
                latency_ms=0,
                output_summary=decision.reason,
                error=decision.reason,
                task_id=task_id,
            )

        if not decision.requires_confirmation:
            return None

        if _ui_confirmation_state(action) == 'rejected':
            return self._record_result(
                harness_action,
                status=HarnessObservationStatus.DENIED,
                latency_ms=0,
                output_summary='confirmation rejected',
                error='confirmation rejected',
                task_id=task_id,
            )

        if _ui_confirmation_state(action) == 'confirmed':
            return None

        if confirmation_token and self.confirmation_gate.consume(
            confirmation_token,
            subject=harness_action.confirmation_subject,
        ):
            return None

        return self._record_result(
            harness_action,
            status=HarnessObservationStatus.CONFIRMATION_REQUIRED,
            latency_ms=0,
            output_summary='confirmation required',
            error='confirmation required',
            task_id=task_id,
        )

    def _record_result(
        self,
        harness_action: Any,
        *,
        status: HarnessObservationStatus,
        latency_ms: int,
        output_summary: str,
        error: str | None = None,
        runtime_observation: Any | None = None,
        task_id: str | None = None,
    ) -> HarnessExecutionResult:
        observation = HarnessObservation(
            action_type=harness_action.action_type,
            permission=harness_action.permission,
            target=harness_action.target,
            redacted_input=redact_payload(harness_action.input),
            status=status,
            latency_ms=latency_ms,
            output_summary=output_summary,
            error=error,
        )
        audit_event = audit_event_from_observation(
            observation,
            task_id=task_id if task_id is not None else self.task_id,
        )
        self._audit_events.append(audit_event)
        return HarnessExecutionResult(
            observation=observation,
            audit_event=audit_event,
            runtime_observation=runtime_observation,
        )


def _ui_confirmation_state(action: Any) -> str | None:
    state = getattr(action, 'confirmation_state', None)
    if state is None:
        return None
    value = getattr(state, 'value', state)
    return str(value)


def _runtime_error_text(result: Any) -> str | None:
    if result is None:
        return None
    if result.__class__.__name__ == 'ErrorObservation':
        return str(getattr(result, 'content', 'runtime error'))
    error = getattr(result, 'error', None)
    if isinstance(error, bool):
        return summarize_runtime_output(result) if error else None
    if error:
        return str(error)
    return None
