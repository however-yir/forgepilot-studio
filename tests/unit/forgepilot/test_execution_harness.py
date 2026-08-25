from __future__ import annotations

from openhands.events.action import CmdRunAction, FileReadAction
from openhands.events.action.mcp import MCPAction
from openhands.events.observation import CmdOutputObservation, FileReadObservation
from openhands.events.observation.mcp import MCPObservation
from openhands.forgepilot.audit.replay import build_audit_replay_summary
from openhands.forgepilot.audit.schema import AuditEventType
from openhands.forgepilot.harness import (
    ConfirmationGate,
    ExecutionHarness,
    HarnessAction,
    HarnessActionType,
    HarnessObservationStatus,
    HarnessPolicy,
    action_from_runtime_action,
)
from openhands.forgepilot.tool_registry.schema import ToolPermission


def test_policy_allows_and_denies_by_permission_and_target():
    policy = HarnessPolicy(
        allowed_permissions=(ToolPermission.READ,),
        blocked_targets=('secrets/*',),
    )

    allowed = policy.evaluate(
        HarnessAction(
            action_type=HarnessActionType.FILE_READ,
            permission=ToolPermission.READ,
            target='README.md',
        )
    )
    denied_permission = policy.evaluate(
        HarnessAction(
            action_type=HarnessActionType.FILE_WRITE,
            permission=ToolPermission.WRITE,
            target='README.md',
        )
    )
    denied_target = policy.evaluate(
        HarnessAction(
            action_type=HarnessActionType.FILE_READ,
            permission=ToolPermission.READ,
            target='secrets/prod.env',
        )
    )

    assert allowed.allowed is True
    assert denied_permission.allowed is False
    assert 'write' in denied_permission.reason
    assert denied_target.allowed is False
    assert 'blocked' in denied_target.reason


def test_harness_wraps_fake_runtime_execution_and_emits_audit_event():
    action = CmdRunAction(command='git status --short')
    harness = ExecutionHarness(task_id='task-1')

    result = harness.execute(
        action,
        lambda runtime_action: CmdOutputObservation(
            content='clean',
            command=runtime_action.command,
            exit_code=0,
        ),
    )

    assert result.runtime_observation.content == 'clean'
    assert result.observation.action_type == HarnessActionType.GIT
    assert result.observation.permission == ToolPermission.EXECUTE
    assert result.observation.status == HarnessObservationStatus.SUCCESS
    assert result.audit_event.event_type == AuditEventType.COMMAND_RUN
    assert result.audit_event.payload['action_type'] == 'git'
    assert result.audit_event.payload['permission_level'] == 'execute'
    assert result.audit_event.payload['target'] == 'git status --short'


def test_file_read_uses_read_permission_without_confirmation():
    action = FileReadAction(path='README.md')
    harness = ExecutionHarness(task_id='task-1')

    result = harness.execute(
        action,
        lambda runtime_action: FileReadObservation(
            content='ForgePilot',
            path=runtime_action.path,
        ),
    )

    assert result.observation.action_type == HarnessActionType.FILE_READ
    assert result.observation.permission == ToolPermission.READ
    assert result.observation.status == HarnessObservationStatus.SUCCESS
    assert result.audit_event.payload['redacted_input']['path'] == 'README.md'


def test_mcp_permission_mapping_uses_exact_or_server_preference():
    exact = action_from_runtime_action(
        MCPAction(name='github.create_issue', arguments={}),
        mcp_permissions={'github.create_issue': 'confirm'},
    )
    server = action_from_runtime_action(
        MCPAction(name='github.list_checks', arguments={}),
        mcp_permissions={'github': {'permission': 'execute'}},
    )

    assert exact.permission == ToolPermission.CONFIRM
    assert exact.requires_confirmation is True
    assert server.permission == ToolPermission.EXECUTE
    assert server.requires_confirmation is True


def test_audit_payload_redacts_sensitive_mcp_arguments():
    action = MCPAction(
        name='github.create_issue',
        arguments={
            'title': 'bug',
            'api_key': 'ghp_secret',
            'nested': {'password': 'hunter2'},
        },
    )
    gate = ConfirmationGate()
    schema = action_from_runtime_action(
        action,
        mcp_permissions={'github': {'permission': 'confirm'}},
    )
    token = gate.issue(schema.confirmation_subject).token
    harness = ExecutionHarness(
        task_id='task-1',
        confirmation_gate=gate,
        mcp_permissions={'github': {'permission': 'confirm'}},
    )

    result = harness.execute(
        action,
        lambda runtime_action: MCPObservation(
            content='{"ok": true}',
            name=runtime_action.name,
            arguments=runtime_action.arguments,
        ),
        confirmation_token=token,
    )

    redacted = result.audit_event.payload['redacted_input']['arguments']
    assert redacted['title'] == 'bug'
    assert redacted['api_key'] == '[REDACTED]'
    assert redacted['nested']['password'] == '[REDACTED]'
    assert result.audit_event.payload['output_summary'] == '{"ok": true}'


