"""ForgePilot platform infrastructure.

G-66: Structured logging with trace_id propagation across frontend/backend.
G-67: Audit log export to object storage (S3-compatible) with archival policy.
G-68: Tenant and role model with billing dimensions.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

# ═══════════════════════════════════════════════════
#  G-66: Structured Logging with trace_id
# ═══════════════════════════════════════════════════


class LogLevel(str, Enum):
    DEBUG = 'debug'
    INFO = 'info'
    WARN = 'warn'
    ERROR = 'error'


class StructuredLogEntry(BaseModel):
    """Single structured log entry with trace_id for full-stack correlation."""

    trace_id: str
    span_id: str = Field(default_factory=lambda: uuid4().hex[:16])
    parent_span_id: str | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    level: LogLevel = LogLevel.INFO
    service: str = 'forgepilot'
    component: str = ''  # e.g. 'control_plane', 'tool_registry', 'frontend'
    message: str
    context: dict[str, Any] = Field(default_factory=dict)
    duration_ms: int | None = None
    error: str | None = None
    user_id: str | None = None
    space_id: str | None = None
    task_id: str | None = None

    def as_json(self) -> str:
        return self.model_dump_json(exclude_none=True)


class TraceContext:
    """Thread-local trace context for trace_id propagation.

    Usage:
        with TraceContext(task_id="task-123") as ctx:
            logger.info(ctx.augment({"action": "execute"}))
    """

    _trace_id: str | None = None
    _span_id: str | None = None
    _task_id: str | None = None
    _space_id: str | None = None

    def __init__(
        self,
        *,
        trace_id: str | None = None,
        task_id: str | None = None,
        space_id: str | None = None,
    ) -> None:
        self._trace_id = trace_id or uuid4().hex
        self._span_id = uuid4().hex[:16]
        self._task_id = task_id
        self._space_id = space_id

    @property
    def trace_id(self) -> str:
        return self._trace_id or ''

    @property
    def span_id(self) -> str:
        return self._span_id or ''

    @property
    def task_id(self) -> str | None:
        return self._task_id

    @property
    def space_id(self) -> str | None:
        return self._space_id

    def augment(self, extra: dict[str, Any]) -> dict[str, Any]:
        """Augment log context with trace metadata."""
        base: dict[str, Any] = {
            'trace_id': self._trace_id,
            'span_id': self._span_id,
        }
        if self._task_id:
            base['task_id'] = self._task_id
        if self._space_id:
            base['space_id'] = self._space_id
        base.update(extra)
        return base

    def child_span(self) -> str:
        """Create a child span ID for a sub-operation."""
        child = uuid4().hex[:16]
        return child

    def __enter__(self) -> TraceContext:
        return self

    def __exit__(self, *_: Any) -> None:
        pass


class StructuredLogger:
    """Structured logger that emits trace_id-tagged log entries."""

    def __init__(self, service: str = 'forgepilot') -> None:
        self._service = service
        self._handlers: list[Any] = []

    def log(
        self,
        level: LogLevel,
        message: str,
        *,
        trace_context: TraceContext | None = None,
        component: str = '',
        **context: Any,
    ) -> StructuredLogEntry:
        ctx = trace_context or TraceContext()
        entry = StructuredLogEntry(
            trace_id=ctx.trace_id,
            span_id=ctx.span_id,
            level=level,
            service=self._service,
            component=component,
            message=message,
            context=context,
            task_id=ctx.task_id,
            space_id=ctx.space_id,
        )
        for handler in self._handlers:
            try:
                handler(entry)
            except Exception:
                # Report the failure instead of silently dropping it; the
                # stdlib logger is used to avoid re-entering our own handlers.
                logging.getLogger(__name__).exception(
                    'structured log handler failed for entry %s', entry.trace_id
                )
        return entry

    def debug(self, message: str, **kwargs: Any) -> StructuredLogEntry:
        return self.log(LogLevel.DEBUG, message, **kwargs)

    def info(self, message: str, **kwargs: Any) -> StructuredLogEntry:
        return self.log(LogLevel.INFO, message, **kwargs)

    def warn(self, message: str, **kwargs: Any) -> StructuredLogEntry:
        return self.log(LogLevel.WARN, message, **kwargs)

    def error(self, message: str, **kwargs: Any) -> StructuredLogEntry:
        return self.log(LogLevel.ERROR, message, **kwargs)


platform_logger = StructuredLogger()


# ═══════════════════════════════════════════════════
#  G-67: Audit Export to Object Storage
# ═══════════════════════════════════════════════════


class ExportFormat(str, Enum):
    JSONL = 'jsonl'
    CSV = 'csv'
    PARQUET = 'parquet'


class ObjectStorageConfig(BaseModel):
    endpoint: str  # S3-compatible endpoint
    bucket: str
    region: str = 'us-east-1'
    access_key: str = ''
    secret_key: str = ''
    prefix: str = 'forgepilot-audit/'


class AuditExportJob(BaseModel):
    job_id: str = Field(default_factory=lambda: uuid4().hex)
    space_id: str
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None
    format: ExportFormat = ExportFormat.JSONL
    event_count: int = 0
    object_key: str = ''
    status: str = 'pending'  # pending | running | completed | failed
    error: str | None = None


class AuditArchivalPolicy(BaseModel):
    space_id: str
    retention_days: int = 90
    export_format: ExportFormat = ExportFormat.JSONL
    auto_archive: bool = False
    archive_after_days: int = 7
    destination: ObjectStorageConfig | None = None


class AuditExporter:
    """Export audit events to S3-compatible object storage.

    NOTE: this is a stub.  No object-storage upload is implemented yet, so
    ``export`` reports ``status='not_implemented'`` instead of pretending the
    archive succeeded.  Wire it to a real S3/boto3 client before relying on it.
    """

    def __init__(self, config: ObjectStorageConfig) -> None:
        self._config = config

    def export(
        self,
        events_jsonl: str,
        *,
        space_id: str,
        task_id: str = '',
        format: ExportFormat = ExportFormat.JSONL,
    ) -> AuditExportJob:
        job = AuditExportJob(space_id=space_id, format=format)
        job.event_count = events_jsonl.count('\n') + 1 if events_jsonl else 0
        job.status = 'not_implemented'
        job.error = (
            'AuditExporter does not implement object-storage upload yet; '
            'events were NOT archived. Integrate a real S3 client before '
            'treating audit archives as durable.'
        )
        platform_logger.warn(
            'audit_export_not_implemented',
            component='audit_exporter',
            job_id=job.job_id,
            space_id=space_id,
            event_count=job.event_count,
        )
        return job

    def archive_events(
        self,
        events_jsonl: str,
        policy: AuditArchivalPolicy,
    ) -> AuditExportJob | None:
        """Automatically archive events according to retention policy."""
        if not policy.auto_archive or policy.destination is None:
            return None
        exporter = AuditExporter(policy.destination)
        return exporter.export(
            events_jsonl,
            space_id=policy.space_id,
            format=policy.export_format,
        )


# ═══════════════════════════════════════════════════
#  G-68: Tenant and Role Model (with Billing)
# ═══════════════════════════════════════════════════


class BillingTier(str, Enum):
    FREE = 'free'
    STARTER = 'starter'
    TEAM = 'team'
    BUSINESS = 'business'
    ENTERPRISE = 'enterprise'


class TenantRole(str, Enum):
    TENANT_OWNER = 'tenant_owner'
    TENANT_ADMIN = 'tenant_admin'
    BILLING_ADMIN = 'billing_admin'
    SPACE_ADMIN = 'space_admin'
    MEMBER = 'member'
    VIEWER = 'viewer'


class BillingPlan(BaseModel):
    tier: BillingTier = BillingTier.FREE
    max_spaces: int = 1
    max_members: int = 5
    max_tasks_per_month: int = 100
    max_cost_per_month_usd: float = 50.0
    model_access: list[str] = Field(default_factory=lambda: ['openai/gpt-4.1'])
    audit_retention_days: int = 30
    mcp_enabled: bool = True
    team_spaces_enabled: bool = False
    delivery_reports_enabled: bool = False


PLANS: dict[BillingTier, BillingPlan] = {
    BillingTier.FREE: BillingPlan(tier=BillingTier.FREE),
    BillingTier.STARTER: BillingPlan(
        tier=BillingTier.STARTER,
        max_spaces=3,
        max_members=10,
        max_tasks_per_month=500,
        max_cost_per_month_usd=200.0,
        model_access=['openai/gpt-4.1', 'anthropic/claude-sonnet-4-6'],
        audit_retention_days=90,
    ),
    BillingTier.TEAM: BillingPlan(
        tier=BillingTier.TEAM,
        max_spaces=10,
        max_members=50,
        max_tasks_per_month=2000,
        max_cost_per_month_usd=1000.0,
        model_access=[
            'openai/gpt-4.1',
            'anthropic/claude-sonnet-4-6',
            'anthropic/claude-opus-4-7',
        ],
        audit_retention_days=180,
        team_spaces_enabled=True,
        delivery_reports_enabled=True,
    ),
    BillingTier.BUSINESS: BillingPlan(
        tier=BillingTier.BUSINESS,
        max_spaces=50,
        max_members=200,
        max_tasks_per_month=10000,
        max_cost_per_month_usd=5000.0,
        audit_retention_days=365,
        team_spaces_enabled=True,
        delivery_reports_enabled=True,
    ),
    BillingTier.ENTERPRISE: BillingPlan(
        tier=BillingTier.ENTERPRISE,
        max_spaces=-1,  # unlimited
        max_members=-1,
        max_tasks_per_month=-1,
        max_cost_per_month_usd=-1.0,
        audit_retention_days=2555,  # 7 years
        team_spaces_enabled=True,
        delivery_reports_enabled=True,
    ),
}


class Tenant(BaseModel):
    tenant_id: str
    name: str
    billing_tier: BillingTier = BillingTier.FREE
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    members: dict[str, TenantRole] = Field(default_factory=dict)
    spaces: list[str] = Field(default_factory=list)  # list of space_ids
    cost_current_month_usd: float = 0.0
    tasks_this_month: int = 0

    @property
    def plan(self) -> BillingPlan:
        return PLANS[self.billing_tier]

    def can_create_space(self) -> bool:
        plan = self.plan
        if plan.max_spaces < 0:
            return True
        return len(self.spaces) < plan.max_spaces

    def can_add_member(self) -> bool:
        plan = self.plan
        if plan.max_members < 0:
            return True
        return len(self.members) < plan.max_members

    def is_over_budget(self) -> bool:
        plan = self.plan
        if plan.max_cost_per_month_usd < 0:
            return False
        return self.cost_current_month_usd >= plan.max_cost_per_month_usd

    def is_over_task_limit(self) -> bool:
        plan = self.plan
        if plan.max_tasks_per_month < 0:
            return False
        return self.tasks_this_month >= plan.max_tasks_per_month

    def record_task_cost(self, cost_usd: float) -> None:
        self.cost_current_month_usd += cost_usd
        self.tasks_this_month += 1


class TenantRegistry:
    """Registry of tenants with billing-aware enforcement."""

    def __init__(self) -> None:
        self._tenants: dict[str, Tenant] = {}

    def create_tenant(
        self,
        tenant_id: str,
        name: str,
        tier: BillingTier = BillingTier.FREE,
        owner_id: str = '',
    ) -> Tenant:
        tenant = Tenant(tenant_id=tenant_id, name=name, billing_tier=tier)
        if owner_id:
            tenant.members[owner_id] = TenantRole.TENANT_OWNER
        self._tenants[tenant_id] = tenant
        return tenant

    def get_tenant(self, tenant_id: str) -> Tenant | None:
        return self._tenants.get(tenant_id)

    def check_task_quota(self, tenant_id: str) -> bool:
        """Check if tenant can create more tasks. Returns False if quota exceeded."""
        tenant = self.get_tenant(tenant_id)
        if tenant is None:
            return False
        if tenant.is_over_budget():
            return False
        if tenant.is_over_task_limit():
            return False
        return True


tenant_registry = TenantRegistry()
