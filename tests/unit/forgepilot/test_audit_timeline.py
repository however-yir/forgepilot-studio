"""Tests for the unified audit timeline builder (B-15)."""

from datetime import UTC, datetime

from openhands.forgepilot.audit.schema import AuditEvent, AuditEventType
from openhands.forgepilot.audit.timeline import build_timeline


def _make_event(
    trace_id: str,
    event_type: AuditEventType,
    task_id: str = 'task-1',
    phase: str = 'execute',
    timestamp: datetime | None = None,
    payload: dict | None = None,
) -> AuditEvent:
    return AuditEvent(
        trace_id=trace_id,
        task_id=task_id,
        event_type=event_type,
        phase=phase,
        timestamp=timestamp or datetime.now(UTC),
        summary=f'{event_type.value} event',
        payload=payload or {},
    )


def test_build_timeline_creates_chains():
    now = datetime.now(UTC)
    events = [
        _make_event('e1', AuditEventType.MODEL, timestamp=now),
        _make_event('e2', AuditEventType.COMMAND, timestamp=now),
        _make_event('e3', AuditEventType.FILE_CHANGE, timestamp=now),
        _make_event('e4', AuditEventType.VERIFICATION, timestamp=now),
    ]
    timeline = build_timeline(events)
    assert len(timeline.chains) >= 1
    assert timeline.task_id == 'task-1'
    assert timeline.total_cost_usd == 0.0


def test_build_timeline_links_unified_audit_event_types():
    now = datetime.now(UTC)
    events = [
        _make_event('e1', AuditEventType.MODEL_RESPONSE, timestamp=now),
        _make_event('e2', AuditEventType.COMMAND_RUN, timestamp=now),
        _make_event('e3', AuditEventType.FILE_CHANGE, timestamp=now),
        _make_event('e4', AuditEventType.TEST_RESULT, timestamp=now),
    ]

    timeline = build_timeline(events)
    chain_nodes = timeline.chains[0].nodes
    assert [node.event.event_type for node in chain_nodes] == [
        AuditEventType.MODEL_RESPONSE,
        AuditEventType.COMMAND_RUN,
        AuditEventType.FILE_CHANGE,
        AuditEventType.TEST_RESULT,
    ]


def test_build_timeline_empty_events():
    timeline = build_timeline([])
    assert timeline.chains == []
    assert 'No events' in timeline.summary


def test_timeline_with_orphan_nodes():
    now = datetime.now(UTC)
    events = [
        _make_event('e1', AuditEventType.MODEL, timestamp=now),
        _make_event('e2', AuditEventType.REPORT, timestamp=now),
    ]
    timeline = build_timeline(events)
    # MODEL events that don't trigger anything end up as roots or orphans
    assert timeline.summary  # should produce a summary