def test_confirmation_token_is_one_shot_for_confirm_gated_actions():
    action = MCPAction(name='github.merge_pr', arguments={'number': 7})
    gate = ConfirmationGate()
    schema = action_from_runtime_action(
        action,
        mcp_permissions={'github': {'permission': 'confirm'}},
    )
    token = gate.issue(schema.confirmation_subject).token
    calls: list[str] = []
    harness = ExecutionHarness(
        confirmation_gate=gate,
        mcp_permissions={'github': {'permission': 'confirm'}},
    )

    first = harness.execute(
        action,
        lambda runtime_action: calls.append(runtime_action.name)
        or MCPObservation(
            content='merged',
            name=runtime_action.name,
            arguments=runtime_action.arguments,
        ),
        confirmation_token=token,
    )
    second = harness.execute(
        action,
        lambda runtime_action: calls.append(runtime_action.name)
        or MCPObservation(
            content='merged',
            name=runtime_action.name,
            arguments=runtime_action.arguments,
        ),
        confirmation_token=token,
    )

    assert first.observation.status == HarnessObservationStatus.SUCCESS
    assert second.observation.status == HarnessObservationStatus.CONFIRMATION_REQUIRED
    assert calls == ['github.merge_pr']


def test_confirmation_required_event_feeds_audit_replay_risk_queue():
    action = MCPAction(name='github.merge_pr', arguments={'number': 7})
    harness = ExecutionHarness(
        task_id='task-1',
        mcp_permissions={'github': {'permission': 'confirm'}},
    )

    result = harness.execute(
        action,
        lambda runtime_action: MCPObservation(
            content='merged',
            name=runtime_action.name,
            arguments=runtime_action.arguments,
        ),
    )
    replay = build_audit_replay_summary([result.audit_event])

    assert result.audit_event.event_type == AuditEventType.APPROVAL_REQUESTED
    assert replay.risk_queues[0].name == 'approval_required'


def test_confirmation_gate_prunes_consumed_and_expired_tokens():
    """Consumed/expired tokens must not accumulate forever (L-2).

    A missing token behaves exactly like a consumed one (consume → False), so
    dropping stale entries preserves replay protection while bounding memory.
    """
    from datetime import UTC, datetime, timedelta

    gate = ConfirmationGate()
    consumed = gate.issue('subject-a', ttl_seconds=300)
    gate.consume(consumed.token, subject='subject-a')
    assert gate.consume(consumed.token, subject='subject-a') is False  # one-shot

    expired = gate.issue('subject-b', ttl_seconds=0)
    gate._tokens[expired.token].expires_at = datetime.now(UTC) - timedelta(seconds=1)
    live = gate.issue('subject-c', ttl_seconds=300)

    # Issuing again prunes consumed + expired entries.
    gate.issue('subject-d', ttl_seconds=300)

    assert consumed.token not in gate._tokens
    assert expired.token not in gate._tokens
    assert live.token in gate._tokens
    assert len(gate._tokens) == 2


def test_harness_audit_events_can_be_filtered_by_task_id():
    """A shared harness must expose per-task audit isolation.

    A single ``ExecutionHarness`` is sometimes reused across concurrent
    tasks. The previous ``audit_events`` property returned every recorded
    event, with no way to slice by ``task_id``; ``audit_events_by_task``
    is the supported per-task view.
    """
    harness = ExecutionHarness()
    action = CmdRunAction(command='echo x')

    def ok(runtime_action):
        return CmdOutputObservation(
            content='x', command=runtime_action.command, exit_code=0
        )

    harness.execute(action, ok, task_id='t1')
    harness.execute(action, ok, task_id='t2')
    harness.execute(action, ok, task_id='t1')

    assert len(harness.audit_events) == 3
    t1_events = harness.audit_events_by_task('t1')
    t2_events = harness.audit_events_by_task('t2')
    assert len(t1_events) == 2
    assert len(t2_events) == 1
    assert all(event.task_id == 't1' for event in t1_events)
    assert t2_events[0].task_id == 't2'
    # Unknown task returns an empty list, not a copy of all events.
    assert harness.audit_events_by_task('missing') == []
