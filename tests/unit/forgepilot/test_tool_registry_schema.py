from openhands.forgepilot.tool_registry.schema import (
    ToolCostBreakdown,
    ToolExecutionMode,
    ToolPermission,
    ToolRegistryEntry,
    ToolSchemaRef,
    summarize_tool_output,
)


def test_tool_cost_breakdown_total():
    cost = ToolCostBreakdown(
        model_cost_usd=1.2,
        ci_cost_usd=0.45,
        external_api_cost_usd=0.35,
    )
    assert cost.total_cost_usd == 2.0


def test_tool_registry_entry_defaults():
    entry = ToolRegistryEntry(
        tool_id='github.issue.lookup',
        display_name='GitHub Issue Lookup',
        provider='github',
        schema_ref=ToolSchemaRef(location='app://github/schema/issue.lookup'),
    )

    assert entry.enabled is True
    assert entry.permission == ToolPermission.READ
    assert entry.permission_scopes == ()
    assert entry.mode == ToolExecutionMode.LIVE
    assert entry.cost.total_cost_usd == 0.0


def test_summarize_tool_output_truncates_long_text():
    output = 'A' * 1500
    summary = summarize_tool_output(output, max_chars=200)
    assert '...' in summary
    assert len(summary) < len(output)


def test_summarize_tool_output_keeps_short_text():
    output = 'short output'
    assert summarize_tool_output(output, max_chars=200) == output
