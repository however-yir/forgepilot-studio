from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import PlainTextResponse

from openhands.app_server.utils.dependencies import get_dependencies
from openhands.events.event_filter import EventFilter
from openhands.events.event_store import EventStore
from openhands.forgepilot.audit import (
    audit_events_from_event_stream,
    build_task_evidence_pack,
)
from openhands.forgepilot.tool_registry import ToolRegistry
from openhands.server.shared import file_store
from openhands.server.utils import get_conversation_metadata
from openhands.storage.data_models.conversation_metadata import ConversationMetadata

router = APIRouter(
    prefix='/forgepilot',
    tags=['ForgePilot'],
    dependencies=get_dependencies(),
)

# Hard cap on how many events a single audit export will read, so a large
# conversation cannot trigger an unbounded read.
MAX_AUDIT_EXPORT_EVENTS = 10_000


@router.get('/audit/export/{conversation_id}')
async def export_audit_jsonl(
    metadata: ConversationMetadata = Depends(get_conversation_metadata),
    task_id: str | None = Query(default=None),
    limit: int = Query(
        default=MAX_AUDIT_EXPORT_EVENTS, ge=1, le=MAX_AUDIT_EXPORT_EVENTS
    ),
) -> PlainTextResponse:
    """Export the audit trail of a conversation as JSONL.

    Ownership is validated by ``get_conversation_metadata`` (the conversation
    store is user-scoped), and the store is re-opened with the metadata's
    ``user_id`` so multi-user deployments read the correct event paths.
    """

    def _load_events() -> list[Any]:
        event_store = EventStore(
            sid=metadata.conversation_id,
            file_store=file_store,
            user_id=metadata.user_id,
        )
        return list(
            event_store.search_events(
                filter=EventFilter(exclude_hidden=True),
                limit=limit,
            )
        )

    try:
        events = await asyncio.get_running_loop().run_in_executor(None, _load_events)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f'Conversation {metadata.conversation_id} was not found.',
        ) from exc

    audit_events = audit_events_from_event_stream(
        events, task_id=task_id or metadata.conversation_id
    )
    pack = build_task_evidence_pack(
        audit_events, task_id=task_id or metadata.conversation_id
    )
    filename = f'{metadata.conversation_id}-audit.jsonl'
    return PlainTextResponse(
        pack.audit_jsonl,
        media_type='application/x-ndjson',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'},
    )


@router.get('/tool-registry')
async def list_tool_registry() -> list[dict[str, object]]:
    registry = ToolRegistry.from_builtin_templates()
    return [registry.preview_schema(entry.tool_id) for entry in registry.list_entries()]
