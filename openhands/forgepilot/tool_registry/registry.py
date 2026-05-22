from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from typing import Callable, Mapping
from uuid import uuid4

from pydantic import BaseModel, Field

from .schema import (
    ToolCostBreakdown,
    ToolExecutionMode,
    ToolHealthCheck,
    ToolHealthStatus,
    ToolPermission,
    ToolRegistryEntry,
    ToolSchemaRef,
    summarize_tool_output,
)


class ConnectorTemplate(BaseModel):
    template_id: str
    display_name: str
    provider: str
    required_env_vars: tuple[str, ...] = ()
    default_permission: ToolPermission = ToolPermission.READ
    schema_location: str


class ToolCallRecord(BaseModel):
    trace_id: str
    tool_id: str
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    duration_ms: int
    parameters_summary: str
    output_summary: str
    error: str | None = None
    mode: ToolExecutionMode = ToolExecutionMode.LIVE


class ToolMockSpec(BaseModel):
    output: str = 'mock response'
    error: str | None = None
    duration_ms: int = 20


class HTTPConnectorConfig(BaseModel):
    connector_id: str
    base_url: str
    path: str
    method: str = 'GET'
    headers: dict[str, str] = Field(default_factory=dict)
    query_params: dict[str, str] = Field(default_factory=dict)
    body: dict[str, object] | None = None


def _render_template(value: str, variables: Mapping[str, object]) -> str:
    rendered = value
    for key, variable in variables.items():
        rendered = rendered.replace(f'{{{{{key}}}}}', str(variable))
    return rendered


def build_http_connector_request(
    config: HTTPConnectorConfig,
    variables: Mapping[str, object] | None = None,
) -> dict[str, object]:
    variables = variables or {}
    path = _render_template(config.path, variables).lstrip('/')
    base_url = config.base_url.rstrip('/')
    url = f'{base_url}/{path}' if path else base_url

    headers = {
        key: _render_template(value, variables) for key, value in config.headers.items()
    }
    query_params = {
        key: _render_template(value, variables)
        for key, value in config.query_params.items()
    }

    return {
        'connector_id': config.connector_id,
        'method': config.method.upper(),
        'url': url,
        'headers': headers,
        'query_params': query_params,
        'body': config.body,
    }


BUILTIN_CONNECTOR_TEMPLATES: tuple[ConnectorTemplate, ...] = (
    ConnectorTemplate(
        template_id='github',
        display_name='GitHub',
        provider='github',
        required_env_vars=('GITHUB_TOKEN',),
        default_permission=ToolPermission.CONFIRM,
        schema_location='app://github/schema',
    ),
    ConnectorTemplate(
        template_id='gitlab',
        display_name='GitLab',
        provider='gitlab',
        required_env_vars=('GITLAB_TOKEN',),
        default_permission=ToolPermission.CONFIRM,
        schema_location='app://gitlab/schema',
    ),
    ConnectorTemplate(
        template_id='jira',
        display_name='Jira',
        provider='jira',
        required_env_vars=('JIRA_BASE_URL', 'JIRA_API_TOKEN'),
        default_permission=ToolPermission.WRITE,
        schema_location='app://jira/schema',
    ),
    ConnectorTemplate(
        template_id='linear',
        display_name='Linear',
        provider='linear',
        required_env_vars=('LINEAR_API_KEY',),
        default_permission=ToolPermission.WRITE,
        schema_location='app://linear/schema',
    ),
    ConnectorTemplate(
        template_id='notion',
        display_name='Notion',
        provider='notion',
        required_env_vars=('NOTION_API_KEY',),
        default_permission=ToolPermission.WRITE,
        schema_location='app://notion/schema',
    ),
    ConnectorTemplate(
        template_id='sentry',
        display_name='Sentry',
        provider='sentry',
        required_env_vars=('SENTRY_AUTH_TOKEN',),
        default_permission=ToolPermission.READ,
        schema_location='app://sentry/schema',
    ),
    ConnectorTemplate(
        template_id='slack',
        display_name='Slack',
        provider='slack',
        required_env_vars=('SLACK_BOT_TOKEN',),
        default_permission=ToolPermission.WRITE,
        schema_location='app://slack/schema',
    ),
)


