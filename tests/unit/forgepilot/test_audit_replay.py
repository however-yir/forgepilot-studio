from datetime import UTC, datetime, timedelta

from openhands.forgepilot.audit.replay import build_audit_replay_summary
from openhands.forgepilot.audit.schema import AuditEvent, AuditEventType


def test_audit_replay_summary_exports_timeline_and_jsonl():
    now = datetime.now(UTC)
    events = [
        AuditEvent(
            trace_id='model-1',
            task_id='task-1',
            event_type=AuditEventType.MODEL_RESPONSE,
            timestamp=now,
            summary='planned fix',
            cost_usd=0.01,
        ),
        AuditEvent(
            trace_id='cmd-1',
            task_id='task-1',
            event_type=AuditEventType.COMMAND_RUN,
            timestamp=now + timedelta(milliseconds=100),
            summary='pytest',
            duration_ms=1200,
            payload={'risk': 'low'},
        ),
        AuditEvent(
            trace_id='verify-1',
            task_id='task-1',
            event_type=AuditEventType.TEST_RESULT,
            timestamp=now + timedelta(milliseconds=200),
            summary='tests passed',
            payload={'status': 'passed'},
        ),
    ]

    summary = build_audit_replay_summary(events)

    assert summary.task_id == 'task-1'
    assert summary.event_count == 3
    assert summary.chain_count == 1
    assert summary.total_cost_usd == 0.01
    assert summary.total_duration_ms == 1200
    assert 'command_run' in summary.audit_jsonl
    assert 'MODEL_RESPONSE' not in summary.render_markdown()


def test_audit_replay_summary_builds_risk_queues():
    event = AuditEvent(
        trace_id='approval-1',
        task_id='task-2',
        event_type=AuditEventType.APPROVAL_REQUESTED,
        summary='deploy needs approval',
    )

    summary = build_audit_replay_summary([event])

    assert summary.risk_queues[0].name == 'approval_required'
    assert 'approval-1' in summary.render_markdown()
