"""Tests for platform infrastructure: logging, tenant model, audit export (G-66/67/68)."""

from openhands.forgepilot.platform import (
    PLANS,
    AuditExporter,
    BillingTier,
    ObjectStorageConfig,
    StructuredLogger,
    Tenant,
    TenantRegistry,
    TraceContext,
)


def test_trace_context_generates_ids():
    ctx = TraceContext(task_id='task-1', space_id='space-1')
    assert ctx.trace_id
    assert ctx.span_id
    assert ctx.task_id == 'task-1'
    assert ctx.space_id == 'space-1'


def test_trace_context_augment():
    ctx = TraceContext(task_id='task-1')
    augmented = ctx.augment({'action': 'test'})
    assert augmented['trace_id'] == ctx.trace_id
    assert augmented['task_id'] == 'task-1'
    assert augmented['action'] == 'test'


def test_structured_logger_emits_entry():
    logger = StructuredLogger()
    ctx = TraceContext(task_id='task-test')
    entry = logger.info('test message', trace_context=ctx, component='test')
    assert entry.trace_id == ctx.trace_id
    assert entry.message == 'test message'
    assert entry.component == 'test'
    assert entry.task_id == 'task-test'


def test_tenant_billing_check():
    tenant = Tenant(
        tenant_id='t1',
        name='Test Corp',
        billing_tier=BillingTier.FREE,
    )
    assert tenant.can_create_space()  # FREE has 1 space, 0 created
    assert tenant.can_add_member()  # no members yet

    # Simulate usage up to limit
    tenant.record_task_cost(30.0)
    tenant.record_task_cost(25.0)
    assert tenant.is_over_budget()  # 55 > 50


def test_tenant_registry_quota():
    registry = TenantRegistry()
    registry.create_tenant('t1', 'Tenant 1', tier=BillingTier.TEAM)
    assert registry.check_task_quota('t1')


def test_tenant_plan_limits():
    plan = PLANS[BillingTier.STARTER]
    assert plan.max_spaces == 3
    assert plan.max_members == 10
    assert plan.team_spaces_enabled is False


def test_structured_logger_survives_failing_handler():
    """A broken handler must not break logging, nor fail silently (L-3)."""
    logger = StructuredLogger()

    def bad_handler(entry):
        raise RuntimeError('handler exploded')

    logger._handlers.append(bad_handler)
    entry = logger.info('still works')
    assert entry.message == 'still works'


def test_audit_exporter_creates_job():
    config = ObjectStorageConfig(
        endpoint='https://s3.example.com',
        bucket='forgepilot-logs',
        access_key='test',
        secret_key='test',
    )
    exporter = AuditExporter(config)
    job = exporter.export(
        '{"trace_id":"t1"}\n{"trace_id":"t2"}',
        space_id='space-1',
        task_id='task-1',
    )
    # No object-storage upload is implemented: the exporter must not pretend
    # the archive succeeded (M-4).
    assert job.status == 'not_implemented'
    assert job.event_count == 2
    assert job.object_key == ''
    assert 'NOT archived' in job.error