class ToolRegistry:
    def __init__(self, entries: list[ToolRegistryEntry] | None = None):
        self._entries: dict[str, ToolRegistryEntry] = {}
        self._call_records: list[ToolCallRecord] = []
        self._mock_specs: dict[str, ToolMockSpec] = {}
        for entry in entries or []:
            self._entries[entry.tool_id] = entry.model_copy(deep=True)

    @classmethod
    def from_builtin_templates(cls) -> 'ToolRegistry':
        entries = [
            ToolRegistryEntry(
                tool_id=f'connector.{template.template_id}',
                display_name=template.display_name,
                provider=template.provider,
                permission=template.default_permission,
                permission_scopes=(template.default_permission.value,),
                schema_ref=ToolSchemaRef(location=template.schema_location),
            )
            for template in BUILTIN_CONNECTOR_TEMPLATES
        ]
        return cls(entries=entries)

    def list_entries(self) -> list[ToolRegistryEntry]:
        return [self._entries[key] for key in sorted(self._entries)]

    def get_entry(self, tool_id: str) -> ToolRegistryEntry:
        return self._entries[tool_id]

    def register(self, entry: ToolRegistryEntry) -> ToolRegistryEntry:
        self._entries[entry.tool_id] = entry.model_copy(deep=True)
        return self._entries[entry.tool_id]

    def set_enabled(self, tool_id: str, enabled: bool) -> ToolRegistryEntry:
        entry = self.get_entry(tool_id)
        entry.enabled = enabled
        return entry

    def set_permission(
        self,
        tool_id: str,
        permission: ToolPermission,
    ) -> ToolRegistryEntry:
        entry = self.get_entry(tool_id)
        entry.permission = permission
        return entry

    def set_permission_scopes(
        self,
        tool_id: str,
        scopes: tuple[str, ...],
    ) -> ToolRegistryEntry:
        entry = self.get_entry(tool_id)
        entry.permission_scopes = scopes
        return entry

    def set_mode(
        self,
        tool_id: str,
        mode: ToolExecutionMode,
    ) -> ToolRegistryEntry:
        entry = self.get_entry(tool_id)
        entry.mode = mode
        return entry

    def set_mock_response(
        self,
        tool_id: str,
        *,
        output: str = 'mock response',
        error: str | None = None,
        duration_ms: int = 20,
    ) -> ToolMockSpec:
        self.get_entry(tool_id)
        spec = ToolMockSpec(output=output, error=error, duration_ms=duration_ms)
        self._mock_specs[tool_id] = spec
        return spec

    def clear_mock_response(self, tool_id: str) -> None:
        self._mock_specs.pop(tool_id, None)

    def invoke(
        self,
        tool_id: str,
        parameters: Mapping[str, object] | str,
        *,
        executor: Callable[[str, Mapping[str, object] | str], str] | None = None,
        trace_id: str | None = None,
    ) -> ToolCallRecord:
        entry = self.get_entry(tool_id)
        mock_spec = self._mock_specs.get(tool_id)
        use_mock = entry.mode == ToolExecutionMode.MOCK or mock_spec is not None

        if use_mock:
            active_spec = mock_spec or ToolMockSpec()
            return self.record_call(
                tool_id=tool_id,
                parameters=parameters,
                output=active_spec.output,
                duration_ms=active_spec.duration_ms,
                error=active_spec.error,
                trace_id=trace_id,
            )

        if executor is None:
            return self.record_call(
                tool_id=tool_id,
                parameters=parameters,
                output='',
                duration_ms=0,
                error='live executor is required when mock mode is disabled',
                trace_id=trace_id,
            )

        started = time.perf_counter()
        try:
            output = executor(tool_id, parameters)
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            return self.record_call(
                tool_id=tool_id,
                parameters=parameters,
                output=output,
                duration_ms=elapsed_ms,
                trace_id=trace_id,
            )
        except Exception as exc:
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            return self.record_call(
                tool_id=tool_id,
                parameters=parameters,
                output='',
                duration_ms=elapsed_ms,
                error=str(exc),
                trace_id=trace_id,
            )

    def record_call(
        self,
        tool_id: str,
        parameters: Mapping[str, object] | str,
        output: str,
        duration_ms: int,
        *,
        error: str | None = None,
        trace_id: str | None = None,
    ) -> ToolCallRecord:
        entry = self.get_entry(tool_id)
        parameters_text = (
            json.dumps(parameters, ensure_ascii=False)
            if isinstance(parameters, Mapping)
            else str(parameters)
        )
        record = ToolCallRecord(
            trace_id=trace_id or uuid4().hex,
            tool_id=tool_id,
            duration_ms=duration_ms,
            parameters_summary=summarize_tool_output(parameters_text, max_chars=300),
            output_summary=summarize_tool_output(output, max_chars=800),
            error=error,
            mode=entry.mode,
        )
        self._call_records.append(record)
        return record

    def list_call_records(self, tool_id: str | None = None) -> list[ToolCallRecord]:
        if tool_id is None:
            return list(self._call_records)
        return [record for record in self._call_records if record.tool_id == tool_id]

    def preview_schema(self, tool_id: str) -> dict[str, object]:
        entry = self.get_entry(tool_id)
        return {
            'tool_id': entry.tool_id,
            'display_name': entry.display_name,
            'provider': entry.provider,
            'enabled': entry.enabled,
            'permission': entry.permission.value,
            'permission_scopes': list(entry.permission_scopes),
            'mode': entry.mode.value,
            'schema_ref': entry.schema_ref.model_dump() if entry.schema_ref else None,
        }

    def run_health_check(
        self,
        tool_id: str,
        *,
        env: Mapping[str, str | None] | None = None,
        network_ok: bool = True,
        version_compatible: bool = True,
    ) -> ToolHealthCheck:
        entry = self.get_entry(tool_id)
        env = env or {}
        template = next(
            (
                value
                for value in BUILTIN_CONNECTOR_TEMPLATES
                if value.provider == entry.provider
            ),
            None,
        )
        required_env_vars = template.required_env_vars if template else ()
        missing_env_vars = [name for name in required_env_vars if not env.get(name)]

        status = ToolHealthStatus.HEALTHY
        details: list[str] = []
        if missing_env_vars:
            status = ToolHealthStatus.UNREACHABLE
            details.append(f'missing credentials: {", ".join(missing_env_vars)}')
        else:
            if not network_ok:
                status = ToolHealthStatus.DEGRADED
                details.append('network check failed')
            if not version_compatible:
                status = ToolHealthStatus.DEGRADED
                details.append('version compatibility check failed')

        health_check = ToolHealthCheck(
            status=status,
            detail='; '.join(details) if details else 'ready',
        )
        entry.health_check = health_check
        return health_check

    def record_cost(
        self,
        tool_id: str,
        *,
        model_cost_usd: float = 0.0,
        ci_cost_usd: float = 0.0,
        external_api_cost_usd: float = 0.0,
    ) -> ToolCostBreakdown:
        entry = self.get_entry(tool_id)
        entry.cost.model_cost_usd = round(entry.cost.model_cost_usd + model_cost_usd, 6)
        entry.cost.ci_cost_usd = round(entry.cost.ci_cost_usd + ci_cost_usd, 6)
        entry.cost.external_api_cost_usd = round(
            entry.cost.external_api_cost_usd + external_api_cost_usd,
            6,
        )
        return entry.cost

    def aggregate_costs(self) -> ToolCostBreakdown:
        total = ToolCostBreakdown()
        for entry in self._entries.values():
            total.model_cost_usd = round(
                total.model_cost_usd + entry.cost.model_cost_usd,
                6,
            )
            total.ci_cost_usd = round(total.ci_cost_usd + entry.cost.ci_cost_usd, 6)
            total.external_api_cost_usd = round(
                total.external_api_cost_usd + entry.cost.external_api_cost_usd,
                6,
            )
        return total
