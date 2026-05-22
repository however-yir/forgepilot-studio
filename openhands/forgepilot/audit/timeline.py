"""Unified audit timeline builder.

Connects commands, file modifications, model responses, and tool calls into
a correlated causal chain view for the audit replay dashboard.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any, Iterable

from pydantic import BaseModel, Field

from .schema import AuditEvent, AuditEventType, ordered_timeline


class TimelineLink(BaseModel):
    """A causal link between two timeline events."""

    source_id: str
    target_id: str
    relation: str  # 'triggered', 'produced', 'verified', 'reported'
    detail: str = ''


class TimelineNode(BaseModel):
    """A single node in the unified audit timeline."""

    event: AuditEvent
    node_id: str = ''
    parent_ids: list[str] = Field(default_factory=list)
    child_ids: list[str] = Field(default_factory=list)
    depth: int = 0
    chain_label: str = ''  # e.g. "Round 1", "Self-heal A"

    def model_post_init(self, __context: Any) -> None:
        if not self.node_id:
            self.node_id = self.event.trace_id


class TimelineChain(BaseModel):
    """A linear causal chain: idea → model → command → file changes → verification."""

    chain_id: str
    nodes: list[TimelineNode]
    started_at: datetime | None = None
    completed_at: datetime | None = None
    self_heal_round: int = 0


class AuditTimeline(BaseModel):
    """Unified audit timeline for a task."""

    task_id: str
    chains: list[TimelineChain]
    orphan_nodes: list[TimelineNode] = Field(default_factory=list)
    total_cost_usd: float = 0.0
    total_duration_ms: int = 0
    summary: str = ''


_CORRELATION_WINDOW_MS = 5000  # events within this window may be causally linked
_MODEL_EVENT_TYPES = {AuditEventType.MODEL, AuditEventType.MODEL_RESPONSE}
_COMMAND_EVENT_TYPES = {AuditEventType.COMMAND, AuditEventType.COMMAND_RUN}
_VERIFICATION_EVENT_TYPES = {AuditEventType.VERIFICATION, AuditEventType.TEST_RESULT}


def _find_preceding(
    event: AuditEvent,
    recent_events: list[AuditEvent],
) -> list[str]:
    """Find preceding events that likely caused this event."""
    parents: list[str] = []
    for prev in reversed(recent_events):
        delta = (event.timestamp - prev.timestamp).total_seconds() * 1000
        if delta < 0 or delta > _CORRELATION_WINDOW_MS:
            continue
        # model responses trigger commands and tool calls
        if prev.event_type in _MODEL_EVENT_TYPES and event.event_type in {
            AuditEventType.COMMAND_RUN,
            AuditEventType.COMMAND,
            AuditEventType.TOOL_CALL,
        }:
            parents.append(prev.trace_id)
        # commands produce file changes
        elif (
            prev.event_type in _COMMAND_EVENT_TYPES
            and event.event_type == AuditEventType.FILE_CHANGE
        ):
            parents.append(prev.trace_id)
        # verifications follow commands
        elif (
            prev.event_type in _COMMAND_EVENT_TYPES
            and event.event_type in _VERIFICATION_EVENT_TYPES
        ):
            parents.append(prev.trace_id)
    return parents


def build_timeline(events: Iterable[AuditEvent]) -> AuditTimeline:
    """Build a unified timeline from raw audit events.

    Correlates model responses → commands → file modifications → verification
    into causal chains suitable for the audit replay dashboard.
    """
    sorted_events = ordered_timeline(events)
    if not sorted_events:
        return AuditTimeline(task_id='', chains=[], summary='No events recorded.')

    task_id = sorted_events[0].task_id or ''

    # Build nodes with parent-child relationships
    nodes_by_trace: dict[str, TimelineNode] = {}
    recent_command: list[AuditEvent] = []
    recent_model: list[AuditEvent] = []

    for event in sorted_events:
        parents: list[str] = []
        chain_label = ''

        if event.event_type in _COMMAND_EVENT_TYPES:
            for prev in reversed(recent_model):
                delta = (event.timestamp - prev.timestamp).total_seconds() * 1000
                if 0 <= delta <= _CORRELATION_WINDOW_MS:
                    parents.append(prev.trace_id)
                    break
            recent_command.append(event)
        elif event.event_type == AuditEventType.FILE_CHANGE:
            for prev in reversed(recent_command):
                delta = (event.timestamp - prev.timestamp).total_seconds() * 1000
                if 0 <= delta <= _CORRELATION_WINDOW_MS:
                    parents.append(prev.trace_id)
                    break
        elif event.event_type in _VERIFICATION_EVENT_TYPES:
            for prev in reversed(recent_command):
                delta = (event.timestamp - prev.timestamp).total_seconds() * 1000
                if 0 <= delta <= _CORRELATION_WINDOW_MS:
                    parents.append(prev.trace_id)
                    chain_label = 'verify'
                    break
        elif event.event_type in _MODEL_EVENT_TYPES:
            recent_model.append(event)
        elif event.event_type == AuditEventType.TOOL_CALL:
            for prev in reversed(recent_model):
                delta = (event.timestamp - prev.timestamp).total_seconds() * 1000
                if 0 <= delta <= _CORRELATION_WINDOW_MS:
                    parents.append(prev.trace_id)
                    break

        node = TimelineNode(
            event=event,
            node_id=event.trace_id,
            parent_ids=parents,
            chain_label=chain_label,
        )
        nodes_by_trace[event.trace_id] = node

    # Wire up child references
    for node in nodes_by_trace.values():
        for pid in node.parent_ids:
            if pid in nodes_by_trace:
                nodes_by_trace[pid].child_ids.append(node.node_id)

    # Build chains by walking from root nodes (no parents) downward
    chains: list[TimelineChain] = []
    visited: set[str] = set()

    def walk_chain(start_id: str) -> list[TimelineNode]:
        chain_nodes: list[TimelineNode] = []
        stack = [start_id]
        while stack:
            nid = stack.pop()
            if nid in visited:
                continue
            visited.add(nid)
            if nid not in nodes_by_trace:
                continue
            node = nodes_by_trace[nid]
            chain_nodes.append(node)
            stack.extend(reversed(node.child_ids))
        return chain_nodes

    chain_idx = 0
    for node in nodes_by_trace.values():
        if not node.parent_ids and node.node_id not in visited:
            chain_nodes = walk_chain(node.node_id)
            if chain_nodes:
                chain_idx += 1
                chain = TimelineChain(
                    chain_id=f'chain-{chain_idx:03d}',
                    nodes=chain_nodes,
                    started_at=chain_nodes[0].event.timestamp,
                    completed_at=chain_nodes[-1].event.timestamp,
                )
                chains.append(chain)

    # Collect orphans
    orphan_nodes = [n for n in nodes_by_trace.values() if n.node_id not in visited]

    # Compute aggregates
    total_cost = sum(e.cost_usd for e in sorted_events if e.cost_usd is not None)
    total_duration = sum(
        e.duration_ms for e in sorted_events if e.duration_ms is not None
    )

    # Build summary
    event_counts: dict[str, int] = defaultdict(int)
    for e in sorted_events:
        event_counts[e.event_type.value] += 1
    summary_parts = [f'{v} {k}' for k, v in event_counts.items()]
    summary = f'{len(chains)} chains: {", ".join(summary_parts)}'

    return AuditTimeline(
        task_id=task_id,
        chains=chains,
        orphan_nodes=orphan_nodes,
        total_cost_usd=total_cost,
        total_duration_ms=total_duration,
        summary=summary,
    )
