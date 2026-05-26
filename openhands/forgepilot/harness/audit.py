from __future__ import annotations

from openhands.forgepilot.audit.schema import AuditEvent, AuditEventType
from openhands.forgepilot.harness.action_schema import HarnessActionType
from openhands.forgepilot.harness.observation import (
    HarnessObservation,
    HarnessObservationStatus,
)


def audit_event_from_observation(
    observation: HarnessObservation,
    *,
    task_id: str | None = None,
) -> AuditEvent:
    event_type = _audit_event_type(observation)
    return AuditEvent(
        trace_id=observation.trace_id,
        task_id=task_id,
        event_type=event_type,
        phase='execute',
        timestamp=observation.timestamp,
        summary=(
            f'{observation.action_type.value} {observation.status.value}: '
            f'{observation.target}'
        ),
        payload={
            'action_type': observation.action_type.value,
            'permission_level': observation.permission.value,
            'target': observation.target,
            'redacted_input': observation.redacted_input,
            'status': observation.status.value,
            'latency_ms': observation.latency_ms,
            'output_summary': observation.output_summary,
            'error': observation.error,
        },
        duration_ms=observation.latency_ms,
    )


def _audit_event_type(observation: HarnessObservation) -> AuditEventType:
    if observation.status == HarnessObservationStatus.CONFIRMATION_REQUIRED:
        return AuditEventType.APPROVAL_REQUESTED

    if observation.action_type in {
        HarnessActionType.TERMINAL,
        HarnessActionType.GIT,
    }:
        return AuditEventType.COMMAND_RUN

    if observation.action_type in {
        HarnessActionType.FILE_WRITE,
        HarnessActionType.FILE_PATCH,
    }:
        return AuditEventType.FILE_CHANGE

    return AuditEventType.TOOL_CALL
