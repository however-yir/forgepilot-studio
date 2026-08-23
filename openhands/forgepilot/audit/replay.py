from __future__ import annotations

from typing import Iterable

from pydantic import BaseModel, Field

from .schema import AuditEvent, AuditEventType, build_task_evidence_pack
from .timeline import AuditTimeline, assign_unique_node_ids, build_timeline


class ReplayRiskQueue(BaseModel):
    name: str
    event_ids: list[str] = Field(default_factory=list)
    reason: str


class AuditReplaySummary(BaseModel):
    task_id: str
    event_count: int
    chain_count: int
    total_cost_usd: float
    total_duration_ms: int
    event_types: list[str]
    risk_queues: list[ReplayRiskQueue]
    timeline: AuditTimeline
    audit_jsonl: str

    def render_markdown(self) -> str:
        lines = [
            '# ForgePilot Audit Replay',
            '',
            f'- Task ID: `{self.task_id}`',
            f'- Events: {self.event_count}',
            f'- Chains: {self.chain_count}',
            f'- Total Cost USD: {self.total_cost_usd:.6f}',
            f'- Total Duration MS: {self.total_duration_ms}',
            '',
            '## Event Types',
            '',
        ]
        for event_type in self.event_types:
            lines.append(f'- `{event_type}`')

        lines.extend(['', '## Risk Queues', ''])
        if not self.risk_queues:
            lines.append('No risk queues.')
        for queue in self.risk_queues:
            joined = ', '.join(queue.event_ids) if queue.event_ids else '-'
            lines.append(f'- `{queue.name}`: {queue.reason} ({joined})')

        lines.extend(['', '## Chains', ''])
        for chain in self.timeline.chains:
            labels = ' -> '.join(node.event.event_type.value for node in chain.nodes)
            lines.append(f'- `{chain.chain_id}`: {labels}')
        lines.append('')
        return '\n'.join(lines)


_FAILED_STATUSES = {'failed', 'fail', 'error'}


def _is_failed_verification(event: AuditEvent) -> bool:
    """Match both producer contracts for verification failures.

    Harness audit events report a ``status`` field, while events derived from
    the live event stream (``CmdOutputObservation``) report an integer
    ``exit_code``; either signal marks the verification as failed.
    """
    if str(event.payload.get('status', '')).lower() in _FAILED_STATUSES:
        return True
    exit_code = event.payload.get('exit_code')
    return exit_code is not None and str(exit_code) != '0'


def _is_high_risk_command_event(event: AuditEvent) -> bool:
    """Read the risk field written by the event-stream producers.

    Live ``CmdRunAction`` events carry ``security_risk``; ``risk`` is kept as
    a fallback for audit events produced by older payloads.
    """
    risk = event.payload.get('security_risk', event.payload.get('risk', ''))
    return str(risk).lower() == 'high'


def _risk_queues(events: list[AuditEvent]) -> list[ReplayRiskQueue]:
    # Event ids must be unique: several events can share a trace_id (all
    # actions of one LLM response), so use the same unique node ids as the
    # timeline builder to keep queue references unambiguous and stable.
    identified = assign_unique_node_ids(events)
    approval_requests = [
        node_id
        for node_id, event in identified
        if event.event_type == AuditEventType.APPROVAL_REQUESTED
    ]
    failed_verifications = [
        node_id
        for node_id, event in identified
        if event.event_type in {AuditEventType.TEST_RESULT, AuditEventType.VERIFICATION}
        and _is_failed_verification(event)
    ]
    high_risk_commands = [
        node_id
        for node_id, event in identified
        if event.event_type in {AuditEventType.COMMAND, AuditEventType.COMMAND_RUN}
        and _is_high_risk_command_event(event)
    ]

    queues: list[ReplayRiskQueue] = []
    if approval_requests:
        queues.append(
            ReplayRiskQueue(
                name='approval_required',
                event_ids=approval_requests,
                reason='Task requested human approval before continuing.',
            )
        )
    if failed_verifications:
        queues.append(
            ReplayRiskQueue(
                name='failed_verification',
                event_ids=failed_verifications,
                reason='Verification or test events reported failure.',
            )
        )
    if high_risk_commands:
        queues.append(
            ReplayRiskQueue(
                name='high_risk_command',
                event_ids=high_risk_commands,
                reason='Command events were marked high risk by policy.',
            )
        )
    return queues


def build_audit_replay_summary(events: Iterable[AuditEvent]) -> AuditReplaySummary:
    event_list = list(events)
    evidence = build_task_evidence_pack(event_list)
    timeline = build_timeline(event_list)
    return AuditReplaySummary(
        task_id=evidence.task_id,
        event_count=evidence.event_count,
        chain_count=len(timeline.chains),
        total_cost_usd=timeline.total_cost_usd,
        total_duration_ms=timeline.total_duration_ms,
        event_types=evidence.event_types,
        risk_queues=_risk_queues(event_list),
        timeline=timeline,
        audit_jsonl=evidence.audit_jsonl,
    )
