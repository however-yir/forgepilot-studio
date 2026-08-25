from openhands.forgepilot.tool_registry.registry import (
    BUILTIN_CONNECTOR_TEMPLATES,
    HTTPConnectorConfig,
    ToolRegistry,
    build_http_connector_request,
)
from openhands.forgepilot.tool_registry.schema import (
    ToolExecutionMode,
    ToolHealthStatus,
)


def test_builtin_templates_include_target_connectors():
    template_ids = {template.template_id for template in BUILTIN_CONNECTOR_TEMPLATES}
    assert {
        'github',
        'gitlab',
        'jira',
        'linear',
        'notion',
        'sentry',
        'slack',
    }.issubset(template_ids)


def test_registry_from_templates_exposes_entries():
    registry = ToolRegistry.from_builtin_templates()
    tool_ids = [entry.tool_id for entry in registry.list_entries()]
    assert 'connector.github' in tool_ids
    assert 'connector.sentry' in tool_ids
    assert registry.get_entry('connector.github').permission_scopes == ('confirm',)


def test_health_check_detects_missing_credentials():
    registry = ToolRegistry.from_builtin_templates()
    health = registry.run_health_check('connector.github', env={})
    assert health.status == ToolHealthStatus.UNREACHABLE
    assert health.detail and 'GITHUB_TOKEN' in health.detail


def test_health_check_detects_network_and_version_degradation():
    registry = ToolRegistry.from_builtin_templates()
    health = registry.run_health_check(
        'connector.github',
        env={'GITHUB_TOKEN': 'x'},
        network_ok=False,
        version_compatible=False,
    )
    assert health.status == ToolHealthStatus.DEGRADED
    assert health.detail and 'network check failed' in health.detail
    assert health.detail and 'version compatibility check failed' in health.detail


def test_record_call_and_cost_aggregation():
    registry = ToolRegistry.from_builtin_templates()

    record = registry.record_call(
        'connector.github',
        parameters={'repo': 'however-yir/forgepilot-studio', 'pr': 418},
        output='checks: lint=success, unit=failed',
        duration_ms=812,
        trace_id='trace-tool-1',
    )
    assert record.trace_id == 'trace-tool-1'
    assert record.parameters_summary.startswith('{"repo":')

    registry.record_cost('connector.github', model_cost_usd=0.21, ci_cost_usd=0.55)
    registry.record_cost(
        'connector.sentry',
        model_cost_usd=0.11,
        external_api_cost_usd=0.09,
    )
    total = registry.aggregate_costs()
    assert total.total_cost_usd == 0.96


def test_invoke_uses_mock_response_when_present():
    registry = ToolRegistry.from_builtin_templates()
    registry.set_mock_response(
        'connector.github',
        output='mock-check-result',
        duration_ms=55,
    )

    record = registry.invoke(
        'connector.github',
        parameters={'repo': 'however-yir/forgepilot-studio'},
        confirmed=True,
    )
    assert record.output_summary == 'mock-check-result'
    assert record.duration_ms == 55


def test_registry_previews_schema_and_permission_scopes():
    registry = ToolRegistry.from_builtin_templates()
    registry.set_enabled('connector.github', False)
    registry.set_permission_scopes('connector.github', ('repo:read', 'checks:read'))

    preview = registry.preview_schema('connector.github')
    assert preview['enabled'] is False
    assert preview['permission_scopes'] == ['repo:read', 'checks:read']
    assert preview['schema_ref'] is not None


def test_invoke_requires_executor_when_live_mode():
    registry = ToolRegistry.from_builtin_templates()
    record = registry.invoke(
        'connector.github', parameters={'repo': 'x'}, confirmed=True
    )
    assert record.error == 'live executor is required when mock mode is disabled'


def test_invoke_live_executor_success():
    registry = ToolRegistry.from_builtin_templates()
    registry.set_mode('connector.github', ToolExecutionMode.LIVE)

    def executor(tool_id: str, params: dict[str, object]) -> str:
        return f'ok:{tool_id}:{params["repo"]}'

    record = registry.invoke(
        'connector.github',
        parameters={'repo': 'however-yir/forgepilot-studio'},
        executor=executor,
        confirmed=True,
    )
    assert record.error is None
    assert 'ok:connector.github:however-yir/forgepilot-studio' in record.output_summary


