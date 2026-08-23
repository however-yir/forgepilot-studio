from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Iterable

from .schema import AuditEvent, AuditEventType

_TEST_COMMAND_MARKERS = (
    'pytest',
    'pre-commit',
    'npm test',
    'npm run test',
    'npm run build',
    'mvn test',
    'gradle test',
    'go test',
    'cargo test',
)


def audit_events_from_event_stream(
    events: Iterable[Any],
    *,
    task_id: str | None = None,
) -> list[AuditEvent]:
    audit_events: list[AuditEvent] = []
    first_user_message_seen = False

    for event in events:
        timestamp = _event_timestamp(event)
        trace_id = _event_trace_id(event)

        event_kind = event.__class__.__name__
        source = _enum_value(getattr(event, 'source', None))

        if event_kind == 'MessageAction':
            if source == 'user':
                if not first_user_message_seen:
                    first_user_message_seen = True
                    audit_events.append(
                        AuditEvent(
                            trace_id=trace_id,
                            task_id=task_id,
                            event_type=AuditEventType.TASK_CREATED,
                            phase='plan',
                            timestamp=timestamp,
                            summary=_truncate(event.content),
                            payload={'source': 'user'},
                        )
                    )
                # Every user message (not only the first one) is recorded so
                # multi-turn conversations keep their user input in the audit
                # trail.
                audit_events.append(
                    AuditEvent(
                        trace_id=trace_id,
                        task_id=task_id,
                        event_type=AuditEventType.USER_MESSAGE,
                        phase='plan',
                        timestamp=timestamp,
                        summary=_truncate(event.content),
                        payload={'source': 'user'},
                    )
                )
            elif source == 'agent':
                audit_events.append(
                    AuditEvent(
                        trace_id=trace_id,
                        task_id=task_id,
                        event_type=AuditEventType.MODEL_RESPONSE,
                        phase='execute',
                        timestamp=timestamp,
                        summary=_truncate(event.content),
                        payload={'source': 'agent'},
                    )
                )
        elif event_kind == 'CmdRunAction':
            audit_events.append(
                AuditEvent(
                    trace_id=trace_id,
                    task_id=task_id,
                    event_type=AuditEventType.COMMAND_RUN,
                    phase='execute',
                    timestamp=timestamp,
                    summary=event.command,
                    payload={
                        'command': event.command,
                        'cwd': getattr(event, 'cwd', None),
                        'blocking': getattr(event, 'blocking', False),
                        'security_risk': _enum_value(
                            getattr(event, 'security_risk', None)
                        ),
                        'confirmation_state': _enum_value(
                            getattr(event, 'confirmation_state', None)
                        ),
                    },
                )
            )
            if (
                _enum_value(getattr(event, 'confirmation_state', None))
                == 'awaiting_confirmation'
            ):
                audit_events.append(
                    AuditEvent(
                        trace_id=f'{trace_id}:approval',
                        task_id=task_id,
                        event_type=AuditEventType.APPROVAL_REQUESTED,
                        phase='execute',
                        timestamp=timestamp,
                        summary=f'Approval requested for command: {event.command}',
                        payload={
                            'subject_type': 'command',
                            'command': event.command,
                            'security_risk': _enum_value(
                                getattr(event, 'security_risk', None)
                            ),
                        },
                    )
                )
        elif event_kind == 'CmdOutputObservation':
            event_type = (
                AuditEventType.TEST_RESULT
                if _looks_like_test_command(event.command)
                else AuditEventType.COMMAND_RUN
            )
            audit_events.append(
                AuditEvent(
                    trace_id=trace_id,
                    task_id=task_id,
                    event_type=event_type,
                    phase='verify'
                    if event_type == AuditEventType.TEST_RESULT
                    else 'execute',
                    timestamp=timestamp,
                    summary=event.command,
                    payload={
                        'command': event.command,
                        'exit_code': getattr(
                            getattr(event, 'metadata', None),
                            'exit_code',
                            None,
                        ),
                        'working_dir': getattr(
                            getattr(event, 'metadata', None),
                            'working_dir',
                            None,
                        ),
                        'output': _truncate(event.content, max_chars=1200),
                    },
                )
            )
        elif event_kind in {'FileEditAction', 'FileWriteAction'}:
            audit_events.append(
                AuditEvent(
                    trace_id=trace_id,
                    task_id=task_id,
                    event_type=AuditEventType.FILE_CHANGE,
                    phase='execute',
                    timestamp=timestamp,
                    summary=f'Change requested for {event.path}',
                    payload={
                        'path': event.path,
                        'action': getattr(event, 'action', 'file_change'),
                        'security_risk': _enum_value(
                            getattr(event, 'security_risk', None)
                        ),
                    },
                )
            )
        elif event_kind in {'FileEditObservation', 'FileWriteObservation'}:
            audit_events.append(
                AuditEvent(
                    trace_id=trace_id,
                    task_id=task_id,
                    event_type=AuditEventType.FILE_CHANGE,
                    phase='execute',
                    timestamp=timestamp,
                    summary=f'Changed {event.path}',
                    payload={
                        'path': event.path,
                        'diff': getattr(event, 'diff', None),
                        'content': _truncate(event.content, max_chars=1200),
                    },
                )
            )
        elif event_kind == 'MCPAction':
            audit_events.append(
                AuditEvent(
                    trace_id=trace_id,
                    task_id=task_id,
                    event_type=AuditEventType.TOOL_CALL,
                    phase='execute',
                    timestamp=timestamp,
                    summary=f'MCP tool call: {event.name}',
                    payload={'tool': event.name, 'arguments': event.arguments},
                )
            )
        elif event_kind == 'MCPObservation':
            audit_events.append(
                AuditEvent(
                    trace_id=trace_id,
                    task_id=task_id,
                    event_type=AuditEventType.TOOL_CALL,
                    phase='execute',
                    timestamp=timestamp,
                    summary=f'MCP tool result: {event.name}',
                    payload={
                        'tool': event.name,
                        'arguments': event.arguments,
                        'output': _truncate(event.content, max_chars=1200),
                    },
                )
            )
        elif event_kind == 'UserRejectObservation':
            audit_events.append(
                AuditEvent(
                    trace_id=trace_id,
                    task_id=task_id,
                    event_type=AuditEventType.APPROVAL_DECISION,
                    phase='execute',
                    timestamp=timestamp,
                    summary='Approval rejected by user',
                    payload={
                        'decision': 'rejected',
                        'message': getattr(event, 'content', ''),
                    },
                )
            )

    return audit_events


def _event_trace_id(event: Any) -> str:
    response_id = getattr(event, 'response_id', None)
    if response_id:
        return str(response_id)
    event_id = getattr(event, 'id', -1)
    if event_id != -1:
        return f'event-{event_id}'
    return f'event-{id(event)}'


def _event_timestamp(event: Any) -> datetime:
    timestamp = getattr(event, 'timestamp', None)
    if timestamp:
        return datetime.fromisoformat(timestamp)
    return datetime.now(UTC)


def _truncate(value: str, max_chars: int = 300) -> str:
    if len(value) <= max_chars:
        return value
    keep = max_chars // 2
    return f'{value[:keep]}\n...\n{value[-keep:]}'


def _looks_like_test_command(command: str) -> bool:
    normalized = command.lower()
    return any(marker in normalized for marker in _TEST_COMMAND_MARKERS)


def _enum_value(value: object) -> object:
    if hasattr(value, 'value'):
        return value.value  # type: ignore[union-attr]
    return value
