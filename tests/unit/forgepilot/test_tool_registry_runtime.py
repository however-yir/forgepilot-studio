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


def test_mermaid_registry_graph_escapes_labels():
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