def test_build_http_connector_request_from_variables():
    connector = HTTPConnectorConfig(
        connector_id='internal-audit-api',
        base_url='https://audit-gateway.internal',
        path='/v1/tenants/{{tenant_id}}/exports',
        method='post',
        headers={'Authorization': 'Bearer {{token}}'},
        query_params={'format': '{{format}}'},
        body={'scope': 'latest'},
    )

    request = build_http_connector_request(
        connector,
        variables={
            'tenant_id': 'team-alpha',
            'token': 'secure-token',
            'format': 'jsonl',
        },
    )
    assert request['method'] == 'POST'
    assert (
        request['url'] == 'https://audit-gateway.internal/v1/tenants/team-alpha/exports'
    )
    assert request['headers']['Authorization'] == 'Bearer secure-token'
    assert request['query_params']['format'] == 'jsonl'


def test_invoke_live_executor_timeout_records_timeout_error():
    """A live executor that exceeds ``timeout_seconds`` must be terminated.

    The audit record must report the timeout as an error and a non-zero
    duration so a hung tool does not silently stall a task. The executor
    thread itself is not interruptible in Python, but the harness must
    still surface a clear failure to the caller.
    """
    import time

    registry = ToolRegistry.from_builtin_templates()
    registry.set_mode('connector.github', ToolExecutionMode.LIVE)

    def slow_executor(tool_id: str, params: dict[str, object]) -> str:
        time.sleep(2.0)
        return 'late'

    started = time.perf_counter()
    record = registry.invoke(
        'connector.github',
        parameters={'repo': 'x'},
        executor=slow_executor,
        confirmed=True,
        timeout_seconds=0.2,
    )
    elapsed = time.perf_counter() - started
    assert record.error is not None
    assert 'timed out after 0.2s' in record.error
    assert record.duration_ms >= 200
    # Should return well before the 2s executor sleep completes.
    assert elapsed < 1.5


def test_invoke_live_executor_exception_chains_type_name():
    """Executor exceptions must surface the original exception class name.

    A bare ``str(exc)`` discarded the type, so a ``ValueError`` looked
    identical to a ``RuntimeError`` in audit logs. The new error format
    is ``"TypeName: message"`` so reviewers can tell the failure mode
    at a glance.
    """
    registry = ToolRegistry.from_builtin_templates()
    registry.set_mode('connector.github', ToolExecutionMode.LIVE)

    def bad_executor(tool_id: str, params: dict[str, object]) -> str:
        raise ValueError('bad input')

    record = registry.invoke(
        'connector.github',
        parameters={'repo': 'x'},
        executor=bad_executor,
        confirmed=True,
    )
    assert record.error is not None
    assert record.error.startswith('ValueError:')
    assert 'bad input' in record.error


def test_clear_call_records_drops_history_bounded_to_tool():
    """``clear_call_records`` must bound the audit-history memory for
    long-running tasks and leave mock / registry state alone.
    """
    registry = ToolRegistry.from_builtin_templates()
    registry.set_mock_response('connector.github', output='gh')
    registry.set_mock_response('connector.sentry', output='sn')

    registry.invoke('connector.github', parameters={'r': 'a'}, confirmed=True)
    registry.invoke('connector.sentry', parameters={'r': 'b'}, confirmed=True)
    registry.invoke('connector.github', parameters={'r': 'c'}, confirmed=True)

    assert len(registry.list_call_records()) == 3

    # Drop only the github records; sentry + mock specs survive.
    dropped = registry.clear_call_records(tool_id='connector.github')
    assert dropped == 2
    remaining = registry.list_call_records()
    assert len(remaining) == 1
    assert remaining[0].tool_id == 'connector.sentry'
    # Mock spec still in place.
    assert (
        registry.invoke(
            'connector.github', parameters={'r': 'd'}, confirmed=True
        ).output_summary
        == 'gh'
    )


def test_clear_call_records_with_no_filter_drops_all():
    registry = ToolRegistry.from_builtin_templates()
    registry.invoke('connector.github', parameters={'r': 'a'}, confirmed=True)
    assert registry.clear_call_records() == 1
    assert registry.list_call_records() == []

    """Display names must not be able to break out of Mermaid labels (L-7)."""
    from openhands.forgepilot.tool_registry.enforcement import (
        generate_mermaid_registry_graph,
    )
    from openhands.forgepilot.tool_registry.schema import ToolRegistryEntry

    registry = ToolRegistry()
    registry.register(
        ToolRegistryEntry(
            tool_id='connector.evil',
            display_name='Evil"] inject\ngraph TD; X["pwned',
            provider='weird"provider',
        )
    )

    graph = generate_mermaid_registry_graph(registry)

    assert '&quot;' in graph
    # The renderer wraps the label in `["..."]`; strip those structural
    # delimiters and verify no raw double-quote or newline remains inside.
    for line in graph.splitlines():
        if 'connector_evil[' in line:
            label = line.split('[', 1)[1]
            assert label.startswith('"') and label.endswith('"]')
            label = label[1:-2]
            assert '"' not in label.replace('&quot;', '')
            assert '\n' not in label
