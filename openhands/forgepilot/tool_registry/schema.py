from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum

from pydantic import BaseModel, Field


class ToolPermission(str, Enum):
    READ = 'read'
    WRITE = 'write'
    EXECUTE = 'execute'
    CONFIRM = 'confirm'


class ToolExecutionMode(str, Enum):
    LIVE = 'live'
    MOCK = 'mock'


class ToolHealthStatus(str, Enum):
    UNKNOWN = 'unknown'
    HEALTHY = 'healthy'
    DEGRADED = 'degraded'
    UNREACHABLE = 'unreachable'


class ToolSchemaRef(BaseModel):
    schema_type: str = Field(
        default='json_schema',
        description='json_schema | openapi | protobuf | custom',
    )
    location: str
    checksum: str | None = None


class ToolHealthCheck(BaseModel):
    status: ToolHealthStatus = ToolHealthStatus.UNKNOWN
    checked_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    detail: str | None = None


class ToolCostBreakdown(BaseModel):
    model_cost_usd: float = 0.0
    ci_cost_usd: float = 0.0
    external_api_cost_usd: float = 0.0

    @property
    def total_cost_usd(self) -> float:
        return round(
            self.model_cost_usd + self.ci_cost_usd + self.external_api_cost_usd,
            6,
        )


class ToolRegistryEntry(BaseModel):
    tool_id: str
    display_name: str
    provider: str
    enabled: bool = True
    permission: ToolPermission = ToolPermission.READ
    permission_scopes: tuple[str, ...] = ()
    mode: ToolExecutionMode = ToolExecutionMode.LIVE
    schema_ref: ToolSchemaRef | None = None
    health_check: ToolHealthCheck | None = None
    cost: ToolCostBreakdown = Field(default_factory=ToolCostBreakdown)


def summarize_tool_output(output: str, max_chars: int = 1200) -> str:
    normalized = output.strip()
    if len(normalized) <= max_chars:
        return normalized

    keep_head = max_chars // 2
    keep_tail = max_chars - keep_head
    head = normalized[:keep_head].rstrip()
    tail = normalized[-keep_tail:].lstrip()
    return f'{head}\n...\n{tail}'
